"""Official Asian marine-weather adapters.

The cache contains normalized fields only. Source HTML/JSON responses are never
persisted. Port rows derived from an official sea-area forecast are labelled as
area-based rather than presented as a port observation.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx


log = logging.getLogger("sea-marine-weather")
REFRESH_SECONDS = 3 * 60 * 60
SCHEMA_VERSION = 4
USER_AGENT = "HRP-Dashboard/1.0 (official maritime forecast visualization)"

MET_BASE = "https://www.met.gov.my"
MET_SHIPPING = f"{MET_BASE}/en/forecast/marine/shipping/"
TMD_SHIPPING = "https://www.tmd.go.th/en/forecast/shipping"
PAGASA_GALE = "https://www.pagasa.dost.gov.ph/marine/gale-warning"
PAGASA_HIGH_SEAS = "https://www.pagasa.dost.gov.ph/marine/high-seas-forecast"
SG_24H = "https://api-open.data.gov.sg/v2/real-time/api/twenty-four-hr-forecast"
SG_SOURCE = "https://www.weather.gov.sg/weather-forecast-24hrforecast/"
NMC_OFFSHORE = "https://www.nmc.cn/publish/marine/offshore.html"
NMC_COASTAL = "https://www.nmc.cn/publish/marine/newcoastal.html"
NCHMF_SEA = "https://nchmf.gov.vn/kttvsiteE/en-US/2/index.html"


PORTS = {
    "Port Klang": (3.0, 101.39), "Penang": (5.414, 100.345),
    "Tanjung Pelepas": (1.365, 103.548), "Kuantan": (3.974, 103.43),
    "Bintulu": (3.267, 113.067), "Labuan": (5.276, 115.241),
    "Sandakan": (5.84, 118.12), "Laem Chabang": (13.083, 100.883),
    "Bangkok": (13.7, 100.57), "Map Ta Phut": (12.64, 101.14),
    "Songkhla": (7.225, 100.575), "Phuket": (7.84, 98.39),
    "Ranong": (9.97, 98.59), "Manila": (14.59, 120.96),
    "Subic Bay": (14.80, 120.28), "Batangas": (13.76, 121.04),
    "Cebu": (10.30, 123.90), "Davao": (7.07, 125.65),
    "Cagayan de Oro": (8.49, 124.66), "Singapore": (1.264, 103.84),
    "Jurong Port": (1.296, 103.72), "Pasir Panjang Terminal": (1.274, 103.78),
    "Muara": (5.02, 115.07), "Sihanoukville": (10.64, 103.50),
    "Yangon": (16.77, 96.25), "Thilawa": (16.65, 96.27),
    "Tianjin": (38.98, 117.74), "Qinhuangdao": (39.91, 119.61),
    "Caofeidian": (39.00, 118.50), "Dalian": (38.94, 121.65),
    "Qingdao": (36.02, 120.25), "Rizhao": (35.36, 119.53),
    "Lianyungang": (34.73, 119.45), "Shanghai": (31.35, 121.70),
    "Ningbo-Zhoushan": (29.87, 122.05), "Fuzhou": (26.00, 119.45),
    "Xiamen": (24.45, 118.07), "Fangcheng": (21.58, 108.35),
    "Qinzhou": (21.72, 108.60), "Haikou": (20.03, 110.28),
    "Guangzhou": (22.75, 113.58), "Shenzhen": (22.47, 114.25),
    "Hong Kong": (22.30, 114.17),
    "Jingtang": (39.20, 119.00), "Huanghua": (38.32, 117.88),
    "Bayuquan": (40.30, 122.10), "Yantai": (37.58, 121.40),
    "Zhanjiang": (21.16, 110.40),
    "Hai Phong": (20.84, 106.78), "Da Nang": (16.12, 108.22),
    "Quy Nhon": (13.77, 109.25), "Nha Trang": (12.24, 109.20),
    "Vung Tau": (10.33, 107.07), "Cai Mep": (10.52, 107.00),
    "Ho Chi Minh City": (10.74, 106.76), "Can Tho": (10.03, 105.79),
}

PORT_COUNTRIES = {
    "Muara": "Brunei", "Sihanoukville": "Cambodia",
    "Yangon": "Myanmar", "Thilawa": "Myanmar",
    **{port: "China" for port in (
        "Tianjin", "Qinhuangdao", "Caofeidian", "Dalian", "Qingdao", "Rizhao",
        "Lianyungang", "Shanghai", "Ningbo-Zhoushan", "Fuzhou", "Xiamen",
        "Fangcheng", "Qinzhou", "Haikou", "Guangzhou", "Shenzhen", "Hong Kong",
        "Jingtang", "Huanghua", "Bayuquan", "Yantai", "Zhanjiang",
    )},
    **{port: "Vietnam" for port in (
        "Hai Phong", "Da Nang", "Quy Nhon", "Nha Trang", "Vung Tau", "Cai Mep",
        "Ho Chi Minh City", "Can Tho",
    )},
}

MET_AREAS = {
    "Sh002": ("Northern Straits of Melaka", ["Penang"]),
    "Sh003": ("Southern Straits of Melaka", ["Port Klang", "Tanjung Pelepas"]),
    "Sh005": ("Tioman", ["Kuantan"]),
    "Sh007": ("Bunguran", ["Bintulu", "Muara"]),
    "Sh008": ("Reef South", ["Bintulu"]),
    "Sh012": ("Labuan", ["Labuan"]),
    "Sh013": ("Sulu", ["Sandakan"]),
}

TMD_AREAS = {
    "The Gulf of Thailand": ["Laem Chabang", "Bangkok", "Map Ta Phut", "Songkhla", "Sihanoukville"],
    "The Andaman Sea and Malacca Strait": ["Phuket", "Ranong", "Yangon", "Thilawa"],
    "Kotabaru to Singapore Route": ["Songkhla"],
    "Tip of Indochina": [],
}

SG_PORTS = ["Singapore", "Jurong Port", "Pasir Panjang Terminal"]


def _clean(value: Any) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def _number_range(value: Any) -> tuple[Optional[float], Optional[float]]:
    numbers = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value or ""))[:2]]
    return (None, None) if not numbers else (numbers[0], numbers[-1])


def _iso_date(value: str, formats: Iterable[str], offset_hours: int = 0) -> Optional[str]:
    value = re.sub(r"\s+", " ", value).strip()
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(
                tzinfo=timezone(timedelta(hours=offset_hours))
            ).isoformat()
        except ValueError:
            pass
    return None


def _severity(text: str, wave_max: Optional[float], wind_max_kn: Optional[float]) -> str:
    lowered = text.lower()
    if any(x in lowered for x in ("typhoon", "tropical cyclone", "tsunami", "hurricane")):
        return "warning"
    if (wave_max or 0) >= 2.5 or (wind_max_kn or 0) >= 22 or any(
        x in lowered for x in ("gale", "stormy", "rough", "heavy rain", "thunderstorm")
    ):
        return "advisory"
    return "normal"


def _parse_time(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return None


def select_forecast_rows(rows: Iterable[Dict[str, Any]], hours: int = 0) -> List[Dict[str, Any]]:
    target = datetime.now(timezone.utc) + timedelta(hours=hours)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("location_id")), []).append(row)
    selected: List[Dict[str, Any]] = []
    for candidates in grouped.values():
        def score(row: Dict[str, Any]) -> tuple[int, float]:
            start, end = _parse_time(row.get("valid_from")), _parse_time(row.get("valid_to"))
            contains = bool(start and end and start <= target < end)
            anchor = start or end or datetime.min.replace(tzinfo=timezone.utc)
            return (0 if contains else 1, abs((anchor - target).total_seconds()))
        selected.append(min(candidates, key=score))
    return sorted(selected, key=lambda row: (row.get("country") or "", row.get("location_name") or ""))


def _port_row(base: Dict[str, Any], port: str) -> Dict[str, Any]:
    lat, lon = PORTS[port]
    return {
        **base,
        "country": PORT_COUNTRIES.get(port, base.get("country")),
        "location_type": "port",
        "location_id": f"{base['provider_code']}-port-{re.sub(r'[^a-z0-9]+', '-', port.lower()).strip('-')}",
        "location_name": port,
        "latitude": lat,
        "longitude": lon,
        "geometry": None,
        "forecast_basis": f"Official marine-area forecast ({base.get('marine_area') or 'regional'}) mapped to port location",
    }


BEAUFORT_KNOTS = {0: 0, 1: 3, 2: 6, 3: 10, 4: 16, 5: 21, 6: 27, 7: 33, 8: 40, 9: 47, 10: 55, 11: 63, 12: 72}


def _beaufort_range(value: str) -> tuple[Optional[float], Optional[float]]:
    values = [int(item) for item in re.findall(r"\d+", value or "")[:2]]
    if not values:
        return None, None
    low, high = min(values), max(values)
    return float(BEAUFORT_KNOTS.get(max(0, low - 1), 0)), float(BEAUFORT_KNOTS.get(high, 72))


CHINA_AREAS = {
    "渤海": ("Bohai Sea", ["Tianjin", "Qinhuangdao", "Caofeidian"]),
    "渤海海峡": ("Bohai Strait", ["Dalian"]),
    "黄海北部": ("Northern Yellow Sea", ["Dalian"]),
    "黄海中部": ("Central Yellow Sea", ["Qingdao", "Rizhao"]),
    "黄海南部": ("Southern Yellow Sea", ["Lianyungang"]),
    "东海北部": ("Northern East China Sea", ["Shanghai", "Ningbo-Zhoushan"]),
    "东海南部": ("Southern East China Sea", ["Ningbo-Zhoushan", "Fuzhou"]),
    "台湾海峡": ("Taiwan Strait", ["Fuzhou", "Xiamen"]),
    "北部湾": ("Beibu Gulf", ["Fangcheng", "Qinzhou"]),
    "琼州海峡": ("Qiongzhou Strait", ["Haikou"]),
    "南海西北部": ("Northwestern South China Sea", ["Guangzhou"]),
    "南海东北部": ("Northeastern South China Sea", ["Shenzhen", "Hong Kong"]),
}

CHINA_COASTAL_AREAS = {
    "辽东半岛西部沿岸": ("Western Liaodong Peninsula coast", ["Bayuquan"]),
    "辽东半岛南部沿岸": ("Southern Liaodong Peninsula coast", ["Dalian"]),
    "辽东半岛东部沿岸": ("Eastern Liaodong Peninsula coast", ["Dalian"]),
    "秦皇岛沿岸": ("Qinhuangdao coast", ["Qinhuangdao"]),
    "唐山沿岸": ("Tangshan coast", ["Caofeidian", "Jingtang"]),
    "沧州沿岸": ("Cangzhou coast", ["Huanghua"]),
    "渤海湾": ("Bohai Bay coast", ["Tianjin"]),
    "山东半岛北部沿岸": ("Northern Shandong Peninsula coast", ["Yantai"]),
    "山东半岛东部沿岸": ("Eastern Shandong Peninsula coast", ["Qingdao"]),
    "山东半岛南部沿岸": ("Southern Shandong Peninsula coast", ["Qingdao", "Rizhao"]),
    "连云港沿岸": ("Lianyungang coast", ["Lianyungang"]),
    "上海沿岸": ("Shanghai coast", ["Shanghai"]),
    "浙江北部沿岸": ("Northern Zhejiang coast", ["Ningbo-Zhoushan"]),
    "浙江中部沿岸": ("Central Zhejiang coast", ["Ningbo-Zhoushan"]),
    "福建北部沿岸": ("Northern Fujian coast", ["Fuzhou"]),
    "福建中部沿岸": ("Central Fujian coast", ["Fuzhou"]),
    "福建南部沿岸": ("Southern Fujian coast", ["Xiamen"]),
    "珠江口外沿岸": ("Outer Pearl River Estuary coast", ["Guangzhou", "Shenzhen", "Hong Kong"]),
    "湛江沿岸": ("Zhanjiang coast", ["Zhanjiang"]),
    "北部湾东北部沿岸": ("Northeastern Beibu Gulf coast", ["Fangcheng", "Qinzhou"]),
    "琼州海峡": ("Qiongzhou Strait", ["Haikou"]),
}

ZH_WEATHER = {
    "晴": "Clear", "多云": "Cloudy", "阴": "Overcast", "雾": "Fog",
    "小雨": "Light rain", "阵雨": "Showers", "雷阵雨": "Thundershowers",
    "中雨": "Moderate rain", "大雨": "Heavy rain", "暴雨": "Torrential rain",
}
ZH_WIND = {
    "北风": "North", "北北东": "North-northeast", "东北风": "Northeast",
    "东北东": "East-northeast", "东风": "East", "东南东": "East-southeast",
    "东南风": "Southeast", "南南东": "South-southeast", "南风": "South",
    "南南西": "South-southwest", "西南风": "Southwest", "西南西": "West-southwest",
    "西风": "West", "西北西": "West-northwest", "西北风": "Northwest",
    "北北西": "North-northwest",
}


def _port_weather_risk(row: Dict[str, Any]) -> Dict[str, Any]:
    """Derive the dry-bulk disruption score proposed in the supplied research brief."""
    wind = float(row.get("wind_speed_max_kn") or 0)
    wave = float(row.get("wave_height_max_m") or 0)
    visibility = row.get("visibility_source")
    visibility = float(visibility) if visibility is not None else None
    condition = str(row.get("weather_condition") or "").lower()
    score = 2 if wind > 30 else 1 if wind > 20 else 0
    score += 2 if wave > 4 else 1 if wave > 2 else 0
    score += 2 if visibility is not None and visibility < 1 else 1 if visibility is not None and visibility < 5 else 0
    score += 2 if any(x in condition for x in ("heavy rain", "torrential rain")) else 1 if any(
        x in condition for x in ("moderate rain", "thundershower")
    ) else 0
    hazard_text = " ".join(str(row.get(key) or "") for key in ("warning_description", "weather_description"))
    if re.search(r"typhoon|tropical cyclone", hazard_text, re.I):
        score = max(score, 6)
    level = "Severe" if score >= 6 else "High" if score >= 4 else "Moderate" if score >= 2 else "Normal"
    impacts: List[str] = []
    if wind > 20:
        impacts.append("Possible crane or loading restrictions")
    if wind > 30:
        impacts.append("Possible berthing and pilotage restrictions")
    if "rain" in condition or "shower" in condition:
        impacts.append("Possible coal, ore or grain loading interruption")
    if visibility is not None and visibility < 5:
        impacts.append("Reduced-visibility pilotage risk")
    if wave > 2:
        impacts.append("Possible anchorage or berthing disruption")
    if score >= 6:
        impacts.append("Major port disruption risk")
    return {
        **row,
        "weather_risk_score": score,
        "weather_risk_level": level,
        "operational_impacts": impacts,
        "risk_methodology": (
            "HRP Port Weather Disruption Index: supplied wind, wave and visibility thresholds; "
            "NMC moderate/thunder rain receives 1 point and heavy/torrential rain 2 points because "
            "this public forecast does not publish rainfall millimetres"
        ),
    }


def parse_nmc_offshore(text: str) -> List[Dict[str, Any]]:
    issued_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日(\d{1,2})时", text)
    issued = None
    if issued_match:
        issued = datetime(*map(int, issued_match.groups()), tzinfo=timezone(timedelta(hours=8))).isoformat()
    rows: List[Dict[str, Any]] = []
    current_area: Optional[str] = None
    for raw_row in re.findall(r"<tr[^>]*>.*?</tr>", text, re.I | re.S):
        name_match = re.search(r'<tr[^>]*name="([^"]+)"', raw_row, re.I)
        cells = [_clean(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", raw_row, re.I | re.S)]
        if name_match:
            current_area = name_match.group(1)
        if current_area not in CHINA_AREAS or len(cells) < 6:
            continue
        if len(cells) == 7:
            cells = cells[1:]
        period, weather_zh, wind_zh, force, wave, visibility = cells[-6:]
        hour_values = [int(item) for item in re.findall(r"\d+", period)[:2]]
        start_hour, end_hour = (hour_values + [12])[:2]
        start = datetime.fromisoformat(issued) + timedelta(hours=start_hour) if issued else None
        end = datetime.fromisoformat(issued) + timedelta(hours=end_hour) if issued else None
        wind_min, wind_max = _beaufort_range(force)
        wave_max = _number_range(wave)[1]
        area_en, ports = CHINA_AREAS[current_area]
        condition = ZH_WEATHER.get(weather_zh, "Marine forecast")
        base = {
            "provider_code": "cma", "provider": "China Meteorological Administration / NMC", "country": "China",
            "marine_area": area_en, "issued_at": issued,
            "valid_from": start.isoformat() if start else None, "valid_to": end.isoformat() if end else None,
            "weather_condition": condition,
            "weather_description": f"{condition}; {ZH_WIND.get(wind_zh, 'Variable')} wind, Beaufort {force}; waves {wave} m; visibility {visibility} km.",
            "warning_description": None, "wind_direction_from": ZH_WIND.get(wind_zh), "wind_direction_to": None,
            "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
            "wave_height_min_m": wave_max, "wave_height_max_m": wave_max,
            "visibility_source": float(visibility) if re.fullmatch(r"\d+(?:\.\d+)?", visibility) else None,
            "visibility_documented_unit": "km", "wave_category": None, "source_url": NMC_OFFSHORE,
        }
        base["severity"] = _severity(condition, wave_max, wind_max)
        rows.extend(_port_weather_risk(_port_row(base, port)) for port in ports)
    return rows


def parse_nmc_coastal(text: str) -> List[Dict[str, Any]]:
    """Normalize NMC's 34-area coastal forecast and map relevant areas to dry-bulk ports."""
    issued_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日(\d{1,2})时", text)
    issued = datetime(*map(int, issued_match.groups()), tzinfo=timezone(timedelta(hours=8))).isoformat() if issued_match else None
    rows: List[Dict[str, Any]] = []
    current_area: Optional[str] = None
    for raw_row in re.findall(r"<tr[^>]*>.*?</tr>", text, re.I | re.S):
        name_match = re.search(r'<tr[^>]*name="([^"]+)"', raw_row, re.I)
        cells = [_clean(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", raw_row, re.I | re.S)]
        if name_match:
            current_area = name_match.group(1)
        if current_area not in CHINA_COASTAL_AREAS or len(cells) < 5:
            continue
        if len(cells) == 6:
            cells = cells[1:]
        period, weather_zh, wind_zh, force, visibility = cells[-5:]
        hour_values = [int(item) for item in re.findall(r"\d+", period)[:2]]
        start_hour, end_hour = (hour_values + [12])[:2]
        start = datetime.fromisoformat(issued) + timedelta(hours=start_hour) if issued else None
        end = datetime.fromisoformat(issued) + timedelta(hours=end_hour) if issued else None
        wind_min, wind_max = _beaufort_range(force)
        area_en, ports = CHINA_COASTAL_AREAS[current_area]
        condition = ZH_WEATHER.get(weather_zh, "Coastal forecast")
        visibility_value = float(visibility) if re.fullmatch(r"\d+(?:\.\d+)?", visibility) else None
        base = {
            "provider_code": "cma", "provider": "China Meteorological Administration / NMC",
            "country": "China", "marine_area": area_en, "issued_at": issued,
            "valid_from": start.isoformat() if start else None, "valid_to": end.isoformat() if end else None,
            "weather_condition": condition,
            "weather_description": f"{condition}; {ZH_WIND.get(wind_zh, 'Variable')} wind, Beaufort {force}; visibility {visibility} km.",
            "warning_description": None, "wind_direction_from": ZH_WIND.get(wind_zh, wind_zh),
            "wind_direction_to": None, "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
            "wave_height_min_m": None, "wave_height_max_m": None,
            "visibility_source": visibility_value, "visibility_documented_unit": "km",
            "wave_category": None, "source_url": NMC_COASTAL,
        }
        base["severity"] = _severity(condition, None, wind_max)
        for port in ports:
            if port in PORTS:
                row = _port_row(base, port)
                row["forecast_basis"] = f"Official NMC coastal-area forecast ({area_en}) mapped to port location"
                rows.append(_port_weather_risk(row))
    return rows


def merge_china_port_forecasts(
    offshore_rows: Iterable[Dict[str, Any]], coastal_rows: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Prefer port-nearer coastal forecasts and enrich them with matching NMC wave data."""
    offshore = list(offshore_rows)
    coastal = list(coastal_rows)
    by_port: Dict[str, List[Dict[str, Any]]] = {}
    for row in offshore:
        by_port.setdefault(str(row.get("location_name")), []).append(row)
    merged: List[Dict[str, Any]] = []
    covered: set[str] = set()
    for row in coastal:
        port = str(row.get("location_name"))
        covered.add(port)
        candidates = by_port.get(port, [])
        target = _parse_time(row.get("valid_from"))
        match = min(
            candidates,
            key=lambda item: abs(((_parse_time(item.get("valid_from")) or datetime.min.replace(tzinfo=timezone.utc)) - (target or datetime.min.replace(tzinfo=timezone.utc))).total_seconds()),
            default=None,
        )
        enriched = dict(row)
        match_time = _parse_time(match.get("valid_from")) if match else None
        if match and target and match_time and abs((match_time - target).total_seconds()) <= 12 * 60 * 60:
            enriched.update({
                "wave_height_min_m": match.get("wave_height_min_m"),
                "wave_height_max_m": match.get("wave_height_max_m"),
                "offshore_marine_area": match.get("marine_area"),
                "forecast_basis": (
                    f"Official NMC coastal-area forecast ({row.get('marine_area')}) mapped to port; "
                    f"wave height from matching NMC offshore area ({match.get('marine_area')})"
                ),
            })
        merged.append(_port_weather_risk(enriched))
    merged.extend(row for row in offshore if str(row.get("location_name")) not in covered)
    return merged


VIETNAM_AREAS = {
    "Bắc Vịnh Bắc bộ": ("Northern Gulf of Tonkin", ["Hai Phong"]),
    "Nam Vịnh Bắc Bộ": ("Southern Gulf of Tonkin", ["Hai Phong"]),
    "Nam Quảng Trị đến Quảng Ngãi": ("Quang Tri to Quang Ngai", ["Da Nang"]),
    "Gia Lai đến Khánh Hoà": ("Gia Lai to Khanh Hoa", ["Quy Nhon", "Nha Trang"]),
    "Lâm Đồng đến Cà Mau": ("Lam Dong to Ca Mau", ["Vung Tau", "Cai Mep", "Ho Chi Minh City"]),
    "Cà Mau đến An Giang": ("Ca Mau to An Giang", ["Can Tho"]),
}


def parse_nchmf_sea(text: str) -> List[Dict[str, Any]]:
    date_match = re.search(r"SEA WEATHER[^<]*(\d{2}/\d{2}/\d{4})", text, re.I)
    issued = _iso_date(date_match.group(1), ("%d/%m/%Y",), 7) if date_match else None
    rows: List[Dict[str, Any]] = []
    for name_vi, (area_en, ports) in VIETNAM_AREAS.items():
        match = re.search(re.escape(name_vi) + r"</a>\s*<p>(.*?)</p>", text, re.I | re.S)
        if not match:
            continue
        detail_vi = _clean(match.group(1))
        wave_match = re.search(r"Sóng cao\s*([\d,.]+)\s*[-–]\s*([\d,.]+)m", detail_vi, re.I)
        wave_min = float(wave_match.group(1).replace(",", ".")) if wave_match else None
        wave_max = float(wave_match.group(2).replace(",", ".")) if wave_match else None
        force_match = re.search(r"(?:Gió|gió)[^.]*?cấp\s*(\d+)(?:\s*[-–]\s*(\d+))?", detail_vi)
        wind_min, wind_max = _beaufort_range("-".join(item for item in force_match.groups() if item)) if force_match else (None, None)
        direction = None
        for vi, en in (("đông bắc", "Northeast"), ("đông nam", "Southeast"), ("tây nam", "Southwest"), ("tây bắc", "Northwest"), ("đông", "East"), ("tây", "West"), ("nam", "South"), ("bắc", "North")):
            if vi in detail_vi.lower():
                direction = en; break
        lowered = detail_vi.lower()
        if "dông" in lowered:
            condition = "Showers and thunderstorms"
        elif "mưa rào" in lowered:
            condition = "Showers"
        elif "không mưa" in lowered:
            condition = "No rain"
        else:
            condition = "Marine forecast"
        visibility = _number_range(re.search(r"Tầm nhìn xa\s*:\s*([^.]*)", detail_vi, re.I).group(1))[0] if re.search(r"Tầm nhìn xa\s*:\s*([^.]*)", detail_vi, re.I) else None
        summary = f"{condition}; {direction or 'variable'} wind"
        if force_match:
            summary += f", Beaufort {'-'.join(item for item in force_match.groups() if item)}"
        if wave_min is not None:
            summary += f"; waves {wave_min:g}-{wave_max:g} m"
        if visibility is not None:
            summary += f"; visibility {visibility:g} km or more"
        base = {
            "provider_code": "nchmf", "provider": "Vietnam National Center for Hydro-Meteorological Forecasting", "country": "Vietnam",
            "marine_area": area_en, "issued_at": issued, "valid_from": issued,
            "valid_to": (datetime.fromisoformat(issued) + timedelta(days=1)).isoformat() if issued else None,
            "weather_condition": condition, "weather_description": summary + ".",
            "warning_description": None, "wind_direction_from": direction, "wind_direction_to": None,
            "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
            "wave_height_min_m": wave_min, "wave_height_max_m": wave_max,
            "visibility_source": visibility, "visibility_documented_unit": "km",
            "wave_category": None, "source_url": NCHMF_SEA,
        }
        base["severity"] = _severity(condition, wave_max, wind_max)
        rows.extend(_port_row(base, port) for port in ports)
    return rows


def parse_met_shipping(area_code: str, area_name: str, text: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", text, re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", match.group(1), re.I | re.S)
        if len(cells) < 3:
            continue
        date_text = _clean(cells[0]).split(" ")[0]
        valid = _iso_date(date_text, ("%d/%m/%Y",), 8)
        if not valid:
            continue
        condition = _clean(cells[1])
        detail = _clean(cells[2])
        wind_direction = re.search(r"Wind Direction:\s*([A-Z]+)", detail, re.I)
        wind = re.search(r"Wind Speed:\s*([\d.]+)\s*[-–]\s*([\d.]+)\s*km/h", detail, re.I)
        wave = re.search(r"Wave Height:\s*([\d.]+)\s*[-–]\s*([\d.]+)\s*m", detail, re.I)
        wind_min_kmh, wind_max_kmh = (float(wind.group(1)), float(wind.group(2))) if wind else (None, None)
        wave_min, wave_max = (float(wave.group(1)), float(wave.group(2))) if wave else (None, None)
        base = {
            "provider_code": "metmalaysia", "provider": "METMalaysia", "country": "Malaysia",
            "marine_area": area_name, "issued_at": None, "valid_from": valid,
            "valid_to": (datetime.fromisoformat(valid) + timedelta(days=1)).isoformat(),
            "weather_condition": condition, "weather_description": detail,
            "warning_description": None,
            "wind_direction_from": wind_direction.group(1).upper() if wind_direction else None,
            "wind_direction_to": None,
            "wind_speed_min_kmph": wind_min_kmh, "wind_speed_max_kmph": wind_max_kmh,
            "wind_speed_min_kn": round(wind_min_kmh / 1.852, 1) if wind_min_kmh is not None else None,
            "wind_speed_max_kn": round(wind_max_kmh / 1.852, 1) if wind_max_kmh is not None else None,
            "wave_height_min_m": wave_min, "wave_height_max_m": wave_max,
            "wave_category": None, "source_url": f"{MET_SHIPPING}{area_code}",
        }
        base["severity"] = _severity(f"{condition} {detail}", wave_max, base["wind_speed_max_kn"])
        rows.extend(_port_row(base, port) for port in MET_AREAS[area_code][1])
    return rows


def parse_tmd_shipping(text: str) -> List[Dict[str, Any]]:
    issued_match = re.search(r"Announcement Date\s+([^<]+)", text, re.I)
    issued = _iso_date(_clean(issued_match.group(1)) if issued_match else "", ("%d %B %Y %H:%M",), 7)
    rows: List[Dict[str, Any]] = []
    blocks = re.findall(
        r'<p class="ship-forecast-title">(.*?)</p>\s*<p class="ship-forecast-description">(.*?)</p>',
        text, re.I | re.S,
    )
    for raw_name, raw_detail in blocks:
        name, detail = _clean(raw_name), _clean(raw_detail)
        ports = TMD_AREAS.get(name)
        if ports is None:
            continue
        wind_ranges = re.findall(r"(?:winds?|wind)\s+(\d+)\s*[-–]\s*(\d+)\s*knots", detail, re.I)
        wave_ranges = re.findall(r"(?:wave(?: height)?(?:s are)?(?: expected)?(?: up to be)?|waves?)\s*(?:about|below|up to)?\s*(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*meters?", detail, re.I)
        wind_min = min((float(x[0]) for x in wind_ranges), default=None)
        wind_max = max((float(x[1]) for x in wind_ranges), default=None)
        wave_values = [float(v) for pair in wave_ranges for v in pair if v]
        wave_min = min(wave_values, default=None)
        wave_max = max(wave_values, default=None)
        direction = re.search(r"([A-Za-z]+(?:erly)?)\s+winds?", detail)
        base = {
            "provider_code": "tmd", "provider": "Thai Meteorological Department", "country": "Thailand",
            "marine_area": name, "issued_at": issued, "valid_from": issued,
            "valid_to": (datetime.fromisoformat(issued) + timedelta(hours=24)).isoformat() if issued else None,
            "weather_condition": "Thundershowers" if "thundershower" in detail.lower() else "Marine forecast",
            "weather_description": detail, "warning_description": detail if "keep ashore" in detail.lower() else None,
            "wind_direction_from": direction.group(1) if direction else None, "wind_direction_to": None,
            "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
            "wave_height_min_m": wave_min, "wave_height_max_m": wave_max,
            "wave_category": None, "source_url": TMD_SHIPPING,
        }
        base["severity"] = _severity(detail, wave_max, wind_max)
        rows.extend(_port_row(base, port) for port in ports)
    return rows


def parse_pagasa_gale(text: str) -> List[Dict[str, Any]]:
    issued_match = re.search(r"Issued at:\s*([^<]+)", text, re.I)
    issued = _iso_date(_clean(issued_match.group(1)) if issued_match else "", ("%I:%M %p, %d %B %Y",), 8)
    cause_match = re.search(
        r"<p>\s*(Strong to gale-force winds associated with.*?)</p>", text, re.I | re.S
    )
    cause = _clean(cause_match.group(1)) if cause_match else "Official gale warning"
    rows: List[Dict[str, Any]] = []
    for match in re.finditer(r"<tr[^>]*>(.*?)</tr>", text, re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", match.group(1), re.I | re.S)
        if len(cells) != 5:
            continue
        seaboard, condition, wind_text, sea_state, wave_text = map(_clean, cells)
        wind_pairs = re.findall(r"\((\d+)\s*[-–]\s*(\d+)\)", wind_text)
        wind_min, wind_max = (float(wind_pairs[-1][0]), float(wind_pairs[-1][1])) if wind_pairs else (None, None)
        wave_min, wave_max = _number_range(wave_text)
        upper = seaboard.upper()
        ports: List[str] = []
        if any(x in upper for x in ("WESTERN SEABOARD OF LUZON", "MANILA", "BATAAN", "ZAMBALES", "PANGASINAN")):
            ports += ["Manila", "Subic Bay"]
        if any(x in upper for x in ("SOUTHERN LUZON", "BATANGAS")):
            ports += ["Batangas"]
        if "VISAYAS" in upper or "CEBU" in upper:
            ports += ["Cebu"]
        if "MINDANAO" in upper:
            ports += ["Davao", "Cagayan de Oro"]
        if not ports:
            continue
        base = {
            "provider_code": "pagasa", "provider": "PAGASA", "country": "Philippines",
            "marine_area": seaboard, "issued_at": issued, "valid_from": issued,
            "valid_to": None, "weather_condition": condition,
            "weather_description": f"{condition}; {sea_state}; waves {wave_text}",
            "warning_description": f"{cause} for {seaboard}",
            "wind_direction_from": None, "wind_direction_to": None,
            "wind_speed_min_kn": wind_min, "wind_speed_max_kn": wind_max,
            "wave_height_min_m": wave_min, "wave_height_max_m": wave_max,
            "wave_category": sea_state, "source_url": PAGASA_GALE, "severity": "advisory",
        }
        rows.extend(_port_row(base, port) for port in dict.fromkeys(ports))
    return rows


def parse_singapore(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = payload.get("data", {}).get("records") or []
    if not records:
        return []
    record = records[0]
    periods = record.get("periods") or []
    if not periods:
        return []
    period = periods[0]
    condition = str((period.get("regions") or {}).get("south") or (period.get("regions") or {}).get("central") or "")
    general = record.get("general") or {}
    wind = general.get("wind") or {}
    temperature = general.get("temperature") or {}
    humidity = general.get("relativeHumidity") or {}
    base = {
        "provider_code": "nea", "provider": "NEA / Meteorological Service Singapore", "country": "Singapore",
        "marine_area": "Singapore south / port waters", "issued_at": record.get("updatedTimestamp"),
        "valid_from": period.get("start"), "valid_to": period.get("end"),
        "weather_condition": condition, "weather_description": f"Singapore 24-hour regional forecast: {condition}.",
        "warning_description": None, "wind_direction_from": wind.get("direction"), "wind_direction_to": None,
        "wind_speed_min_kn": round(float(wind.get("speed", {}).get("low")) / 1.852, 1) if wind.get("speed", {}).get("low") is not None else None,
        "wind_speed_max_kn": round(float(wind.get("speed", {}).get("high")) / 1.852, 1) if wind.get("speed", {}).get("high") is not None else None,
        "wind_speed_min_kmph": wind.get("speed", {}).get("low"), "wind_speed_max_kmph": wind.get("speed", {}).get("high"),
        "wave_height_min_m": None, "wave_height_max_m": None, "wave_category": None,
        "temperature_min_c": temperature.get("low"), "temperature_max_c": temperature.get("high"),
        "humidity_min_pct": humidity.get("low"), "humidity_max_pct": humidity.get("high"),
        "source_url": SG_SOURCE,
    }
    base["severity"] = _severity(condition, None, base["wind_speed_max_kn"])
    return [_port_row(base, port) for port in SG_PORTS]


class SeaMarineWeatherManager:
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
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self.payload = data if data.get("schema_version") == SCHEMA_VERSION else {}
        except (OSError, json.JSONDecodeError):
            self.payload = {}

    async def _fetch_provider(self, client: httpx.AsyncClient, provider: str) -> List[Dict[str, Any]]:
        if provider == "metmalaysia":
            async def fetch_area(code: str) -> List[Dict[str, Any]]:
                response = await client.get(f"{MET_SHIPPING}{code}")
                response.raise_for_status()
                return parse_met_shipping(code, MET_AREAS[code][0], response.text)
            results = await asyncio.gather(*(fetch_area(code) for code in MET_AREAS))
            return [row for group in results for row in group]
        if provider == "tmd":
            response = await client.get(TMD_SHIPPING); response.raise_for_status()
            return parse_tmd_shipping(response.text)
        if provider == "pagasa":
            response = await client.get(PAGASA_GALE); response.raise_for_status()
            return parse_pagasa_gale(response.text)
        if provider == "nea":
            response = await client.get(SG_24H); response.raise_for_status()
            return parse_singapore(response.json())
        if provider == "cma":
            offshore_response, coastal_response = await asyncio.gather(
                client.get(NMC_OFFSHORE), client.get(NMC_COASTAL), return_exceptions=True
            )
            if isinstance(offshore_response, Exception) and isinstance(coastal_response, Exception):
                raise RuntimeError(f"NMC offshore and coastal feeds failed: {offshore_response}; {coastal_response}")
            offshore_rows: List[Dict[str, Any]] = []
            coastal_rows: List[Dict[str, Any]] = []
            if not isinstance(offshore_response, Exception):
                offshore_response.raise_for_status()
                offshore_rows = parse_nmc_offshore(offshore_response.text)
            if not isinstance(coastal_response, Exception):
                coastal_response.raise_for_status()
                coastal_rows = parse_nmc_coastal(coastal_response.text)
            return merge_china_port_forecasts(offshore_rows, coastal_rows)
        if provider == "nchmf":
            response = await client.get(NCHMF_SEA); response.raise_for_status()
            return parse_nchmf_sea(response.text)
        raise ValueError(provider)

    async def refresh(self, force: bool = False) -> Dict[str, Any]:
        async with self.lock:
            fetched = self.payload.get("fetched_at")
            if not force and fetched:
                try:
                    if (datetime.now(timezone.utc) - datetime.fromisoformat(fetched)).total_seconds() < self.refresh_seconds:
                        return self.payload
                except ValueError:
                    pass
            providers = ("metmalaysia", "tmd", "pagasa", "nea", "cma", "nchmf")
            previous = list(self.payload.get("rows") or [])
            errors: List[str] = []
            rows: List[Dict[str, Any]] = []
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=45) as client:
                results = await asyncio.gather(*(self._fetch_provider(client, p) for p in providers), return_exceptions=True)
            for provider, result in zip(providers, results):
                if isinstance(result, Exception):
                    errors.append(f"{provider}: {result}")
                    rows.extend(row for row in previous if row.get("provider_code") == provider)
                else:
                    rows.extend(result)
            if not rows:
                raise RuntimeError("No official Southeast Asian forecast rows were available")
            now = datetime.now(timezone.utc)
            payload = {
                "schema_version": SCHEMA_VERSION, "provider_code": "sea-official",
                "provider": "Official Southeast Asian meteorological agencies",
                "fetched_at": now.isoformat(),
                "next_refresh_at": (now + timedelta(seconds=self.refresh_seconds)).isoformat(),
                "refresh_seconds": self.refresh_seconds,
                "inventory": {
                    country: sum(1 for row in rows if row.get("country") == country)
                    for country in ("Malaysia", "Thailand", "Philippines", "Singapore", "Brunei", "Cambodia", "Myanmar", "Vietnam", "China")
                },
                "source_status": [
                    {"country": "Malaysia", "agency": "METMalaysia", "status": "live", "url": MET_SHIPPING},
                    {"country": "Thailand", "agency": "TMD", "status": "live", "url": TMD_SHIPPING},
                    {"country": "Philippines", "agency": "PAGASA", "status": "warning-only", "url": PAGASA_GALE},
                    {"country": "Singapore", "agency": "NEA / MSS", "status": "live-regional", "url": SG_SOURCE},
                    {"country": "China", "agency": "CMA / NMC", "status": "live coastal + offshore wave enrichment", "url": NMC_COASTAL},
                    {"country": "Vietnam", "agency": "NCHMF", "status": "live-marine", "url": NCHMF_SEA},
                    {"country": "Brunei", "agency": "METMalaysia", "status": "official regional area mapped to Muara", "url": MET_SHIPPING},
                    {"country": "Cambodia", "agency": "TMD", "status": "official Gulf forecast mapped to Sihanoukville", "url": TMD_SHIPPING},
                    {"country": "Myanmar", "agency": "TMD", "status": "official Andaman forecast mapped to Yangon/Thilawa", "url": TMD_SHIPPING},
                    {"country": "Timor-Leste", "agency": "DNMG", "status": "not integrated: no stable operational official marine feed", "url": "https://www.gov.tl/"},
                    {"country": "Laos", "agency": "DMH", "status": "excluded: landlocked", "url": "https://dmh.gov.la/"},
                    {"country": "ASEAN", "agency": "ASMC", "status": "context only: not port-specific", "url": "https://asmc.asean.org/"},
                ],
                "parse_warnings": errors, "rows": rows,
            }
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.payload = payload
            self.last_error = "; ".join(errors) if errors else None
            return payload

    def selected_payload(self, country: Optional[str] = None, hours: int = 0) -> Dict[str, Any]:
        result = {key: value for key, value in self.payload.items() if key != "rows"}
        rows = list(self.payload.get("rows") or [])
        if country:
            rows = [row for row in rows if str(row.get("country", "")).casefold() == country.casefold()]
        result["country"] = country
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
                log.warning("SEA maritime refresh failed: %s", exc)
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
