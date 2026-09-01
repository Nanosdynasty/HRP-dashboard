"""Official weather adapters for major dry-bulk ports outside the existing Asia feeds.

Only normalized forecast values are cached. National meteorological agencies
remain the source of truth; weather is never interpreted as a port closure.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx
from shapely.geometry import Point, shape


REFRESH_SECONDS = 3 * 60 * 60
SCHEMA_VERSION = 1
NOAA_USER_AGENT = "HRP-Dashboard/1.0 (official marine forecast visualization)"
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
CANADA_MARINE_URL = "https://api.weather.gc.ca/collections/marineweather-realtime/items?f=json&limit=500"
METNO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
METNO_USER_AGENT = "HRP-Dashboard/1.0 github.com/Nanosdynasty/HRP-dashboard"


PORTS: Dict[str, Dict[str, Any]] = {
    # Australia: export coal, iron ore, grain and alumina corridors.
    "Port Hedland": {"country": "Australia", "lat": -20.31, "lon": 118.58, "tier": 1},
    "Dampier": {"country": "Australia", "lat": -20.65, "lon": 116.71, "tier": 1},
    "Cape Lambert": {"country": "Australia", "lat": -20.59, "lon": 117.20, "tier": 1},
    "Geraldton": {"country": "Australia", "lat": -28.78, "lon": 114.58, "tier": 2},
    "Bunbury": {"country": "Australia", "lat": -33.31, "lon": 115.65, "tier": 2},
    "Albany": {"country": "Australia", "lat": -35.04, "lon": 117.89, "tier": 2},
    "Esperance": {"country": "Australia", "lat": -33.87, "lon": 121.90, "tier": 2},
    "Abbot Point": {"country": "Australia", "lat": -19.88, "lon": 148.08, "tier": 1},
    "Hay Point": {"country": "Australia", "lat": -21.30, "lon": 149.30, "tier": 1},
    "Gladstone": {"country": "Australia", "lat": -23.84, "lon": 151.26, "tier": 1},
    "Brisbane": {"country": "Australia", "lat": -27.38, "lon": 153.17, "tier": 2},
    "Newcastle": {"country": "Australia", "lat": -32.92, "lon": 151.79, "tier": 1},
    "Port Kembla": {"country": "Australia", "lat": -34.47, "lon": 150.91, "tier": 1},
    "Whyalla": {"country": "Australia", "lat": -33.03, "lon": 137.59, "tier": 2},
    "Port Bonython": {"country": "Australia", "lat": -33.02, "lon": 137.76, "tier": 2},
    "Portland": {"country": "Australia", "lat": -38.35, "lon": 141.61, "tier": 2},
    # United States: major grain, coal, ore and bulk gateways.
    "Lower Mississippi / New Orleans": {"country": "United States", "lat": 29.10, "lon": -89.25, "tier": 1},
    "Houston / Galveston": {"country": "United States", "lat": 29.31, "lon": -94.79, "tier": 1},
    "Mobile": {"country": "United States", "lat": 30.20, "lon": -88.05, "tier": 1},
    "Hampton Roads": {"country": "United States", "lat": 36.90, "lon": -75.85, "tier": 1},
    "Baltimore": {"country": "United States", "lat": 39.20, "lon": -76.45, "tier": 2},
    "Long Beach / Los Angeles": {"country": "United States", "lat": 33.70, "lon": -118.25, "tier": 2},
    "Columbia River export terminals": {"country": "United States", "lat": 46.22, "lon": -123.96, "tier": 1},
    "Seattle / Tacoma": {"country": "United States", "lat": 47.36, "lon": -122.47, "tier": 2},
    "Duluth-Superior": {"country": "United States", "lat": 46.78, "lon": -92.08, "tier": 1},
    # Canada: Pacific, St Lawrence and Great Lakes bulk gateways.
    "Vancouver": {"country": "Canada", "lat": 49.30, "lon": -123.15, "tier": 1},
    "Prince Rupert": {"country": "Canada", "lat": 54.31, "lon": -130.33, "tier": 1},
    "Sept-Îles": {"country": "Canada", "lat": 50.20, "lon": -66.38, "tier": 1},
    "Port-Cartier": {"country": "Canada", "lat": 50.03, "lon": -66.78, "tier": 1},
    "Québec": {"country": "Canada", "lat": 46.83, "lon": -71.17, "tier": 2},
    "Montréal": {"country": "Canada", "lat": 45.55, "lon": -73.52, "tier": 2},
    "Thunder Bay": {"country": "Canada", "lat": 48.39, "lon": -89.22, "tier": 1},
    "Hamilton": {"country": "Canada", "lat": 43.29, "lon": -79.80, "tier": 2},
    # Japan: principal coal, ore, grain and steelmaking gateways.
    "Kashima": {"country": "Japan", "lat": 35.94, "lon": 140.69, "tier": 1},
    "Tokyo / Yokohama / Chiba": {"country": "Japan", "lat": 35.47, "lon": 139.83, "tier": 1},
    "Nagoya": {"country": "Japan", "lat": 35.04, "lon": 136.84, "tier": 1},
    "Osaka / Kobe": {"country": "Japan", "lat": 34.62, "lon": 135.22, "tier": 1},
    "Mizushima": {"country": "Japan", "lat": 34.47, "lon": 133.75, "tier": 1},
    "Fukuyama": {"country": "Japan", "lat": 34.42, "lon": 133.43, "tier": 1},
    "Hiroshima": {"country": "Japan", "lat": 34.35, "lon": 132.45, "tier": 2},
    "Tokuyama / Ube": {"country": "Japan", "lat": 33.94, "lon": 131.18, "tier": 1},
    "Kitakyushu": {"country": "Japan", "lat": 33.91, "lon": 130.88, "tier": 1},
    "Oita": {"country": "Japan", "lat": 33.27, "lon": 131.70, "tier": 1},
    "Tomakomai / Muroran": {"country": "Japan", "lat": 42.63, "lon": 141.65, "tier": 1},
    "Kushiro": {"country": "Japan", "lat": 42.97, "lon": 144.35, "tier": 2},
}

# Key global dry-bulk gateways covered by MET Norway's official worldwide
# atmospheric point forecast. National marine warnings remain separate.
PORTS.update({
    # Europe
    "Rotterdam": {"country": "Netherlands", "region": "Europe", "lat": 51.96, "lon": 4.03, "tier": 1},
    "Amsterdam / IJmuiden": {"country": "Netherlands", "region": "Europe", "lat": 52.47, "lon": 4.57, "tier": 2},
    "Antwerp": {"country": "Belgium", "region": "Europe", "lat": 51.34, "lon": 4.28, "tier": 1},
    "Hamburg": {"country": "Germany", "region": "Europe", "lat": 53.54, "lon": 9.85, "tier": 1},
    "Wilhelmshaven": {"country": "Germany", "region": "Europe", "lat": 53.57, "lon": 8.15, "tier": 1},
    "Dunkirk": {"country": "France", "region": "Europe", "lat": 51.05, "lon": 2.28, "tier": 1},
    "Le Havre / Rouen": {"country": "France", "region": "Europe", "lat": 49.48, "lon": 0.10, "tier": 1},
    "Immingham": {"country": "United Kingdom", "region": "Europe", "lat": 53.63, "lon": -0.19, "tier": 1},
    "Port Talbot": {"country": "United Kingdom", "region": "Europe", "lat": 51.58, "lon": -3.80, "tier": 1},
    "Teesport": {"country": "United Kingdom", "region": "Europe", "lat": 54.61, "lon": -1.15, "tier": 2},
    "Gijón": {"country": "Spain", "region": "Europe", "lat": 43.57, "lon": -5.70, "tier": 1},
    "Bilbao": {"country": "Spain", "region": "Europe", "lat": 43.35, "lon": -3.07, "tier": 2},
    "Algeciras": {"country": "Spain", "region": "Europe", "lat": 36.13, "lon": -5.43, "tier": 2},
    "Taranto": {"country": "Italy", "region": "Europe", "lat": 40.47, "lon": 17.18, "tier": 1},
    "Ravenna": {"country": "Italy", "region": "Europe", "lat": 44.50, "lon": 12.28, "tier": 2},
    "Constanța": {"country": "Romania", "region": "Europe", "lat": 44.12, "lon": 28.68, "tier": 1},
    "Gdańsk": {"country": "Poland", "region": "Europe", "lat": 54.40, "lon": 18.72, "tier": 1},
    "Koper": {"country": "Slovenia", "region": "Europe", "lat": 45.55, "lon": 13.73, "tier": 2},
    "Narvik": {"country": "Norway", "region": "Europe", "lat": 68.43, "lon": 17.42, "tier": 1},
    # South America
    "Ponta da Madeira": {"country": "Brazil", "region": "South America", "lat": -2.57, "lon": -44.37, "tier": 1},
    "Tubarão": {"country": "Brazil", "region": "South America", "lat": -20.29, "lon": -40.24, "tier": 1},
    "Itaguaí": {"country": "Brazil", "region": "South America", "lat": -22.93, "lon": -43.85, "tier": 1},
    "Açu": {"country": "Brazil", "region": "South America", "lat": -21.82, "lon": -41.00, "tier": 1},
    "Santos": {"country": "Brazil", "region": "South America", "lat": -23.97, "lon": -46.30, "tier": 1},
    "Paranaguá": {"country": "Brazil", "region": "South America", "lat": -25.51, "lon": -48.52, "tier": 1},
    "Rio Grande": {"country": "Brazil", "region": "South America", "lat": -32.08, "lon": -52.08, "tier": 2},
    "Rosario / Paraná River": {"country": "Argentina", "region": "South America", "lat": -33.02, "lon": -60.57, "tier": 1},
    "Bahía Blanca": {"country": "Argentina", "region": "South America", "lat": -38.79, "lon": -62.28, "tier": 1},
    "Necochea / Quequén": {"country": "Argentina", "region": "South America", "lat": -38.58, "lon": -58.70, "tier": 1},
    "Nueva Palmira": {"country": "Uruguay", "region": "South America", "lat": -33.88, "lon": -58.42, "tier": 1},
    "Puerto Bolívar": {"country": "Colombia", "region": "South America", "lat": 12.25, "lon": -71.97, "tier": 1},
    "Santa Marta": {"country": "Colombia", "region": "South America", "lat": 11.25, "lon": -74.22, "tier": 2},
    "Mejillones": {"country": "Chile", "region": "South America", "lat": -23.10, "lon": -70.46, "tier": 1},
    "Huasco": {"country": "Chile", "region": "South America", "lat": -28.47, "lon": -71.25, "tier": 2},
    "Matarani": {"country": "Peru", "region": "South America", "lat": -17.00, "lon": -72.11, "tier": 2},
    # Africa
    "Richards Bay": {"country": "South Africa", "region": "Africa", "lat": -28.82, "lon": 32.08, "tier": 1},
    "Saldanha Bay": {"country": "South Africa", "region": "Africa", "lat": -33.03, "lon": 17.96, "tier": 1},
    "Durban": {"country": "South Africa", "region": "Africa", "lat": -29.87, "lon": 31.05, "tier": 1},
    "Maputo": {"country": "Mozambique", "region": "Africa", "lat": -25.98, "lon": 32.58, "tier": 1},
    "Beira": {"country": "Mozambique", "region": "Africa", "lat": -19.83, "lon": 34.86, "tier": 2},
    "Nacala": {"country": "Mozambique", "region": "Africa", "lat": -14.54, "lon": 40.68, "tier": 1},
    "Walvis Bay": {"country": "Namibia", "region": "Africa", "lat": -22.94, "lon": 14.50, "tier": 1},
    "Nouadhibou": {"country": "Mauritania", "region": "Africa", "lat": 20.91, "lon": -17.06, "tier": 1},
    "Kamsar": {"country": "Guinea", "region": "Africa", "lat": 10.64, "lon": -14.63, "tier": 1},
    "Conakry": {"country": "Guinea", "region": "Africa", "lat": 9.51, "lon": -13.72, "tier": 2},
    "Abidjan": {"country": "Côte d’Ivoire", "region": "Africa", "lat": 5.25, "lon": -4.02, "tier": 2},
    "Tema": {"country": "Ghana", "region": "Africa", "lat": 5.63, "lon": 0.01, "tier": 2},
    "Jorf Lasfar": {"country": "Morocco", "region": "Africa", "lat": 33.12, "lon": -8.63, "tier": 1},
    "Safi": {"country": "Morocco", "region": "Africa", "lat": 32.32, "lon": -9.25, "tier": 2},
    "Annaba": {"country": "Algeria", "region": "Africa", "lat": 36.90, "lon": 7.77, "tier": 2},
    "Alexandria / El Dekheila": {"country": "Egypt", "region": "Africa", "lat": 31.16, "lon": 29.80, "tier": 1},
    # Middle East and neighbouring South Asian bulk gateways
    "Fujairah": {"country": "United Arab Emirates", "region": "Middle East", "lat": 25.17, "lon": 56.37, "tier": 1},
    "Jebel Ali": {"country": "United Arab Emirates", "region": "Middle East", "lat": 25.00, "lon": 55.03, "tier": 1},
    "Mina Saqr": {"country": "United Arab Emirates", "region": "Middle East", "lat": 25.98, "lon": 56.05, "tier": 1},
    "Ruwais": {"country": "United Arab Emirates", "region": "Middle East", "lat": 24.12, "lon": 52.73, "tier": 1},
    "Sohar": {"country": "Oman", "region": "Middle East", "lat": 24.51, "lon": 56.63, "tier": 1},
    "Duqm": {"country": "Oman", "region": "Middle East", "lat": 19.67, "lon": 57.70, "tier": 1},
    "Salalah": {"country": "Oman", "region": "Middle East", "lat": 16.95, "lon": 54.00, "tier": 2},
    "Yanbu": {"country": "Saudi Arabia", "region": "Middle East", "lat": 23.95, "lon": 38.21, "tier": 1},
    "Jubail / Ras Al-Khair": {"country": "Saudi Arabia", "region": "Middle East", "lat": 27.07, "lon": 49.61, "tier": 1},
    "Karachi": {"country": "Pakistan", "region": "Middle East", "lat": 24.79, "lon": 66.97, "tier": 1},
    "Port Qasim": {"country": "Pakistan", "region": "Middle East", "lat": 24.76, "lon": 67.34, "tier": 1},
})


BOM_PRODUCTS = {
    "IDW11120": "https://www.bom.gov.au/fwo/IDW11120.xml",
    "IDW11130": "https://www.bom.gov.au/fwo/IDW11130.xml",
    "IDW11140": "https://www.bom.gov.au/fwo/IDW11140.xml",
    "IDQ11290": "https://www.bom.gov.au/fwo/IDQ11290.xml",
    "IDN11001": "https://www.bom.gov.au/fwo/IDN11001.xml",
    "IDS11072": "https://www.bom.gov.au/fwo/IDS11072.xml",
    "IDV10200": "https://www.bom.gov.au/fwo/IDV10200.xml",
}

BOM_ZONE_PORTS = {
    "Pilbara Coast East": ["Port Hedland", "Cape Lambert"],
    "Pilbara Coast West": ["Dampier"],
    "Geraldton Coast": ["Geraldton"],
    "Bunbury Geographe Coast": ["Bunbury"],
    "Leeuwin Coast": ["Albany"],
    "Albany Coast": ["Albany"],
    "Esperance Coast": ["Esperance"],
    "Townsville Coast": ["Abbot Point"],
    "Mackay Coast": ["Hay Point"],
    "Capricornia Coast": ["Gladstone"],
    "Moreton Bay": ["Brisbane"],
    "Gold Coast Waters": ["Brisbane"],
    "Hunter Coast": ["Newcastle"],
    "Illawarra Coast": ["Port Kembla"],
    "Spencer Gulf": ["Whyalla", "Port Bonython"],
    "Upper South East Coast": ["Portland"],
    "Lower South East Coast": ["Portland"],
    "West Coast": ["Portland"],
}

JMA_PRODUCTS = {
    "080000": {"080020": ["Kashima"]},
    "130000": {"130010": ["Tokyo / Yokohama / Chiba"]},
    "230000": {"230010": ["Nagoya"]},
    "270000": {"270000": ["Osaka / Kobe"]},
    "280000": {"280010": ["Osaka / Kobe"]},
    "330000": {"330010": ["Mizushima"]},
    "340000": {"340010": ["Fukuyama", "Hiroshima"]},
    "350000": {"350010": ["Tokuyama / Ube"]},
    "400000": {"400020": ["Kitakyushu"]},
    "440000": {"440010": ["Oita"]},
    "015000": {"015010": ["Tomakomai / Muroran"]},
    "014100": {"014020": ["Kushiro"]},
}

JMA_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{code}.json"


def _numbers(text: Any) -> List[float]:
    return [float(value) for value in re.findall(r"\d+(?:\.\d+)?", str(text or ""))]


def _range(text: Any) -> tuple[Optional[float], Optional[float]]:
    values = _numbers(text)
    return (None, None) if not values else (min(values), max(values))


def _direction(text: str) -> Optional[str]:
    lowered = text.lower()
    directions = (
        ("northwesterly", "Northwest"), ("northeasterly", "Northeast"),
        ("southwesterly", "Southwest"), ("southeasterly", "Southeast"),
        ("northern", "North"), ("southern", "South"),
        ("westerly", "West"), ("easterly", "East"),
        ("northwest", "Northwest"), ("northeast", "Northeast"),
        ("southwest", "Southwest"), ("southeast", "Southeast"),
        ("north", "North"), ("south", "South"), ("west", "West"), ("east", "East"),
    )
    return next((label for token, label in directions if token in lowered), None)


def _severity(text: str, wind_kn: Optional[float], wave_m: Optional[float]) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("hurricane", "typhoon", "tsunami", "tropical cyclone")):
        return "warning"
    if (wind_kn or 0) >= 22 or (wave_m or 0) >= 2.5 or any(token in lowered for token in ("gale", "storm warning", "very rough")):
        return "advisory"
    return "normal"


def _port_row(base: Dict[str, Any], port: str) -> Dict[str, Any]:
    meta = PORTS[port]
    slug = re.sub(r"[^a-z0-9]+", "-", port.lower()).strip("-")
    return {
        **base,
        "country": meta["country"],
        "location_type": "port",
        "location_id": f"{base['provider_code']}-major-port-{slug}",
        "location_name": port,
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "port_visibility_tier": meta["tier"],
        "region": meta.get("region"),
        "geometry": None,
    }


def _metno_condition(symbol_code: Any) -> str:
    value = re.sub(r"_(?:day|night|polartwilight)$", "", str(symbol_code or ""))
    return value.replace("_", " ").strip().capitalize() or "Port forecast"


def parse_metno_forecast(port: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize MET Norway's official global point forecast at a port approach."""
    properties = payload.get("properties") or {}
    timeseries = properties.get("timeseries") or []
    issued = (properties.get("meta") or {}).get("updated_at")
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(timeseries[:97]):
        if index % 6:
            continue
        data = item.get("data") or {}
        instant = ((data.get("instant") or {}).get("details") or {})
        period = data.get("next_6_hours") or data.get("next_1_hours") or {}
        period_details = period.get("details") or {}
        symbol = (period.get("summary") or {}).get("symbol_code")
        condition = _metno_condition(symbol)
        wind_ms = instant.get("wind_speed")
        gust_ms = instant.get("wind_speed_of_gust")
        wind_kn = round(float(wind_ms) * 1.943844, 1) if wind_ms is not None else None
        rainfall = period_details.get("precipitation_amount")
        summary_parts = [condition]
        if wind_kn is not None:
            summary_parts.append(f"wind {_compass(instant.get('wind_from_direction')) or 'variable'} {wind_kn:g} kt")
        if rainfall is not None:
            summary_parts.append(f"precipitation {float(rainfall):g} mm")
        start = str(item.get("time") or "")
        if index + 6 < len(timeseries):
            end = str(timeseries[index + 6].get("time") or "")
        else:
            try:
                end = (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=6)).isoformat()
            except ValueError:
                end = start
        base = {
            "provider_code": "metno", "provider": "MET Norway",
            "marine_area": f"{PORTS[port]['region']} port approach", "issued_at": issued,
            "valid_from": start, "valid_to": end,
            "weather_condition": condition, "weather_description": "; ".join(summary_parts),
            "warning_description": None,
            "wind_direction_from": _compass(instant.get("wind_from_direction")), "wind_direction_to": None,
            "wind_speed_min_kn": wind_kn, "wind_speed_max_kn": wind_kn,
            "wind_speed_min_kmph": round(float(wind_ms) * 3.6, 1) if wind_ms is not None else None,
            "wind_speed_max_kmph": round(float(wind_ms) * 3.6, 1) if wind_ms is not None else None,
            "gust_kmph": round(float(gust_ms) * 3.6, 1) if gust_ms is not None else None,
            "wave_height_min_m": None, "wave_height_max_m": None, "wave_category": None,
            "temperature_min_c": instant.get("air_temperature"), "temperature_max_c": instant.get("air_temperature"),
            "humidity_min_pct": instant.get("relative_humidity"), "humidity_max_pct": instant.get("relative_humidity"),
            "rainfall_mm": rainfall, "source_url": METNO_URL,
            "forecast_basis": "Official MET Norway global atmospheric point forecast at port approach; sea-state fields are not published by this feed",
        }
        base["severity"] = _severity(condition, wind_kn, None)
        rows.append(_port_row(base, port))
    return rows


