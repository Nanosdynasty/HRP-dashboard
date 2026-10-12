"""Build a versioned, water-only ECA display snapshot from published control lines.

Run only when refreshing the bundled snapshot. Runtime never downloads geometry.
Coastline closures use the project's Natural Earth 1:50m mask; this remains an
analytical map layer, not a navigational or legal boundary product.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
from pathlib import Path

import httpx
from pypdf import PdfReader
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, box, mapping, shape
from shapely.ops import substring, unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "imo_eca_verified.geojson"
LAND = ROOT / "data" / "voyage_land_50m.geojson"
IMO_PAGE = "https://www.imo.org/en/ourwork/environment/pages/emission-control-areas-%28ecas%29-designated-under-regulation-13-of-marpol-annex-vi-%28nox-emission-control%29.aspx"
ARCTIC_PDF = "https://wwwcdn.imo.org/localresources/en/MediaCentre/Documents/Resolution%20MEPC.392%2882%29.pdf"
MEDITERRANEAN_PDF = "https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MEPCDocuments/MEPC.361%2879%29.pdf"
NORWEGIAN_PROPOSAL = "https://cleanarctic.org/wp-content/uploads/2024/03/MEPC-81-11-1-Proposal-to-designate-the-Norwegian-Sea-as-an-Emission-Control-Area-for-Nitrogen-Oxide-.pdf"


def _read(url):
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()
    return response.content


def _parts(text):
    text = html.unescape(re.sub(r"<[^>]*>", " ", text))
    numbers = re.findall(r"\d+", text)
    if len(numbers) < 3:
        raise ValueError("Missing coordinate: " + text[:50])
    degrees, minutes, seconds = map(int, numbers[:3])
    return degrees + minutes / 60 + seconds / 3600


def _official_html_rings(content):
    page = content.decode("utf-8")
    tables = re.findall(r"<table.*?</table>", page, re.I | re.S)
    if len(tables) < 8:
        raise ValueError("IMO coordinate tables changed")
    rings = []
    for table in tables[:4]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", table, re.I | re.S)
        if len(cells) < 3:
            raise ValueError("IMO point table changed")
        if not re.search(r"<p", cells[0], re.I):
            cells = cells[3:]
        columns = [re.findall(r"<p[^>]*>(.*?)</p>", cell, re.I | re.S) for cell in cells[:3]]
        if len(set(map(len, columns))) != 1:
            raise ValueError("IMO latitude/longitude count mismatch")
        coords = []
        for lat, lon in zip(columns[1], columns[2]):
            lat_num, lon_num = _parts(lat), _parts(lon)
            if "S" in html.unescape(re.sub(r"<[^>]*>", "", lat)).upper():
                lat_num = -lat_num
            if "W" in html.unescape(re.sub(r"<[^>]*>", "", lon)).upper():
                lon_num = -lon_num
            coords.append((lon_num, lat_num))
        rings.append(coords)
    if list(map(len, rings)) != [47, 206, 45, 55]:
        raise ValueError("IMO point counts changed: " + str(list(map(len, rings))))
    return rings


_PDF_POINT = re.compile(r"(?m)^\s*(\d{1,3})\s+(\d{1,3})[?°](\d{1,2})'[.,](\d+)\s*N\s+(\d{1,3})[?°](\d{1,2})'[.,](\d+)\s*W\b")
_NORWAY_POINT = re.compile(r"(?m)^\s*(\d{1,2})\s+(\d{1,2})[?°](\d*(?:\.\d+)?)'?\s*N\s+(\d{1,3})[?°](\d*(?:\.\d+)?)'\s*([EW])")


def _arctic_ring(content):
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages[:8])
    points = {}
    for number, latd, latm, lat_fraction, lond, lonm, lon_fraction in _PDF_POINT.findall(text):
        number = int(number)
        if number > 179:
            continue
        lat = int(latd) + (int(latm) + int(lat_fraction) / 10 ** len(lat_fraction)) / 60
        lon = -(int(lond) + (int(lonm) + int(lon_fraction) / 10 ** len(lon_fraction)) / 60)
        points[number] = (lon, lat)
    if len(points) != 179 or set(points) != set(range(1, 180)):
        raise ValueError("Canadian Arctic IMO control points changed: " + str(len(points)))
    return [points[i] for i in range(1, 180)]


def _norwegian_ring(content):
    text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
    start = text.rindex("Boundaries of the proposed emission control area")
    excerpt = text[start:start + 4500]
    points = {}
    for number, latd, latm, lond, lonm, direction in _NORWAY_POINT.findall(excerpt):
        number = int(number)
        if number > 29:
            continue
        lat = int(latd) + float(latm or 0) / 60
        lon = (int(lond) + float(lonm or 0) / 60) * (-1 if direction == "W" else 1)
        points[number] = (lon, lat)
    if set(points) != set(range(1, 30)):
        raise ValueError("Norwegian Sea control points changed: " + str(len(points)))
    return [points[i] for i in range(1, 30)]


def _polygons(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for child in geometry.geoms for part in _polygons(child)]


def _water_land():
    features = json.loads(LAND.read_text(encoding="utf-8"))["features"]
    return unary_union([shape(feature["geometry"]) for feature in features])


def _coastal_close(offshore, land, anchor):
    """Close an official offshore chain along the generalized mainland shore."""
    mainland = next(part for part in _polygons(land) if part.covers(Point(*anchor)))
    coast = LineString(mainland.exterior.coords)
    start = coast.project(Point(offshore[-1]))
    end = coast.project(Point(offshore[0]))
    total = coast.length
    def forward(a, b):
        if a <= b:
            return list(substring(coast, a, b).coords)
        return list(substring(coast, a, total).coords) + list(substring(coast, 0, b).coords)[1:]
    first = forward(start, end)
    second = list(reversed(forward(end, start)))
    shore = min((first, second), key=lambda points: LineString(points).length)
    candidate = Polygon(offshore + shore)
    return candidate.buffer(0)


def _make_feature(name, area_id, raw, land, source_url, quality):
    clean = raw.buffer(0).difference(land)
    polygons = [part for part in _polygons(clean) if part.area > 0.00001]
    if not polygons:
        raise ValueError("Empty ECA " + area_id)
    return {"type":"Feature", "geometry":mapping(unary_union(polygons)),
            "properties":{"id":area_id,"name":name,"risk_family":"eca","zone_type":"ECA",
                          "eca_controls":["SOx", "PM"],
                          "boundary_quality":quality,"display_scope":"water_only",
                          "source_title":"IMO MARPOL Annex VI / published control lines",
                          "source_url":source_url,"land_mask":"Natural Earth 1:50m",
                          "description":"IMO ECA/SECA water area; analytical coast-clipped display geometry."}}


def build():
    html_data = _read(IMO_PAGE)
    arctic_data = _read(ARCTIC_PDF)
    mediterranean_data = _read(MEDITERRANEAN_PDF)
    norway_data = _read(NORWEGIAN_PROPOSAL)
    if b"Mediterranean Sea" not in mediterranean_data and len(mediterranean_data) < 5000:
        raise ValueError("Mediterranean resolution missing")
    west, east, hawaii, caribbean = _official_html_rings(html_data)
    arctic = _arctic_ring(arctic_data)
    norway = _norwegian_ring(norway_data)
    land = _water_land()
    def marine(rect):
        return rect.difference(land)
    # Regulatory cut lines from Annex I/V and MEPC.361(79); the 1:50m
    # coastline is used only to close shores and exclude land.
    baltic_water = marine(box(9, 53, 32, 67)).difference(LineString([(8, 57.7466667), (14, 57.7466667)]).buffer(0.002))
    baltic_parts = [part for part in _polygons(baltic_water) if part.covers(Point(20, 57))]
    if not baltic_parts:
        raise ValueError("Baltic basin could not be isolated")
    baltic = unary_union(baltic_parts)
    north_sea = marine(box(-4, 48.5, 14, 62).union(box(-5, 48.5, 0, 51))).difference(baltic)
    # Gibraltar, Dardanelles and Suez controls prevent neighbouring basins
    # from inheriting Mediterranean ECA status.
    mediterranean = marine(box(-6.04, 29.5, 37, 46))
    # Close only the Dardanelles entrance; a broad eastern-Aegean rectangle
    # would wrongly remove Greek and Turkish coastal ECA waters.
    mediterranean = mediterranean.difference(
        LineString([(26.14, 40.06), (26.27, 40.01)]).buffer(0.01)
    )
    # Natural Earth joins the narrow Turkish straits at this resolution;
    # exclude Marmara/Black Sea water beyond the Dardanelles control line.
    mediterranean = mediterranean.difference(box(26.3, 40.12, 42, 48))
    mediterranean = mediterranean.difference(LineString([(-6.0333333, 36.1833333), (-5.9166667, 35.8)]).buffer(0.002))
    mediterranean_parts = [part for part in _polygons(mediterranean) if part.covers(Point(18, 36))]
    if not mediterranean_parts:
        raise ValueError("Mediterranean basin could not be isolated")
    mediterranean = unary_union(mediterranean_parts)
    areas = [
        ("Baltic Sea ECA", "eca-baltic-sea", baltic, IMO_PAGE, "regulatory_area_with_generalized_coast"),
        ("North Sea ECA", "eca-north-sea", north_sea, IMO_PAGE, "regulatory_area_with_generalized_coast"),
        ("North American ECA", "eca-north-american", unary_union([_coastal_close(west, land, (-120, 35)), _coastal_close(east, land, (-80, 35)), Polygon(hawaii).buffer(0)]), IMO_PAGE, "imo_control_points_with_generalized_coastal_closure"),
        ("United States Caribbean Sea ECA", "eca-us-caribbean", Polygon(caribbean), IMO_PAGE, "imo_control_points_with_generalized_coastal_closure"),
        ("Mediterranean Sea ECA", "eca-mediterranean", mediterranean, MEDITERRANEAN_PDF, "imo_strait_controls_with_generalized_coast"),
        ("Canadian Arctic ECA", "eca-canadian-arctic", Polygon(arctic), ARCTIC_PDF, "imo_control_points_with_generalized_coastal_closure"),
        ("Norwegian Sea ECA", "eca-norwegian-sea", Polygon(norway), NORWEGIAN_PROPOSAL, "imo_annex_ii_control_points_with_generalized_coast"),
    ]
    features = [_make_feature(*area[:3], land, *area[3:]) for area in areas]
    payload = {"type":"FeatureCollection","metadata":{
        "snapshot_date":"2026-10-12", "source":"IMO MARPOL Annex VI (and cited Annex I/II/V area definitions)",
        "land_mask":"Natural Earth 1:50m", "not_for_navigation":True,
        "source_sha256":{url:hashlib.sha256(blob).hexdigest() for url,blob in
                         [(IMO_PAGE,html_data),(ARCTIC_PDF,arctic_data),(MEDITERRANEAN_PDF,mediterranean_data),(NORWEGIAN_PROPOSAL,norway_data)]}},
        "features":features}
    OUT.write_text(json.dumps(payload, separators=(",",":"), ensure_ascii=False), encoding="utf-8")
    print([(f["properties"]["id"], round(shape(f["geometry"]).area, 1)) for f in features])
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    build()
