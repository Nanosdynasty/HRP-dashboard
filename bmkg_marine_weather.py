"""Normalize BMKG maritime forecasts into map-ready port and water records.

Only the normalized fields used by the dashboard are persisted.  BMKG source
files are requested as JSON and are not retained verbatim.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import httpx


log = logging.getLogger("bmkg-marine-weather")

BMKG_ROOT = "https://maritim.bmkg.go.id/"
BMKG_PORT_LIST = f"{BMKG_ROOT}public_api/pelabuhan_list"
BMKG_WATER_LIST = f"{BMKG_ROOT}public_api/perairan_list"
BMKG_PORT_FILE = f"{BMKG_ROOT}public_api/pelabuhan/{{file_name}}"
BMKG_WATER_FILE = f"{BMKG_ROOT}public_api/perairan/{{file_name}}"
BMKG_WATER_GEOMETRY = f"{BMKG_ROOT}public_api/static/wilayah_perairan.json"
BMKG_PORT_SOURCE = f"{BMKG_ROOT}cuaca/pelabuhan"
BMKG_WATER_SOURCE = f"{BMKG_ROOT}cuaca/perairan"
REFRESH_SECONDS = 3 * 60 * 60
FAILED_REFRESH_RETRY_SECONDS = 10 * 60
SCHEMA_VERSION = 3

DIRECTION_EN = {
    "utara": "North", "timur laut": "Northeast", "timur": "East",
    "tenggara": "Southeast", "selatan": "South", "barat daya": "Southwest",
    "barat": "West", "barat laut": "Northwest", "bervariasi": "Variable",
}
WEATHER_EN = {
    "cerah": "Clear", "cerah berawan": "Partly cloudy", "berawan": "Cloudy",
    "berawan tebal": "Overcast", "hujan": "Rain", "hujan ringan": "Light rain",
    "hujan sedang": "Moderate rain", "hujan lebat": "Heavy rain",
    "hujan sangat lebat": "Very heavy rain", "hujan ekstrem": "Extreme rain",
    "petir": "Thunderstorms", "kabut": "Fog", "asap": "Haze",
    "udara kabur": "Mist",
}
WAVE_EN = {
    "tenang": "Calm", "rendah": "Low", "sedang": "Moderate",
    "tinggi": "High", "sangat tinggi": "Very high", "ekstrem": "Extreme",
}
PORT_TYPE_EN = {
    "utama": "Main", "pengumpul": "Collector", "pengumpan": "Feeder",
    "terminal khusus": "Special terminal",
}


def _translate_exact(value: Any, mapping: Dict[str, str]) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    return mapping.get(text.casefold(), text)


def _translate_warning(value: Any) -> Optional[str]:
    text = _clean_warning(value)
    if not text:
        return None
    replacements = (
        (r"\bwaspadai?\b", "Warning:"),
        (r"\bgelombang sangat tinggi\b", "very high waves"),
        (r"\bgelombang tinggi\b", "high waves"),
        (r"\bgelombang sedang\b", "moderate waves"),
        (r"\bgelombang\b", "waves"),
        (r"\bangin kencang\b", "strong winds"),
        (r"\bhujan lebat\b", "heavy rain"),
        (r"\bmelebihi\b", "exceeding"),
        (r"\bdan\b", "and"),
        (r"\bknot\b", "kt"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _translate_water_name(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    replacements = (
        (r"^Perairan\b", "Waters"), (r"^Laut\b", "Sea"),
        (r"^Selat\b", "Strait"), (r"^Teluk\b", "Bay"),
        (r"\bbagian utara\b", "northern sector"),
        (r"\bbagian selatan\b", "southern sector"),
        (r"\bbagian barat\b", "western sector"),
        (r"\bbagian timur\b", "eastern sector"),
        (r"\butara\b", "north"), (r"\bselatan\b", "south"),
        (r"\bbarat\b", "west"), (r"\btimur\b", "east"),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _english_summary(row: Dict[str, Any]) -> Optional[str]:
    parts: List[str] = []
    if row.get("weather_condition"):
        parts.append(str(row["weather_condition"]))
    wind_min, wind_max = row.get("wind_speed_min_kn"), row.get("wind_speed_max_kn")
    if wind_min is not None or wind_max is not None:
        wind_value = wind_max if wind_min is None or wind_min == wind_max else f"{wind_min:g}–{wind_max:g}"
        direction = row.get("wind_direction_from")
        parts.append(f"winds {wind_value} kt" + (f" from {direction}" if direction else ""))
    if row.get("wave_description"):
        parts.append(f"waves {row['wave_description']}")
    if not parts:
        return None
    return f"{row.get('location_name')}: " + "; ".join(parts) + "."


def _number(value: Any) -> Optional[float]:
    if value in (None, "", "NIL", "-"):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _wave_range(value: Any) -> tuple[Optional[float], Optional[float]]:
    numbers = re.findall(r"-?\d+(?:[.,]\d+)?", str(value or ""))
    parsed = [float(item.replace(",", ".")) for item in numbers[:2]]
    if not parsed:
        return None, None
    return parsed[0], parsed[-1]


def _clean_warning(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return None if not text or text.upper() in {"NIL", "NONE", "-"} else text


def _severity(record: Dict[str, Any]) -> str:
    text = " ".join(
        str(record.get(field) or "")
        for field in ("warning_description", "weather_condition", "wave_category")
    ).lower()
    if record.get("warning_description") or any(
        token in text
        for token in ("ekstrem", "sangat tinggi", "hujan lebat", "hujan badai", "badai", "extreme", "very high", "heavy rain", "storm")
    ):
        return "warning"
    if any(token in text for token in ("tinggi", "sedang", "hujan", "kabut", "high", "moderate", "rain", "fog")):
        return "advisory"
    return "normal"


def _base_forecast(
    *, location_type: str, location_id: str, location_name: str,
    source_file: str, forecast_index: int, source_url: str,
) -> Dict[str, Any]:
    return {
        "provider_code": "bmkg",
        "provider": "BMKG",
        "country": "Indonesia",
        "location_type": location_type,
        "location_id": location_id,
        "location_name": location_name,
        "source_file": source_file,
        "forecast_index": forecast_index,
        "source_url": source_url,
    }


def normalize_port(payload: Dict[str, Any], source_file: str) -> List[Dict[str, Any]]:
    port_id = str(payload.get("port_id") or source_file.split("_", 1)[0]).strip()
    name = str(payload.get("name") or source_file.rsplit(".", 1)[0]).strip()
    latitude = _number(payload.get("latitude"))
    longitude = _number(payload.get("longitude"))
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(payload.get("data") or []):
        row = _base_forecast(
            location_type="port",
            location_id=f"bmkg-port-{port_id}",
            location_name=name,
            source_file=source_file,
            forecast_index=index,
            source_url=BMKG_PORT_SOURCE,
        )
        wave_min, wave_max = _wave_range(item.get("wave_desc"))
        row.update({
            "latitude": latitude,
            "longitude": longitude,
            "port_type": _translate_exact(payload.get("type"), PORT_TYPE_EN),
            "issued_at": item.get("issued"),
            "valid_from": item.get("valid_from"),
            "valid_to": item.get("valid_to"),
            "time_description": _translate_exact(item.get("time_desc"), {"hari ini": "Today", "besok": "Tomorrow", "lusa": "Day after tomorrow"}),
            "weather_condition": _translate_exact(item.get("weather"), WEATHER_EN),
            "weather_description": None,
            "warning_description": _translate_warning(item.get("warning_desc")),
            "wind_direction_from": _translate_exact(item.get("wind_from"), DIRECTION_EN),
            "wind_direction_to": _translate_exact(item.get("wind_to"), DIRECTION_EN),
            "wind_speed_min_kn": _number(item.get("wind_speed_min")),
            "wind_speed_max_kn": _number(item.get("wind_speed_max")),
            "wave_category": _translate_exact(item.get("wave_cat"), WAVE_EN),
            "wave_description": item.get("wave_desc"),
            "wave_height_min_m": wave_min,
            "wave_height_max_m": wave_max,
            "current_direction_from": _translate_exact(item.get("current_from"), DIRECTION_EN),
            "current_direction_to": _translate_exact(item.get("current_to"), DIRECTION_EN),
            "current_speed_min_source": _number(item.get("current_speed_min")),
            "current_speed_max_source": _number(item.get("current_speed_max")),
            "current_speed_documented_unit": "cm/s",
            "visibility_source": _number(item.get("visibility")),
            "visibility_documented_unit": None,
            "humidity_min_pct": _number(item.get("rh_min")),
            "humidity_max_pct": _number(item.get("rh_max")),
            "temperature_min_c": _number(item.get("temp_min")),
            "temperature_max_c": _number(item.get("temp_max")),
            "low_tide_height_m": _number(item.get("low_tide")),
            "low_tide_time": item.get("low_tide_time"),
            "high_tide_height_m": _number(item.get("high_tide")),
            "high_tide_time": item.get("high_tide_time"),
            "geometry": None,
        })
        row["weather_description"] = _english_summary(row)
        row["severity"] = _severity(row)
        rows.append(row)
    return rows


def normalize_water(
    payload: Dict[str, Any], source_file: str,
    geometry_by_code: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    code = str(payload.get("code") or source_file.split("_", 1)[0]).strip()
    name = _translate_water_name(payload.get("name") or source_file.rsplit(".", 1)[0])
    geometry = geometry_by_code.get(code.upper())
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(payload.get("data") or []):
        row = _base_forecast(
            location_type="water",
            location_id=f"bmkg-water-{code}",
            location_name=name,
            source_file=source_file,
            forecast_index=index,
            source_url=BMKG_WATER_SOURCE,
        )
        wave_min, wave_max = _wave_range(item.get("wave_desc"))
        row.update({
            "water_code": code,
            "issued_at": payload.get("issued"),
            "valid_from": item.get("valid_from"),
            "valid_to": item.get("valid_to"),
            "time_description": _translate_exact(item.get("time_desc"), {"hari ini": "Today", "besok": "Tomorrow", "lusa": "Day after tomorrow"}),
            "weather_condition": _translate_exact(item.get("weather"), WEATHER_EN),
            "weather_description": None,
            "warning_description": _translate_warning(item.get("warning_desc")),
            "station_remark": item.get("station_remark"),
            "wind_direction_from": _translate_exact(item.get("wind_from"), DIRECTION_EN),
            "wind_direction_to": _translate_exact(item.get("wind_to"), DIRECTION_EN),
            "wind_speed_min_kn": _number(item.get("wind_speed_min")),
            "wind_speed_max_kn": _number(item.get("wind_speed_max")),
            "wave_category": _translate_exact(item.get("wave_cat"), WAVE_EN),
            "wave_description": item.get("wave_desc"),
            "wave_height_min_m": wave_min,
            "wave_height_max_m": wave_max,
            "geometry": geometry,
        })
        row["weather_description"] = _english_summary(row)
        row["severity"] = _severity(row)
        rows.append(row)
    return rows


def _parse_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip().replace(" UTC", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)


def select_forecast_rows(
    rows: Iterable[Dict[str, Any]], hours: int,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    target = (now or datetime.now(timezone.utc)) + timedelta(hours=hours)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("location_id")), []).append(row)
    selected: List[Dict[str, Any]] = []
    for candidates in grouped.values():
        def score(row: Dict[str, Any]) -> tuple[int, float]:
            start = _parse_utc(row.get("valid_from"))
            end = _parse_utc(row.get("valid_to"))
            contains = bool(start and end and start <= target < end)
            anchor = start or end or datetime.min.replace(tzinfo=timezone.utc)
            return (0 if contains else 1, abs((anchor - target).total_seconds()))
        selected.append(min(candidates, key=score))
    return sorted(
        selected,
        key=lambda row: (row.get("location_type") != "water", row.get("location_name") or ""),
    )


class BmkgMarineWeatherManager:
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
            self.payload = _json_safe(
                json.loads(self.cache_path.read_text(encoding="utf-8"))
            )
            if self.payload.get("schema_version") != SCHEMA_VERSION:
                self.payload = {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.payload = {}

    @staticmethod
    def _files(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [item for item in (payload.get("files") or []) if item.get("name")]

    async def _fetch_changed(
        self, client: httpx.AsyncClient, files: List[Dict[str, Any]],
        template: str, normalizer: Any, previous_rows: List[Dict[str, Any]],
        previous_dates: Dict[str, str], geometry_by_code: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, str], List[str]]:
        dates = {str(item["name"]): str(item.get("file_date") or "") for item in files}
        retained = [
            row for row in previous_rows
            if row.get("source_file") in dates
            and previous_dates.get(str(row.get("source_file"))) == dates[str(row.get("source_file"))]
        ]
        changed = [
            str(item["name"]) for item in files
            if previous_dates.get(str(item["name"])) != dates[str(item["name"])]
            or not any(row.get("source_file") == item["name"] for row in retained)
        ]
        semaphore = asyncio.Semaphore(18)

        async def fetch_one(file_name: str) -> tuple[str, Any]:
            async with semaphore:
                try:
                    response = await client.get(template.format(file_name=quote(file_name, safe="")))
                    response.raise_for_status()
                    return file_name, response.json()
                except Exception as exc:
                    return file_name, exc

        fetched = await asyncio.gather(*(fetch_one(name) for name in changed))
        errors: List[str] = []
        rows = list(retained)
        for file_name, result in fetched:
            if isinstance(result, Exception):
                errors.append(f"{file_name}: {result}")
                # A listing timestamp is not proof the file was downloaded.
                # Keep the successful timestamp so this file is retried.
                dates.pop(file_name, None)
                if file_name in previous_dates:
                    dates[file_name] = previous_dates[file_name]
                # Preserve the last successful normalized version on a partial outage.
                rows.extend(row for row in previous_rows if row.get("source_file") == file_name)
                continue
            if geometry_by_code is None:
                normalized = normalizer(result, file_name)
            else:
                normalized = normalizer(result, file_name, geometry_by_code)
            if not normalized:
                errors.append(f"{file_name}: no usable forecasts")
                dates.pop(file_name, None)
                if file_name in previous_dates:
                    dates[file_name] = previous_dates[file_name]
                rows.extend(row for row in previous_rows if row.get("source_file") == file_name)
            else:
                rows.extend(normalized)
        return rows, dates, errors

    async def refresh(self, force: bool = False) -> Dict[str, Any]:
        async with self.lock:
            fetched_at = _parse_utc(self.payload.get("fetched_at"))
            if not force and fetched_at:
                age = datetime.now(timezone.utc) - fetched_at
                retry_seconds = FAILED_REFRESH_RETRY_SECONDS if self.payload.get("parse_warnings") else self.refresh_seconds
                if age.total_seconds() < retry_seconds:
                    return self.payload
            headers = {"User-Agent": "HRP-Dashboard/1.0 (+BMKG maritime forecast visualization)"}
            async with httpx.AsyncClient(
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(25.0, connect=8.0),
            ) as client:
                port_list_response, water_list_response, geometry_response = await asyncio.gather(
                    client.get(BMKG_PORT_LIST),
                    client.get(BMKG_WATER_LIST),
                    client.get(BMKG_WATER_GEOMETRY),
                )
                for response in (port_list_response, water_list_response, geometry_response):
                    response.raise_for_status()
                port_files = self._files(port_list_response.json())
                water_files = self._files(water_list_response.json())
                geometry_payload = geometry_response.json()
                geometry_by_code = {
                    str(feature.get("properties", {}).get("WP_1") or "").strip().upper(): feature.get("geometry")
                    for feature in geometry_payload.get("features") or []
                    if feature.get("geometry")
                }
                previous_rows = list(self.payload.get("rows") or [])
                previous_dates = dict(self.payload.get("source_file_dates") or {})
                port_rows, port_dates, port_errors = await self._fetch_changed(
                    client, port_files, BMKG_PORT_FILE, normalize_port,
                    [row for row in previous_rows if row.get("location_type") == "port"],
                    previous_dates,
                )
                water_rows, water_dates, water_errors = await self._fetch_changed(
                    client, water_files, BMKG_WATER_FILE, normalize_water,
                    [row for row in previous_rows if row.get("location_type") == "water"],
                    previous_dates, geometry_by_code,
                )
            rows = port_rows + water_rows
            if not rows:
                raise RuntimeError("BMKG sources returned no usable maritime forecasts")
            now = datetime.now(timezone.utc)
            errors = port_errors + water_errors
            payload = _json_safe({
                "schema_version": SCHEMA_VERSION,
                "provider": "Badan Meteorologi, Klimatologi, dan Geofisika (BMKG)",
                "provider_code": "bmkg",
                "source_page": BMKG_ROOT,
                "fetched_at": now.isoformat(),
                "next_refresh_at": (now + timedelta(seconds=self.refresh_seconds)).isoformat(),
                "refresh_seconds": self.refresh_seconds,
                "coverage_note": (
                    "Official modeled maritime forecasts. Forecasts are not observations and are not for navigation."
                ),
                "inventory": {"ports": len(port_files), "waters": len(water_files)},
                "source_file_dates": {**port_dates, **water_dates},
                "parse_warnings": errors[:50],
                "rows": rows,
            })
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.payload = payload
            self.last_error = "; ".join(errors[:3]) if errors else None
            return payload

    def selected_payload(self, hours: int = 0) -> Dict[str, Any]:
        payload = {
            key: value for key, value in self.payload.items()
            if key not in {"rows", "source_file_dates"}
        }
        payload["hours"] = hours
        payload["rows"] = select_forecast_rows(self.payload.get("rows") or [], hours)
        payload["last_error"] = self.last_error
        fetched_at = _parse_utc(self.payload.get("fetched_at"))
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds() if fetched_at else None
        payload["refresh_age_hours"] = age / 3600 if age is not None else None
        payload["stale"] = age is None or age >= self.refresh_seconds
        return payload

    async def _run(self) -> None:
        while not self.stopping:
            wait_seconds = self.refresh_seconds
            try:
                await self.refresh()
                if self.last_error:
                    wait_seconds = min(self.refresh_seconds, FAILED_REFRESH_RETRY_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("BMKG maritime refresh failed: %s", exc)
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