def parse_bom_xml(text: str, source_url: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(text)
    issued = root.findtext("./amoc/issue-time-utc")
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for area in root.findall("./forecast/area[@type='coast']"):
        description = area.attrib.get("description", "")
        zone = description.split(":", 1)[0].strip()
        ports = BOM_ZONE_PORTS.get(zone, [])
        if not ports:
            continue
        for period in area.findall("forecast-period"):
            values = {item.attrib.get("type"): " ".join("".join(item.itertext()).split()) for item in period.findall("text")}
            wind_text = values.get("forecast_winds", "")
            sea_text = " ".join(values.get(key, "") for key in ("forecast_seas", "forecast_swell1", "forecast_swell2"))
            weather = values.get("forecast_weather", "Marine forecast").rstrip(".")
            wind_values = _numbers(re.sub(r"\b(?:morning|afternoon|evening|night)\b.*", "", wind_text, flags=re.I))
            wind_min, wind_max = (min(wind_values), max(wind_values)) if wind_values else (None, None)
            wave_min, wave_max = _range(sea_text)
            summary = "; ".join(value for value in (weather, wind_text, values.get("forecast_seas"), values.get("forecast_swell1")) if value)
            base = {
                "provider_code": "bom", "provider": "Australian Bureau of Meteorology",
                "marine_area": description, "issued_at": issued,
                "valid_from": period.attrib.get("start-time-utc"), "valid_to": period.attrib.get("end-time-utc"),
                "weather_condition": weather, "weather_description": summary,
                "warning_description": None, "wind_direction_from": _direction(wind_text),
                "wind_direction_to": None, "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
                "wave_height_min_m": wave_min, "wave_height_max_m": wave_max,
                "wave_category": values.get("forecast_seas"), "source_url": source_url,
                "forecast_basis": f"Official BOM coastal-waters forecast ({zone}) mapped to port location",
            }
            base["severity"] = _severity(summary, wind_max, wave_max)
            for port in ports:
                key = (port, str(base["valid_from"]), zone)
                if key not in seen:
                    seen.add(key)
                    rows.append(_port_row(base, port))
    return rows


JMA_REPLACEMENTS = {
    "晴れ": "Clear", "くもり": "Cloudy", "曇り": "Cloudy", "雨": "Rain", "雪": "Snow",
    "雷": "thunderstorms", "霧": "fog", "時々": "at times", "一時": "temporarily",
    "所により": "locally", "を伴う": "possible", "強く": "strong", "やや強く": "moderate to strong",
    "北西": "Northwest", "北東": "Northeast", "南西": "Southwest", "南東": "Southeast",
    "北": "North", "南": "South", "西": "West", "東": "East", "の風": " wind",
    "メートル": "m", "うねり": "swell", "後": "then", "から": "from", "まで": "until",
}


def _translate_jma(text: Any) -> str:
    value = str(text or "")
    value = value.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    for source, target in sorted(JMA_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        value = value.replace(source, f" {target} ")
    value = re.sub(r"[　\s]+", " ", value).strip(" ,")
    return value or "Official coastal forecast"


def _jma_condition(code: Any, raw: Any) -> str:
    text = str(raw or "")
    if "雷" in text:
        return "Rain with possible thunderstorms" if "雨" in text else "Possible thunderstorms"
    if "雪" in text:
        return "Snow"
    if "雨" in text:
        return "Rain"
    family = str(code or "")[:1]
    return {"1": "Clear", "2": "Cloudy", "3": "Rain", "4": "Snow"}.get(family, "Coastal forecast")


def _jma_wind(raw: Any) -> tuple[Optional[str], str]:
    text = str(raw or "")
    directions = (
        ("北東", "Northeast"), ("北西", "Northwest"),
        ("南東", "Southeast"), ("南西", "Southwest"),
        ("北", "North"), ("南", "South"), ("東", "East"), ("西", "West"),
    )
    direction = next((label for token, label in directions if token in text), None)
    strength = "moderate to strong" if "やや強く" in text else "strong" if "強く" in text else None
    summary = f"{direction or 'Variable'} wind" + (f", {strength}" if strength else "")
    return direction, summary


def _jma_wave(raw: Any) -> tuple[Optional[float], Optional[float], str]:
    text = str(raw or "").translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    low, high = _range(text)
    if high is None:
        return low, high, "Wave height not quantified"
    summary = f"Waves {low:g}-{high:g} m" if low != high else f"Waves {high:g} m"
    if "うねり" in text:
        summary += " with swell"
    return low, high, summary


def parse_jma_forecast(payload: List[Dict[str, Any]], product_code: str) -> List[Dict[str, Any]]:
    if not payload:
        return []
    report = payload[0]
    periods = (report.get("timeSeries") or [{}])[0]
    times = periods.get("timeDefines") or []
    area_map = JMA_PRODUCTS.get(product_code, {})
    rows: List[Dict[str, Any]] = []
    for area in periods.get("areas") or []:
        code = str((area.get("area") or {}).get("code") or "")
        ports = area_map.get(code, [])
        if not ports:
            continue
        weather_values = area.get("weathers") or []
        weather_codes = area.get("weatherCodes") or []
        wind_values = area.get("winds") or []
        wave_values = area.get("waves") or []
        for index, start in enumerate(times):
            end = times[index + 1] if index + 1 < len(times) else (datetime.fromisoformat(start) + timedelta(hours=24)).isoformat()
            raw_weather = weather_values[index] if index < len(weather_values) else ""
            raw_wind = wind_values[index] if index < len(wind_values) else ""
            raw_wave = wave_values[index] if index < len(wave_values) else ""
            weather = _jma_condition(weather_codes[index] if index < len(weather_codes) else None, raw_weather)
            wind_direction, wind = _jma_wind(raw_wind)
            wave_min, wave_max, wave = _jma_wave(raw_wave)
            summary = "; ".join(value for value in (weather, wind, wave) if value)
            base = {
                "provider_code": "jma", "provider": "Japan Meteorological Agency",
                "marine_area": str((area.get("area") or {}).get("name") or code),
                "issued_at": report.get("reportDatetime"), "valid_from": start, "valid_to": end,
                "weather_condition": weather, "weather_description": summary,
                "warning_description": None, "wind_direction_from": wind_direction, "wind_direction_to": None,
                "wind_speed_min_kn": None, "wind_speed_max_kn": None,
                "wave_height_min_m": wave_min, "wave_height_max_m": wave_max,
                "wave_category": wave or None, "source_url": JMA_URL.format(code=product_code),
                "forecast_basis": "Official JMA prefectural coastal forecast mapped to major port location",
            }
            base["severity"] = _severity(summary, None, wave_max)
            rows.extend(_port_row(base, port) for port in ports)
    return rows


def _parse_iso_duration(value: str) -> timedelta:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", value or "")
    if not match:
        return timedelta(hours=1)
    days, hours, minutes = (int(item or 0) for item in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)


def _value_at(series: Dict[str, Any], target: datetime) -> Any:
    for item in series.get("values") or []:
        raw = str(item.get("validTime") or "")
        if "/" not in raw:
            continue
        start_raw, duration_raw = raw.split("/", 1)
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        if start <= target < start + _parse_iso_duration(duration_raw):
            return item.get("value")
    return None


def _compass(degrees: Any) -> Optional[str]:
    if degrees is None:
        return None
    labels = ["North", "Northeast", "East", "Southeast", "South", "Southwest", "West", "Northwest"]
    return labels[int((float(degrees) + 22.5) // 45) % 8]


def parse_noaa_grid(port: str, payload: Dict[str, Any], alerts: Dict[str, Any]) -> List[Dict[str, Any]]:
    props = payload.get("properties") or {}
    issued = props.get("updateTime")
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    alert_items = alerts.get("features") or []
    alert_text = "; ".join(
        str((item.get("properties") or {}).get("headline") or (item.get("properties") or {}).get("event") or "")
        for item in alert_items
    ).strip("; ") or None
    rows: List[Dict[str, Any]] = []
    for hours in (0, 12, 24, 36, 48, 60, 72):
        target = start + timedelta(hours=hours)
        end = target + timedelta(hours=12)
        wind_kmh = _value_at(props.get("windSpeed") or {}, target)
        gust_kmh = _value_at(props.get("windGust") or {}, target)
        wave = _value_at(props.get("waveHeight") or {}, target)
        weather_items = _value_at(props.get("weather") or {}, target) or []
        conditions = []
        visibility = _value_at(props.get("visibility") or {}, target)
        for item in weather_items:
            condition = " ".join(str(item.get(key) or "") for key in ("coverage", "intensity", "weather")).replace("_", " ").strip()
            if condition:
                conditions.append(condition.title())
            candidate = (item.get("visibility") or {}).get("value")
            if candidate is not None:
                visibility = candidate
        condition = ", ".join(conditions) or "Marine forecast"
        summary = f"{condition}; wind {_compass(_value_at(props.get('windDirection') or {}, target)) or 'variable'} {float(wind_kmh or 0) / 1.852:.0f} kt"
        if wave is not None:
            summary += f"; wave height {float(wave):g} m"
        base = {
            "provider_code": "noaa", "provider": "NOAA / National Weather Service",
            "marine_area": str(props.get("gridId") or "NWS marine grid"), "issued_at": issued,
            "valid_from": target.isoformat(), "valid_to": end.isoformat(),
            "weather_condition": condition, "weather_description": summary,
            "warning_description": alert_text, "wind_direction_from": _compass(_value_at(props.get("windDirection") or {}, target)),
            "wind_direction_to": None, "wind_speed_min_kn": round(float(wind_kmh) / 1.852, 1) if wind_kmh is not None else None,
            "wind_speed_max_kn": round(float(wind_kmh) / 1.852, 1) if wind_kmh is not None else None,
            "wind_speed_min_kmph": wind_kmh, "wind_speed_max_kmph": wind_kmh, "gust_kmph": gust_kmh,
            "wave_height_min_m": wave, "wave_height_max_m": wave, "wave_category": None,
            "temperature_min_c": _value_at(props.get("temperature") or {}, target),
            "temperature_max_c": _value_at(props.get("temperature") or {}, target),
            "humidity_min_pct": _value_at(props.get("relativeHumidity") or {}, target),
            "humidity_max_pct": _value_at(props.get("relativeHumidity") or {}, target),
            "visibility_source": round(float(visibility) / 1000, 1) if visibility is not None else None,
            "visibility_documented_unit": "km", "source_url": str(props.get("@id") or "https://api.weather.gov/"),
            "forecast_basis": "Official NOAA/NWS coastal marine grid forecast at port approach point",
        }
        base["severity"] = _severity(f"{condition} {alert_text or ''}", base["wind_speed_max_kn"], wave)
        rows.append(_port_row(base, port))
    return rows


def _canada_text(value: Any) -> str:
    return str((value or {}).get("en") or "") if isinstance(value, dict) else str(value or "")


def parse_canada_feature(port: str, feature: Dict[str, Any]) -> List[Dict[str, Any]]:
    props = feature.get("properties") or {}
    regular = props.get("regularForecast") or {}
    wave = props.get("waveForecast") or {}
    extended = props.get("extendedForecast") or {}
    warning_locations = (props.get("warnings") or {}).get("locations") or []
    warnings = []
    for location in warning_locations:
        for event in location.get("events") or []:
            if _canada_text(event.get("status")).upper() != "ENDED":
                warnings.append(_canada_text(event.get("name")))
    forecast_locations = regular.get("locations") or []
    condition = forecast_locations[0].get("weatherCondition") if forecast_locations else {}
    visibility_text = _canada_text((condition or {}).get("weatherVisibility"))
    wind_text = _canada_text((condition or {}).get("wind"))
    wave_locations = wave.get("locations") or []
    wave_text = _canada_text(((wave_locations[0].get("weatherCondition") or {}).get("textSummary"))) if wave_locations else ""
    wind_min, wind_max = _range(wind_text)
    wave_min, wave_max = _range(wave_text)
    issued = regular.get("issuedDatetimeUTC") or props.get("lastUpdated")
    start = datetime.fromisoformat(str(issued).replace("Z", "+00:00")) if issued else datetime.now(timezone.utc)
    area = _canada_text((props.get("area") or {}).get("value"))
    summary = "; ".join(value for value in (visibility_text, wind_text, wave_text) if value)
    base = {
        "provider_code": "eccc", "provider": "Environment and Climate Change Canada",
        "marine_area": area, "issued_at": issued, "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(hours=24)).isoformat(),
        "weather_condition": visibility_text or "Marine forecast", "weather_description": summary,
        "warning_description": "; ".join(warnings) or None, "wind_direction_from": _direction(wind_text),
        "wind_direction_to": None, "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
        "wave_height_min_m": wave_min, "wave_height_max_m": wave_max, "wave_category": wave_text or None,
        "source_url": "https://api.weather.gc.ca/collections/marineweather-realtime",
        "forecast_basis": f"Official Environment Canada marine forecast ({area}) mapped to port location",
    }
    base["severity"] = _severity(f"{summary} {' '.join(warnings)}", wind_max, wave_max)
    row = _port_row(base, port)
    extended_periods = (((extended.get("locations") or [{}])[0].get("weatherCondition") or {}).get("forecastPeriods") or [])
    row["forecast_24h"] = summary
    row["forecast_72h"] = "; ".join(
        f"{_canada_text(period.get('name'))}: {_canada_text(period.get('value'))}" for period in extended_periods[:3]
    )
    return [row]


def select_forecast_rows(rows: Iterable[Dict[str, Any]], hours: int = 0) -> List[Dict[str, Any]]:
    target = datetime.now(timezone.utc) + timedelta(hours=hours)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("location_id")), []).append(row)
    output = []
    for candidates in grouped.values():
        def score(row: Dict[str, Any]) -> tuple[int, float]:
            try:
                start = datetime.fromisoformat(str(row.get("valid_from")).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(row.get("valid_to")).replace("Z", "+00:00"))
            except ValueError:
                start = end = datetime.min.replace(tzinfo=timezone.utc)
            return (0 if start <= target < end else 1, abs((start - target).total_seconds()))
        output.append(min(candidates, key=score))
    return sorted(output, key=lambda row: (str(row.get("country")), str(row.get("location_name"))))


class MajorPortWeatherManager:
    def __init__(self, cache_path: Path, refresh_seconds: int = REFRESH_SECONDS):
        self.cache_path = cache_path
        self.refresh_seconds = refresh_seconds
        self.payload: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        self.stopping = False
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == SCHEMA_VERSION:
                self.payload = payload
        except (OSError, json.JSONDecodeError):
            pass

    async def _fetch_bom(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        async def fetch(url: str) -> List[Dict[str, Any]]:
            response = await client.get(url, headers={"User-Agent": BROWSER_USER_AGENT})
            response.raise_for_status()
            return parse_bom_xml(response.text, url)
        groups = await asyncio.gather(*(fetch(url) for url in BOM_PRODUCTS.values()), return_exceptions=True)
        rows = [row for group in groups if isinstance(group, list) for row in group]
        if not rows:
            raise RuntimeError("BOM coastal products returned no mapped port rows")
        return rows

    async def _fetch_jma(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        async def fetch(code: str) -> List[Dict[str, Any]]:
            response = await client.get(JMA_URL.format(code=code)); response.raise_for_status()
            return parse_jma_forecast(response.json(), code)
        groups = await asyncio.gather(*(fetch(code) for code in JMA_PRODUCTS), return_exceptions=True)
        rows = [row for group in groups if isinstance(group, list) for row in group]
        if not rows:
            raise RuntimeError("JMA products returned no mapped port rows")
        return rows

    async def _fetch_noaa(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        names = [name for name, meta in PORTS.items() if meta["country"] == "United States"]
        async def fetch(port: str) -> List[Dict[str, Any]]:
            meta = PORTS[port]
            headers = {"User-Agent": NOAA_USER_AGENT, "Accept": "application/geo+json"}
            point_url = f"https://api.weather.gov/points/{meta['lat']},{meta['lon']}"
            point_response = await client.get(point_url, headers=headers); point_response.raise_for_status()
            grid_url = point_response.json()["properties"]["forecastGridData"]
            grid_response, alert_response = await asyncio.gather(
                client.get(grid_url, headers=headers),
                client.get(f"https://api.weather.gov/alerts/active?point={meta['lat']},{meta['lon']}", headers=headers),
            )
            grid_response.raise_for_status(); alert_response.raise_for_status()
            return parse_noaa_grid(port, grid_response.json(), alert_response.json())
        groups = await asyncio.gather(*(fetch(port) for port in names), return_exceptions=True)
        rows = [row for group in groups if isinstance(group, list) for row in group]
        if not rows:
            raise RuntimeError("NOAA marine grids returned no port rows")
        return rows

    async def _fetch_canada(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        response = await client.get(CANADA_MARINE_URL); response.raise_for_status()
        features = response.json().get("features") or []
        rows: List[Dict[str, Any]] = []
        for port, meta in PORTS.items():
            if meta["country"] != "Canada":
                continue
            point = Point(float(meta["lon"]), float(meta["lat"]))
            ranked = []
            for feature in features:
                try:
                    polygon = shape(feature.get("geometry"))
                    ranked.append((0 if polygon.covers(point) else 1, polygon.distance(point), feature))
                except Exception:
                    continue
            if ranked:
                rows.extend(parse_canada_feature(port, min(ranked, key=lambda item: (item[0], item[1]))[2]))
        if not rows:
            raise RuntimeError("Environment Canada marine feed returned no mapped port rows")
        return rows

    async def _fetch_metno(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        names = [name for name, meta in PORTS.items() if meta.get("region")]
        semaphore = asyncio.Semaphore(6)

        async def fetch(port: str) -> List[Dict[str, Any]]:
            meta = PORTS[port]
            async with semaphore:
                response = await client.get(
                    METNO_URL,
                    params={"lat": meta["lat"], "lon": meta["lon"]},
                    headers={"User-Agent": METNO_USER_AGENT},
                )
                response.raise_for_status()
                return parse_metno_forecast(port, response.json())

        groups = await asyncio.gather(*(fetch(port) for port in names), return_exceptions=True)
        rows = [row for group in groups if isinstance(group, list) for row in group]
        if not rows:
            raise RuntimeError("MET Norway global forecast returned no mapped port rows")
        return rows

    async def refresh(self, force: bool = False) -> Dict[str, Any]:
        async with self.lock:
            fetched = self.payload.get("fetched_at")
            if not force and fetched:
                try:
                    if (datetime.now(timezone.utc) - datetime.fromisoformat(fetched)).total_seconds() < self.refresh_seconds:
                        return self.payload
                except ValueError:
                    pass
            previous = list(self.payload.get("rows") or [])
            providers = {"bom": self._fetch_bom, "noaa": self._fetch_noaa, "eccc": self._fetch_canada, "jma": self._fetch_jma, "metno": self._fetch_metno}
            errors: List[str] = []
            rows: List[Dict[str, Any]] = []
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                results = await asyncio.gather(*(fetcher(client) for fetcher in providers.values()), return_exceptions=True)
            for provider, result in zip(providers, results):
                if isinstance(result, Exception):
                    errors.append(f"{provider}: {result}")
                    rows.extend(row for row in previous if row.get("provider_code") == provider)
                else:
                    rows.extend(result)
            if not rows:
                raise RuntimeError("No official major-port weather rows were available")
            now = datetime.now(timezone.utc)
            payload = {
                "schema_version": SCHEMA_VERSION, "provider_code": "major-port-official",
                "provider": "Official national meteorological agencies",
                "fetched_at": now.isoformat(), "next_refresh_at": (now + timedelta(seconds=self.refresh_seconds)).isoformat(),
                "refresh_seconds": self.refresh_seconds,
                "inventory": {
                    country: len({row.get("location_name") for row in rows if row.get("country") == country})
                    for country in sorted({str(row.get("country")) for row in rows if row.get("country")})
                },
                "parse_warnings": errors, "rows": rows,
            }
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.payload = payload
            self.last_error = "; ".join(errors) if errors else None
            return payload

    def selected_payload(self, country: Optional[str] = None, hours: int = 0, region: Optional[str] = None) -> Dict[str, Any]:
        result = {key: value for key, value in self.payload.items() if key != "rows"}
        rows = list(self.payload.get("rows") or [])
        if country:
            rows = [row for row in rows if str(row.get("country", "")).casefold() == country.casefold()]
        if region:
            rows = [row for row in rows if str(row.get("region", "")).casefold() == region.casefold()]
        result["country"] = country
        result["region"] = region
        result["hours"] = hours
        result["rows"] = select_forecast_rows(rows, hours)
        result["last_error"] = self.last_error
        return result

    async def _run(self) -> None:
        while not self.stopping:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
            await asyncio.sleep(self.refresh_seconds)

    def start(self) -> None:
        if not self.task or self.task.done():
            self.stopping = False
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.stopping = True
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
