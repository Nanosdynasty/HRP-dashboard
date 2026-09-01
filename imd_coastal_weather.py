"""Normalize IMD coastal bulletins into map-ready forecast records.

The importer intentionally keeps only the fields used by the dashboard. Source
documents are processed in memory and are never persisted.
"""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader


log = logging.getLogger("imd-coastal-weather")

IMD_ROOT = "https://mausam.imd.gov.in/"
IMD_MARINE_PAGE = urljoin(IMD_ROOT, "responsive/text_bulletins.php")
IMD_COASTAL_PAGE = urljoin(IMD_ROOT, "responsive/coastal_forecast.php")
IMD_COASTAL_BULLETINS = [
    urljoin(IMD_ROOT, "Forecast/coastal_bulletin_new.php"),
    *[
        urljoin(IMD_ROOT, f"Forecast/coastal_bulletin_new.php?id={item}")
        for item in (2, 3, 4, 5, 6, 7)
    ],
]
REFRESH_SECONDS = 5 * 60 * 60
# A source or network issue should not leave the dashboard on an old bulletin for
# the entire regular refresh window.  Failed collection attempts are retried on a
# short, bounded interval while successful collection remains every five hours.
FAILED_REFRESH_RETRY_SECONDS = 5 * 60
KNOT_TO_KMPH = 1.852


def _polygon(*points: tuple[float, float]) -> Dict[str, Any]:
    """Create a GeoJSON polygon from (lat, lon) points."""
    ring = [[lon, lat] for lat, lon in points]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


# Generalized water-side forecast bands. They are display regions, not marine
# navigation boundaries, and deliberately sit offshore rather than over land.
ZONES: Dict[str, Dict[str, Any]] = {
    "north_gujarat": {
        "name": "North Gujarat coast",
        "aliases": ["north gujarat coast", "north gujrath coast"],
        "geometry": _polygon((24.0, 67.7), (22.0, 68.0), (20.6, 70.1), (21.1, 71.1), (22.5, 69.5), (24.1, 69.0)),
    },
    "south_gujarat": {
        "name": "South Gujarat coast",
        "aliases": ["south gujarat coast", "south gujrath coast"],
        "geometry": _polygon((21.1, 71.1), (20.6, 70.1), (18.9, 71.8), (19.2, 72.5), (20.2, 72.3)),
    },
    "north_maharashtra": {
        "name": "North Maharashtra coast",
        "aliases": ["north maharashtra coast"],
        "geometry": _polygon((20.1, 72.1), (19.0, 71.6), (17.9, 72.6), (18.2, 73.2), (19.2, 72.9)),
    },
    "south_maharashtra_goa": {
        "name": "South Maharashtra & Goa coast",
        "aliases": ["south maharashtra and goa coast", "south maharashtra & goa", "south maharashtra coast", "goa coast", "konkan & goa", "konkan and goa"],
        "geometry": _polygon((18.2, 72.7), (17.8, 72.4), (14.8, 73.0), (14.9, 73.8), (16.2, 73.6), (17.5, 73.3)),
    },
    "karnataka": {
        "name": "Karnataka coast",
        "aliases": ["karnataka coast"],
        "geometry": _polygon((14.9, 73.1), (12.6, 73.8), (12.7, 74.7), (14.4, 74.0)),
    },
    "north_kerala": {
        "name": "North Kerala coast",
        "aliases": ["north kerala coast", "kerala coast", "kerala coasts", "kerla coast", "kerla coasts", "keralam coast"],
        "geometry": _polygon((12.7, 73.8), (10.6, 74.6), (10.8, 75.6), (12.6, 74.7)),
    },
    "south_kerala": {
        "name": "South Kerala coast",
        "aliases": ["south kerala coast", "kerala coast", "kerala coasts", "kerla coast", "kerla coasts", "keralam coast"],
        "geometry": _polygon((10.8, 74.7), (8.0, 75.9), (8.2, 77.0), (9.4, 76.2), (10.8, 75.6)),
    },
    "lakshadweep": {
        "name": "Lakshadweep area",
        "aliases": ["lakshadweep area", "lakshadweep islands"],
        "geometry": _polygon((13.2, 70.4), (8.0, 70.4), (6.8, 74.0), (11.2, 74.0)),
    },
    "north_tamil_nadu": {
        "name": "North Tamil Nadu coast",
        "aliases": ["north tamilnadu coast", "north tamil nadu coast"],
        "geometry": _polygon((13.6, 80.3), (11.1, 79.5), (10.9, 80.5), (12.8, 81.1)),
    },
    "south_tamil_nadu": {
        "name": "South Tamil Nadu coast",
        "aliases": ["south tamilnadu coast", "south tamil nadu coast"],
        "geometry": _polygon((11.2, 79.5), (8.0, 77.4), (7.7, 79.0), (9.1, 79.5), (10.8, 80.5)),
    },
    "north_andhra": {
        "name": "North Andhra coast",
        "aliases": ["north andhra coast", "north coastal andhra pradesh"],
        "geometry": _polygon((19.2, 84.8), (16.1, 82.2), (15.7, 83.2), (18.2, 85.5)),
    },
    "south_andhra": {
        "name": "South Andhra coast",
        "aliases": ["south andhra coast", "south coastal andhra pradesh"],
        "geometry": _polygon((16.1, 82.2), (13.5, 80.3), (12.8, 81.2), (15.7, 83.2)),
    },
    "north_odisha": {
        "name": "North Odisha coast",
        "aliases": ["north odisha coast", "north orissa coast"],
        "geometry": _polygon((22.0, 88.3), (20.5, 86.6), (19.9, 87.5), (21.3, 89.2)),
    },
    "south_odisha": {
        "name": "South Odisha coast",
        "aliases": ["south odisha coast", "south orissa coast"],
        "geometry": _polygon((20.7, 86.6), (19.1, 84.9), (18.4, 85.8), (20.0, 87.6)),
    },
    "west_bengal": {
        "name": "West Bengal coast",
        "aliases": ["west bengal coast"],
        "geometry": _polygon((22.0, 88.2), (20.9, 88.8), (21.0, 90.0), (22.2, 89.5)),
    },
    "andaman": {
        "name": "Andaman & Nicobar area",
        "aliases": ["andaman area", "andaman sea", "andaman & nicobar", "andaman and nicobar"],
        "geometry": _polygon((14.7, 91.5), (6.2, 91.5), (5.5, 95.5), (13.8, 95.5)),
    },
}

