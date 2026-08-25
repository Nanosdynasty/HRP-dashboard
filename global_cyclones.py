"""Global active tropical-cyclone adapter backed by the official GDACS API.

Only normalized fields used by the dashboard are persisted.  Port impacts are
analytical proximity estimates to the published forecast track; they are not
port closure notices or official landfall forecasts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlencode

import httpx
from shapely.geometry import mapping, shape


log = logging.getLogger("global-cyclones")
REFRESH_SECONDS = 60 * 60
SCHEMA_VERSION = 1
USER_AGENT = "HRP-Dashboard/1.0 (global tropical cyclone visualization)"
GDACS_SEARCH = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _haversine_km(a: Sequence[float], b: Sequence[float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def _point_segment_km(point: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    """Short-range equirectangular point-to-segment distance."""
    mean_lat = math.radians((point[0] + a[0] + b[0]) / 3)
    scale = max(0.15, math.cos(mean_lat))
    px, py = point[1] * scale, point[0]
    ax, ay = a[1] * scale, a[0]
    bx, by = b[1] * scale, b[0]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        nearest = a
    else:
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        nearest = [ay + t * dy, (ax + t * dx) / scale]
    return _haversine_km(point, nearest)


def _distance_to_track_km(point: Sequence[float], track: Sequence[Sequence[float]]) -> float:
    if not track:
        return float("inf")
    if len(track) == 1:
        return _haversine_km(point, track[0])
    return min(_point_segment_km(point, track[index], track[index + 1]) for index in range(len(track) - 1))


def _bearing(a: Sequence[float], b: Sequence[float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _bearing_name(value: float) -> str:
    names = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
    return names[int((value + 22.5) // 45) % 8]


def _ocean_label(lat: float, lon: float) -> tuple[str, str]:
    if 5 <= lat <= 31 and 78 <= lon <= 101:
        return "North Indian Ocean", "Bay of Bengal"
    if 5 <= lat <= 31 and 43 <= lon < 78:
        return "North Indian Ocean", "Arabian Sea"
    if 0 <= lat <= 32 and 99 <= lon <= 122:
        return "Northwest Pacific Ocean", "South China Sea"
    if 20 <= lat <= 40 and 118 <= lon <= 132:
        return "Northwest Pacific Ocean", "East China Sea"
    if 25 <= lat <= 48 and 127 <= lon <= 143:
        return "Northwest Pacific Ocean", "Sea of Japan / western Pacific"
    if lat >= 0 and lon >= 100:
        return "Northwest Pacific Ocean", "Western Pacific"
    if lat >= 0 and lon <= -100:
        return "Northeast Pacific Ocean", "Eastern Pacific"
    if lat >= 0 and -100 < lon <= -75 and lat < 32:
        return "North Atlantic Ocean", "Caribbean Sea / Gulf of Mexico"
    if lat >= 0 and -100 < lon < 40:
        return "North Atlantic Ocean", "Atlantic Ocean"
    if lat < 0 and 20 <= lon < 110:
        return "Southwest Indian Ocean", "Indian Ocean"
    if lat < 0 and (lon >= 110 or lon <= -70):
        return "South Pacific Ocean", "South Pacific"
    return ("South Atlantic Ocean", "Atlantic Ocean") if lat < 0 else ("North Indian Ocean", "Indian Ocean")


def _chain_segments(segments: Iterable[Sequence[Sequence[float]]], anchor: Sequence[float]) -> List[List[float]]:
    remaining = [[list(pair[0]), list(pair[-1])] for pair in segments if len(pair) >= 2]
    path = [list(anchor)]
    while remaining:
        best_index, best_reverse, best_distance = -1, False, float("inf")
        for index, (first, last) in enumerate(remaining):
            first_distance = _haversine_km(path[-1], first)
            last_distance = _haversine_km(path[-1], last)
            if first_distance < best_distance:
                best_index, best_reverse, best_distance = index, False, first_distance
            if last_distance < best_distance:
                best_index, best_reverse, best_distance = index, True, last_distance
        if best_index < 0 or best_distance > 500:
            break
        first, last = remaining.pop(best_index)
        path.append(first if best_reverse else last)
    return path


def _simplified_cone(features: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") in {"Polygon", "MultiPolygon"} and "uncertainty" in str(props.get("polygonlabel", "")).lower():
            try:
                return mapping(shape(geometry).simplify(0.12, preserve_topology=True))
            except Exception:
                return geometry
    return None


def _impact_radius(max_wind_kmph: float) -> int:
    if max_wind_kmph >= 200:
        return 400
    if max_wind_kmph >= 120:
        return 320
    if max_wind_kmph >= 63:
        return 250
    return 180


def _affected_ports(ports: Iterable[Dict[str, Any]], track: Sequence[Sequence[float]], radius_km: int) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for port in ports:
        lat, lon = _number(port.get("lat")), _number(port.get("lon"))
        if lat is None or lon is None:
            continue
        distance = _distance_to_track_km([lat, lon], track)
        if distance > radius_km:
            continue
        matches.append({
            "port_id": str(port.get("id") or ""),
            "port_name": str(port.get("name") or "Unknown port"),
            "country": str(port.get("country") or ""),
            "latitude": lat,
            "longitude": lon,
            "distance_to_forecast_track_km": round(distance, 1),
            "impact_band": "inner proximity band" if distance <= radius_km * 0.4 else "forecast-track corridor",
        })
    matches.sort(key=lambda row: (row["distance_to_forecast_track_km"], row["port_name"]))
    deduplicated: List[Dict[str, Any]] = []
    seen = set()
    for row in matches:
        name_key = re.sub(r"\b(port|harbour|harbor|ko)\b", " ", row["port_name"].lower())
        name_key = re.sub(r"[^a-z0-9]+", "", name_key)
        key = (row["country"].lower(), name_key)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(row)
    return deduplicated[:30]


def build_cyclone_records(
    event_payload: Dict[str, Any],
    geometry_by_event: Dict[str, Dict[str, Any]],
    ports: Iterable[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    for feature in event_payload.get("features", []):
        props = feature.get("properties") or {}
        if str(props.get("iscurrent", "")).lower() != "true":
            continue
        end = _parse_date(props.get("todate"))
        if end and end < now - timedelta(hours=36):
            continue
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) < 2:
            continue
        current = [float(coordinates[1]), float(coordinates[0])]
        event_id = str(props.get("eventid"))
        geometry_payload = geometry_by_event.get(event_id) or {}
        geometry_features = geometry_payload.get("features", [])
        observed_segments, forecast_segments = [], []
        land_signals = set()
        for item in geometry_features:
            item_geometry = item.get("geometry") or {}
            item_props = item.get("properties") or {}
            if item_props.get("countryonland"):
                land_signals.add(str(item_props["countryonland"]))
            if item_geometry.get("type") != "LineString":
                continue
            pair = [[float(point[1]), float(point[0])] for point in item_geometry.get("coordinates", []) if len(point) >= 2]
            (forecast_segments if item_props.get("forecast") is True else observed_segments).append(pair)
        forecast_track = _chain_segments(forecast_segments, current)
        observed_from_current = _chain_segments(observed_segments, current)
        observed_track = list(reversed(observed_from_current))
        if len(forecast_track) < 2:
            forecast_track = [current]
        max_wind = _number((props.get("severitydata") or {}).get("severity")) or 0.0
        radius_km = _impact_radius(max_wind)
        impacted_ports = _affected_ports(ports, forecast_track, radius_km)
        affected_countries = [
            str(item.get("countryname")) for item in props.get("affectedcountries", [])
            if item.get("countryname")
        ]
        affected_countries = sorted(set(affected_countries) | land_signals)
        basin, local_sea = _ocean_label(current[0], current[1])
        next_point = forecast_track[1] if len(forecast_track) > 1 else None
        bearing = _bearing(current, next_point) if next_point else None
        destination = forecast_track[-1]
        landfall_text = (
            "Possible coastal impact or landfall area: " + ", ".join(affected_countries)
            + ". Exact landfall point and timing remain uncertain."
            if affected_countries else
            "No coastal landfall area is identified in the current GDACS affected-country signal."
        )
        source_urls = props.get("url") or {}
        alert = str(props.get("alertlevel") or "Green").title()
        rows.append({
            "provider": "Global Disaster Alert and Coordination System",
            "provider_code": "gdacs",
            "source_agency": props.get("source") or "RSMC / TCWC",
            "location_type": "storm",
            "location_id": f"gdacs-tc-{event_id}",
            "location_name": props.get("name") or props.get("eventname") or f"Tropical Cyclone {event_id}",
            "storm_name": props.get("eventname") or props.get("name"),
            "event_id": event_id,
            "episode_id": props.get("episodeid"),
            "latitude": current[0],
            "longitude": current[1],
            "current_position": {"latitude": current[0], "longitude": current[1]},
            "basin": basin,
            "ocean_or_sea": local_sea,
            "issued_at": props.get("datemodified"),
            "valid_from": props.get("fromdate"),
            "valid_to": props.get("todate"),
            "weather_condition": (props.get("severitydata") or {}).get("severitytext") or "Tropical cyclone",
            "weather_description": props.get("description"),
            "warning_description": f"{alert} GDACS tropical-cyclone alert",
            "severity": "warning" if alert in {"Orange", "Red"} else "advisory",
            "alert_level": alert,
            "alert_score": props.get("alertscore"),
            "max_wind_kmph": round(max_wind, 1),
            "max_wind_kn": round(max_wind / 1.852, 1),
            "observed_track": observed_track,
            "forecast_track": forecast_track,
            "forecast_cone": _simplified_cone(geometry_features),
            "movement_bearing_deg": round(bearing, 1) if bearing is not None else None,
            "movement_direction": _bearing_name(bearing) if bearing is not None else "not published",
            "forecast_destination": {"latitude": destination[0], "longitude": destination[1]},
            "affected_countries": affected_countries,
            "possible_landfall": landfall_text,
            "impact_radius_km": radius_km,
            "affected_ports": impacted_ports,
            "affected_port_count": len(impacted_ports),
            "impact_methodology": (
                f"Ports within {radius_km} km of the published forecast-track centreline; "
                "distance is an HRP proximity estimate, not an official closure or damage forecast"
            ),
            "source_url": source_urls.get("report") or f"https://www.gdacs.org/report.aspx?eventid={event_id}&eventtype=TC",
            "source_geometry_url": source_urls.get("geometry"),
            "forecast_basis": "GDACS global event feed and forecast geometry; originating agency shown separately",
            "forecast_disclaimer": "Track, intensity and landfall can change with each advisory; not for navigation.",
        })
    return sorted(rows, key=lambda row: ({"Red": 0, "Orange": 1, "Green": 2}.get(row["alert_level"], 3), -row["max_wind_kmph"]))


class GlobalCycloneManager:
    def __init__(self, cache_path: Path, ports: Iterable[Dict[str, Any]], refresh_seconds: int = REFRESH_SECONDS):
        self.cache_path = cache_path
        self.ports = list(ports)
        self.refresh_seconds = refresh_seconds
        self.payload: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if self.cache_path.exists():
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if cached.get("schema_version") == SCHEMA_VERSION:
                    self.payload = cached
        except (OSError, ValueError) as exc:
            log.warning("Could not load global cyclone cache: %s", exc)

    async def _fetch_json(self, client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def refresh(self, force: bool = False) -> Dict[str, Any]:
        async with self._lock:
            fetched = _parse_date(self.payload.get("fetched_at")) if self.payload else None
            if not force and fetched and (datetime.now(timezone.utc) - fetched).total_seconds() < self.refresh_seconds:
                return self.payload
            now = datetime.now(timezone.utc)
            params = {
                "eventlist": "TC",
                "fromdate": (now - timedelta(days=14)).date().isoformat(),
                "todate": (now + timedelta(days=1)).date().isoformat(),
                "alertlevel": "red;orange;green",
            }
            url = f"{GDACS_SEARCH}?{urlencode(params)}"
            try:
                async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
                    events = await self._fetch_json(client, url)
                    active = []
                    for feature in events.get("features", []):
                        props = feature.get("properties") or {}
                        end = _parse_date(props.get("todate"))
                        if str(props.get("iscurrent", "")).lower() == "true" and (not end or end >= now - timedelta(hours=36)):
                            active.append(feature)
                    geometry_results = await asyncio.gather(*[
                        self._fetch_json(client, str((feature.get("properties") or {}).get("url", {}).get("geometry")))
                        for feature in active
                    ], return_exceptions=True)
                geometry_by_event: Dict[str, Dict[str, Any]] = {}
                for feature, result in zip(active, geometry_results):
                    if isinstance(result, Exception):
                        log.warning("GDACS geometry unavailable for %s: %s", (feature.get("properties") or {}).get("eventid"), result)
                        continue
                    geometry_by_event[str((feature.get("properties") or {}).get("eventid"))] = result
                rows = build_cyclone_records({"features": active}, geometry_by_event, self.ports, now)
                self.payload = {
                    "schema_version": SCHEMA_VERSION,
                    "provider": "GDACS",
                    "fetched_at": now.isoformat(),
                    "next_refresh_at": (now + timedelta(seconds=self.refresh_seconds)).isoformat(),
                    "refresh_seconds": self.refresh_seconds,
                    "rows": rows,
                    "source_url": GDACS_SEARCH,
                    "source_attribution": "Global Disaster Alert and Coordination System (GDACS), UN–European Commission/JRC",
                }
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                if not self.payload:
                    raise
                log.warning("GDACS refresh failed; retaining cache: %s", exc)
            return self.payload

    async def _run(self) -> None:
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Global cyclone refresh failed: %s", exc)
            await asyncio.sleep(self.refresh_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
