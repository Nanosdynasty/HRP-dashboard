"""
Maritime helpers: WPI depth/harbor enrichment, maritime-risk zone analysis,
Open-Meteo marine weather, EuroOilWatch bunker prices, fuel-cost estimator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import math
from shapely.geometry import LineString, Point, shape

import httpx

BASE_DIR = Path(__file__).parent
ZONES_PATH = BASE_DIR / "data" / "zones.json"
ECA_PATH = BASE_DIR / "data" / "imo_eca_verified.geojson"

# ---------------------------------------------------------------------------
# WPI letter-code maps (Pub 150)
# ---------------------------------------------------------------------------
DEPTH_CODE: Dict[str, str] = {
    "A": "≥ 23.2 m (76 ft+)",
    "B": "21.6 – 22.9 m",
    "C": "20.1 – 21.3 m",
    "D": "18.6 – 19.8 m",
    "E": "17.1 – 18.2 m",
    "F": "15.5 – 16.8 m",
    "G": "14.0 – 15.2 m",
    "H": "12.5 – 13.7 m",
    "I": "11.0 – 12.2 m",
    "J": "11.0 – 12.2 m",
    "K": "9.4 – 10.7 m",
    "L": "7.9 – 9.1 m",
    "M": "6.4 – 7.6 m",
    "N": "4.9 – 6.1 m",
    "O": "3.4 – 4.6 m",
    "P": "1.8 – 3.0 m",
    "Q": "0 – 1.5 m",
}

HARBOR_SIZE: Dict[str, str] = {
    "V": "Very small",
    "S": "Small",
    "M": "Medium",
    "L": "Large",
}

HARBOR_TYPE: Dict[str, str] = {
    "CN": "Coastal natural",
    "CB": "Coastal breakwater",
    "CT": "Coastal tide gate",
    "RN": "River natural",
    "RB": "River basin",
    "RT": "River tide gate",
    "OR": "Open roadstead / offshore terminal",
    "LC": "Lake or canal",
    "TH": "Typhoon harbor",
}

MAX_VESSEL: Dict[str, str] = {
    "L": "Large (deep-draft capable)",
    "M": "Medium",
    "S": "Small",
    "V": "Very small / restricted",
}


def enrich_port_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """Turn raw WPI letter codes into human-readable port details for popups."""
    chan = str(row.get("CHAN_DEPTH") or row.get("chan_depth") or "").strip().upper()
    cargo = str(row.get("CARGODEPTH") or row.get("cargo_depth") or "").strip().upper()
    hsize = str(row.get("HARBORSIZE") or row.get("harbor_size") or "").strip().upper()
    htype = str(row.get("HARBORTYPE") or row.get("harbor_type") or "").strip().upper()
    maxv = str(row.get("MAX_VESSEL") or row.get("max_vessel") or "").strip().upper()

    details = {
        "channel_depth": DEPTH_CODE.get(chan, chan or "Unknown"),
        "channel_depth_code": chan or None,
        "cargo_depth": DEPTH_CODE.get(cargo, cargo or "Unknown / n/a"),
        "cargo_depth_code": cargo or None,
        "harbor_size": HARBOR_SIZE.get(hsize, hsize or "Unknown"),
        "harbor_type": HARBOR_TYPE.get(htype, htype or "Unknown"),
        "max_vessel": MAX_VESSEL.get(maxv, maxv or "Unknown"),
        "anchorage_note": (
            "Open roadstead / offshore – vessels typically anchor or use SPM / SBM"
            if htype == "OR"
            else "Check local sailing directions for designated anchorage depths"
        ),
    }
    return details


# ---------------------------------------------------------------------------
# Maritime risk zones (JWC + piracy watch)
# ---------------------------------------------------------------------------
_zones_cache: Optional[Dict] = None

def _append_eca_features(payload: Dict) -> Dict:
    features = payload.setdefault("features", [])
    existing = {str((item.get("properties") or {}).get("id")) for item in features}
    if ECA_PATH.exists():
        snapshot = json.loads(ECA_PATH.read_text(encoding="utf-8"))
        for feature in snapshot.get("features", []):
            if str((feature.get("properties") or {}).get("id")) not in existing:
                features.append(feature)
        payload.setdefault("metadata", {})["eca_snapshot"] = snapshot.get("metadata", {})
    else:
        payload.setdefault("metadata", {})["eca_limitation"] = "Verified ECA geometry unavailable; no ECA route is highlighted."
    return payload


def load_zones() -> Dict:
    global _zones_cache
    if _zones_cache is not None:
        return _zones_cache
    if ZONES_PATH.exists():
        with open(ZONES_PATH, encoding="utf-8") as f:
            _zones_cache = _append_eca_features(json.load(f))
    else:
        _zones_cache = {"type": "FeatureCollection", "features": []}
    return _zones_cache


def _point_in_poly(lon: float, lat: float, poly: List[List[float]]) -> bool:
    """Ray-casting point-in-polygon; points on the boundary count as outside."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        cross = (lon - xi) * (yj - yi) - (lat - yi) * (xj - xi)
        tolerance = 1e-9 * (1.0 + abs(xj - xi) + abs(yj - yi))
        if (
            abs(cross) <= tolerance
            and min(xi, xj) - tolerance <= lon <= max(xi, xj) + tolerance
            and min(yi, yj) - tolerance <= lat <= max(yi, yj) + tolerance
        ):
            return False
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def _geometry_rings(geometry: Dict[str, Any]) -> Iterable[List[List[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon" and coordinates:
        yield coordinates[0]
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            if polygon:
                yield polygon[0]


def _feature_contains(feature: Dict[str, Any], lon: float, lat: float) -> bool:
    return any(
        _point_in_poly(lon, lat, ring)
        for ring in _geometry_rings(feature.get("geometry") or {})
    )


def point_risk_families(
    lon: float,
    lat: float,
    selected_families: Optional[Iterable[str]] = None,
) -> Set[str]:
    selected = {
        str(value).lower() for value in (selected_families or ("jwc", "piracy"))
    }
    families: Set[str] = set()
    for feature in load_zones().get("features", []):
        family = str(
            (feature.get("properties") or {}).get("risk_family") or ""
        ).lower()
        if family in selected and _feature_contains(feature, lon, lat):
            families.add(family)
    return families


def _haversine_nm(left: List[float], right: List[float]) -> float:
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    delta_lon = (lon2 - lon1 + math.pi) % (2 * math.pi) - math.pi
    delta_lat = lat2 - lat1
    hav = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(hav)))


def _segment_samples(
    left: List[float],
    right: List[float],
    max_step_nm: float = 10.0,
) -> Iterable[Tuple[float, float, float]]:
    distance_nm = _haversine_nm(left, right)
    steps = max(1, math.ceil(distance_nm / max_step_nm))
    step_nm = distance_nm / steps
    lon_delta = (right[0] - left[0] + 180.0) % 360.0 - 180.0
    for index in range(steps):
        fraction = (index + 0.5) / steps
        lon = (left[0] + lon_delta * fraction + 180.0) % 360.0 - 180.0
        lat = left[1] + (right[1] - left[1]) * fraction
        yield lon, lat, step_nm


def _intersection_points(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Point":
        yield geometry
    elif geometry.geom_type in {"LineString", "LinearRing"}:
        yield Point(geometry.coords[0])
        yield Point(geometry.coords[-1])
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _intersection_points(part)


def _split_route_eca(coords: List[List[float]], features: List[Dict]) -> List[Dict[str, Any]]:
    """Split displayed straight route legs at coast-clipped ECA boundaries."""
    ecas = [(str(f["properties"]["id"]), shape(f["geometry"])) for f in features
            if (f.get("properties") or {}).get("risk_family") == "eca"
            and f["properties"].get("boundary_quality") != "official_area_envelope"]
    segments: List[Dict[str, Any]] = []
    for left, right in zip(coords, coords[1:]):
        if left == right:
            continue
        # The ordinary Leaflet line and these geometries use the same lon/lat
        # interpolation. A dateline jump cannot be safely classified here.
        if abs(right[0] - left[0]) > 180:
            pieces = [(left, right, (), "unverified")]
        else:
            line = LineString([left, right])
            boundaries = [0.0, 1.0]
            for _, geometry in ecas:
                if not line.intersects(geometry):
                    continue
                for crossing in _intersection_points(line.intersection(geometry.boundary)):
                    boundaries.append(line.project(crossing) / line.length)
            boundaries = sorted(set(round(max(0, min(1, value)), 12) for value in boundaries))
            pieces = []
            for start, end in zip(boundaries, boundaries[1:]):
                if end - start <= 1e-12:
                    continue
                midpoint = line.interpolate((start + end) * line.length / 2)
                inside = tuple(zone_id for zone_id, geometry in ecas if geometry.contains(midpoint))
                first, last = line.interpolate(start * line.length), line.interpolate(end * line.length)
                pieces.append(([first.x, first.y], [last.x, last.y], inside, "verified" if ecas else "unverified"))
        for first, last, zone_ids, quality in pieces:
            if segments and segments[-1]["zone_ids"] == list(zone_ids) and segments[-1]["boundary_status"] == quality and segments[-1]["coordinates"][-1] == first:
                segments[-1]["coordinates"].append(last)
            else:
                segments.append({"coordinates": [first, last], "in_eca": bool(zone_ids),
                                 "zone_ids": list(zone_ids), "boundary_status": quality})
    for item in segments:
        item["distance_nm"] = round(sum(_haversine_nm(a, b) for a, b in
                                         zip(item["coordinates"], item["coordinates"][1:])), 3)
    return segments


def analyze_route_zones(coords: List[List[float]]) -> Dict[str, Any]:
    """
    Measure route exposure to JWC listed waters and analytical piracy-watch
    envelopes. Distances are sampled along each segment rather than inferred
    from the number of route vertices.
    """
    zones = load_zones()
    features = zones.get("features", [])
    eca_segments = _split_route_eca(coords, features)
    exposure_by_id: Dict[str, float] = {}
    total_distance_nm = 0.0
    for index in range(1, len(coords)):
        left, right = coords[index - 1], coords[index]
        segment_nm = _haversine_nm(left, right)
        total_distance_nm += segment_nm
        for lon, lat, step_nm in _segment_samples(left, right):
            for feature in features:
                props = feature.get("properties") or {}
                if props.get("risk_family") == "eca":
                    continue
                if _feature_contains(feature, lon, lat):
                    zone_id = str(props.get("id") or props.get("name"))
                    exposure_by_id[zone_id] = (
                        exposure_by_id.get(zone_id, 0.0) + step_nm
                    )

    exposures: List[Dict[str, Any]] = []
    for feature in features:
        props = feature.get("properties") or {}
        zone_id = str(props.get("id") or props.get("name"))
        distance_nm = exposure_by_id.get(zone_id, 0.0)
        if distance_nm <= 0.05:
            continue
        exposures.append({
            "id": zone_id,
            "name": props.get("name"),
            "risk_family": props.get("risk_family"),
            "zone_type": props.get("zone_type"),
            "description": props.get("description"),
            "boundary_quality": props.get("boundary_quality"),
            "source_title": props.get("source_title"),
            "source_url": props.get("source_url"),
            "distance_nm": round(distance_nm, 1),
            "fraction": round(
                distance_nm / total_distance_nm if total_distance_nm else 0.0,
                4,
            ),
        })

    jwc_distance_nm = sum(
        item["distance_nm"]
        for item in exposures
        if item["risk_family"] == "jwc"
    )
    piracy_distance_nm = sum(
        item["distance_nm"]
        for item in exposures
        if item["risk_family"] == "piracy"
    )
    eca_distance_nm = sum(item["distance_nm"] for item in eca_segments if item["in_eca"])
    eca_by_id: Dict[str, float] = {}
    for segment in eca_segments:
        for zone_id in segment["zone_ids"]:
            eca_by_id[zone_id] = eca_by_id.get(zone_id, 0.0) + segment["distance_nm"]
    eca_zones = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("risk_family") != "eca":
            continue
        distance_nm = eca_by_id.get(str(props.get("id")), 0.0)
        if distance_nm <= 0.05:
            continue
        eca_zones.append({"id": props.get("id"), "name": props.get("name"),
                          "risk_family": "eca", "zone_type": "ECA",
                          "source_url": props.get("source_url"),
                          "boundary_quality": props.get("boundary_quality"),
                          "distance_nm": round(distance_nm, 1),
                          "fraction": round(distance_nm / total_distance_nm, 4) if total_distance_nm else 0.0})
    exposures.extend(eca_zones)
    return {
        "exposures": exposures,
        "jwc_zones": [
            item for item in exposures if item["risk_family"] == "jwc"
        ],
        "piracy_zones": [
            item for item in exposures if item["risk_family"] == "piracy"
        ],
        "jwc_distance_nm": round(jwc_distance_nm, 1),
        "piracy_distance_nm": round(piracy_distance_nm, 1),
        "jwc_fraction": round(
            jwc_distance_nm / total_distance_nm if total_distance_nm else 0.0,
            4,
        ),
        "piracy_fraction": round(
            piracy_distance_nm / total_distance_nm if total_distance_nm else 0.0,
            4,
        ),
        "route_distance_nm": round(total_distance_nm, 1),
        "eca_zones": eca_zones,
        "eca_segments": eca_segments,
        "eca_boundary_status": "verified" if features and any(
            (f.get("properties") or {}).get("risk_family") == "eca" for f in features
        ) and all(item["boundary_status"] == "verified" for item in eca_segments) else "unverified",
        "eca_distance_nm": round(eca_distance_nm, 1),
        "eca_fraction": round(
            eca_distance_nm
            / total_distance_nm if total_distance_nm else 0.0,
            4,
        ),
        "requires_mgo": eca_distance_nm > 0,
    }


# ---------------------------------------------------------------------------
# Weather (Open-Meteo Marine — free, no key)
# ---------------------------------------------------------------------------
async def fetch_weather(lat: float, lon: float) -> Dict[str, Any]:
    """Current marine conditions + wind at a point."""
    url = "https://marine-api.open-meteo.com/v1/marine"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "wave_height",
            "wave_direction",
            "wave_period",
            "wind_wave_height",
            "ocean_current_velocity",
            "ocean_current_direction",
            "sea_surface_temperature",
        ]),
        "timezone": "UTC",
    }
    wind_url = "https://api.open-meteo.com/v1/forecast"
    wind_params = {
        "latitude": lat,
        "longitude": lon,
        "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "kn",
        "timezone": "UTC",
    }
    out: Dict[str, Any] = {"lat": lat, "lon": lon, "source": "Open-Meteo"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                cur = data.get("current", {})
                out.update({
                    "wave_height_m": cur.get("wave_height"),
                    "wave_direction_deg": cur.get("wave_direction"),
                    "wave_period_s": cur.get("wave_period"),
                    "wind_wave_height_m": cur.get("wind_wave_height"),
                    "current_velocity_ms": cur.get("ocean_current_velocity"),
                    "current_direction_deg": cur.get("ocean_current_direction"),
                    "sst_c": cur.get("sea_surface_temperature"),
                    "time": cur.get("time"),
                })
            rw = await client.get(wind_url, params=wind_params)
            if rw.status_code == 200:
                wcur = rw.json().get("current", {})
                out["wind_speed_kn"] = wcur.get("wind_speed_10m")
                out["wind_direction_deg"] = wcur.get("wind_direction_10m")
                out["wind_gusts_kn"] = wcur.get("wind_gusts_10m")
    except Exception as e:
        out["error"] = str(e)
    return out


# ---------------------------------------------------------------------------
# Bunker prices (EuroOilWatch free derived estimates)
# ---------------------------------------------------------------------------
_DEFAULT_BUNKER = {
    "vlsfo_usd_mt": 580.0,
    "mgo_usd_mt": 820.0,
    "hsfo_usd_mt": 480.0,
    "source": "fallback illustrative (update live)",
    "note": "Approximate global average — not a live quote",
}


async def fetch_bunker_prices() -> Dict[str, Any]:
    """Try EuroOilWatch free bunker endpoint; fall back to defaults."""
    url = "https://eurooilwatch.com/api/v1/bunker"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                vlsfo = (
                    data.get("vlsfo")
                    or data.get("VLSFO")
                    or data.get("vlsfo_usd")
                    or data.get("prices", {}).get("vlsfo")
                )
                mgo = (
                    data.get("mgo")
                    or data.get("MGO")
                    or data.get("mgo_usd")
                    or data.get("prices", {}).get("mgo")
                )
                if isinstance(vlsfo, dict):
                    vlsfo = vlsfo.get("price") or vlsfo.get("usd")
                if isinstance(mgo, dict):
                    mgo = mgo.get("price") or mgo.get("usd")
                out = {
                    "vlsfo_usd_mt": float(vlsfo) if vlsfo is not None else _DEFAULT_BUNKER["vlsfo_usd_mt"],
                    "mgo_usd_mt": float(mgo) if mgo is not None else _DEFAULT_BUNKER["mgo_usd_mt"],
                    "hsfo_usd_mt": float(
                        data.get("hsfo") or data.get("HSFO") or _DEFAULT_BUNKER["hsfo_usd_mt"]
                    ),
                    "source": "EuroOilWatch (derived from Brent)",
                    "raw": data,
                    "note": "Illustrative estimate — verify with broker for fixture",
                }
                return out
    except Exception:
        pass
    return dict(_DEFAULT_BUNKER)


def estimate_fuel_cost(
    distance_nm: float,
    speed_knots: float,
    consumption_tpd: float,
    eca_fraction: float,
    bunker: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Simple voyage fuel model:
    - Days = distance / (speed * 24)
    - Total tons = days * consumption_tpd
    - Split by eca_fraction → MGO inside ECA, VLSFO outside
    - Cost = tons_mgo * mgo_price + tons_vlsfo * vlsfo_price
    """
    if speed_knots <= 0:
        speed_knots = 12.0
    days = distance_nm / (speed_knots * 24.0)
    total_tons = days * consumption_tpd
    mgo_tons = total_tons * eca_fraction
    vlsfo_tons = total_tons * (1.0 - eca_fraction)
    mgo_price = float(bunker.get("mgo_usd_mt", 820))
    vlsfo_price = float(bunker.get("vlsfo_usd_mt", 580))
    cost_mgo = mgo_tons * mgo_price
    cost_vlsfo = vlsfo_tons * vlsfo_price
    return {
        "distance_nm": round(distance_nm, 1),
        "steaming_days": round(days, 2),
        "consumption_tpd": consumption_tpd,
        "total_fuel_mt": round(total_tons, 1),
        "mgo_mt": round(mgo_tons, 1),
        "vlsfo_mt": round(vlsfo_tons, 1),
        "mgo_price_usd_mt": mgo_price,
        "vlsfo_price_usd_mt": vlsfo_price,
        "cost_mgo_usd": round(cost_mgo, 0),
        "cost_vlsfo_usd": round(cost_vlsfo, 0),
        "total_fuel_cost_usd": round(cost_mgo + cost_vlsfo, 0),
        "eca_fraction": eca_fraction,
        "fuel_note": (
            "Inside ECA only MGO (≤0.10% S) may be used. "
            "Outside ECA VLSFO (0.50% S) is assumed. "
            "HSFO only with scrubber (not modelled here)."
        ),
        "bunker_source": bunker.get("source"),
    }