ZONE_ALIAS_LOOKUP = sorted(
    (
        (alias.lower(), zone_id)
        for zone_id, zone in ZONES.items()
        for alias in zone["aliases"]
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)


# Port points are display anchors for official IMD coastal-area forecasts. They
# are not represented as observations at the port itself.
INDIA_COASTAL_PORTS: Dict[str, List[tuple[str, float, float]]] = {
    "north_gujarat": [
        ("Deendayal (Kandla)", 23.03, 70.22), ("Mundra", 22.74, 69.70),
    ],
    "south_gujarat": [("Dahej", 21.70, 72.58), ("Hazira", 21.11, 72.65)],
    "north_maharashtra": [
        ("Mumbai", 18.95, 72.84), ("JNPA (Nhava Sheva)", 18.95, 72.95),
    ],
    "south_maharashtra_goa": [
        ("Jaigarh", 17.30, 73.22), ("Mormugao", 15.41, 73.80),
    ],
    "karnataka": [
        ("New Mangalore", 12.93, 74.81), ("Karwar", 14.82, 74.12),
    ],
    "north_kerala": [("Beypore", 11.17, 75.80)],
    "south_kerala": [("Kochi", 9.97, 76.26), ("Vizhinjam", 8.38, 76.99)],
    "north_tamil_nadu": [
        ("Chennai", 13.09, 80.30), ("Kamarajar (Ennore)", 13.25, 80.33),
        ("Kattupalli", 13.31, 80.35),
    ],
    "south_tamil_nadu": [
        ("V.O. Chidambaranar (Tuticorin)", 8.76, 78.20),
        ("Karaikal", 10.84, 79.86),
    ],
    "north_andhra": [
        ("Visakhapatnam", 17.69, 83.30), ("Gangavaram", 17.63, 83.24),
        ("Kakinada", 16.95, 82.28),
    ],
    "south_andhra": [("Krishnapatnam", 14.25, 80.13)],
    "north_odisha": [("Paradip", 20.26, 86.68), ("Dhamra", 20.82, 86.95)],
    "south_odisha": [("Gopalpur", 19.27, 84.92)],
    "west_bengal": [("Haldia", 22.03, 88.06), ("Kolkata", 22.55, 88.30)],
    "andaman": [("Port Blair", 11.67, 92.74)],
}


def _blank_record(zone_id: str, day: int) -> Dict[str, Any]:
    zone = ZONES[zone_id]
    return {
        "zone_id": zone_id,
        "zone_name": zone["name"],
        "day": day,
        "valid_date": None,
        "rainfall_category": None,
        "wind_speed_min_kmph": None,
        "wind_speed_max_kmph": None,
        "gust_kmph": None,
        "wave_height_min_m": None,
        "wave_height_max_m": None,
        "severity": "normal",
        "summary": None,
        "source_url": None,
        "source_issue_time": None,
        "geometry": zone["geometry"],
    }


def _has_published_weather(record: Dict[str, Any]) -> bool:
    return any(record.get(field) is not None for field in (
        "rainfall_category", "wind_speed_min_kmph", "wind_speed_max_kmph",
        "gust_kmph", "wave_height_min_m", "wave_height_max_m",
    ))


def _port_weather_risk(record: Dict[str, Any]) -> Dict[str, Any]:
    wind_kmph = max(float(record.get("gust_kmph") or 0), float(record.get("wind_speed_max_kmph") or 0))
    wind_kn = wind_kmph / KNOT_TO_KMPH
    wave = float(record.get("wave_height_max_m") or 0)
    rain = str(record.get("rainfall_category") or "").lower()
    score = 2 if wind_kn > 30 else 1 if wind_kn > 20 else 0
    score += 2 if wave > 4 else 1 if wave > 2 else 0
    score += 2 if any(x in rain for x in ("extremely heavy", "very heavy", "heavy")) else 1 if any(
        x in rain for x in ("widespread", "many places", "thunder")
    ) else 0
    level = "Severe" if score >= 6 else "High" if score >= 4 else "Moderate" if score >= 2 else "Normal"
    impacts: List[str] = []
    if wind_kn > 20:
        impacts.append("Possible crane or loading restrictions")
    if wind_kn > 30:
        impacts.append("Possible berthing and pilotage restrictions")
    if record.get("rainfall_category"):
        impacts.append("Possible coal, ore or grain loading interruption")
    if wave > 2:
        impacts.append("Possible anchorage or berthing disruption")
    return {
        "weather_risk_score": score,
        "weather_risk_level": level,
        "operational_impacts": impacts,
        "risk_methodology": (
            "HRP Port Weather Disruption Index using published IMD wind, gust, wave "
            "and qualitative rainfall fields; IMD visibility is not quantified in this feed"
        ),
    }


def expand_imd_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return shared-schema marine-area and port rows for the weather UI."""
    output: List[Dict[str, Any]] = []
    for record in records:
        if not _has_published_weather(record):
            continue
        zone_id = str(record["zone_id"])
        zone_name = str(record["zone_name"])
        common = {
            **record,
            "provider_code": "imd",
            "provider": "India Meteorological Department",
            "country": "India",
            "issued_at": record.get("source_issue_time"),
            "valid_from": record.get("valid_date"),
            "valid_to": None,
            "weather_condition": record.get("rainfall_category") or "Coastal forecast",
            "weather_description": record.get("summary"),
            "warning_description": None,
            "marine_area": zone_name,
            "wind_direction_from": None,
            "wind_direction_to": None,
            "wave_category": None,
            "forecast_day": record.get("day"),
        }
        area = {
            **common,
            "location_type": "water",
            "location_id": f"imd-area-{zone_id}",
            "location_name": zone_name,
            "latitude": None,
            "longitude": None,
            "forecast_basis": "Official IMD coastal-area forecast polygon",
        }
        output.append(area)
        for port_name, latitude, longitude in INDIA_COASTAL_PORTS.get(zone_id, []):
            slug = re.sub(r"[^a-z0-9]+", "-", port_name.lower()).strip("-")
            port = {
                **common,
                **_port_weather_risk(record),
                "location_type": "port",
                "location_id": f"imd-port-{slug}",
                "location_name": port_name,
                "latitude": latitude,
                "longitude": longitude,
                "geometry": None,
                "port_type": "Trading port",
                "forecast_basis": (
                    f"Official IMD coastal-area forecast ({zone_name}) mapped to port location; "
                    "not a port observation"
                ),
            }
            output.append(port)
    return output


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>|</(?:p|tr|td|th|div|h\d)>", " \n ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _number_range(text: str, units: str) -> Optional[tuple[float, float]]:
    match = re.search(
        rf"(\d+(?:\.\d+)?)\s*(?:-|–|TO)\s*(\d+(?:\.\d+)?)\s*{units}",
        text,
        re.IGNORECASE,
    )
    if not match:
        single = re.search(rf"(\d+(?:\.\d+)?)\s*{units}", text, re.IGNORECASE)
        return (float(single.group(1)), float(single.group(1))) if single else None
    return float(match.group(1)), float(match.group(2))


def _rain_category(text: str) -> Optional[str]:
    lowered = text.lower()
    categories = [
        ("extremely heavy", "Extremely heavy"),
        ("very heavy", "Very heavy"),
        ("heavy", "Heavy"),
        ("fairly widespread", "Fairly widespread rain"),
        ("widespread", "Widespread rain"),
        ("many places", "Rain at many places"),
        ("scattered", "Scattered rain"),
        ("isolated", "Isolated rain"),
        ("rain", "Rain / thundershowers"),
    ]
    for needle, label in categories:
        if needle in lowered:
            return label
    return None


def _severity(record: Dict[str, Any]) -> str:
    gust = record.get("gust_kmph") or record.get("wind_speed_max_kmph") or 0
    wave = record.get("wave_height_max_m") or 0
    rain = str(record.get("rainfall_category") or "").lower()
    if gust >= 75 or wave >= 4 or "extremely heavy" in rain or "very heavy" in rain:
        return "warning"
    if gust >= 45 or wave >= 2.5 or "heavy" in rain or "widespread" in rain:
        return "advisory"
    return "normal"


def _apply_weather_text(record: Dict[str, Any], text: str) -> None:
    wind_knots = _number_range(text, r"(?:KNOTS?|KTS?)")
    wind_kmph = _number_range(text, r"KMPH")
    if wind_knots:
        record["wind_speed_min_kmph"] = round(wind_knots[0] * KNOT_TO_KMPH, 1)
        record["wind_speed_max_kmph"] = round(wind_knots[1] * KNOT_TO_KMPH, 1)
    elif wind_kmph:
        record["wind_speed_min_kmph"] = wind_kmph[0]
        record["wind_speed_max_kmph"] = wind_kmph[1]
    gust = re.search(
        r"(?:GUSTING(?:\s+TO)?|GUSTY\s+WINDS?(?:\s+SPEED\s+REACHING)?)\s*"
        r"(\d+(?:\.\d+)?)\s*(KNOTS?|KTS?|KMPH)",
        text,
        re.IGNORECASE,
    )
    if gust:
        value = float(gust.group(1))
        record["gust_kmph"] = round(
            value * KNOT_TO_KMPH if gust.group(2).upper().startswith(("KNOT", "KT")) else value,
            1,
        )
    wave = re.search(
        r"(?:HIGH|SWELL)?\s*WAVES?.{0,80}?"
        r"(?:RANGE\s+OF\s+)?(\d+(?:\.\d+)?)\s*(?:-|–|TO)\s*"
        r"(\d+(?:\.\d+)?)\s*(?:M|METERS?)\b",
        text,
        re.IGNORECASE,
    )
    if wave:
        record["wave_height_min_m"] = float(wave.group(1))
        record["wave_height_max_m"] = float(wave.group(2))
    record["rainfall_category"] = _rain_category(text)
    record["severity"] = _severity(record)


def _find_zone_ids(text: str) -> List[str]:
    lowered = text.lower()
    found: List[str] = []
    for alias, zone_id in ZONE_ALIAS_LOOKUP:
        if alias in lowered and zone_id not in found:
            found.append(zone_id)
    return found


def parse_coastal_bulletin_html(
    page_html: str, source_url: str
) -> List[Dict[str, Any]]:
    """Parse current 12-hour regional coastal values."""
    text = re.sub(r"\s+", " ", _html_to_text(page_html))
    issue = re.search(
        r"Time of Issue\s*:?\s*("
        r"\d{1,2}[:.]\d{2}\s*(?:HRS\s*)?IST"
        r"(?:\s+of\s+\d{4}-\d{2}-\d{2})?"
        r")",
        text,
        re.IGNORECASE,
    )
    valid = re.search(
        r"Valid for 12 hrs from\s+(.+?)\s+to\s+(.+?)(?:Synoptic Situation|-->)",
        text,
        re.IGNORECASE,
    )
    issue_text = issue.group(1).strip() if issue else None
    valid_text = valid.group(1).strip() if valid else None
    candidates: List[tuple[int, int, str]] = []
    lowered = text.lower()
    for alias, zone_id in ZONE_ALIAS_LOOKUP:
        for match in re.finditer(re.escape(alias), lowered):
            candidates.append((match.start(), match.end(), zone_id))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    positions: List[tuple[int, str]] = []
    occupied: List[tuple[int, int]] = []
    seen_zones: set[str] = set()
    for start, end, zone_id in candidates:
        if zone_id in seen_zones:
            continue
        if any(start < prior_end and end > prior_start for prior_start, prior_end in occupied):
            continue
        positions.append((start, zone_id))
        occupied.append((start, end))
        seen_zones.add(zone_id)
    positions.sort()
    records: List[Dict[str, Any]] = []
    for index, (start, zone_id) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        section = text[start:end]
        if " Wind " not in section and not re.search(r"\bWIND\b", section, re.I):
            continue
        record = _blank_record(zone_id, 1)
        _apply_weather_text(record, section)
        record["source_url"] = source_url
        record["source_issue_time"] = issue_text
        record["valid_date"] = valid_text
        record["summary"] = _summary(record)
        records.append(record)
    return records


def extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def latest_document_date(text: str) -> Optional[datetime]:
    """Return the latest explicit calendar date found in a bulletin."""
    values: List[datetime] = []
    for day, month, year in re.findall(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", text
    ):
        numeric_year = int(year)
        if numeric_year < 100:
            numeric_year += 2000
        try:
            values.append(
                datetime(numeric_year, int(month), int(day), tzinfo=timezone.utc)
            )
        except ValueError:
            continue
    for year, month, day in re.findall(
        r"\b(20\d{2})[./-](\d{1,2})[./-](\d{1,2})\b", text
    ):
        try:
            values.append(
                datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
            )
        except ValueError:
            continue
    return max(values) if values else None


def parse_five_day_warning_text(
    pdf_text: str, source_url: str
) -> List[Dict[str, Any]]:
    """Extract explicitly published Day 1–5 coastal/sea warnings."""
    cleaned = re.sub(r"\s+", " ", pdf_text.replace("\r", "\n"))
    issue = re.search(
        r"(?:Time of Issue|TIME OF ISSUE)\s*:?\s*("
        r"(?:\d{1,2}[:.]\d{2}|\d{3,4})\s*(?:HRS\s*)?IST"
        r"(?:\s+of\s+\d{4}-\d{2}-\d{2})?"
        r")",
        cleaned,
        re.IGNORECASE,
    )
    day_matches = list(
        re.finditer(
            r"(?i)\bDAY\s*[-:]?\s*([1-5])\b",
            cleaned,
        )
    )
    records: List[Dict[str, Any]] = []
    for index, match in enumerate(day_matches):
        day = int(match.group(1))
        end = day_matches[index + 1].start() if index + 1 < len(day_matches) else len(cleaned)
        segment = cleaned[match.start():end]
        heading = cleaned[match.start(): min(match.start() + 48, end)]
        valid_date_match = re.search(
            r"\((\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\)", heading
        )
        # Warning sentences normally share one value across all named sea areas.
        sentences = re.split(r"(?<=[.;])\s+", segment)
        for sentence in sentences:
            zone_ids = _find_zone_ids(sentence)
            if not zone_ids:
                continue
            if not re.search(
                r"rain|thunder|wind|squall|wave|rough|storm", sentence, re.I
            ):
                continue
            for zone_id in zone_ids:
                record = _blank_record(zone_id, day)
                _apply_weather_text(record, sentence)
                if not any(
                    record.get(field) is not None
                    for field in (
                        "rainfall_category",
                        "wind_speed_max_kmph",
                        "gust_kmph",
                        "wave_height_max_m",
                    )
                ):
                    continue
                record["source_url"] = source_url
                record["source_issue_time"] = issue.group(1).strip() if issue else None
                record["valid_date"] = (
                    valid_date_match.group(1) if valid_date_match else None
                )
                record["summary"] = _summary(record)
                records.append(record)
    return records


def _summary(record: Dict[str, Any]) -> str:
    parts: List[str] = []
    if record.get("rainfall_category"):
        parts.append(str(record["rainfall_category"]))
    if record.get("wind_speed_max_kmph") is not None:
        wind = f'{record["wind_speed_min_kmph"]:g}–{record["wind_speed_max_kmph"]:g} km/h'
        if record.get("gust_kmph") is not None:
            wind += f' (gust {record["gust_kmph"]:g})'
        parts.append(wind)
    if record.get("wave_height_max_m") is not None:
        parts.append(
            f'{record["wave_height_min_m"]:g}–{record["wave_height_max_m"]:g} m waves'
        )
    return " · ".join(parts) or "No quantified warning in the source bulletin"


def merge_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, int], Dict[str, Any]] = {}
    severity_order = {"normal": 0, "advisory": 1, "warning": 2}
    for incoming in records:
        key = (incoming["zone_id"], int(incoming["day"]))
        current = merged.setdefault(key, _blank_record(*key))
        for field in (
            "valid_date",
            "rainfall_category",
            "wind_speed_min_kmph",
            "wind_speed_max_kmph",
            "gust_kmph",
            "wave_height_min_m",
            "wave_height_max_m",
            "source_issue_time",
        ):
            value = incoming.get(field)
            if value is None:
                continue
            if field in {
                "wind_speed_max_kmph",
                "gust_kmph",
                "wave_height_max_m",
            }:
                current[field] = max(value, current.get(field) or value)
            elif current.get(field) is None or int(incoming["day"]) == 1:
                current[field] = value
        source_url = incoming.get("source_url")
        if source_url:
            sources = current.setdefault("source_urls", [])
            if source_url not in sources:
                sources.append(source_url)
            current["source_url"] = sources[0]
        if severity_order.get(incoming.get("severity", "normal"), 0) > severity_order.get(
            current.get("severity", "normal"), 0
        ):
            current["severity"] = incoming["severity"]
    # Include every zone/day so the selector is predictable and absence is explicit.
    for day in range(1, 6):
        for zone_id in ZONES:
            merged.setdefault((zone_id, day), _blank_record(zone_id, day))
    output = list(merged.values())
    for record in output:
        record["severity"] = _severity(record)
        record["summary"] = _summary(record)
    return sorted(output, key=lambda row: (row["day"], row["zone_name"]))


def discover_pdf_urls(page_html: str) -> List[str]:
    """Extract only official current marine PDFs linked by the IMD page."""
    paths = re.findall(
        r"(?i)href\s*=\s*[\"']?([^\"'\s>]+\.pdf(?:\?[^\"'\s>]*)?)",
        page_html,
    )
    output: List[str] = []
    for path in paths:
        url = urljoin(IMD_MARINE_PAGE, html.unescape(path))
        parsed = urlparse(url)
        if parsed.hostname != "mausam.imd.gov.in":
            continue
        if "/backend/assets/" not in parsed.path:
            continue
        if url not in output:
            output.append(url)
    return output


class ImdCoastalWeatherManager:
    def __init__(self, cache_path: Path, refresh_seconds: int = REFRESH_SECONDS):
        self.cache_path = cache_path
        self.refresh_seconds = refresh_seconds
        self.payload: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        self.stopping = False
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            self.payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.payload = {}

    async def refresh(self, force: bool = False) -> Dict[str, Any]:
        async with self.lock:
            fetched_at = self.payload.get("fetched_at")
            if not force and fetched_at:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
                    if age.total_seconds() < self.refresh_seconds:
                        return self.payload
                except ValueError:
                    pass
            headers = {
                "User-Agent": "HRP-Dashboard/1.0 (+IMD coastal forecast visualization)"
            }
            records: List[Dict[str, Any]] = []
            pdf_urls: List[str] = []
            errors: List[str] = []
            skips: List[str] = []
            async with httpx.AsyncClient(
                headers=headers, follow_redirects=True, timeout=40
            ) as client:
                marine_response = await client.get(IMD_MARINE_PAGE)
                marine_response.raise_for_status()
                pdf_urls = discover_pdf_urls(marine_response.text)
                requests = [
                    *(client.get(url) for url in IMD_COASTAL_BULLETINS),
                    *(client.get(url) for url in pdf_urls),
                ]
                responses = await asyncio.gather(*requests, return_exceptions=True)
            coastal_responses = responses[: len(IMD_COASTAL_BULLETINS)]
            pdf_responses = responses[len(IMD_COASTAL_BULLETINS):]
            for url, response in zip(IMD_COASTAL_BULLETINS, coastal_responses):
                try:
                    if isinstance(response, Exception):
                        raise response
                    response.raise_for_status()
                    records.extend(parse_coastal_bulletin_html(response.text, url))
                except Exception as exc:  # keep other regional sources usable
                    errors.append(f"{url}: {exc}")
            for url, response in zip(pdf_urls, pdf_responses):
                try:
                    if isinstance(response, Exception):
                        raise response
                    response.raise_for_status()
                    pdf_text = extract_pdf_text(response.content)
                    document_date = latest_document_date(pdf_text)
                    if (
                        document_date is None
                        or abs(
                            (
                                datetime.now(timezone.utc) - document_date
                            ).total_seconds()
                        )
                        > 14 * 24 * 60 * 60
                    ):
                        skips.append(
                            f"{url}: skipped stale or undated bulletin"
                        )
                        continue
                    records.extend(
                        parse_five_day_warning_text(
                            pdf_text, url
                        )
                    )
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
            if not records:
                raise RuntimeError("IMD sources returned no parseable coastal records")
            now = datetime.now(timezone.utc)
            payload = {
                "provider": "India Meteorological Department",
                "source_page": IMD_COASTAL_PAGE,
                "fetched_at": now.isoformat(),
                "next_refresh_at": (
                    now + timedelta(seconds=self.refresh_seconds)
                ).isoformat(),
                "refresh_seconds": self.refresh_seconds,
                "coverage_note": (
                    "Generalized offshore display regions—not for navigation. "
                    "Blank values mean IMD did not quantify that field in the parsed bulletin."
                ),
                "source_document_count": len(pdf_urls),
                "source_skips": skips,
                "parse_warnings": errors,
                "rows": merge_records(records),
            }
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.payload = payload
            self.last_error = "; ".join(errors[:3]) if errors else None
            return payload

    async def _run(self) -> None:
        while not self.stopping:
            wait_seconds = self.refresh_seconds
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("IMD coastal refresh failed: %s", exc)
                wait_seconds = min(self.refresh_seconds, FAILED_REFRESH_RETRY_SECONDS)
            await asyncio.sleep(wait_seconds)

    def start(self) -> None:
        if not self.task or self.task.done():
            self.stopping = False
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.stopping = True
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
