"""Global Energy Transition Dashboard"""
from __future__ import annotations
import os, json, io, csv, uuid, asyncio, logging, math, re, zipfile, sqlite3, time, hmac
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta, timezone
import pandas as pd
import duckdb
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from maritime_extras import (
    load_zones, enrich_port_fields, analyze_route_zones,
    fetch_weather, fetch_bunker_prices, estimate_fuel_cost,
)
from port_catalog import PortCatalog
from imd_coastal_weather import ImdCoastalWeatherManager, expand_imd_records
from bmkg_marine_weather import BmkgMarineWeatherManager
from sea_marine_weather import SeaMarineWeatherManager
from major_port_weather import MajorPortWeatherManager
from global_cyclones import GlobalCycloneManager
from coastal_weather_schema import (
    COASTAL_WEATHER_SOURCE_CATALOG,
    normalize_coastal_weather_rows,
)
from river_levels import RiverLevelManager, SOURCE_CATALOG, export_rows_csv, export_river_levels_xlsx
from data_hub import create_data_hub_router

log = logging.getLogger("ais")
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    # Hosted environments normally inject variables directly. Local .env
    # loading becomes available after requirements.txt is installed.
    pass
DATA_DIR = BASE_DIR / "data"
# Hosted deployments can point this at a persistent mounted disk. Local
# development keeps the existing repository-local uploads directory.
UPLOAD_DIR = Path(
    os.getenv("HRP_STORAGE_DIR", str(BASE_DIR / "uploads"))
).expanduser().resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
COAL_UPLOAD_DIR = UPLOAD_DIR / "coal"
COAL_UPLOAD_DIR.mkdir(exist_ok=True)
BUNDLED_DATA_DIR = UPLOAD_DIR / "_bundled_data"
BUNDLED_DATA_DIR.mkdir(exist_ok=True)
NPP_CACHE_DIR = UPLOAD_DIR / "_npp_cache"
NPP_CACHE_DIR.mkdir(exist_ok=True)
NPP_CACHE_PATH = NPP_CACHE_DIR / "power_dashboard.json"
NPP_CACHE_TTL_SECONDS = int(os.getenv("NPP_CACHE_TTL_SECONDS", "43200"))
NPP_ALL_INDIA_URL = "https://npp.gov.in/dashBoard/getAllZone"
NPP_HISTORY_URL = "https://npp.gov.in/dashBoard/get_installed_capacity_list"
NPP_GENERATION_URL = "https://npp.gov.in/dashBoard/getAllZoneGen"
CEA_POWER_STATION_LIST_URL = (
    "https://cea.nic.in/wp-content/uploads/pdm/2025/09/"
    "List_of_Power_Station_as_on_31.03.2025.pdf"
)
NPP_PUBLISHED_REPORTS_URL = "https://npp.gov.in/publishedReports"
MINISTRY_COAL_LINKAGE_URL = (
    "https://coal.gov.in/public-information/standing-linkage-committee1"
)
INDIA_COAL_PORT_SPECS_PATH = DATA_DIR / "india_coal_port_specs.json"
INDIA_COAL_MASTER_PATH = DATA_DIR / "india_coal_master" / "india_coal_master.json"
INDIA_COAL_ANALYSIS_PATH = (
    DATA_DIR / "india_coal_master" / "ui" / "coal_analysis.json"
)
INDIA_COAL_ANNUAL_CSV_PATH = (
    DATA_DIR / "india_coal_master" / "canonical" / "coal_india_annual.csv"
)
INDIA_COAL_CANONICAL_DIR = DATA_DIR / "india_coal_master" / "canonical"
INDIA_COAL_DASHBOARD_QUALITY_PATH = (
    DATA_DIR / "india_coal_master" / "ui" / "coal_dashboard_quality.json"
)
INDIA_POWER_MIX_PATH = (
    DATA_DIR / "india_coal_master" / "ui" / "india_power_mix.json"
)
PORT_APPROACHES_PATH = DATA_DIR / "port_approaches.json"
RISK_ZONE_SOURCE_PATH = DATA_DIR / "zones_source.json"

# Exact location-level matches that have been checked against the official CEA
# station register.  Keeping this explicit prevents a fuzzy name match from
# being presented as government verification.
CEA_VERIFIED_COAL_PLANTS: Dict[str, Dict[str, Any]] = {
    "L100000102436": {
        "cea_verified": True,
        "cea_project_name": "WARDHA WARORA TPP",
        "cea_organisation": "WPCL",
        "cea_sector": "Private Sector",
        "cea_region": "WR",
        "cea_unit_count": 4,
        "cea_capacity_mw": 540,
        "cea_commissioning": "2010–2011",
        "cea_source_as_of": "2025-03-31",
        "cea_source_url": CEA_POWER_STATION_LIST_URL,
    },
}

AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY", "").strip()
AIS_REGION_BOXES = {
    "india": [[[5.0, 64.0], [31.0, 100.0]]],
    "china": [[[17.0, 105.0], [42.0, 125.0]]],
    "gulf": [[[12.0, 42.0], [31.5, 62.5]]],
    "southeast_asia": [[[-12.0, 94.0], [22.0, 132.0]]],
    "japan_korea": [[[30.0, 124.0], [47.0, 147.0]]],
    "australia": [[[-47.0, 108.0], [-8.0, 158.0]]],
    "europe_med": [[[28.0, -12.0], [72.0, 45.0]]],
    "africa": [[[-38.0, -20.0], [38.0, 58.0]]],
    "north_america": [[[5.0, -170.0], [72.0, -50.0]]],
    "south_america": [[[-58.0, -92.0], [15.0, -30.0]]],
    "world": [[[-90.0, -180.0], [90.0, 180.0]]],
}
AIS_BACKGROUND_REGION_IDS = (
    "india",
    "china",
    "gulf",
    "southeast_asia",
)
AIS_DATA_DIR = UPLOAD_DIR / "_ais"
AIS_DATA_DIR.mkdir(exist_ok=True)
AIS_TRAIL_DB_PATH = AIS_DATA_DIR / "observations.sqlite3"
AIS_RAW_RETENTION_DAYS = max(1, int(os.getenv("AIS_RAW_RETENTION_DAYS", "90")))
AIS_MAX_OBSERVATIONS = max(10000, int(os.getenv("AIS_MAX_OBSERVATIONS", "2000000")))
AIS_MAINTENANCE_INTERVAL_SECONDS = max(
    300, int(os.getenv("AIS_MAINTENANCE_INTERVAL_SECONDS", "3600"))
)
IMD_COASTAL_CACHE_DIR = UPLOAD_DIR / "_imd_coastal_weather"
IMD_COASTAL_CACHE_PATH = IMD_COASTAL_CACHE_DIR / "latest.json"
BMKG_MARINE_CACHE_DIR = UPLOAD_DIR / "_bmkg_marine_weather"
BMKG_MARINE_CACHE_PATH = BMKG_MARINE_CACHE_DIR / "latest.json"
SEA_MARINE_CACHE_DIR = UPLOAD_DIR / "_sea_marine_weather"
SEA_MARINE_CACHE_PATH = SEA_MARINE_CACHE_DIR / "latest.json"
MAJOR_PORT_WEATHER_CACHE_DIR = UPLOAD_DIR / "_major_port_weather"
MAJOR_PORT_WEATHER_CACHE_PATH = MAJOR_PORT_WEATHER_CACHE_DIR / "latest.json"
GLOBAL_CYCLONE_CACHE_DIR = UPLOAD_DIR / "_global_cyclones"
GLOBAL_CYCLONE_CACHE_PATH = GLOBAL_CYCLONE_CACHE_DIR / "latest.json"
RIVER_LEVEL_CACHE_DIR = UPLOAD_DIR / "_river_levels"
RIVER_LEVEL_CACHE_PATH = RIVER_LEVEL_CACHE_DIR / "latest.json"


def _init_ais_trail_db() -> None:
    with sqlite3.connect(AIS_TRAIL_DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ais_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mmsi TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                sog_kn REAL,
                cog_deg REAL,
                heading_deg REAL,
                vessel_name TEXT
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ais_observations_mmsi_time "
            "ON ais_observations (mmsi, observed_at)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ais_observations_time "
            "ON ais_observations (observed_at)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ais_latest_positions (
                mmsi TEXT PRIMARY KEY,
                observed_at TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                sog_kn REAL,
                cog_deg REAL,
                heading_deg REAL,
                vessel_name TEXT
            )
            """
        )
        latest_count = db.execute(
            "SELECT COUNT(*) FROM ais_latest_positions"
        ).fetchone()[0]
        if not latest_count:
            db.execute(
                """
                INSERT OR REPLACE INTO ais_latest_positions
                SELECT observation.mmsi, observation.observed_at,
                       observation.latitude, observation.longitude,
                       observation.sog_kn, observation.cog_deg,
                       observation.heading_deg, observation.vessel_name
                FROM ais_observations AS observation
                JOIN (
                    SELECT mmsi, MAX(id) AS latest_id
                    FROM ais_observations
                    GROUP BY mmsi
                ) AS latest ON latest.latest_id = observation.id
                """
            )


_init_ais_trail_db()

TRACKERS = {
    "coal_plants": {"label": "Coal Plants", "file": "coal_plants.csv.gz", "icon": "🔥"},
    "coal_terminals": {"label": "Coal Terminals", "file": "coal_terminals.csv", "icon": "🚢"},
    "world_ports": {"label": "World Ports", "file": "world_ports.csv.gz", "icon": "⚓"},
    "solar": {"label": "Solar", "file": "solar.csv.gz", "icon": "☀️"},
    "wind": {"label": "Wind", "file": "wind.csv.gz", "icon": "💨"},
    "hydro": {"label": "Hydropower", "file": "hydro.csv.gz", "icon": "💧"},
    "nuclear": {"label": "Nuclear", "file": "nuclear.csv.gz", "icon": "⚛️"},
    "geothermal": {"label": "Geothermal Power", "file": "geothermal.csv.gz", "icon": "♨"},
    "bioenergy": {"label": "Bioenergy Power", "file": "bioenergy.csv.gz", "icon": "◉"},
    "coal_mines": {"label": "Coal Mines", "file": "coal_mines.csv.gz", "icon": "◆"},
    "iron_ore_mines": {"label": "Iron Ore Mines", "file": "iron_ore_mines.csv.gz", "icon": "◆"},
    "iron_ore_terminals": {
        "label": "Iron Ore Trade Terminals",
        "file": "iron_ore_terminals.csv.gz",
        "icon": "◆",
    },
    "steel_plants": {"label": "Iron & Steel Plants", "file": "steel_plants.csv.gz", "icon": "●"},
    "cement_plants": {"label": "Cement Plants", "file": "cement_plants.csv.gz", "icon": "●"},
    "coal_trade_terminals": {
        "label": "Coal Trade Terminals",
        "file": "coal_trade_terminals.csv.gz",
        "icon": "◆",
    },
}
NORMALIZED_MAP_TRACKERS = {
    "geothermal",
    "bioenergy",
    "coal_mines",
    "iron_ore_mines",
    "iron_ore_terminals",
    "steel_plants",
    "cement_plants",
    "coal_trade_terminals",
}

INDIA_PORT_IDENTITY_ALIASES = {
    "calcutta": "kolkata",
    "cochin": "kochi",
    "magdalla": "magadalla",
    "marmagao": "mormugao",
    "vishakhapatnam": "visakhapatnam",
}
INDIA_PORT_IDENTITY_STOPWORDS = {
    "bandar",
    "bay",
    "coal",
    "dock",
    "essar",
    "port",
    "system",
    "terminal",
}


def _india_port_identity(value: Any) -> str:
    """Return a stable physical-port key across WPI/GEM naming variants."""
    text = re.sub(r"\([^)]*\)", " ", str(value or "").lower())
    tokens = re.findall(r"[a-z0-9]+", text)
    canonical = [INDIA_PORT_IDENTITY_ALIASES.get(token, token) for token in tokens]
    canonical = [
        token for token in canonical
        if token not in INDIA_PORT_IDENTITY_STOPWORDS
    ]
    return "-".join(canonical)
user_datasets: Dict[str, Path] = {}
con = duckdb.connect(database=":memory:")

COAL_DATASET_TYPES = {
    "production": "Coal production",
    "imports": "Coal imports",
    "power_use": "Coal used in power generation",
    "power_stocks": "Power-sector coal stock cover",
    "renewables": "Renewable generation",
    "weather": "Weather, monsoon and heat",
}

STATUS_GROUPS = {
    "operating": {"operating", "operating pre-retirement"},
    "construction": {"construction", "under construction"},
    "proposed": {
        "proposed",
        "pre-construction",
        "announced",
        "permitted",
        "pre-permit",
    },
}


def _status_values(value: Optional[str]) -> List[str]:
    output: List[str] = []
    for item in _csv_values(value):
        canonical = item.strip().lower()
        output.extend(sorted(STATUS_GROUPS.get(canonical, {canonical})))
    return list(dict.fromkeys(output))


def _coal_dataset_metadata() -> List[Dict[str, Any]]:
    datasets: List[Dict[str, Any]] = []
    for path in sorted(COAL_UPLOAD_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                datasets.append(payload)
        except (OSError, json.JSONDecodeError):
            log.warning("Skipping unreadable coal dataset metadata: %s", path)
    return sorted(datasets, key=lambda item: item.get("uploaded_at", ""), reverse=True)


def _india_coal_master() -> Dict[str, Any]:
    if not INDIA_COAL_MASTER_PATH.exists():
        return {
            "dataset": "India coal official master",
            "coverage": {"status": "not_fetched"},
            "sources": [],
            "source_tables": [],
            "ui_views": {},
        }
    try:
        payload = json.loads(INDIA_COAL_MASTER_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Invalid India coal master shape")
        return payload
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Could not load India coal master: %s", exc)
        return {
            "dataset": "India coal official master",
            "coverage": {"status": "unreadable", "error": str(exc)},
            "sources": [],
            "source_tables": [],
            "ui_views": {},
        }


def _india_coal_analysis() -> Dict[str, Any]:
    if not INDIA_COAL_ANALYSIS_PATH.exists():
        return {
            "status": "not_mapped",
            "annual": [],
            "analysis": {},
            "sources": [],
            "methodology": [],
        }
    try:
        payload = json.loads(
            INDIA_COAL_ANALYSIS_PATH.read_text(encoding="utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("Invalid India coal analysis shape")
        return payload
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Could not load India coal analysis: %s", exc)
        return {
            "status": "unreadable",
            "annual": [],
            "analysis": {},
            "sources": [],
            "methodology": [str(exc)],
        }


def _india_power_mix() -> Dict[str, Any]:
    if not INDIA_POWER_MIX_PATH.exists():
        return {"records": [], "quality": {"status": "not_fetched"}}
    try:
        payload = json.loads(INDIA_POWER_MIX_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"records": []}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not load India power mix: %s", exc)
        return {"records": [], "quality": {"status": "unreadable"}}


class CoalResearchQuery(BaseModel):
    question: str


def _canonical_frame(name: str) -> pd.DataFrame:
    path = INDIA_COAL_CANONICAL_DIR / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


COAL_DASHBOARD_TABS = {"overview", "supply", "trade", "power", "stocks", "table"}


def _dashboard_quality() -> Dict[str, Any]:
    try:
        return json.loads(INDIA_COAL_DASHBOARD_QUALITY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"generated_at": None, "coal": {}, "power": {}}


def _json_records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")


def _filter_months(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if frame.empty or "period" not in frame.columns:
        return frame.copy()
    periods = frame["period"].astype(str)
    return frame.loc[(periods >= start) & (periods <= end)].copy()


def _aggregate_dashboard(frame: pd.DataFrame, frequency: str, flow_columns: List[str]) -> pd.DataFrame:
    if frame.empty or frequency == "monthly":
        return frame.copy()
    dates = pd.to_datetime(frame["period"].astype(str) + "-01", errors="coerce")
    result = frame.assign(_date=dates).dropna(subset=["_date"])
    if frequency == "quarterly":
        result["period"] = result["_date"].dt.to_period("Q").astype(str)
    else:
        year = result["_date"].dt.year.where(result["_date"].dt.month >= 4, result["_date"].dt.year - 1)
        result["period"] = year.astype(int).astype(str) + "-" + (year + 1).astype(int).astype(str).str[-2:]
    available = [column for column in flow_columns if column in result.columns]
    return result.groupby("period", as_index=False)[available].sum(min_count=1)


def _coal_dashboard_payload(
    tab: str, start: str, end: str, frequency: str,
    focus: str = "all", comparison: str = "previous_period",
) -> Dict[str, Any]:
    if tab not in COAL_DASHBOARD_TABS:
        raise HTTPException(400, "Unknown coal dashboard tab")
    if frequency not in {"monthly", "quarterly", "financial_year"}:
        raise HTTPException(400, "Frequency must be monthly, quarterly or financial_year")
    if comparison not in {"none", "previous_period", "previous_year"}:
        raise HTTPException(400, "Unknown comparison mode")
    if not re.fullmatch(r"\d{4}-\d{2}", start) or not re.fullmatch(r"\d{4}-\d{2}", end) or start > end:
        raise HTTPException(400, "Use a valid From/To month range")

    coal_all = _canonical_frame("coal_monthly_official.csv")
    power_all = _canonical_frame("india_power_generation_monthly.csv")
    try:
        mix_all = _canonical_frame("india_power_mix_monthly.csv")
    except FileNotFoundError:
        mix_all = _canonical_frame("india_power_mix_june.csv")
    imports_all = _canonical_frame("coal_imports_monthly.csv")
    annual_all = _canonical_frame("coal_india_annual.csv")
    quality = _dashboard_quality()
    sources = {
        "coal": {"title": "Ministry of Coal — Monthly Statistics at a Glance", "url": "https://coal.gov.in/public-information/monthly-statistics-at-glance"},
        "power": {"title": "National Power Portal — Published Reports", "url": "https://npp.gov.in/publishedReports"},
        "renewable": {"title": "CEA — Monthly Renewable Generation Report", "url": "https://cea.nic.in/renewable-generation-report/?lang=en"},
        "directory": {"title": "Coal Directory 2024-25", "url": "https://coal.gov.in/major-statistics/coal-statistics"},
        "imports_latest": {"title": "Ministry of Coal — Production and Supplies (DDG import totals)", "url": "https://coal.gov.in/major-statistics/production-and-supplies"},
        "imports_quarterly": {"title": "Ministry of Coal — Quarterly Booklet, Q4 FY2025-26 (Table 33)", "url": "https://coal.gov.in/sites/default/files/2025-09/29-06-2026a-qety.pdf"},
    }

    if tab in {"overview", "supply", "table"}:
        frame = _filter_months(coal_all, start, end)
        frame = _aggregate_dashboard(
            frame, frequency,
            ["production_mt", "production_prior_year_mt", "production_ytd_mt",
             "dispatch_mt", "dispatch_prior_year_mt", "dispatch_ytd_mt"],
        )
        if tab == "overview":
            power_summary = _aggregate_dashboard(
                _filter_months(power_all, start, end), frequency,
                ["coal_generation_gwh", "large_hydro_generation_gwh", "conventional_generation_gwh"],
            )
            frame = frame.merge(power_summary, on="period", how="outer").sort_values("period")
            frame["coal_share_conventional_pct"] = frame["coal_generation_gwh"] / frame["conventional_generation_gwh"] * 100
            mix_flow = [
                "coal_generation_gwh", "lignite_generation_gwh", "thermal_generation_gwh",
                "nuclear_generation_gwh", "large_hydro_generation_gwh", "bhutan_import_gwh",
                "wind_generation_gwh", "solar_generation_gwh", "biomass_generation_gwh",
                "bagasse_generation_gwh", "small_hydro_generation_gwh",
                "other_renewables_generation_gwh", "renewables_ex_large_hydro_gwh",
                "total_generation_gwh",
            ]
            mix_frame = _aggregate_dashboard(_filter_months(mix_all, start, end), frequency, mix_flow)
            if not mix_frame.empty:
                mix_frame["other_thermal_generation_gwh"] = (
                    mix_frame["thermal_generation_gwh"] - mix_frame["coal_generation_gwh"] - mix_frame["lignite_generation_gwh"]
                ).clip(lower=0)
                mix_frame["other_renewables_total_gwh"] = (
                    mix_frame["renewables_ex_large_hydro_gwh"] - mix_frame["wind_generation_gwh"] - mix_frame["solar_generation_gwh"]
                ).clip(lower=0)
                mix_frame["coal_share_pct"] = mix_frame["coal_generation_gwh"] / mix_frame["total_generation_gwh"] * 100
                mix_frame["renewables_share_pct"] = (
                    mix_frame["renewables_ex_large_hydro_gwh"] + mix_frame["large_hydro_generation_gwh"]
                ) / mix_frame["total_generation_gwh"] * 100
        if not frame.empty:
            frame["production_yoy_pct"] = frame["production_mt"].pct_change() * 100
            if "dispatch_mt" in frame:
                frame["dispatch_yoy_pct"] = frame["dispatch_mt"].pct_change() * 100
        charts = [
            {"id": "supply-volume", "title": "Domestic production and dispatch", "subtitle": "Official national totals; gaps are retained, never interpolated", "x_label": "Reporting period", "y_label": "Million tonnes (MT)", "type": "line", "series": [
                {"key": "production_mt", "label": "Production", "color": "#003671"},
                {"key": "dispatch_mt", "label": "Dispatch", "color": "#db2f34"},
            ]},
            {"id": "supply-yoy", "title": "Period-on-period change", "subtitle": "Recomputed at the selected aggregation frequency", "x_label": "Reporting period", "y_label": "Change (%)", "type": "column", "series": [
                {"key": "production_yoy_pct", "label": "Production change", "color": "#003671"},
                {"key": "dispatch_yoy_pct", "label": "Dispatch change", "color": "#d8902f"},
            ]},
        ]
        if tab == "overview":
            charts = [
                charts[0],
                {"id": "overview-power", "title": "All-source electricity generation mix", "subtitle": "NPP conventional generation merged month-for-month with CEA renewable generation; installed capacity is never used as generation", "x_label": "Reporting period", "y_label": "Generation (GWh)", "type": "stacked_column", "rows": _json_records(mix_frame), "series": [
                    {"key": "coal_generation_gwh", "label": "Coal", "color": "#26344f"},
                    {"key": "lignite_generation_gwh", "label": "Lignite", "color": "#705747"},
                    {"key": "other_thermal_generation_gwh", "label": "Other thermal", "color": "#a46f5a"},
                    {"key": "nuclear_generation_gwh", "label": "Nuclear", "color": "#7d5ca6"},
                    {"key": "large_hydro_generation_gwh", "label": "Large hydro", "color": "#2e78b7"},
                    {"key": "wind_generation_gwh", "label": "Wind", "color": "#43a2ca"},
                    {"key": "solar_generation_gwh", "label": "Solar", "color": "#e4a72e"},
                    {"key": "other_renewables_total_gwh", "label": "Other renewables", "color": "#54a66f"},
                ]},
            ]
        latest = frame.dropna(subset=["production_mt"]).iloc[-1].to_dict() if not frame.dropna(subset=["production_mt"]).empty else {}
        latest_dispatch = frame.dropna(subset=["dispatch_mt"]).iloc[-1].to_dict() if "dispatch_mt" in frame and not frame.dropna(subset=["dispatch_mt"]).empty else {}
        kpis = [
            {"label": "Latest production", "value": latest.get("production_mt"), "unit": "MT", "detail": latest.get("period", "—")},
            {"label": "Latest dispatch", "value": latest_dispatch.get("dispatch_mt"), "unit": "MT", "detail": latest_dispatch.get("period", "—")},
            {"label": "Periods returned", "value": len(frame), "unit": "", "detail": f"{start} to {end}"},
            {"label": "Latest official month", "value": None, "display": quality.get("coal", {}).get("latest", "—"), "unit": "", "detail": "Provisional bulletin"},
        ]
        if tab == "overview" and not mix_frame.empty:
            power_latest = mix_frame.dropna(subset=["coal_share_pct"]).iloc[-1]
            kpis[2] = {"label": "Coal share of all generation", "value": power_latest["coal_share_pct"], "unit": "%", "detail": f"Coal ÷ all-source total · {power_latest['period']}"}
        tab_sources = [sources["coal"], sources["power"], sources["renewable"]] if tab == "overview" else [sources["coal"]]
        availability = {"start": str(coal_all.period.min()), "end": str(coal_all.period.max()), "grain": "monthly", "status": "provisional"}
    elif tab == "power":
        frame = _filter_months(power_all, start, end)
        flow = ["coal_generation_gwh", "lignite_generation_gwh", "thermal_generation_gwh",
                "nuclear_generation_gwh", "large_hydro_generation_gwh", "bhutan_import_gwh",
                "conventional_generation_gwh"]
        frame = _aggregate_dashboard(frame, frequency, flow)
        if not frame.empty:
            frame["coal_share_conventional_pct"] = frame["coal_generation_gwh"] / frame["conventional_generation_gwh"] * 100
        mix_flow = [
            "coal_generation_gwh", "lignite_generation_gwh", "thermal_generation_gwh",
            "nuclear_generation_gwh", "large_hydro_generation_gwh", "bhutan_import_gwh",
            "wind_generation_gwh", "solar_generation_gwh", "biomass_generation_gwh",
            "bagasse_generation_gwh", "small_hydro_generation_gwh",
            "other_renewables_generation_gwh", "renewables_ex_large_hydro_gwh",
            "total_generation_gwh",
        ]
        mix_frame = _aggregate_dashboard(_filter_months(mix_all, start, end), frequency, mix_flow)
        if not mix_frame.empty:
            mix_frame["other_thermal_generation_gwh"] = (
                mix_frame["thermal_generation_gwh"] - mix_frame["coal_generation_gwh"] - mix_frame["lignite_generation_gwh"]
            ).clip(lower=0)
            mix_frame["other_renewables_total_gwh"] = (
                mix_frame["renewables_ex_large_hydro_gwh"] - mix_frame["wind_generation_gwh"] - mix_frame["solar_generation_gwh"]
            ).clip(lower=0)
            mix_frame["coal_share_pct"] = mix_frame["coal_generation_gwh"] / mix_frame["total_generation_gwh"] * 100
            mix_frame["solar_share_pct"] = mix_frame["solar_generation_gwh"] / mix_frame["total_generation_gwh"] * 100
            mix_frame["renewables_share_pct"] = (
                mix_frame["renewables_ex_large_hydro_gwh"] + mix_frame["large_hydro_generation_gwh"]
            ) / mix_frame["total_generation_gwh"] * 100
            frame = mix_frame.copy()
        charts = [
            {"id": "power-generation", "title": "Monthly conventional generation by source", "subtitle": "NPP monthly actuals. This chart is explicitly conventional-only; renewables are shown in the all-source chart below.", "x_label": "Reporting period", "y_label": "Generation (GWh)", "type": "line", "series": [
                {"key": "coal_generation_gwh", "label": "Coal", "color": "#26344f"},
                {"key": "lignite_generation_gwh", "label": "Lignite", "color": "#705747"},
                {"key": "large_hydro_generation_gwh", "label": "Large hydro", "color": "#2e78b7"},
                {"key": "nuclear_generation_gwh", "label": "Nuclear", "color": "#7d5ca6"},
            ]},
            {"id": "power-all-source", "title": "All-source generation mix", "subtitle": "Monthly NPP + CEA actual generation, including wind, solar and other renewables", "x_label": "Reporting period", "y_label": "Generation (GWh)", "type": "stacked_column", "rows": _json_records(mix_frame), "series": [
                {"key": "coal_generation_gwh", "label": "Coal", "color": "#26344f"},
                {"key": "lignite_generation_gwh", "label": "Lignite", "color": "#705747"},
                {"key": "other_thermal_generation_gwh", "label": "Other thermal", "color": "#a46f5a"},
                {"key": "nuclear_generation_gwh", "label": "Nuclear", "color": "#7d5ca6"},
                {"key": "large_hydro_generation_gwh", "label": "Large hydro", "color": "#2e78b7"},
                {"key": "wind_generation_gwh", "label": "Wind", "color": "#43a2ca"},
                {"key": "solar_generation_gwh", "label": "Solar", "color": "#e4a72e"},
                {"key": "other_renewables_total_gwh", "label": "Other renewables", "color": "#54a66f"},
            ]},
            {"id": "power-share", "title": "All-source generation shares", "subtitle": "Coal and renewable shares use total generation as the denominator; renewables include large hydro", "x_label": "Reporting period", "y_label": "Share (%)", "type": "line", "rows": _json_records(mix_frame), "series": [
                {"key": "coal_share_pct", "label": "Coal share", "color": "#db2f34"},
                {"key": "renewables_share_pct", "label": "Renewables incl. large hydro", "color": "#2f8f56"},
                {"key": "solar_share_pct", "label": "Solar share", "color": "#e4a72e"},
            ]},
        ]
        latest = mix_frame.iloc[-1].to_dict() if not mix_frame.empty else {}
        kpis = [
            {"label": "Coal generation", "value": latest.get("coal_generation_gwh"), "unit": "GWh", "detail": latest.get("period", "—")},
            {"label": "Coal share of all generation", "value": latest.get("coal_share_pct"), "unit": "%", "detail": "All-source denominator"},
            {"label": "Renewables incl. large hydro", "value": latest.get("renewables_share_pct"), "unit": "%", "detail": latest.get("period", "—")},
            {"label": "Solar generation", "value": latest.get("solar_generation_gwh"), "unit": "GWh", "detail": latest.get("period", "—")},
        ]
        tab_sources = [sources["power"], sources["renewable"]]
        availability = {"start": str(mix_all.period.min()), "end": str(mix_all.period.max()), "grain": "monthly", "status": "official reported", "limitation": "NPP provides the conventional series; CEA Monthly Renewable Generation supplies wind, solar, biomass, bagasse, small hydro and other renewables."}
    elif tab == "trade":
        monthly = _filter_months(imports_all, start, end)
        if frequency == "financial_year":
            frame = annual_all[[column for column in [
                "period", "coking_imports_mt", "non_coking_imports_mt",
                "total_imports_mt", "status", "source_url",
            ] if column in annual_all.columns]].copy()
            frame = frame.rename(columns={
                "coking_imports_mt": "coking_coal_mt",
                "non_coking_imports_mt": "non_coking_coal_mt",
                "total_imports_mt": "total_coal_mt",
            })
            frame = frame.loc[(frame["period"] >= "2021-22") & (frame["period"] <= "2025-26")]
        else:
            frame = _aggregate_dashboard(
                monthly, frequency,
                ["coking_coal_mt", "non_coking_coal_mt", "total_coal_mt", "coke_products_mt"],
            )
        annual_imports = annual_all[[column for column in [
            "period", "coking_imports_mt", "non_coking_imports_mt",
            "total_imports_mt", "imports_yoy_pct", "status",
        ] if column in annual_all.columns]].copy()
        annual_imports = annual_imports.loc[annual_imports["period"] >= "2015-16"]
        charts = [
            {"id": "trade-volume", "title": "Monthly coal imports by coal type", "subtitle": "FY2024-25 final; FY2025-26 and April 2026 provisional. Values come from official DGCI&S/DDG tables and no missing month is interpolated.", "x_label": "Reporting period", "y_label": "Import quantity (MT)", "type": "column", "rows": _json_records(monthly), "series": [
                {"key": "coking_coal_mt", "label": "Coking coal", "color": "#8c2e3d"},
                {"key": "non_coking_coal_mt", "label": "Non-coking coal", "color": "#d8902f"},
            ]},
            {"id": "trade-annual", "title": "Annual coal imports and change", "subtitle": "Official financial-year totals through FY2025-26. Monthly rounded components can differ from the published annual total by 0.01 MT.", "x_label": "Financial year", "y_label": "Import quantity (MT)", "type": "column", "rows": _json_records(annual_imports), "series": [
                {"key": "coking_imports_mt", "label": "Coking coal", "color": "#8c2e3d"},
                {"key": "non_coking_imports_mt", "label": "Non-coking coal", "color": "#d8902f"},
            ]},
        ]
        latest = imports_all.sort_values("period").iloc[-1].to_dict() if not imports_all.empty else {}
        latest_annual = annual_all.sort_values("period").iloc[-1].to_dict() if not annual_all.empty else {}
        kpis = [
            {"label": "Latest imports", "value": latest.get("total_coal_mt"), "unit": "MT", "detail": latest.get("period", "No rows in range")},
            {"label": "Coking coal", "value": latest.get("coking_coal_mt"), "unit": "MT", "detail": latest.get("period", "—")},
            {"label": "Non-coking coal", "value": latest.get("non_coking_coal_mt"), "unit": "MT", "detail": latest.get("period", "—")},
            {"label": "FY2025-26 imports", "value": latest_annual.get("total_imports_mt"), "unit": "MT", "detail": "Published annual total"},
        ]
        tab_sources = [sources["imports_latest"], sources["imports_quarterly"], sources["directory"]]
        availability = {"start": str(imports_all.period.min()), "end": str(imports_all.period.max()), "grain": "monthly", "status": "final through 2025-03; provisional thereafter", "limitation": "Country and Indian-port breakdowns remain at FY2024-25, their latest loaded official granular release. Customs reporting country is not presented as physical mine origin."}
    else:  # stocks
        frame = annual_all[[column for column in ["period", "closing_stock_mt", "offtake_mt", "production_mt", "status"] if column in annual_all.columns]].copy()
        charts = [
            {"id": "stock-level", "title": "Pit-head closing stock", "subtitle": "Annual inventory at coal producers; not power-station stock-cover days", "x_label": "Financial year", "y_label": "Closing stock (MT)", "type": "column", "series": [
                {"key": "closing_stock_mt", "label": "Pit-head stock", "color": "#d8902f"},
            ]},
            {"id": "stock-flow", "title": "Production and off-take", "subtitle": "Annual supply-chain context", "x_label": "Financial year", "y_label": "Million tonnes (MT)", "type": "line", "series": [
                {"key": "production_mt", "label": "Production", "color": "#003671"},
                {"key": "offtake_mt", "label": "Off-take", "color": "#2e6d92"},
            ]},
        ]
        latest = frame.iloc[-1].to_dict() if not frame.empty else {}
        latest_stock_frame = frame.dropna(subset=["closing_stock_mt"]) if "closing_stock_mt" in frame else pd.DataFrame()
        latest_stock = latest_stock_frame.iloc[-1].to_dict() if not latest_stock_frame.empty else {}
        kpis = [
            {"label": "Pit-head closing stock", "value": latest_stock.get("closing_stock_mt"), "unit": "MT", "detail": latest_stock.get("period", "—")},
            {"label": "Annual off-take", "value": latest.get("offtake_mt"), "unit": "MT", "detail": latest.get("period", "—")},
            {"label": "Annual production", "value": latest.get("production_mt"), "unit": "MT", "detail": latest.get("period", "—")},
            {"label": "Stock-cover days", "value": None, "display": "Not substituted", "unit": "", "detail": "Requires plant inventory and burn rate"},
        ]
        tab_sources = [sources["directory"]]
        availability = {"start": str(frame.period.min()), "end": str(frame.period.max()), "grain": "financial year", "status": "final"}

    focus_options = {
        "overview": [("all", "All measures"), ("coal", "Coal"), ("renewables", "Renewables"), ("solar", "Solar"), ("hydro", "Large hydro")],
        "supply": [("all", "Production + dispatch"), ("production", "Production"), ("dispatch", "Dispatch")],
        "trade": [("all", "All coal imports"), ("coking", "Coking coal"), ("non_coking", "Non-coking coal")],
        "power": [("all", "All generation sources"), ("coal", "Coal"), ("renewables", "Renewables"), ("solar", "Solar"), ("hydro", "Large hydro")],
        "stocks": [("all", "Stocks + supply"), ("stock", "Pit-head stock"), ("production", "Production"), ("offtake", "Off-take")],
        "table": [("all", "All measures"), ("production", "Production"), ("dispatch", "Dispatch")],
    }
    allowed_focus = {item[0] for item in focus_options[tab]}
    if focus not in allowed_focus:
        focus = "all"
    focus_keys = {
        "coal": {"coal_generation_gwh", "coal_share_pct", "coal_share_conventional_pct"},
        "renewables": {"renewables_share_pct", "renewables_ex_large_hydro_gwh", "wind_generation_gwh", "solar_generation_gwh", "other_renewables_total_gwh", "large_hydro_generation_gwh"},
        "solar": {"solar_generation_gwh", "solar_share_pct"},
        "hydro": {"large_hydro_generation_gwh"},
        "production": {"production_mt", "production_yoy_pct", "production_prior_year_mt", "production_ytd_mt"},
        "dispatch": {"dispatch_mt", "dispatch_yoy_pct", "dispatch_prior_year_mt", "dispatch_ytd_mt"},
        "coking": {"coking_coal_mt", "coking_imports_mt"},
        "non_coking": {"non_coking_coal_mt", "non_coking_imports_mt"},
        "stock": {"closing_stock_mt"},
        "offtake": {"offtake_mt"},
    }.get(focus)
    context_columns = {"period", "financial_year", "status", "source_url"}
    if focus_keys:
        focused_charts = []
        for chart in charts:
            filtered_series = [series for series in chart.get("series", []) if series.get("key") in focus_keys]
            if filtered_series:
                chart["series"] = filtered_series
                if chart.get("rows"):
                    chart_columns = context_columns | {series["key"] for series in filtered_series}
                    chart["rows"] = [
                        {key: value for key, value in row.items() if key in chart_columns}
                        for row in chart["rows"]
                    ]
                focused_charts.append(chart)
            elif not (tab == "overview" and focus in {"renewables", "solar", "hydro"}):
                focused_charts.append(chart)
        charts = focused_charts
        selected_columns = [column for column in frame.columns if column in context_columns or column in focus_keys]
        if len(selected_columns) > 1:
            frame = frame[selected_columns]

    return {
        "tab": tab, "frequency": frequency, "filters": {"from": start, "to": end},
        "focus": focus, "comparison": comparison,
        "focus_options": [{"id": item[0], "label": item[1]} for item in focus_options[tab]],
        "available_range": availability, "kpis": kpis, "charts": charts,
        "columns": list(frame.columns), "rows": _json_records(frame), "sources": tab_sources,
        "quality": {"generated_at": quality.get("generated_at"), "missing_values_retained": True,
                    "note": "Official values only. Missing observations remain blank and are excluded from calculations."},
    }


def _research_payload(question: str) -> Dict[str, Any]:
    text = " ".join(question.lower().split())
    sources: List[Dict[str, str]] = []
    unit = "million tonnes"
    chart_type = "line"
    category = "period"
    status = "official final"

    if any(token in text for token in ("electric", "generation", "solar", "hydro", "renewable", "power mix")):
        all_source_june = (
            any(token in text for token in ("solar", "renewable", "all-source", "all source"))
            or ("percentage" in text and "june 2026" in text and "june 2025" in text)
        )
        frame = _canonical_frame("india_power_mix_june.csv" if all_source_june else "india_power_generation_monthly.csv")
        title = "India electricity generation mix — June comparison" if all_source_june else "India monthly conventional generation mix"
        if "solar" in text:
            columns = ["period", "solar_generation_gwh", "solar_share_pct", "total_generation_gwh", "status"]
            series = [{"key": "solar_share_pct", "label": "Solar share", "color": "#d8902f"}]
            unit = "% of all-source generation"
        elif "hydro" in text or "monsoon" in text or "reservoir" in text:
            columns = ["period", "coal_generation_gwh", "large_hydro_generation_gwh", "coal_share_conventional_pct", "status"]
            series = [
                {"key": "coal_generation_gwh", "label": "Coal", "color": "#1f2a3f"},
                {"key": "large_hydro_generation_gwh", "label": "Large hydro", "color": "#296fba"},
            ]
            unit = "GWh"
            title = "Monthly coal and large-hydro generation"
        else:
            if all_source_june:
                columns = ["period", "coal_generation_gwh", "coal_share_pct", "solar_generation_gwh", "solar_share_pct", "large_hydro_generation_gwh", "wind_generation_gwh", "nuclear_generation_gwh", "total_generation_gwh", "status"]
                series = [
                    {"key": "coal_share_pct", "label": "Coal share", "color": "#1f2a3f"},
                    {"key": "solar_share_pct", "label": "Solar share", "color": "#d8902f"},
                ]
                unit = "% of all-source generation"
            else:
                columns = ["period", "coal_generation_gwh", "lignite_generation_gwh", "large_hydro_generation_gwh", "nuclear_generation_gwh", "conventional_generation_gwh", "coal_share_conventional_pct", "status"]
                series = [
                    {"key": "coal_generation_gwh", "label": "Coal", "color": "#1f2a3f"},
                    {"key": "large_hydro_generation_gwh", "label": "Large hydro", "color": "#296fba"},
                ]
                unit = "GWh"
        sources = [
            {"title": "NPP Monthly Actual Generation Report", "url": "https://npp.gov.in/publishedReports"},
            {"title": "CEA Renewable Generation Report", "url": "https://cea.nic.in/renewable-generation-report/?lang=en"},
        ]
    elif any(token in text for token in ("steel", "hot metal", "coking consumption", "coking coal consumption", "blend")):
        frame = _canonical_frame("steel_plant_coking_coal.csv")
        title = "Steel-plant coking coal consumption"
        category = "steel_plant"
        columns = ["steel_plant", "period", "prime_coking_kt", "medium_coking_kt", "blendable_kt", "imported_coking_kt", "total_coking_kt", "hot_metal_kt", "status"]
        series = [{"key": "total_coking_kt", "label": "Total coking coal", "color": "#8c2e3d"}]
        unit = "thousand tonnes"
        chart_type = "bar"
        sources = [{"title": "Coal Directory 2024-25, Table 8.2", "url": "https://coal.gov.in/sites/default/files/2024-03/cdchap8.xlsx"}]
    elif re.search(r"\b(ports?|clearance|discharge)\b", text):
        frame = _canonical_frame("coal_imports_by_port.csv")
        title = "Coal imports by Indian customs port"
        category = "import_port"
        columns = ["import_port", "period", "coking_coal_mt", "non_coking_coal_mt", "total_coal_mt", "status"]
        series = [{"key": "total_coal_mt", "label": "Total coal", "color": "#003671"}]
        chart_type = "bar"
        sources = [{"title": "Coal Directory 2024-25, Table 8.5", "url": "https://coal.gov.in/sites/default/files/2024-03/cdchap7.xlsx"}]
    elif any(token in text for token in ("origin", "supplier", "country", "australia", "indonesia", "south africa")):
        frame = _canonical_frame("coal_imports_by_origin.csv")
        title = "Coal imports by reported country of origin"
        category = "origin_country"
        columns = ["origin_country", "period", "coking_coal_mt", "non_coking_coal_mt", "total_coal_mt", "status"]
        series = [{"key": "total_coal_mt", "label": "Total coal", "color": "#db2f34"}]
        chart_type = "bar"
        sources = [{"title": "Coal Directory 2024-25, Table 8.3", "url": "https://coal.gov.in/sites/default/files/2024-03/cdchap7.xlsx"}]
    elif any(token in text for token in ("sector", "used", "use", "cement", "sponge", "offtake", "off-take")):
        frame = _canonical_frame("coal_offtake_by_sector.csv")
        title = "Domestic coal off-take by consuming sector"
        columns = list(frame.columns)
        series = [
            {"key": "power_utility_mt", "label": "Utility power", "color": "#003671"},
            {"key": "cement_mt", "label": "Cement", "color": "#d8902f"},
            {"key": "sponge_iron_mt", "label": "Sponge iron", "color": "#8c2e3d"},
        ]
        sources = [{"title": "Coal Directory 2024-25, Table 4.22", "url": "https://coal.gov.in/sites/default/files/2024-03/cdchap3.xlsx"}]
    elif "import" in text and any(token in text for token in ("month", "monthly", "2024-25", "coking", "non-coking")):
        frame = _canonical_frame("coal_imports_monthly.csv")
        title = "Monthly coal imports by coal type"
        columns = list(frame.columns)
        series = [
            {"key": "coking_coal_mt", "label": "Coking", "color": "#8c2e3d"},
            {"key": "non_coking_coal_mt", "label": "Non-coking", "color": "#d8902f"},
        ]
        sources = [{"title": "Coal Directory 2024-25, Table 8.7", "url": "https://coal.gov.in/sites/default/files/2024-03/cdchap7.xlsx"}]
    elif "production" in text and any(token in text for token in ("month", "monthly", "2024-25", "coking", "lignite")):
        detailed_type = any(token in text for token in ("coking", "lignite", "non-coking", "non coking"))
        frame = _canonical_frame("coal_production_monthly.csv" if detailed_type else "coal_monthly_official.csv")
        title = "Monthly domestic coal production by type" if detailed_type else "Monthly domestic coal production and dispatch"
        columns = list(frame.columns)
        series = ([
            {"key": "coking_coal_mt", "label": "Coking", "color": "#8c2e3d"},
            {"key": "non_coking_coal_mt", "label": "Non-coking", "color": "#003671"},
        ] if detailed_type else [
            {"key": "production_mt", "label": "Production", "color": "#003671"},
            {"key": "dispatch_mt", "label": "Dispatch", "color": "#db2f34"},
        ])
        sources = ([{"title": "Coal Directory 2024-25, Table 3.6", "url": "https://coal.gov.in/sites/default/files/2024-03/cdchap2.xlsx"}]
                   if detailed_type else [{"title": "Ministry of Coal — Monthly Statistics at a Glance", "url": "https://coal.gov.in/public-information/monthly-statistics-at-glance"}])
    else:
        frame = _canonical_frame("coal_india_annual.csv")
        title = "India coal supply balance"
        columns = list(frame.columns)
        series = [
            {"key": "production_mt", "label": "Production", "color": "#003671"},
            {"key": "total_imports_mt", "label": "Imports", "color": "#db2f34"},
        ]
        sources = [{"title": "Coal Directory 2024-25 annual tables", "url": "https://coal.gov.in/major-statistics/coal-statistics"}]

    if "weekly" in text and title.startswith("Monthly"):
        raise HTTPException(409, "No official weekly series is loaded for this dataset. Monthly is the finest verified frequency currently available.")
    if "quarter" in text and title.startswith("Monthly") and not frame.empty:
        dates = pd.to_datetime(frame["period"].astype(str) + "-01", errors="coerce")
        numeric_columns = [column for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
        # Dashboard quarter labels use calendar quarters.  A fiscal year ending
        # in March would label Apr-Jun 2026 as 2027Q1, which is technically a
        # fiscal-period convention but misleading in a calendar date filter.
        frame = frame.assign(period=dates.dt.to_period("Q").astype(str))
        frame = frame.groupby("period", as_index=False)[numeric_columns].sum(min_count=1)
        title = title.replace("Monthly", "Quarterly")
        columns = list(frame.columns)
    grade_tokens = None
    if "non-coking" in text or "non coking" in text or "thermal coal" in text:
        grade_tokens = ("period", "financial_year", "non_coking", "total", "status")
    elif "coking" in text and "non-coking" not in text and "non coking" not in text:
        grade_tokens = ("period", "financial_year", "coking", "status")
    elif "lignite" in text:
        grade_tokens = ("period", "financial_year", "lignite", "status")
    if grade_tokens and title.startswith(("Monthly", "Quarterly")):
        selected = [column for column in frame.columns if any(token in column.lower() for token in grade_tokens)]
        if selected:
            frame = frame[selected]
            columns = selected
            series = [item for item in series if item["key"] in selected]
    requested_years = sorted(set(re.findall(r"\b20\d{2}\b", text)))
    if requested_years and "period" in frame.columns:
        period_text = frame["period"].astype(str)
        frame = frame[period_text.str[:4].isin(requested_years)].copy()
    if frame.empty:
        raise HTTPException(404, "The requested official research dataset is not available.")
    frame = frame[[column for column in columns if column in frame.columns]].copy()
    if category in frame.columns and chart_type == "bar":
        numeric_key = series[0]["key"]
        frame = frame.sort_values(numeric_key, ascending=False).head(20)
    records = frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")
    period_values = [str(item.get("period")) for item in records if item.get("period")]
    latest = max(period_values) if period_values else "available period"
    answer = f"Returned {len(records)} official observations through {latest}. Hover the chart for exact values and download the filtered result below."
    if len(records) >= 2 and "coal_share_pct" in frame.columns:
        first, last = records[0], records[-1]
        delta = float(last["coal_share_pct"]) - float(first["coal_share_pct"])
        answer = (
            f"Coal-fired plants supplied {float(last['coal_share_pct']):.2f}% of all-source "
            f"generation in {last['period']}, versus {float(first['coal_share_pct']):.2f}% "
            f"in {first['period']} ({delta:+.2f} percentage points). The denominator includes "
            "thermal, nuclear, large hydro, Bhutan imports and CEA renewables without double-counting large hydro."
        )
    elif len(records) >= 2 and "solar_share_pct" in frame.columns:
        first, last = records[0], records[-1]
        delta = float(last["solar_share_pct"]) - float(first["solar_share_pct"])
        generation_growth = (float(last["solar_generation_gwh"]) / float(first["solar_generation_gwh"]) - 1) * 100
        answer = (
            f"Solar supplied {float(last['solar_share_pct']):.2f}% of all-source generation in "
            f"{last['period']}, up {delta:.2f} percentage points from {first['period']}; "
            f"solar output increased {generation_growth:.1f}% year on year."
        )
    elif len(records) >= 2 and "large_hydro_generation_gwh" in frame.columns and "coal_generation_gwh" in frame.columns:
        first, last = records[0], records[-1]
        coal_growth = (float(last["coal_generation_gwh"]) / float(first["coal_generation_gwh"]) - 1) * 100
        hydro_growth = (float(last["large_hydro_generation_gwh"]) / float(first["large_hydro_generation_gwh"]) - 1) * 100
        answer = (
            f"In the June comparison, coal generation changed {coal_growth:+.1f}% while large-hydro "
            f"generation changed {hydro_growth:+.1f}%. This is a descriptive comparison, not a "
            "monsoon-effect estimate; that requires aligned multi-year rainfall, reservoir and monthly generation data."
        )
    return {
        "question": question,
        "title": title,
        "answer": answer,
        "unit": unit,
        "status": status,
        "chart": {"type": chart_type, "category": category, "series": series},
        "columns": list(frame.columns),
        "rows": records,
        "sources": sources,
        "guardrail": "Associations and comparisons are descriptive; they do not by themselves establish causation.",
    }


def _period_limit(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    limits = {"12m": 1, "3y": 3, "5y": 5, "10y": 10}
    count = limits.get(period)
    if not count or "period" not in frame.columns or frame.empty:
        return frame
    values = frame["period"].astype(str)
    if values.str.fullmatch(r"\d{4}-\d{2}").all():
        dates = pd.to_datetime(values + "-01", errors="coerce")
        latest = dates.max()
        if pd.notna(latest):
            first = latest - pd.DateOffset(months=count * 12 - 1)
            return frame.loc[dates >= first].copy()
    years = pd.to_numeric(values.str[:4], errors="coerce")
    if years.notna().any():
        return frame.loc[years >= years.max() - count + 1].copy()
    return frame


def _filtered_official_frame(
    dataset_type: str, frequency: str, coal_type: str, period: str
) -> tuple[pd.DataFrame, str, str]:
    if dataset_type == "production":
        if frequency == "yearly":
            frame = _canonical_frame("coal_india_annual.csv")
            label = "Official annual production"
        elif frequency in {"monthly", "quarterly"}:
            frame = _canonical_frame("coal_monthly_official.csv")
            label = "Official Ministry monthly production"
        else:
            raise HTTPException(409, "No official weekly production series is loaded. Choose monthly, quarterly or yearly.")
    elif dataset_type == "imports":
        if frequency == "yearly":
            frame = _canonical_frame("coal_india_annual.csv")
            label = "Official annual imports"
        elif frequency in {"monthly", "quarterly"}:
            frame = _canonical_frame("coal_imports_monthly.csv")
            label = "Official monthly imports"
        else:
            raise HTTPException(409, "No official weekly import series is loaded. Choose monthly, quarterly or yearly.")
    elif dataset_type == "power_use":
        if frequency != "yearly":
            raise HTTPException(409, "The loaded official sector off-take series is yearly. Choose yearly.")
        frame = _canonical_frame("coal_offtake_by_sector.csv")
        label = "Official coal off-take by sector"
    elif dataset_type == "renewables":
        if frequency not in {"monthly", "yearly"}:
            raise HTTPException(409, "The loaded official power-mix comparison is monthly (June snapshots).")
        frame = _canonical_frame("india_power_generation_monthly.csv")
        label = "Official NPP monthly generation mix"
    elif dataset_type == "power_stocks":
        raise HTTPException(409, "Plant-level stock-cover days are not yet present in the canonical store; pit-head stock will not be substituted.")
    else:
        raise HTTPException(409, "No canonical official weather/driver series is loaded for this selection.")
    if frame.empty:
        raise HTTPException(404, "The selected canonical dataset is unavailable.")

    if frequency == "quarterly" and "period" in frame.columns:
        dates = pd.to_datetime(frame["period"].astype(str) + "-01", errors="coerce")
        numeric = [column for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
        frame = frame.assign(period=dates.dt.to_period("Q").astype(str))
        frame = frame.groupby("period", as_index=False)[numeric].sum(min_count=1)
        label = label.replace("monthly", "quarterly")

    grade = coal_type.strip().lower()
    if grade and grade != "thermal":
        tokens = {
            "coking": ("period", "financial_year", "coking", "status"),
            "lignite": ("period", "financial_year", "lignite", "status"),
        }.get(grade)
        if tokens:
            selected = [column for column in frame.columns if any(token in column.lower() for token in tokens)]
            if selected:
                frame = frame[selected]
    elif grade == "thermal":
        selected = [
            column for column in frame.columns
            if any(token in column.lower() for token in ("period", "financial_year", "non_coking", "total", "status"))
        ]
        if selected:
            frame = frame[selected]
    frame = _period_limit(frame, period)
    return frame, label, "Official values only; status columns identify final/provisional observations."


def _india_coal_port_specs() -> Dict[str, Any]:
    if not INDIA_COAL_PORT_SPECS_PATH.exists():
        return {
            "dataset": "India coal-port specifications",
            "quality_summary": {},
            "ports": [],
        }
    try:
        payload = json.loads(
            INDIA_COAL_PORT_SPECS_PATH.read_text(encoding="utf-8")
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("ports"), list
        ):
            raise ValueError("Invalid port specification dataset shape")
        return payload
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Could not load India coal-port specifications: %s", exc)
        return {
            "dataset": "India coal-port specifications",
            "quality_summary": {},
            "ports": [],
        }


def _port_specification_summary(
    specification: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not specification:
        return None
    return {
        "official_port_name": specification.get("official_port_name"),
        "state_ut": specification.get("state_ut"),
        "port_class": specification.get("port_class"),
        "max_documented_draft_m": specification.get(
            "max_documented_draft_m"
        ),
        "documented_berth_count": specification.get(
            "documented_berth_count"
        ),
        "port_capacity_mtpa": specification.get("port_capacity_mtpa"),
        "latest_traffic_mt": specification.get("latest_traffic_mt"),
        "latest_traffic_period": specification.get(
            "latest_traffic_period"
        ),
        "official_website": specification.get("official_website"),
        "source_as_of": specification.get("source_as_of"),
    }


def _coal_asset_rows(status_group: str = "operating") -> List[Dict[str, Any]]:
    if status_group not in STATUS_GROUPS:
        raise ValueError("Status must be operating, construction or proposed")
    allowed_statuses = STATUS_GROUPS[status_group]
    table_names = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    rows: List[Dict[str, Any]] = []
    coal_terminal_identities: set[str] = set()
    for tracker_id, label, asset_kind in (
        ("coal_mines", "Coal mine", "coal_mines"),
        ("steel_plants", "Steel plant", "steel_consumers"),
        ("cement_plants", "Cement plant", "cement_consumers"),
    ):
        if tracker_id not in table_names:
            continue
        placeholders = ",".join(["?"] * len(allowed_statuses))
        frame = con.execute(
            "SELECT asset_id AS id, name, status, capacity, capacity_unit, "
            "lat, lon, country, asset_type, parent_port, source_text "
            f"FROM {tracker_id} WHERE LOWER(CAST(country AS VARCHAR)) = 'india' "
            f"AND LOWER(TRIM(CAST(status AS VARCHAR))) IN ({placeholders})",
            sorted(allowed_statuses),
        ).fetchdf()
        for record in json.loads(frame.to_json(orient="records")):
            record["source_status"] = record.get("status")
            record["status"] = (
                "Operating"
                if status_group == "operating"
                else (
                    "Under construction"
                    if status_group == "construction"
                    else "Proposed"
                )
            )
            record["asset_kind"] = asset_kind
            record["asset_label"] = label
            record["project_status"] = (
                "Under construction" if status_group == "construction"
                else status_group.title()
            )
            rows.append(record)

    if "coal_plants" in table_names:
        placeholders = ",".join(["?"] * len(allowed_statuses))
        frame = con.execute(
            'SELECT "Plant name" AS name, LOWER(TRIM(CAST("Status" AS VARCHAR))) '
            'AS source_status, SUM(TRY_CAST("Capacity (MW)" AS DOUBLE)) AS capacity, '
            'COUNT(*) AS unit_count, '
            'MIN(TRY_CAST("Start year" AS INTEGER)) AS commissioning_start_year, '
            'MAX(TRY_CAST("Start year" AS INTEGER)) AS commissioning_end_year, '
            'AVG(TRY_CAST("Latitude" AS DOUBLE)) AS lat, '
            'AVG(TRY_CAST("Longitude" AS DOUBLE)) AS lon, '
            'MAX(CAST("Country/Area" AS VARCHAR)) AS country, '
            'MAX(CAST("GEM location ID" AS VARCHAR)) AS gem_location_id, '
            'MAX(CAST("Owner" AS VARCHAR)) AS owner, '
            'MAX(CAST("Parent" AS VARCHAR)) AS parent_company, '
            'MAX(CAST("Combustion technology" AS VARCHAR)) AS combustion_technology, '
            'MAX(CAST("Coal type" AS VARCHAR)) AS coal_type, '
            'MAX(CAST("Coal source" AS VARCHAR)) AS coal_source, '
            'MAX(CAST("Location" AS VARCHAR)) AS location, '
            'MAX(CAST("Major area (prefecture, district)" AS VARCHAR)) AS district, '
            'MAX(CAST("Subnational unit (province, state)" AS VARCHAR)) AS state, '
            'MAX(CAST("Permits" AS VARCHAR)) AS permits, '
            'MAX(CAST("Captive industry use" AS VARCHAR)) AS captive_use, '
            'AVG(TRY_CAST("Capacity factor" AS DOUBLE)) AS capacity_factor, '
            'SUM(TRY_CAST("Annual CO2 (million tonnes / annum)" AS DOUBLE)) AS annual_co2_mtpa, '
            'MAX(CAST("Wiki URL" AS VARCHAR)) AS source_url '
            'FROM coal_plants WHERE LOWER(CAST("Country/Area" AS VARCHAR)) = ? '
            f'AND LOWER(TRIM(CAST("Status" AS VARCHAR))) IN ({placeholders}) '
            'GROUP BY 1, 2',
            ["india", *sorted(allowed_statuses)],
        ).fetchdf()
        for index, record in enumerate(
            json.loads(frame.to_json(orient="records"))
        ):
            record.update(
                {
                    "id": f"india-coal-power-{index + 1}",
                    "status": (
                        "Under construction"
                        if status_group == "construction"
                        else status_group.title()
                    ),
                    "project_status": (
                        "Under construction"
                        if status_group == "construction"
                        else status_group.title()
                    ),
                    "capacity_unit": "MW",
                    "asset_type": "Coal-fired power",
                    "parent_port": None,
                    "source_text": "Global Energy Monitor coal plant tracker",
                    "asset_kind": "power_consumers",
                    "asset_label": "Coal-fired power plant",
                    "npp_source_url": NPP_PUBLISHED_REPORTS_URL,
                    "ministry_coal_source_url": MINISTRY_COAL_LINKAGE_URL,
                }
            )
            record.update(
                CEA_VERIFIED_COAL_PLANTS.get(
                    str(record.get("gem_location_id") or ""), {}
                )
            )
            rows.append(record)

    if "coal_trade_terminals" in table_names:
        port_specifications = _india_coal_port_specs()
        specifications_by_id = {
            str(item.get("asset_id")): item
            for item in port_specifications.get("ports", [])
            if item.get("asset_id")
        }
        terminal_frame = con.execute(
            "SELECT asset_id AS id, name, status, capacity, capacity_unit, "
            "lat, lon, country, asset_type, parent_port, source_text "
            "FROM coal_trade_terminals "
            "WHERE LOWER(CAST(country AS VARCHAR)) = 'india' "
            "AND LOWER(TRIM(CAST(status AS VARCHAR))) IN "
            "('operating','construction','proposed')"
        ).fetchdf()
        terminals = json.loads(terminal_frame.to_json(orient="records"))
        by_parent: Dict[str, List[Dict[str, Any]]] = {}
        for terminal in terminals:
            key = str(
                terminal.get("parent_port")
                or terminal.get("name")
                or terminal.get("id")
            ).strip()
            by_parent.setdefault(key, []).append(terminal)
        for parent, group in by_parent.items():
            operating = [
                item for item in group
                if str(item.get("status") or "").lower() == "operating"
            ]
            expansion = [
                item for item in group
                if str(item.get("status") or "").lower()
                in {"construction", "proposed"}
            ]
            selected = (
                operating if status_group == "operating"
                else [
                    item for item in group
                    if str(item.get("status") or "").lower()
                    in allowed_statuses
                ]
            )
            if not selected:
                continue
            representative = selected[0]
            operating_capacity = sum(
                float(item.get("capacity") or 0) for item in operating
            )
            expansion_capacity = sum(
                float(item.get("capacity") or 0) for item in expansion
            )
            project_status = (
                "Operating" if status_group == "operating"
                else (
                    "Under construction"
                    if status_group == "construction"
                    else "Proposed"
                )
            )
            display_status = (
                "Operating"
                if operating
                else project_status
            )
            terminal_id = (
                "india-coal-terminal-"
                + re.sub(r"[^a-z0-9]+", "-", parent.lower()).strip("-")
            )
            terminal_row = {
                    **representative,
                    "id": terminal_id,
                    "name": parent,
                    "status": display_status,
                    "project_status": project_status,
                    "capacity": (
                        operating_capacity
                        if operating
                        else sum(float(item.get("capacity") or 0) for item in selected)
                    ),
                    "operating_capacity": operating_capacity or None,
                    "expansion_capacity": expansion_capacity or None,
                    "expansion_status": sorted(
                        {
                            (
                                "Under construction"
                                if str(item.get("status") or "").lower()
                                == "construction"
                                else "Proposed"
                            )
                            for item in expansion
                        }
                    ),
                    "potential_capacity": (
                        operating_capacity + expansion_capacity
                        if operating_capacity or expansion_capacity
                        else None
                    ),
                    "asset_kind": "coal_trade_terminals",
                    "asset_label": "Coal trade terminal",
                    "canonical_port_id": _india_port_identity(parent),
                    "source_record_count": len(group),
                }
            port_summary = _port_specification_summary(
                specifications_by_id.get(terminal_id)
            )
            terminal_row["port_specification"] = port_summary
            terminal_row["port_specification_available"] = bool(port_summary)
            rows.append(terminal_row)
            if terminal_row["canonical_port_id"]:
                coal_terminal_identities.add(terminal_row["canonical_port_id"])

    if status_group == "operating":
        for port in ports.filtered(
            categories=["dry_bulk"], countries=["IN"]
        ):
            compact = ports.compact(port)
            canonical_port_id = _india_port_identity(compact["name"])
            if canonical_port_id in coal_terminal_identities:
                continue
            rows.append(
                {
                    "id": compact["id"],
                    "name": compact["name"],
                    "status": "Operating",
                    "project_status": "Operating",
                    "capacity": None,
                    "capacity_unit": None,
                    "lat": compact["lat"],
                    "lon": compact["lon"],
                    "country": "India",
                    "asset_type": (
                        "Coal-linked"
                        if "coal" in compact["categories"]
                        else "Dry bulk"
                    ),
                    "parent_port": None,
                    "source_text": (
                        "NGA World Port Index; port role is source-classified "
                        "only and no project pipeline status is inferred"
                    ),
                    "asset_kind": "dry_bulk_ports",
                    "asset_label": "Dry-bulk port",
                    "canonical_port_id": canonical_port_id,
                }
            )
    return rows


_npp_cache_lock = asyncio.Lock()
_npp_memory_cache: Optional[Dict[str, Any]] = None


def _npp_iso_date(value: Any) -> Optional[str]:
    try:
        india_timezone = timezone(timedelta(hours=5, minutes=30))
        return datetime.fromtimestamp(
            float(value) / 1000, tz=india_timezone
        ).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _transform_npp_power(
    all_india: Dict[str, Any],
    history: Dict[str, Any],
    generation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    generation = generation or {}
    installed = all_india.get("installed_Capacity") or {}
    status = all_india.get("monthlyAllIndiaGen") or {}
    category = [
        {"id": "thermal", "label": "Thermal", "mw": installed.get("installed_capacity_thermal")},
        {"id": "hydro", "label": "Hydro", "mw": installed.get("installed_capacity_hydro")},
        {"id": "nuclear", "label": "Nuclear", "mw": installed.get("installed_capacity_nuclear")},
        {"id": "renewables", "label": "Renewable energy", "mw": installed.get("installed_capacity_res")},
    ]
    category = [
        {**item, "mw": float(item["mw"] or 0)}
        for item in category
    ]
    sector = [
        {
            "id": re.sub(
                r"[^a-z0-9]+",
                "_",
                str(item.get("sector_name") or "").lower(),
            ).strip("_"),
            "label": str(item.get("sector_name") or "").title(),
            "mw": float(item.get("installed_capacity") or 0),
        }
        for item in (all_india.get("installed_Capacity_List") or [])
        if item.get("sector_name")
    ]
    daily_demand = [
        {
            "date": item.get("reporting_date"),
            "peak_requirement_mw": float(item.get("peak_requirement") or 0),
            "demand_met_mw": float(item.get("max_demand_met") or 0),
            "deficit_mw": float(item.get("surplus_deficit") or 0),
        }
        for item in (all_india.get("dailyDemmandCp") or [])
    ]
    historical = []
    for item in history.get("linechartforCapacity") or []:
        row = {
            "date": _npp_iso_date(item.get("reporting_date")),
            "thermal_mw": float(item.get("installed_capacity_thermal") or 0),
            "hydro_mw": float(item.get("installed_capacity_hydro") or 0),
            "nuclear_mw": float(item.get("installed_capacity_nuclear") or 0),
            "renewables_mw": float(item.get("installed_capacity_res") or 0),
        }
        row["total_mw"] = sum(
            row[key]
            for key in ("thermal_mw", "hydro_mw", "nuclear_mw", "renewables_mw")
        )
        historical.append(row)
    historical = sorted(
        [row for row in historical if row["date"]],
        key=lambda row: row["date"],
    )
    installed_total = float(
        status.get("installed_capacity")
        or sum(item["mw"] for item in category)
    )
    category_total = sum(item["mw"] for item in category)
    sector_total = sum(item["mw"] for item in sector)
    tolerance = max(1.0, installed_total * 0.001)
    quality_checks = {
        "category_reconciles": abs(category_total - installed_total) <= tolerance,
        "sector_reconciles": abs(sector_total - installed_total) <= tolerance,
        "daily_demand_available": bool(daily_demand),
        "history_available": bool(historical),
    }
    daily_generation_source = generation.get("dailyPGen") or {}
    daily_generation = {
        "date": _npp_iso_date(daily_generation_source.get("generation_date")),
        "prior_year_date": _npp_iso_date(
            daily_generation_source.get("generation_date_ly")
        ),
        "actual_mu": float(
            daily_generation_source.get("actual_generation") or 0
        ),
        "prior_year_actual_mu": float(
            daily_generation_source.get("actual_generation_ly") or 0
        ),
        "program_mu": float(
            daily_generation_source.get("program_generation") or 0
        ),
        "deviation_percent": float(
            daily_generation_source.get("pdeviation") or 0
        ),
    }
    cumulative_generation = {
        "period_start": _npp_iso_date(
            daily_generation_source.get("generation_date_apr")
        ),
        "period_end": _npp_iso_date(
            daily_generation_source.get("generation_date")
        ),
        "prior_period_start": _npp_iso_date(
            daily_generation_source.get("generation_date_apr_ly")
        ),
        "prior_period_end": _npp_iso_date(
            daily_generation_source.get("generation_date_ly")
        ),
        "actual_mu": float(
            daily_generation_source.get("actual_generation_cumulative") or 0
        ),
        "prior_year_actual_mu": float(
            daily_generation_source.get(
                "actual_generation_cumulative_ly"
            ) or 0
        ),
        "program_mu": float(
            daily_generation_source.get("program_generation_cumulative") or 0
        ),
        "deviation_percent": float(
            daily_generation_source.get("pdeviation_cumulative") or 0
        ),
    }
    stock_band_fields = (
        ("0–5 days", "coal_0_5"),
        ("6–15 days", "coal_5_15"),
        ("16–25 days", "coal_15_25"),
        ("26+ days", "coal_gt_25"),
    )
    stock_mode_labels = {
        "N": "Non-pithead stations",
        "P": "Pithead stations",
    }
    coal_stock_availability = []
    coal_stock_date = None
    for item in generation.get("dailyColeStock") or []:
        mode = str(item.get("mode_transport") or "").upper()
        coal_stock_date = coal_stock_date or _npp_iso_date(
            item.get("coal_date")
        )
        for band, field in stock_band_fields:
            coal_stock_availability.append(
                {
                    "stock_cover_band": band,
                    "station_type": stock_mode_labels.get(
                        mode, f"Mode {mode or 'unclassified'}"
                    ),
                    "station_count": int(item.get(field) or 0),
                }
            )
    plf_rows = generation.get("plfMonthWise") or []

    def plf_snapshot(item: Dict[str, Any], category_name: str) -> Dict[str, Any]:
        return {
            "category": category_name,
            "financial_year": item.get("fin_year"),
            "report_type": item.get("report_type"),
            "period_end": _npp_iso_date(item.get("month_period_end")),
            "all_india_percent": float(item.get("plf_allindia") or 0),
            "central_percent": float(item.get("plf_central") or 0),
            "state_percent": float(item.get("plf_state") or 0),
            "private_percent": float(item.get("plf_private") or 0),
        }

    sector_plf = {
        "thermal_current": (
            plf_snapshot(plf_rows[0], "Thermal") if len(plf_rows) > 0 else None
        ),
        "thermal_previous": (
            plf_snapshot(plf_rows[1], "Thermal") if len(plf_rows) > 1 else None
        ),
        "nuclear_current": (
            plf_snapshot(plf_rows[2], "Nuclear") if len(plf_rows) > 2 else None
        ),
        "nuclear_previous": (
            plf_snapshot(plf_rows[3], "Nuclear") if len(plf_rows) > 3 else None
        ),
    }
    generation_quality_checks = {
        "daily_generation_available": bool(
            daily_generation_source.get("generation_date")
            and daily_generation["actual_mu"]
        ),
        "cumulative_generation_available": bool(
            cumulative_generation["actual_mu"]
        ),
        "coal_stock_availability_available": bool(coal_stock_availability),
        "sector_plf_available": bool(sector_plf["thermal_current"]),
    }
    return {
        "source": {
            "name": "National Power Portal, Government of India",
            "dashboard_url": "https://npp.gov.in/dashBoard/cp-map-dashboard",
            "generation_dashboard_url": (
                "https://npp.gov.in/dashBoard/gc-map-dashboard"
            ),
            "all_india_endpoint": NPP_ALL_INDIA_URL,
            "history_endpoint": NPP_HISTORY_URL,
            "generation_endpoint": NPP_GENERATION_URL,
        },
        "source_reported_date": _npp_iso_date(
            installed.get("reporting_date") or status.get("reporting_date")
        ),
        "installed_capacity_mw": installed_total,
        "category_capacity": category,
        "sector_capacity": sector,
        "all_india_status": {
            "monitored_capacity_mw": float(status.get("monitored_capacity") or 0),
            "online_capacity_mw": float(status.get("online_capacity") or 0),
            "under_maintenance_capacity_mw": float(
                status.get("under_maintenance_capacity") or 0
            ),
            "shutdown_capacity_mw": float(status.get("shutdown_capacity") or 0),
            "unscheduled_capacity_mw": float(
                status.get("unscheduled_capacity") or 0
            ),
            "note": (
                "Shutdown and unscheduled capacity are NPP-reported supporting "
                "status measures and are not added to the installed-capacity total."
            ),
        },
        "daily_demand": daily_demand,
        "daily_generation": daily_generation,
        "cumulative_generation": cumulative_generation,
        "coal_stock_availability": {
            "date": coal_stock_date,
            "unit": "stations",
            "rows": coal_stock_availability,
            "definition": (
                "Number of NPP-reported generating stations grouped by coal "
                "stock-cover days and pithead status."
            ),
        },
        "sector_plf": sector_plf,
        "historical_installed_capacity": historical,
        "quality_checks": quality_checks,
        "generation_quality_checks": generation_quality_checks,
        "excluded_visuals": ["Historical growth of electricity consumption"],
    }


async def _get_npp_power_dashboard(force: bool = False) -> Dict[str, Any]:
    global _npp_memory_cache
    now = datetime.now(timezone.utc)
    if _npp_memory_cache and not force:
        fetched = datetime.fromisoformat(
            str(_npp_memory_cache["fetched_at"]).replace("Z", "+00:00")
        )
        if (now - fetched).total_seconds() < NPP_CACHE_TTL_SECONDS:
            return _npp_memory_cache
    async with _npp_cache_lock:
        if _npp_memory_cache and not force:
            fetched = datetime.fromisoformat(
                str(_npp_memory_cache["fetched_at"]).replace("Z", "+00:00")
            )
            if (now - fetched).total_seconds() < NPP_CACHE_TTL_SECONDS:
                return _npp_memory_cache
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                all_response, history_response, generation_response = await asyncio.gather(
                    client.get(NPP_ALL_INDIA_URL),
                    client.get(NPP_HISTORY_URL),
                    client.get(NPP_GENERATION_URL),
                )
            all_response.raise_for_status()
            history_response.raise_for_status()
            generation_response.raise_for_status()
            all_india = all_response.json()
            if isinstance(all_india, str):
                all_india = json.loads(all_india)
            history = history_response.json()
            if isinstance(history, str):
                history = json.loads(history)
            generation = generation_response.json()
            if isinstance(generation, str):
                generation = json.loads(generation)
            payload = _transform_npp_power(all_india, history, generation)
            if not all(payload["quality_checks"].values()):
                raise ValueError(
                    "NPP response failed one or more reconciliation/freshness checks"
                )
            payload.update(
                {
                    "fetched_at": now.isoformat().replace("+00:00", "Z"),
                    "refresh_interval_seconds": NPP_CACHE_TTL_SECONDS,
                    "stale": False,
                }
            )
            NPP_CACHE_PATH.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            _npp_memory_cache = payload
            return payload
        except Exception as exc:
            log.warning("NPP refresh failed: %s", exc)
            cached = _npp_memory_cache
            if cached is None and NPP_CACHE_PATH.exists():
                try:
                    cached = json.loads(
                        NPP_CACHE_PATH.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    cached = None
            if cached:
                fallback = dict(cached)
                fallback["stale"] = True
                fallback["refresh_error"] = str(exc)
                fallback["refresh_interval_seconds"] = NPP_CACHE_TTL_SECONDS
                _npp_memory_cache = fallback
                return fallback
            raise HTTPException(
                502,
                "Official NPP data is temporarily unavailable and no validated cache exists.",
            )

def _ensure_bundled_trackers() -> None:
    """Extract optional prototype datasets into the ignored runtime directory."""
    bundle = BASE_DIR / "gem-dashboard (1).zip"
    if not bundle.exists():
        return
    wanted = {
        "coal_terminals.csv",
        "coal_terminals.csv.gz",
        "world_ports.csv",
        "world_ports.csv.gz",
        "summaries.json",
    }
    try:
        with zipfile.ZipFile(bundle) as archive:
            members = {
                Path(name).name: name
                for name in archive.namelist()
                if "/data/" in name.replace("\\", "/")
                and Path(name).name in wanted
            }
            for filename, member in members.items():
                destination = BUNDLED_DATA_DIR / filename
                if destination.exists():
                    continue
                destination.write_bytes(archive.read(member))
    except (OSError, zipfile.BadZipFile) as exc:
        log.warning("Could not extract bundled tracker data: %s", exc)


def _tracker_path(name: str, meta: Dict[str, str]) -> Path:
    candidates = [meta["file"]]
    if name == "world_ports":
        candidates.extend(["world_ports.csv", "world_ports.csv.gz"])
    if name == "coal_terminals":
        candidates.extend(["coal_terminals.csv", "coal_terminals.csv.gz"])
    for directory in (DATA_DIR, BUNDLED_DATA_DIR):
        for filename in dict.fromkeys(candidates):
            path = directory / filename
            if path.exists():
                return path
    return DATA_DIR / meta["file"]


def _summary_path() -> Path:
    for directory in (DATA_DIR, BUNDLED_DATA_DIR):
        path = directory / "summaries.json"
        if path.exists():
            return path
    return DATA_DIR / "summaries.json"


def register_all():
    for name, meta in TRACKERS.items():
        path = _tracker_path(name, meta)
        if path.exists():
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_csv_auto('{path}')")
    for uname, upath in user_datasets.items():
        safe = uname.replace("-", "_").replace(" ", "_")
        con.execute(f"CREATE OR REPLACE TABLE user_{safe} AS SELECT * FROM read_csv_auto('{upath}')")

_ensure_bundled_trackers()
register_all()
ports = PortCatalog(con)
ports.refresh()

app = FastAPI(title="Global Energy & Maritime Intelligence", version="4.0.0")
app.include_router(create_data_hub_router(BASE_DIR, storage_dir=UPLOAD_DIR))
cors_origins = [
    value.strip()
    for value in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Admin-Token"],
)

ADMIN_API_TOKEN = os.getenv("APP_ADMIN_TOKEN", "").strip()
REQUIRE_ADMIN_TOKEN = bool(os.getenv("RENDER")) or os.getenv(
    "APP_ENV", "development"
).strip().lower() == "production"
_rate_windows: Dict[str, deque] = defaultdict(deque)
_MUTATING_ADMIN_PREFIXES = (
    "/api/data-hub/upload",
    "/api/data-hub/api-connections",
    "/api/data-hub/relationships/",
    "/api/imd/coastal-weather/refresh",
    "/api/bmkg/marine-weather/refresh",
    "/api/sea/marine-weather/refresh",
    "/api/major-port-weather/refresh",
    "/api/weather/cyclones/refresh",
    "/api/river-levels/refresh",
)


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    """Protect expensive writes and add baseline browser security headers."""
    path = request.url.path
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        client = request.client.host if request.client else "unknown"
        bucket = f"{client}:{path.split('/', 3)[:3]}"
        now = time.monotonic()
        window = _rate_windows[bucket]
        while window and now - window[0] > 60:
            window.popleft()
        limit = 12 if path.startswith(("/api/chat", "/api/data-hub/upload")) else 40
        if len(window) >= limit:
            return JSONResponse(
                {"detail": "Too many requests. Please wait before trying again."},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        window.append(now)
        if REQUIRE_ADMIN_TOKEN and not ADMIN_API_TOKEN and path.startswith(_MUTATING_ADMIN_PREFIXES):
            return JSONResponse(
                {"detail": "Administrator operations are disabled until APP_ADMIN_TOKEN is configured."},
                status_code=503,
            )
        if ADMIN_API_TOKEN and path.startswith(_MUTATING_ADMIN_PREFIXES):
            supplied = request.headers.get("X-Admin-Token", "")
            if not hmac.compare_digest(supplied, ADMIN_API_TOKEN):
                return JSONResponse(
                    {"detail": "Administrator token required for this operation."},
                    status_code=401,
                )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob: https:; "
        "style-src 'self' 'unsafe-inline' https:; script-src 'self' https:; "
        "connect-src 'self' https: wss:; font-src 'self' data: https:; "
        "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    )
    if request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "static" / "index.html")

class ChatRequest(BaseModel):
    message: str

class VesselTrackRequest(BaseModel):
    ids: List[str] = []
    timeout_sec: float = 25.0


class AisSnapshotRequest(BaseModel):
    south: float
    north: float
    west: float
    east: float
    query: Optional[str] = None
    mmsis: List[str] = []
    regions: List[str] = []
    timeout_sec: float = 6.0
    max_vessels: int = 500

class RouteRequest(BaseModel):
    from_lon: float
    from_lat: float
    to_lon: float
    to_lat: float
    from_port_id: Optional[str] = None
    to_port_id: Optional[str] = None
    speed_knots: float = 12.0
    from_name: Optional[str] = None
    to_name: Optional[str] = None
    avoid: Optional[List[str]] = None
    avoid_jwc: bool = False
    avoid_piracy: bool = False
    sea_margin_pct: float = 5.0
    port_time_hours: float = 0.0
    canal_delay_hours: float = 0.0
    consumption_tpd: float = 25.0  # tonnes per day fuel burn


PASSAGE_LABELS = {
    "babalmandab": "Bab el-Mandeb",
    "bosporus": "Bosporus",
    "gibraltar": "Strait of Gibraltar",
    "suez": "Suez Canal",
    "panama": "Panama Canal",
    "ormuz": "Strait of Hormuz",
    "northwest": "Northwest Passage",
    "malacca": "Strait of Malacca",
    "sunda": "Sunda Strait",
    "chili": "Cape Horn / Chilean route",
    "south_africa": "Cape of Good Hope",
}
ALLOWED_ROUTE_RESTRICTIONS = set(PASSAGE_LABELS)
JWC_NAMED_COUNTRY_CODES = set(
    load_zones().get("listed_country_codes", {}).get("jwc", [])
)


def _load_port_approach_data() -> Dict[str, Any]:
    try:
        payload = json.loads(PORT_APPROACHES_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload.get("approaches"), dict):
            raise ValueError("approaches must be an object")
        if not isinstance(payload.get("corridors"), list):
            raise ValueError("corridors must be an array")
        return payload
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Could not load verified port approaches: %s", exc)
        return {"approaches": {}, "corridors": []}


PORT_APPROACH_DATA = _load_port_approach_data()


def _port_approach(port_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if port_id is None:
        return None
    return PORT_APPROACH_DATA["approaches"].get(str(port_id))


def _haversine_nm(left: List[float], right: List[float]) -> float:
    """Great-circle distance between [lon, lat] points in nautical miles."""
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    delta_lon = (lon2 - lon1 + math.pi) % (2 * math.pi) - math.pi
    delta_lat = lat2 - lat1
    hav = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 3440.065 * 2 * math.asin(min(1.0, math.sqrt(hav)))


def _wrapped_lon_near(lon: float, reference: float) -> float:
    """Return the equivalent longitude closest to the previous route point."""
    return lon + 360.0 * round((reference - lon) / 360.0)


def _route_with_endpoints(
    origin: List[float],
    network_coordinates: List[List[float]],
    destination: List[float],
) -> List[List[float]]:
    """Unwrap a route continuously and attach exact selected port coordinates."""
    output: List[List[float]] = [[float(origin[0]), float(origin[1])]]
    for raw_lon, raw_lat in network_coordinates:
        output.append([
            _wrapped_lon_near(float(raw_lon), output[-1][0]),
            float(raw_lat),
        ])
    output.append([
        _wrapped_lon_near(float(destination[0]), output[-1][0]),
        float(destination[1]),
    ])
    deduplicated: List[List[float]] = []
    for point in output:
        if not deduplicated or _haversine_nm(deduplicated[-1], point) > 0.001:
            deduplicated.append(point)
    return deduplicated


def _polyline_distance_nm(coordinates: List[List[float]]) -> float:
    return sum(
        _haversine_nm(coordinates[index - 1], coordinates[index])
        for index in range(1, len(coordinates))
    )


def _geodesic_point(
    left: List[float], right: List[float], fraction: float
) -> List[float]:
    """Spherical interpolation between two [lon, lat] points."""
    lon1, lat1 = map(math.radians, left)
    lon2, lat2 = map(math.radians, right)
    vectors = [
        (
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        )
        for lon, lat in ((lon1, lat1), (lon2, lat2))
    ]
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(*vectors))))
    angle = math.acos(dot)
    if angle < 1e-12:
        return [float(left[0]), float(left[1])]
    scale = math.sin(angle)
    left_weight = math.sin((1.0 - fraction) * angle) / scale
    right_weight = math.sin(fraction * angle) / scale
    x, y, z = (
        left_weight * vectors[0][index] + right_weight * vectors[1][index]
        for index in range(3)
    )
    lon = math.degrees(math.atan2(y, x))
    lat = math.degrees(math.atan2(z, math.hypot(x, y)))
    return [lon, lat]


def _densify_geodesic_route(
    waypoints: List[List[float]], max_leg_nm: float = 25.0
) -> List[List[float]]:
    """Add graph nodes so every analytical corridor edge is short and smooth."""
    if len(waypoints) < 2:
        return [list(point) for point in waypoints]
    output = [[float(waypoints[0][0]), float(waypoints[0][1])]]
    for right in waypoints[1:]:
        left = output[-1]
        distance = _haversine_nm(left, right)
        steps = max(1, math.ceil(distance / max_leg_nm))
        for step in range(1, steps + 1):
            point = _geodesic_point(left, right, step / steps)
            point[0] = _wrapped_lon_near(point[0], output[-1][0])
            output.append(point)
    return output


def _compute_curated_corridor(
    from_port_id: Optional[str],
    to_port_id: Optional[str],
    speed_knots: float,
    restrictions: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Use a provenance-backed dense corridor when both endpoints match."""
    if from_port_id is None or to_port_id is None:
        return None
    from_id, to_id = str(from_port_id), str(to_port_id)
    origin_approach = _port_approach(from_id)
    destination_approach = _port_approach(to_id)
    if not origin_approach or not destination_approach:
        return None
    canonical_from_id = str(
        origin_approach.get("canonical_port_id") or from_id
    )
    canonical_to_id = str(
        destination_approach.get("canonical_port_id") or to_id
    )
    corridor = next(
        (
            item
            for item in PORT_APPROACH_DATA["corridors"]
            if set(map(str, item.get("endpoint_port_ids", [])))
            == {canonical_from_id, canonical_to_id}
        ),
        None,
    )
    if not corridor:
        return None
    configured_ids = list(map(str, corridor["endpoint_port_ids"]))
    forward = configured_ids == [canonical_from_id, canonical_to_id]
    intermediate = [
        [float(item["longitude"]), float(item["latitude"])]
        for item in corridor.get("waypoints", [])
    ]
    if not forward:
        intermediate.reverse()
    origin = [
        float(origin_approach["longitude"]),
        float(origin_approach["latitude"]),
    ]
    destination = [
        float(destination_approach["longitude"]),
        float(destination_approach["latitude"]),
    ]
    coordinates = _densify_geodesic_route(
        [origin, *intermediate, destination], max_leg_nm=25.0
    )
    distance_nm = _polyline_distance_nm(coordinates)
    direct_nm = _haversine_nm(origin, destination)
    duration_hours = distance_nm / speed_knots if speed_knots > 0 else 0.0
    return {
        "distance_nm": round(distance_nm, 1),
        "network_distance_nm": round(distance_nm, 1),
        "great_circle_nm": round(direct_nm, 1),
        "detour_factor": round(distance_nm / direct_nm, 3) if direct_nm else 1.0,
        "origin_connector_nm": 0.0,
        "destination_connector_nm": 0.0,
        "route_confidence": "high",
        "waypoint_count": len(coordinates),
        "distance_miles": round(distance_nm * 1.150779, 1),
        "distance_km": round(distance_nm * 1.852, 1),
        "duration_hours": round(duration_hours, 2),
        "duration_days": round(duration_hours / 24.0, 2),
        "speed_knots": speed_knots,
        "coordinates": coordinates,
        "units": "nm",
        "via": corridor.get("label"),
        "passages": [],
        "passage_ids": [],
        "restrictions": restrictions or [],
        "routing_profile": "verified-approach-dense-corridor",
        "corridor_id": corridor["id"],
        "approach_sources": [
            {
                "port_id": from_id,
                "port_name": origin_approach["port_name"],
                "kind": origin_approach["kind"],
                "source_title": origin_approach["source_title"],
                "source_url": origin_approach["source_url"],
            },
            {
                "port_id": to_id,
                "port_name": destination_approach["port_name"],
                "kind": destination_approach["kind"],
                "source_title": destination_approach["source_title"],
                "source_url": destination_approach["source_url"],
            },
        ],
    }


def _infer_passage(coords):
    if not coords:
        return None
    tags = []
    for lon, lat in coords:
        lon = ((float(lon) + 180.0) % 360.0) - 180.0
        if 29 < lat < 32 and 32 < lon < 33: tags.append("Suez Canal")
        elif 8.5 < lat < 9.5 and -80 < lon < -79: tags.append("Panama Canal")
        elif 25.5 < lat < 27 and 56 < lon < 57.5: tags.append("Strait of Hormuz")
        elif 1 < lat < 4 and 100 < lon < 104: tags.append("Strait of Malacca")
        elif -7 < lat < -5 and 104.5 < lon < 106.5: tags.append("Sunda Strait")
        elif 12 < lat < 14 and 42 < lon < 44: tags.append("Bab el-Mandeb")
        elif lat < -33 and 15 < lon < 22: tags.append("Cape of Good Hope")
        elif lat < -54 and -70 < lon < -65: tags.append("Cape Horn / Chilean route")
        elif 35.5 < lat < 36.5 and -6 < lon < -5: tags.append("Strait of Gibraltar")
        elif 40.5 < lat < 41.5 and 28.5 < lon < 29.5: tags.append("Bosporus")
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t); out.append(t)
    return ", ".join(out) if out else None

def _length_to_nm(length: float, units: str) -> float:
    u = (units or "").lower().strip()
    if u in ("naut", "nm", "nmi", "nautical", "nauticals"): return float(length)
    if u in ("km", "kilometer", "kilometers"): return float(length) / 1.852
    if u in ("mi", "mile", "miles"): return float(length) / 1.150779
    if u in ("m", "meter", "meters"): return float(length) / 1852.0
    return float(length) / 1.852

def _compute_route(
    from_lon,
    from_lat,
    to_lon,
    to_lat,
    speed_knots,
    restrictions: Optional[List[str]] = None,
):
    import searoute as sr
    restrictions = [
        value for value in (restrictions or ["northwest"])
        if value in ALLOWED_ROUTE_RESTRICTIONS
    ]
    origin = [float(from_lon), float(from_lat)]
    destination = [float(to_lon), float(to_lat)]
    feature = sr.searoute(
        origin, destination,
        units="naut", speed_knot=speed_knots, append_orig_dest=False,
        restrictions=restrictions, return_passages=True,
        algorithm="astar",
    )
    props = feature.get("properties", {}) if isinstance(feature, dict) else feature.properties
    geom = feature.get("geometry", {}) if isinstance(feature, dict) else feature.geometry
    network_coords = geom.get("coordinates", []) if isinstance(geom, dict) else getattr(geom, "coordinates", [])
    if not network_coords:
        raise ValueError("No navigable maritime-network path was found")
    coords = _route_with_endpoints(origin, network_coords, destination)
    length = float(props.get("length", 0) or 0)
    units = str(props.get("units", "naut"))
    network_distance_nm = _length_to_nm(length, units)
    origin_connector_nm = _haversine_nm(origin, network_coords[0])
    destination_connector_nm = _haversine_nm(network_coords[-1], destination)
    distance_nm = _polyline_distance_nm(coords)
    direct_nm = _haversine_nm(origin, destination)
    duration_hours = distance_nm / speed_knots if speed_knots > 0 else 0.0
    passage_ids = [
        str(value).lower()
        for value in (props.get("traversed_passages") or props.get("passages") or [])
    ]
    reported_passages = [
        PASSAGE_LABELS.get(value, value.replace("_", " ").title())
        for value in passage_ids
    ]
    inferred_via = _infer_passage(coords)
    ordered_passages = inferred_via.split(", ") if inferred_via else []
    passages = ordered_passages + [
        value for value in reported_passages if value not in ordered_passages
    ]
    via = ", ".join(passages) if passages else None
    max_connector_nm = max(origin_connector_nm, destination_connector_nm)
    confidence = "high" if max_connector_nm <= 5 else "medium" if max_connector_nm <= 20 else "low"
    return {
        "distance_nm": round(distance_nm, 1),
        "network_distance_nm": round(network_distance_nm, 1),
        "great_circle_nm": round(direct_nm, 1),
        "detour_factor": round(distance_nm / direct_nm, 3) if direct_nm else 1.0,
        "origin_connector_nm": round(origin_connector_nm, 1),
        "destination_connector_nm": round(destination_connector_nm, 1),
        "route_confidence": confidence,
        "waypoint_count": len(coords),
        "distance_miles": round(distance_nm * 1.150779, 1),
        "distance_km": round(distance_nm * 1.852, 1),
        "duration_hours": round(duration_hours, 2),
        "duration_days": round(duration_hours / 24.0, 2),
        "speed_knots": speed_knots,
        "coordinates": coords,
        "units": "nm",
        "via": via,
        "passages": passages,
        "passage_ids": passage_ids,
        "restrictions": restrictions,
        "routing_profile": "maritime-network",
        "risk_families_avoided": [],
    }


@lru_cache(maxsize=1)
def _piracy_source_polygons():
    """Return only the large WIO JWC polygon used as the route barrier."""
    from shapely.geometry import shape

    payload = json.loads(RISK_ZONE_SOURCE_PATH.read_text(encoding="utf-8"))
    output = []
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("id") != "jwc-jwla033-western-indian-ocean":
            continue
        geometry = shape(feature.get("geometry") or {})
        polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
        polygons = [polygon for polygon in polygons if not polygon.is_empty]
        if polygons:
            output.append((max(polygons, key=lambda polygon: polygon.area), properties))
    return tuple(output)


def _primary_jwc_exposure_nm(coordinates: List[List[float]]) -> float:
    """Measure distance inside the avoided WIO JWC polygon; boundary is safe."""
    from shapely.geometry import LineString

    if len(coordinates) < 2:
        return 0.0
    route = LineString(coordinates)
    distance_nm = 0.0
    for polygon, _ in _piracy_source_polygons():
        interior = polygon.buffer(-1e-7)
        intersection = route.intersection(interior)
        pending = [intersection]
        while pending:
            geometry = pending.pop()
            if geometry.is_empty:
                continue
            if geometry.geom_type == "LineString":
                distance_nm += _polyline_distance_nm(
                    [[float(x), float(y)] for x, y in geometry.coords]
                )
            elif hasattr(geometry, "geoms"):
                pending.extend(geometry.geoms)
    return round(distance_nm, 1)


def _join_coordinate_parts(*parts: List[List[float]]) -> List[List[float]]:
    output: List[List[float]] = []
    for part in parts:
        for point in part:
            normalized = [float(point[0]), float(point[1])]
            if not output or _haversine_nm(output[-1], normalized) > 0.001:
                output.append(normalized)
    return output


def _geometry_coordinates(geometry) -> List[List[float]]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [[float(geometry.x), float(geometry.y)]]
    return [[float(x), float(y)] for x, y in geometry.coords]


def _piracy_boundary_arc(polygon, entry, exit, preference: Optional[str]):
    """Choose an entry-to-exit arc on the watch polygon's outer boundary."""
    from shapely.geometry import LineString
    from shapely.ops import substring

    boundary = LineString(polygon.exterior.coords)
    length = boundary.length
    entry_distance = boundary.project(entry)
    exit_distance = boundary.project(exit)

    if entry_distance <= exit_distance:
        direct = _geometry_coordinates(
            substring(boundary, entry_distance, exit_distance)
        )
        complement = _join_coordinate_parts(
            _geometry_coordinates(substring(boundary, exit_distance, length)),
            _geometry_coordinates(substring(boundary, 0.0, entry_distance)),
        )
        complement.reverse()
    else:
        direct = _join_coordinate_parts(
            _geometry_coordinates(substring(boundary, entry_distance, length)),
            _geometry_coordinates(substring(boundary, 0.0, exit_distance)),
        )
        complement = _geometry_coordinates(
            substring(boundary, exit_distance, entry_distance)
        )
        complement.reverse()

    candidates = [direct, complement]
    if preference == "offshore_east_south":
        return max(
            candidates,
            key=lambda points: (
                sum(point[0] for point in points) / max(1, len(points)),
                -sum(point[1] for point in points) / max(1, len(points)),
            ),
        )
    return min(candidates, key=_polyline_distance_nm)


def _piracy_avoidance_polygon(polygon, properties: Dict[str, Any]):
    """Return the displayed piracy boundary used by the route engine."""
    buffer_nm = max(0.0, float(properties.get("avoidance_buffer_nm") or 0.0))
    if buffer_nm <= 0:
        return polygon
    return polygon.buffer(buffer_nm / 60.0, join_style=2)


def _mandatory_piracy_detour(
    avoidance_polygon,
    properties: Dict[str, Any],
    entry,
    exit,
) -> Optional[List[List[float]]]:
    """Route on the boundary through the shared piracy/JWC junction."""
    from shapely.geometry import Point

    junction = properties.get("mandatory_shared_junction")
    if not (isinstance(junction, list) and len(junction) == 2):
        return None

    junction_point = avoidance_polygon.exterior.interpolate(
        avoidance_polygon.exterior.project(
            Point(float(junction[0]), float(junction[1]))
        )
    )
    entry_to_junction = _piracy_boundary_arc(
        avoidance_polygon,
        entry,
        junction_point,
        properties.get("preferred_boundary_arc"),
    )
    junction_to_exit = _piracy_boundary_arc(
        avoidance_polygon,
        junction_point,
        exit,
        None,
    )
    return _join_coordinate_parts(
        entry_to_junction,
        [[float(junction_point.x), float(junction_point.y)]],
        junction_to_exit,
    )


def _eastbound_piracy_rejoin(
    baseline_line,
    baseline_coordinates: List[List[float]],
    avoidance_polygon,
    properties: Dict[str, Any],
    original_exit_distance: float,
):
    """Find the first safe network point after the mandatory JWC junction."""
    from shapely.geometry import LineString, Point

    eastern_exit = properties.get("mandatory_shared_junction")
    destination = Point(baseline_coordinates[-1])
    if not (
        isinstance(eastern_exit, list)
        and len(eastern_exit) == 2
        and destination.x >= float(eastern_exit[0])
    ):
        return None

    exit_point = avoidance_polygon.exterior.interpolate(
        avoidance_polygon.exterior.project(
            Point(float(eastern_exit[0]), float(eastern_exit[1]))
        )
    )
    candidates = []
    for coordinate in baseline_coordinates:
        point = Point(coordinate)
        distance = baseline_line.project(point)
        if distance <= original_exit_distance + 1e-8:
            continue
        connector = LineString([exit_point, point])
        overlap = connector.intersection(avoidance_polygon)
        overlap_lines = [
            geometry
            for geometry in (
                list(overlap.geoms) if hasattr(overlap, "geoms") else [overlap]
            )
            if geometry.geom_type in {"LineString", "MultiLineString"}
        ]
        if sum(geometry.length for geometry in overlap_lines) <= 1e-8:
            candidates.append((distance, point))
    if not candidates:
        return None
    rejoin_distance, rejoin_point = min(candidates, key=lambda item: item[0])
    return exit_point, rejoin_distance, rejoin_point


def _result_with_replaced_coordinates(
    baseline: Dict[str, Any],
    coordinates: List[List[float]],
    speed_knots: float,
    routing_profile: str,
) -> Dict[str, Any]:
    """Recalculate route metrics after replacing only an exposed route section."""
    deduplicated: List[List[float]] = []
    for point in coordinates:
        normalized = [float(point[0]), float(point[1])]
        if not deduplicated or _haversine_nm(deduplicated[-1], normalized) > 0.001:
            deduplicated.append(normalized)
    distance_nm = _polyline_distance_nm(deduplicated)
    direct_nm = float(baseline.get("great_circle_nm") or 0.0)
    duration_hours = distance_nm / speed_knots if speed_knots > 0 else 0.0
    inferred_via = _infer_passage(deduplicated)
    passages = inferred_via.split(", ") if inferred_via else []
    return {
        **baseline,
        "distance_nm": round(distance_nm, 1),
        "network_distance_nm": round(
            max(
                0.0,
                distance_nm
                - float(baseline.get("origin_connector_nm") or 0.0)
                - float(baseline.get("destination_connector_nm") or 0.0),
            ),
            1,
        ),
        "detour_factor": round(distance_nm / direct_nm, 3) if direct_nm else 1.0,
        "waypoint_count": len(deduplicated),
        "distance_miles": round(distance_nm * 1.150779, 1),
        "distance_km": round(distance_nm * 1.852, 1),
        "duration_hours": round(duration_hours, 2),
        "duration_days": round(duration_hours / 24.0, 2),
        "coordinates": deduplicated,
        "via": ", ".join(passages) if passages else baseline.get("via"),
        "passages": passages or baseline.get("passages", []),
        "routing_profile": routing_profile,
        "risk_families_avoided": ["jwc_western_indian_ocean"],
    }


def _apply_local_piracy_detours(
    baseline: Dict[str, Any],
    speed_knots: float,
    restrictions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Avoid the large WIO JWC polygon via its shared Oman junction."""
    from shapely.geometry import LineString, Point
    from shapely.ops import substring

    coordinates = [
        [float(point[0]), float(point[1])]
        for point in (baseline.get("coordinates") or [])
    ]
    if len(coordinates) < 2:
        return baseline
    baseline_line = LineString(coordinates)
    detours = []
    for polygon, properties in _piracy_source_polygons():
        avoidance_polygon = _piracy_avoidance_polygon(polygon, properties)
        intersection = baseline_line.intersection(avoidance_polygon)
        pending = [intersection]
        exposed_sections = []
        while pending:
            geometry = pending.pop()
            if geometry.is_empty:
                continue
            if geometry.geom_type == "LineString":
                if geometry.length > 1e-8:
                    exposed_sections.append(geometry)
            elif hasattr(geometry, "geoms"):
                pending.extend(geometry.geoms)
        for section in exposed_sections:
            endpoints = [Point(section.coords[0]), Point(section.coords[-1])]
            projected = sorted(
                (baseline_line.project(point), point) for point in endpoints
            )
            entry_distance, entry = projected[0]
            exit_distance, exit = projected[-1]
            if exit_distance - entry_distance <= 1e-8:
                continue
            eastbound_rejoin = _eastbound_piracy_rejoin(
                baseline_line,
                coordinates,
                avoidance_polygon,
                properties,
                exit_distance,
            )
            detour_exit = eastbound_rejoin[0] if eastbound_rejoin else exit
            arc = _mandatory_piracy_detour(
                avoidance_polygon,
                properties,
                entry,
                detour_exit,
            ) or _piracy_boundary_arc(
                avoidance_polygon,
                entry,
                detour_exit,
                properties.get("preferred_boundary_arc"),
            )
            if eastbound_rejoin:
                _, exit_distance, rejoin_point = eastbound_rejoin
                arc = _join_coordinate_parts(
                    arc,
                    [[float(rejoin_point.x), float(rejoin_point.y)]],
                )
            detours.append((entry_distance, exit_distance, arc))

    if not detours:
        return {
            **baseline,
            "routing_profile": "normal-route-jwc-clear",
            "risk_families_avoided": ["jwc_western_indian_ocean"],
        }

    output: List[List[float]] = []
    cursor_distance = 0.0
    for entry_distance, exit_distance, arc in sorted(detours):
        if entry_distance < cursor_distance - 1e-8:
            continue
        output = _join_coordinate_parts(
            output,
            _geometry_coordinates(
                substring(baseline_line, cursor_distance, entry_distance)
            ),
            arc,
        )
        cursor_distance = exit_distance
    output = _join_coordinate_parts(
        output,
        _geometry_coordinates(
            substring(baseline_line, cursor_distance, baseline_line.length)
        ),
    )

    return _result_with_replaced_coordinates(
        baseline,
        output,
        speed_knots,
        "local-jwc-boundary-detour",
    )


def _route_reference_ports(
    coordinates: List[List[float]],
    from_port_id: Optional[str] = None,
    to_port_id: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Choose geographically useful named ports along a calculated track.

    Five evenly distributed progress targets are used so labels describe the
    route instead of clustering around a single port complex. The distance is
    measured to route nodes and disclosed as an analytical proximity value.
    """
    if len(coordinates) < 2 or limit < 1:
        return []
    excluded = {
        str(value)
        for value in (from_port_id, to_port_id)
        if value is not None
    }
    # Bound work for very dense routes while retaining endpoints.
    stride = max(1, math.ceil(len(coordinates) / 500))
    sampled = [
        (index, coordinates[index])
        for index in range(0, len(coordinates), stride)
    ]
    if sampled[-1][0] != len(coordinates) - 1:
        sampled.append((len(coordinates) - 1, coordinates[-1]))
    candidates: List[Dict[str, Any]] = []
    for port in ports.ports:
        if str(port.get("id")) in excluded:
            continue
        lat = port.get("lat")
        lon = port.get("lon")
        if lat is None or lon is None:
            continue
        port_point = [float(lon), float(lat)]
        nearest_index, distance_nm = min(
            (
                (index, _haversine_nm(port_point, route_point))
                for index, route_point in sampled
            ),
            key=lambda item: item[1],
        )
        candidates.append(
            {
                "id": str(port.get("id")),
                "name": port.get("name"),
                "country": port.get("country"),
                "lat": float(lat),
                "lon": float(lon),
                "distance_from_route_nm": round(distance_nm, 1),
                "progress_pct": round(
                    nearest_index / (len(coordinates) - 1) * 100.0, 1
                ),
                "specialist_terminal": bool(
                    port.get("specialist_terminal")
                ),
            }
        )
    if not candidates:
        return []
    selected: List[Dict[str, Any]] = []
    selected_ids: set[str] = set()
    for target in [
        (index + 1) / (limit + 1) * 100.0 for index in range(limit)
    ]:
        eligible = [
            item for item in candidates if item["id"] not in selected_ids
        ]
        if not eligible:
            break
        choice = min(
            eligible,
            key=lambda item: (
                abs(item["progress_pct"] - target) * 12.0
                + item["distance_from_route_nm"],
                item["distance_from_route_nm"],
                str(item.get("name") or ""),
            ),
        )
        choice["label_role"] = "route_reference"
        selected.append(choice)
        selected_ids.add(choice["id"])
    return sorted(selected, key=lambda item: item["progress_pct"])

@app.get("/api/trackers")
async def list_trackers():
    summaries_path = _summary_path()
    summaries = json.loads(summaries_path.read_text()) if summaries_path.exists() else {}
    result = []
    for key, meta in TRACKERS.items():
        s = summaries.get(key, {})
        result.append({
            "id": key, "label": meta["label"], "icon": meta["icon"],
            "rows": s.get("rows", 0),
            "operating_capacity_mw": s.get("operating_capacity_mw", 0),
            "operating_units": s.get("operating_units", 0),
            "countries": s.get("countries", 0),
            "status_counts": s.get("status_counts", {}),
        })
    for uname in user_datasets:
        result.append({"id": f"user_{uname}", "label": f"📤 {uname}", "icon": "📁", "rows": 0, "is_user": True})
    return result


@app.get("/api/layer-facets")
async def layer_facets(trackers: str = Query(...)):
    """Return shared country/status/type filters for one or more map layers."""
    selected = [
        value for value in _csv_values(trackers)
        if value in TRACKERS and value != "world_ports"
    ]
    if not selected:
        raise HTTPException(400, "No valid map layers selected")
    country_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    type_counts: Dict[str, int] = {}
    for tracker_id in selected:
        normalized = tracker_id in NORMALIZED_MAP_TRACKERS
        columns = {row[0] for row in con.execute(f"DESCRIBE {tracker_id}").fetchall()}
        country_name = "country" if normalized else (
            "Country/Area" if "Country/Area" in columns else None
        )
        status_name = "status" if normalized else (
            "Status" if "Status" in columns else None
        )
        countries = []
        statuses = []
        if country_name:
            country_column = f'"{country_name}"'
            countries = con.execute(
                f"SELECT CAST({country_column} AS VARCHAR), COUNT(*) FROM {tracker_id} "
                f"WHERE {country_column} IS NOT NULL "
                f"AND TRIM(CAST({country_column} AS VARCHAR)) NOT IN ('', '-', 'unknown') "
                f"GROUP BY 1"
            ).fetchall()
        if status_name:
            status_column = f'"{status_name}"'
            statuses = con.execute(
                f"SELECT CAST({status_column} AS VARCHAR), COUNT(*) FROM {tracker_id} "
                f"WHERE {status_column} IS NOT NULL "
                f"AND TRIM(CAST({status_column} AS VARCHAR)) NOT IN ('', '-', 'unknown') "
                f"GROUP BY 1"
            ).fetchall()
        for label, count in countries:
            country_counts[str(label)] = country_counts.get(str(label), 0) + int(count)
        for label, count in statuses:
            canonical = str(label).strip().lower()
            status_counts[canonical] = status_counts.get(canonical, 0) + int(count)
        if normalized:
            types = con.execute(
                f"SELECT CAST(asset_type AS VARCHAR), COUNT(*) FROM {tracker_id} "
                "WHERE asset_type IS NOT NULL "
                "AND TRIM(CAST(asset_type AS VARCHAR)) NOT IN ('', '-', 'unknown') "
                "GROUP BY 1"
            ).fetchall()
            for label, count in types:
                type_counts[str(label)] = type_counts.get(str(label), 0) + int(count)
    return {
        "countries": [
            {"id": label, "label": label, "count": count}
            for label, count in sorted(country_counts.items())
        ],
        "statuses": [
            {"id": label, "label": label.replace("_", " ").title(), "count": count}
            for label, count in sorted(
                status_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "asset_types": [
            {"id": label, "label": label, "count": count}
            for label, count in sorted(type_counts.items())
        ],
    }

def _filters(status, country, region, min_mw, max_mw, search):
    clauses, params = [], []
    if status:
        statuses = [s.strip() for s in status.split(",")]
        placeholders = ",".join(["?"] * len(statuses))
        clauses.append(f"LOWER(CAST(Status AS VARCHAR)) IN ({placeholders})")
        params.extend([s.lower() for s in statuses])
    if country:
        countries = [c.strip() for c in country.split(",") if c.strip()]
        if len(countries) == 1:
            clauses.append('"Country/Area" ILIKE ?'); params.append(f"%{countries[0]}%")
        elif countries:
            placeholders = ",".join(["?"] * len(countries))
            clauses.append(f'"Country/Area" IN ({placeholders})'); params.extend(countries)
    if region:
        clauses.append("Region ILIKE ?"); params.append(f"%{region}%")
    if min_mw is not None:
        clauses.append('TRY_CAST("Capacity (MW)" AS DOUBLE) >= ?'); params.append(min_mw)
    if max_mw is not None:
        clauses.append('TRY_CAST("Capacity (MW)" AS DOUBLE) <= ?'); params.append(max_mw)
    if search:
        clauses.append('("Plant name" ILIKE ? OR "Unit name" ILIKE ? OR Owner ILIKE ?)')
        params.extend([f"%{search}%"] * 3)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params

@app.get("/api/data/{tracker_id}")
async def get_data(tracker_id: str, status: Optional[str] = None, country: Optional[str] = None,
                   region: Optional[str] = None, min_mw: Optional[float] = None, max_mw: Optional[float] = None,
                   search: Optional[str] = None, limit: int = Query(500, ge=1, le=5000), offset: int = Query(0, ge=0)):
    if tracker_id not in TRACKERS and not tracker_id.startswith("user_"):
        raise HTTPException(404, "Unknown tracker")
    where, params = _filters(status, country, region, min_mw, max_mw, search)
    try:
        df = con.execute(f"SELECT * FROM {tracker_id}{where} LIMIT {limit} OFFSET {offset}", params).fetchdf()
        total = con.execute(f"SELECT COUNT(*) FROM {tracker_id}{where}", params).fetchone()[0]
    except Exception as e:
        raise HTTPException(400, f"Query error: {e}")
    return {"data": json.loads(df.to_json(orient="records", date_format="iso")), "total": total, "limit": limit, "offset": offset}

@app.get("/api/map/{tracker_id}")
async def get_map_points(
    tracker_id: str,
    status: Optional[str] = None,
    country: Optional[str] = None,
    categories: Optional[str] = None,
    countries: Optional[str] = None,
    harbor_sizes: Optional[str] = None,
    q: Optional[str] = None,
    min_channel_m: Optional[float] = None,
    min_cargo_m: Optional[float] = None,
    min_anchorage_m: Optional[float] = None,
    limit: int = Query(5000, ge=1, le=150000),
):
    if tracker_id not in TRACKERS and not tracker_id.startswith("user_"):
        raise HTTPException(404)
    if tracker_id == "world_ports":
        selected_countries = _csv_values(countries or country)
        filtered = ports.filtered(
            q=q,
            categories=_csv_values(categories),
            countries=selected_countries,
            harbor_sizes=_csv_values(harbor_sizes),
            min_channel_m=min_channel_m,
            min_cargo_m=min_cargo_m,
            min_anchorage_m=min_anchorage_m,
        )
        return [ports.compact(item) for item in filtered[:limit]]
    if tracker_id in NORMALIZED_MAP_TRACKERS:
        columns = {
            row[0] for row in con.execute(f"DESCRIBE {tracker_id}").fetchall()
        }
        clauses = ["lat IS NOT NULL", "lon IS NOT NULL"]
        params: List[Any] = []
        if status:
            values = _status_values(status)
            if values:
                clauses.append(
                    "LOWER(CAST(status AS VARCHAR)) IN ("
                    + ",".join(["?"] * len(values))
                    + ")"
                )
                params.extend(value.lower() for value in values)
        if country:
            values = _csv_values(country)
            if values:
                clauses.append(
                    "LOWER(CAST(country AS VARCHAR)) IN ("
                    + ",".join(["?"] * len(values))
                    + ")"
                )
                params.extend(value.lower() for value in values)
        optional_columns = {
            name for name in (
                "source_url",
                "source_date",
                "evidence_level",
                "coverage_note",
                "coordinate_accuracy",
                "municipality",
                "subnational_unit",
                "region",
                "production_2024_ktpa",
                "production_2023_ktpa",
                "production_2022_ktpa",
                "reserves_kt",
                "resources_kt",
                "start_date",
                "stop_date",
                "owner",
                "parent_company",
                "location_address",
                "plant_age",
                "pellet_capacity_ktpa",
                "coking_capacity_ktpa",
                "steel_end_users",
                "workforce_size",
                "main_equipment",
                "power_source",
                "iron_ore_source",
                "met_coal_source",
                "iron_capacity_ktpa",
                "bf_capacity_ktpa",
                "dri_capacity_ktpa",
            )
            if name in columns
        }
        optional_select = "".join(
            f", {name}" for name in sorted(optional_columns)
        )
        sql = (
            "SELECT asset_id AS id, name, unit, status, capacity, "
            "capacity_unit, lat, lon, country, layer, asset_type, parent_port, "
            "product_type, source_text"
            + optional_select
            + " FROM "
            + tracker_id
            + " WHERE "
            + " AND ".join(clauses)
            + " LIMIT "
            + str(limit)
        )
        frame = con.execute(sql, params).fetchdf()
        return json.loads(frame.to_json(orient="records"))
    columns = {row[0] for row in con.execute(f"DESCRIBE {tracker_id}").fetchall()}
    clauses = ['"Latitude" IS NOT NULL', '"Longitude" IS NOT NULL']
    params = []
    if status and "Status" in columns:
        values = _status_values(status)
        clauses.append(
            'LOWER(CAST("Status" AS VARCHAR)) IN ('
            + ",".join(["?"] * len(values))
            + ")"
        )
        params.extend(value.lower() for value in values)
    if country:
        values = _csv_values(country)
        if "Country/Area" not in columns:
            return []
        clauses.append(
            'LOWER(CAST("Country/Area" AS VARCHAR)) IN ('
            + ",".join(["?"] * len(values))
            + ")"
        )
        params.extend(value.lower() for value in values)
    if tracker_id == "coal_plants":
        partition = '"Plant name", LOWER(TRIM(CAST("Status" AS VARCHAR)))'
        sql = (
            'SELECT CAST("GEM unit/phase ID" AS VARCHAR) AS id, '
            'CAST("GEM location ID" AS VARCHAR) AS gem_location_id, '
            '"Plant name" AS name, "Unit name" AS unit, "Status" AS status, '
            'TRY_CAST("Capacity (MW)" AS DOUBLE) AS capacity, '
            'SUM(TRY_CAST("Capacity (MW)" AS DOUBLE)) OVER '
            f'(PARTITION BY {partition}) AS plant_capacity, '
            f'COUNT(*) OVER (PARTITION BY {partition}) AS unit_count, '
            'MIN(TRY_CAST("Start year" AS INTEGER)) OVER '
            f'(PARTITION BY {partition}) AS commissioning_start_year, '
            'MAX(TRY_CAST("Start year" AS INTEGER)) OVER '
            f'(PARTITION BY {partition}) AS commissioning_end_year, '
            'TRY_CAST("Start year" AS INTEGER) AS unit_start_year, '
            'TRY_CAST("Latitude" AS DOUBLE) AS lat, '
            'TRY_CAST("Longitude" AS DOUBLE) AS lon, '
            '"Country/Area" AS country, "Owner" AS owner, '
            '"Parent" AS parent_company, '
            '"Combustion technology" AS combustion_technology, '
            '"Coal type" AS coal_type, "Coal source" AS coal_source, '
            '"Location" AS location, '
            '"Major area (prefecture, district)" AS district, '
            '"Subnational unit (province, state)" AS state, '
            '"Location accuracy" AS location_accuracy, "Permits" AS permits, '
            '"Captive industry use" AS captive_use, '
            'AVG(TRY_CAST("Capacity factor" AS DOUBLE)) OVER '
            f'(PARTITION BY {partition}) AS capacity_factor, '
            'SUM(TRY_CAST("Annual CO2 (million tonnes / annum)" AS DOUBLE)) '
            f'OVER (PARTITION BY {partition}) AS annual_co2_mtpa, '
            '"Wiki URL" AS source_url '
            'FROM coal_plants WHERE '
            + " AND ".join(clauses)
            + " LIMIT "
            + str(limit)
        )
        frame = con.execute(sql, params).fetchdf()
        records = json.loads(frame.to_json(orient="records"))
        for record in records:
            record.update(
                {
                    "capacity_unit": "MW",
                    "source_text": "Global Energy Monitor coal plant tracker",
                    "coverage_note": (
                        "Plant and unit attributes are from Global Energy "
                        "Monitor. Official CEA verification is shown only "
                        "where an exact station match has been reviewed."
                    ),
                }
            )
            if str(record.get("country") or "").lower() == "india":
                record["npp_source_url"] = NPP_PUBLISHED_REPORTS_URL
                record["ministry_coal_source_url"] = MINISTRY_COAL_LINKAGE_URL
            record.update(
                CEA_VERIFIED_COAL_PLANTS.get(
                    str(record.get("gem_location_id") or ""), {}
                )
            )
        return records
    name_expr = (
        '"Plant name"' if "Plant name" in columns
        else '"Project Name"' if "Project Name" in columns
        else '"GEM location ID"'
    )
    unit_expr = '"Unit name"' if "Unit name" in columns else "NULL"
    country_expr = '"Country/Area"' if "Country/Area" in columns else "NULL"
    capacity_expr = (
        'TRY_CAST("Capacity (MW)" AS DOUBLE)'
        if "Capacity (MW)" in columns else "NULL"
    )
    sql = (
        f"SELECT {name_expr} as name, {unit_expr} as unit, "
        f'"Status" as status, {capacity_expr} as capacity, '
        'TRY_CAST("Latitude" AS DOUBLE) as lat, '
        'TRY_CAST("Longitude" AS DOUBLE) as lon, '
        f"{country_expr} as country FROM {tracker_id} WHERE "
        + " AND ".join(clauses)
        + " LIMIT "
        + str(limit)
    )
    try:
        df = con.execute(sql, params).fetchdf()
        return json.loads(df.to_json(orient="records"))
    except Exception as e:
        # Fallback without depth columns if schema missing
        try:
            sql2 = (
                'SELECT "Plant name" as name, "Unit name" as unit, Status as status, '
                'TRY_CAST("Capacity (MW)" AS DOUBLE) as capacity, '
                'TRY_CAST(Latitude AS DOUBLE) as lat, TRY_CAST(Longitude AS DOUBLE) as lon, '
                '"Country/Area" as country FROM ' + tracker_id + where + ' LIMIT ' + str(limit)
            )
            df = con.execute(sql2, params).fetchdf()
            return json.loads(df.to_json(orient="records"))
        except Exception as e2:
            raise HTTPException(400, str(e2))

@app.get("/api/kpis/{tracker_id}")
async def get_kpis(tracker_id: str):
    if tracker_id not in TRACKERS:
        raise HTTPException(404)
    if tracker_id == "world_ports":
        return {
            "total_units": ports.summary.get("total", 0),
            "operating_units": ports.summary.get("total", 0),
            "operating_mw": 0,
            "total_mw": 0,
            "countries": len(ports.facets.get("countries", [])),
            "dry_bulk": ports.summary.get("dry_bulk", 0),
            "coal": ports.summary.get("coal", 0),
            "classified": ports.summary.get("classified", 0),
            "with_channel_depth": ports.summary.get("with_channel_depth", 0),
        }
    op = "operating"
    try:
        q = ("SELECT COUNT(*) as total_units, "
             "SUM(CASE WHEN LOWER(CAST(Status AS VARCHAR)) = ? THEN 1 ELSE 0 END) as operating_units, "
             "SUM(CASE WHEN LOWER(CAST(Status AS VARCHAR)) = ? THEN TRY_CAST(\"Capacity (MW)\" AS DOUBLE) ELSE 0 END) as operating_mw, "
             "SUM(TRY_CAST(\"Capacity (MW)\" AS DOUBLE)) as total_mw, "
             "COUNT(DISTINCT \"Country/Area\") as countries FROM " + tracker_id)
        df = con.execute(q, [op, op]).fetchdf()
        row = df.iloc[0].to_dict()
        status_df = con.execute(
            "SELECT Status, COUNT(*) as cnt, SUM(TRY_CAST(\"Capacity (MW)\" AS DOUBLE)) as mw FROM "
            + tracker_id + " GROUP BY Status ORDER BY cnt DESC"
        ).fetchdf()
        row["by_status"] = json.loads(status_df.to_json(orient="records"))
        return row
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/api/countries/{tracker_id}")
async def countries_by_capacity(tracker_id: str):
    if tracker_id not in TRACKERS and not tracker_id.startswith("user_"):
        raise HTTPException(404)
    if tracker_id == "world_ports":
        return [
            {
                "country": item["id"],
                "capacity": 0,
                "units": item["count"],
            }
            for item in ports.facets.get("countries", [])
        ]
    op = "operating"
    try:
        q = ("SELECT \"Country/Area\" as country, "
             "COALESCE(SUM(CASE WHEN LOWER(CAST(Status AS VARCHAR)) = ? THEN TRY_CAST(\"Capacity (MW)\" AS DOUBLE) ELSE 0 END), 0) as capacity, "
             "COUNT(*) as units FROM " + tracker_id + " "
             "WHERE \"Country/Area\" IS NOT NULL AND CAST(\"Country/Area\" AS VARCHAR) != '' "
             "GROUP BY \"Country/Area\" ORDER BY capacity DESC, units DESC")
        df = con.execute(q, [op]).fetchdf()
        return json.loads(df.to_json(orient="records"))
    except Exception as e:
        raise HTTPException(400, str(e))

def _csv_values(value: Optional[str]) -> List[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


@app.get("/api/ports")
async def list_ports(
    q: Optional[str] = None,
    categories: Optional[str] = None,
    countries: Optional[str] = None,
    harbor_sizes: Optional[str] = None,
    min_channel_m: Optional[float] = None,
    min_cargo_m: Optional[float] = None,
    min_anchorage_m: Optional[float] = None,
    limit: int = Query(5000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    filtered = ports.filtered(
        q=q,
        categories=_csv_values(categories),
        countries=_csv_values(countries),
        harbor_sizes=_csv_values(harbor_sizes),
        min_channel_m=min_channel_m,
        min_cargo_m=min_cargo_m,
        min_anchorage_m=min_anchorage_m,
    )
    return {
        "data": [ports.compact(item) for item in filtered[offset : offset + limit]],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "facets": ports.facets,
        "summary": ports.summary,
    }


@app.get("/api/ports/facets")
async def port_facets():
    return {"facets": ports.facets, "summary": ports.summary}


@app.get("/api/ports/{port_id}")
async def port_detail(port_id: str):
    port = ports.by_id.get(port_id)
    if not port:
        raise HTTPException(404, "Unknown port")
    return port


@app.get("/api/coal/summary")
async def coal_summary():
    """Describe verified India map coverage and uploaded analytical datasets."""
    datasets = _coal_dataset_metadata()
    official_master = _india_coal_master()
    official_analysis = _india_coal_analysis()
    official_coverage = official_master.get("coverage") or {}
    assets = _coal_asset_rows()
    counts = {
        key: sum(row["asset_kind"] == key for row in assets)
        for key in (
            "coal_mines",
            "coal_trade_terminals",
            "dry_bulk_ports",
            "power_consumers",
            "steel_consumers",
            "cement_consumers",
        )
    }
    available_types = sorted(
        {item.get("dataset_type") for item in datasets if item.get("dataset_type")}
    )
    if official_analysis.get("annual"):
        available_types = sorted(
            set(available_types)
            | {"production", "imports", "power_stocks", "power_use"}
        )
    return {
        "status": (
            "ready"
            if datasets or official_analysis.get("annual")
            else "awaiting_data"
        ),
        "country": "India",
        "map_assets": counts,
        "datasets": datasets,
        "official_master": {
            "status": official_master.get("quality", {}).get(
                "status", official_coverage.get("status", "available")
            ),
            "generated_at": official_master.get("generated_at"),
            "source_file_count": official_coverage.get("source_file_count", 0),
            "extracted_file_count": official_coverage.get("extracted_file_count", 0),
            "normalized_row_count": official_coverage.get("normalized_row_count", 0),
            "source_table_count": len(official_master.get("source_tables", [])),
            "ui_views": official_master.get("ui_views", {}),
        },
        "available_dataset_types": available_types,
        "official_analysis": {
            "status": official_analysis.get("status"),
            "period_count": len(official_analysis.get("annual", [])),
            "latest": official_analysis.get("latest", {}),
        },
        "dataset_types": [
            {"id": key, "label": label}
            for key, label in COAL_DATASET_TYPES.items()
        ],
        "supported_analysis": [
            "Monthly production versus imports",
            "Year-on-year production and imports",
            "Coal used in power generation by week, month, quarter and year",
            "Aligned-series correlation with renewables, monsoon and heat",
        ],
        "metric_definitions": {
            "stock_cover_days": {
                "label": "Coal stock cover",
                "unit": "days",
                "formula": (
                    "usable coal inventory tonnes / average daily coal "
                    "consumption tonnes"
                ),
                "supporting_fields": [
                    "usable coal inventory tonnes",
                    "average daily coal consumption tonnes",
                    "observation date",
                    "plant, state or national scope",
                ],
                "caveat": (
                    "Use a reported days-of-stock figure when authoritative. "
                    "Otherwise calculate only when inventory and consumption "
                    "refer to the same scope and observation period."
                ),
            }
        },
        "quality_note": (
            "Map assets use GEM and WPI sources. Official Coal Directory "
            "financial-year production, imports, off-take and pit-head stocks "
            "are mapped separately with source and methodology notes."
        ),
        "status_policy": {
            "default": "operating",
            "available": ["operating", "construction", "proposed"],
            "excluded": ["retired", "cancelled", "shelved", "mothballed"],
        },
    }


@app.get("/api/coal/assets")
async def coal_assets(
    asset_kind: Optional[str] = None,
    status_group: str = Query("operating"),
    limit: int = Query(5000, ge=1, le=20_000),
):
    try:
        rows = _coal_asset_rows(status_group=status_group)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if asset_kind:
        allowed = set(_csv_values(asset_kind))
        rows = [row for row in rows if row["asset_kind"] in allowed]
    return {"data": rows[:limit], "total": len(rows)}


@app.get("/api/coal/port-specifications")
async def coal_port_specifications():
    return _india_coal_port_specs()


@app.get("/api/coal/port-specifications/export")
async def export_coal_port_specifications():
    payload = _india_coal_port_specs()
    export_rows = []
    for item in payload.get("ports", []):
        export_rows.append(
            {
                "Asset ID": item.get("asset_id"),
                "Coal terminal card": item.get("asset_name"),
                "Official port name": item.get("official_port_name"),
                "State / UT": item.get("state_ut"),
                "Coast": item.get("coast"),
                "Port class": item.get("port_class"),
                "Operating status": item.get("operating_status"),
                "Latitude": item.get("latitude"),
                "Longitude": item.get("longitude"),
                "Max documented draft (m)": item.get(
                    "max_documented_draft_m"
                ),
                "Documented berth count": item.get(
                    "documented_berth_count"
                ),
                "Documented dry-bulk berth count": item.get(
                    "documented_dry_bulk_berth_count"
                ),
                "Facility record count": len(
                    item.get("berth_facilities", [])
                ),
                "Port capacity (MTPA)": item.get("port_capacity_mtpa"),
                "Terminal operating capacity (MTPA)": item.get(
                    "terminal_operating_capacity_mtpa"
                ),
                "Terminal expansion capacity (MTPA)": item.get(
                    "terminal_expansion_capacity_mtpa"
                ),
                "Latest port traffic (MT)": item.get("latest_traffic_mt"),
                "Latest traffic period": item.get("latest_traffic_period"),
                "Coal flow record count": len(
                    item.get("commodity_flows", [])
                ),
                "Official website": item.get("official_website"),
                "Source as of": item.get("source_as_of"),
                "Specification note": item.get("specification_note"),
                "Data caveat": item.get("data_caveat"),
            }
        )
    frame = pd.DataFrame(export_rows)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                "attachment; filename=india_coal_port_specifications.csv"
            )
        },
    )


@app.get("/api/coal/port-specifications/{asset_id}")
async def coal_port_specification(asset_id: str):
    payload = _india_coal_port_specs()
    specification = next(
        (
            item
            for item in payload.get("ports", [])
            if str(item.get("asset_id")) == asset_id
        ),
        None,
    )
    if not specification:
        raise HTTPException(404, "Port specification not found")
    return specification


@app.get("/api/coal/datasets")
async def coal_datasets():
    return {"data": _coal_dataset_metadata()}


@app.get("/api/coal/master")
async def coal_master(
    include_records: bool = Query(False),
):
    payload = _india_coal_master()
    if not include_records and "records" in payload:
        payload = dict(payload)
        payload["records"] = []
        payload["records_omitted"] = True
    return payload


@app.get("/api/coal/master/source-table-catalog.csv")
async def export_coal_master_source_table_catalog():
    payload = _india_coal_master()
    rows = payload.get("source_tables", [])
    frame = pd.DataFrame(rows)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                "attachment; filename=india_coal_source_table_catalog.csv"
            )
        },
    )


@app.get("/api/coal/analysis")
async def coal_analysis():
    return _india_coal_analysis()


@app.get("/api/coal/dashboard")
async def coal_dashboard(
    tab: str = Query("overview"),
    start: str = Query("2023-05"),
    end: str = Query("2026-06"),
    frequency: str = Query("monthly"),
    focus: str = Query("all"),
    comparison: str = Query("previous_period"),
):
    return _coal_dashboard_payload(tab, start, end, frequency, focus, comparison)


@app.get("/api/coal/dashboard/export")
async def export_coal_dashboard(
    tab: str = Query("overview"),
    start: str = Query("2023-05"),
    end: str = Query("2026-06"),
    frequency: str = Query("monthly"),
    focus: str = Query("all"),
    comparison: str = Query("previous_period"),
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
):
    payload = _coal_dashboard_payload(tab, start, end, frequency, focus, comparison)
    frame = pd.DataFrame(payload["rows"], columns=payload["columns"])
    filename = f"india_coal_{tab}_{frequency}_{start}_to_{end}"
    if format == "csv":
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        return StreamingResponse(
            iter([buffer.getvalue()]), media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Filtered data")
        used_sheets = {"Filtered data", "Sources", "Selection"}
        for index, chart in enumerate(payload.get("charts", []), start=1):
            chart_rows = chart.get("rows")
            if not chart_rows:
                continue
            base_name = re.sub(r"[^A-Za-z0-9 _-]", "", chart.get("title", f"Chart {index}"))[:31].strip() or f"Chart {index}"
            sheet_name = base_name
            suffix = 2
            while sheet_name in used_sheets:
                tail = f" {suffix}"
                sheet_name = f"{base_name[:31 - len(tail)]}{tail}"
                suffix += 1
            used_sheets.add(sheet_name)
            pd.DataFrame(chart_rows).to_excel(writer, index=False, sheet_name=sheet_name)
        pd.DataFrame(payload["sources"]).to_excel(writer, index=False, sheet_name="Sources")
        pd.DataFrame([
            {"field": "Dashboard tab", "value": tab},
            {"field": "Requested from", "value": start},
            {"field": "Requested to", "value": end},
            {"field": "Frequency", "value": frequency},
            {"field": "Measure focus", "value": focus},
            {"field": "Comparison", "value": comparison},
            {"field": "Returned rows", "value": len(frame)},
            {"field": "Available start", "value": payload["available_range"].get("start")},
            {"field": "Available end", "value": payload["available_range"].get("end")},
            {"field": "Limitation", "value": payload["available_range"].get("limitation", "")},
        ]).to_excel(writer, index=False, sheet_name="Selection")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
    )


@app.get("/api/coal/analysis.csv")
async def export_coal_analysis_csv():
    if not INDIA_COAL_ANNUAL_CSV_PATH.exists():
        raise HTTPException(404, "Mapped India coal analysis is unavailable")
    return FileResponse(
        INDIA_COAL_ANNUAL_CSV_PATH,
        media_type="text/csv; charset=utf-8",
        filename="india_coal_annual_analysis.csv",
    )


@app.post("/api/coal/research/query")
async def coal_research_query(request: CoalResearchQuery):
    question = request.question.strip()
    if len(question) < 4:
        raise HTTPException(400, "Write a more specific research question.")
    return _research_payload(question)


@app.get("/api/coal/research/export")
async def export_coal_research(
    q: str = Query(..., min_length=4),
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
):
    payload = _research_payload(q)
    frame = pd.DataFrame(payload["rows"])
    if format == "csv":
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="india_coal_research.csv"'},
        )
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Research result")
        pd.DataFrame(payload["sources"]).to_excel(writer, index=False, sheet_name="Sources")
        pd.DataFrame([{
            "question": q,
            "answer": payload["answer"],
            "unit": payload["unit"],
            "status": payload["status"],
            "guardrail": payload["guardrail"],
        }]).to_excel(writer, index=False, sheet_name="Methodology")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="india_coal_research.xlsx"'},
    )


@app.get("/api/npp/power-dashboard")
async def npp_power_dashboard(force: bool = Query(False)):
    return await _get_npp_power_dashboard(force=force)


@app.post("/api/coal/upload")
async def upload_coal_dataset(
    dataset_type: str = Query(...),
    file: UploadFile = File(...),
):
    if dataset_type not in COAL_DATASET_TYPES:
        raise HTTPException(400, "Unknown coal dataset type")
    original_name = Path(file.filename or "coal-data")
    ext = original_name.suffix.lower()
    if ext not in {".xlsx", ".xls", ".csv", ".json"}:
        raise HTTPException(400, "Supported: Excel, CSV, JSON")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 50 MB)")
    try:
        if ext in {".xlsx", ".xls"}:
            frame = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        elif ext == ".csv":
            frame = pd.read_csv(io.BytesIO(content))
        else:
            frame = pd.read_json(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(400, f"Parse error: {exc}")
    if frame.empty:
        raise HTTPException(400, "The uploaded dataset has no rows")
    frame.columns = [str(column).strip() for column in frame.columns]
    uid = uuid.uuid4().hex[:12]
    safe_stem = re.sub(
        r"[^A-Za-z0-9_-]+", "_", original_name.stem
    ).strip("_") or "coal_data"
    csv_path = COAL_UPLOAD_DIR / f"{dataset_type}_{safe_stem}_{uid}.csv"
    meta_path = csv_path.with_suffix(".json")
    frame.to_csv(csv_path, index=False)
    date_candidates = [
        column for column in frame.columns
        if any(token in column.lower() for token in ("date", "month", "week", "year", "period"))
    ]
    numeric_candidates = [
        column for column in frame.columns
        if pd.to_numeric(frame[column], errors="coerce").notna().sum()
        >= max(1, int(len(frame) * 0.5))
    ]
    stock_cover_candidates = [
        column for column in frame.columns
        if "day" in column.lower()
        and any(token in column.lower() for token in ("stock", "cover", "left"))
    ]
    inventory_candidates = [
        column for column in frame.columns
        if any(token in column.lower() for token in ("stock", "inventory"))
        and column not in stock_cover_candidates
    ]
    consumption_candidates = [
        column for column in frame.columns
        if any(token in column.lower() for token in ("consumption", "daily use", "burn"))
    ]
    stock_cover_issue = (
        dataset_type == "power_stocks"
        and not stock_cover_candidates
        and not (inventory_candidates and consumption_candidates)
    )
    metadata = {
        "id": csv_path.stem,
        "dataset_type": dataset_type,
        "dataset_label": COAL_DATASET_TYPES[dataset_type],
        "original_name": original_name.name,
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "date_candidates": date_candidates,
        "numeric_candidates": numeric_candidates,
        "stock_cover_candidates": stock_cover_candidates,
        "inventory_candidates": inventory_candidates,
        "consumption_candidates": consumption_candidates,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "quality_status": (
            "review_needed"
            if not date_candidates or not numeric_candidates or stock_cover_issue
            else "profiled"
        ),
        "quality_issues": [
            issue
            for condition, issue in (
                (not date_candidates, "No obvious date or period column was detected."),
                (not numeric_candidates, "No mostly numeric measure column was detected."),
                (
                    stock_cover_issue,
                    "Stock-cover data needs a reported days-left field or both "
                    "inventory tonnes and aligned daily consumption.",
                ),
            )
            if condition
        ],
        "csv_file": csv_path.name,
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


@app.get("/api/coal/export")
async def export_coal_data(
    dataset_type: str = Query("production"),
    frequency: str = Query("yearly", pattern="^(weekly|monthly|quarterly|yearly)$"),
    coal_type: str = Query(""),
    period: str = Query("all", pattern="^(12m|3y|5y|10y|all)$"),
):
    if dataset_type not in COAL_DATASET_TYPES:
        raise HTTPException(400, "Unknown coal dataset type")
    datasets = _coal_dataset_metadata()
    datasets = [
        item for item in datasets if item.get("dataset_type") == dataset_type
    ]
    official_analysis = _india_coal_analysis()
    official_frame, official_label, selection_note = _filtered_official_frame(
        dataset_type, frequency, coal_type, period
    )
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        used_sheets: set[str] = set()
        official_frame.to_excel(writer, index=False, sheet_name="Filtered official data")
        used_sheets.add("Filtered official data")
        for index, metadata in enumerate(datasets):
            csv_path = COAL_UPLOAD_DIR / str(metadata.get("csv_file", ""))
            if not csv_path.exists():
                continue
            frame = pd.read_csv(csv_path)
            base = str(metadata.get("dataset_type") or f"data_{index + 1}")[:27]
            sheet = base
            suffix = 2
            while sheet in used_sheets:
                sheet = f"{base[:27]}_{suffix}"
                suffix += 1
            used_sheets.add(sheet)
            frame.to_excel(writer, index=False, sheet_name=sheet)
        methodology = pd.DataFrame([
            {"field": "Dataset", "value": official_label},
            {"field": "Frequency", "value": frequency},
            {"field": "Coal type", "value": coal_type or "all coal"},
            {"field": "Period", "value": period},
            {"field": "Quality", "value": selection_note},
            {"field": "Guardrail", "value": "Correlation is association, not causation."},
        ])
        methodology.to_excel(writer, index=False, sheet_name="Methodology")
        pd.DataFrame(official_analysis.get("sources", [])).to_excel(
            writer, index=False, sheet_name="Sources"
        )
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="india_coal_{dataset_type}_{frequency}.xlsx"'
            )
        },
    )

@app.get("/api/zones")
async def get_zones():
    payload = load_zones()
    return {
        **payload,
        "features": [
            feature
            for feature in payload.get("features", [])
            if (feature.get("properties") or {}).get("risk_family") == "jwc"
        ],
    }

@app.get("/api/weather")
async def weather(lat: float = Query(...), lon: float = Query(...)):
    return await fetch_weather(lat, lon)

@app.get("/api/bunker")
async def bunker():
    return await fetch_bunker_prices()

@app.post("/api/route")
async def sea_route(req: RouteRequest):
    try:
        from_port = (
            ports.by_id.get(str(req.from_port_id))
            if req.from_port_id is not None else None
        )
        to_port = (
            ports.by_id.get(str(req.to_port_id))
            if req.to_port_id is not None else None
        )
        from_lon = float(from_port["lon"] if from_port else req.from_lon)
        from_lat = float(from_port["lat"] if from_port else req.from_lat)
        to_lon = float(to_port["lon"] if to_port else req.to_lon)
        to_lat = float(to_port["lat"] if to_port else req.to_lat)
        if not (-180 <= from_lon <= 180 and -90 <= from_lat <= 90):
            raise ValueError("Origin coordinates are outside valid longitude/latitude bounds")
        if not (-180 <= to_lon <= 180 and -90 <= to_lat <= 90):
            raise ValueError("Destination coordinates are outside valid longitude/latitude bounds")
        if _haversine_nm([from_lon, from_lat], [to_lon, to_lat]) < 0.05:
            raise ValueError("Origin and destination must be different ports")

        speed = min(40.0, max(1.0, float(req.speed_knots or 12.0)))
        sea_margin_pct = min(50.0, max(0.0, float(req.sea_margin_pct or 0.0)))
        port_time_hours = min(720.0, max(0.0, float(req.port_time_hours or 0.0)))
        canal_delay_hours = min(240.0, max(0.0, float(req.canal_delay_hours or 0.0)))
        avoid = [
            str(value).lower()
            for value in (req.avoid or [])
            if str(value).lower() in ALLOWED_ROUTE_RESTRICTIONS
        ]
        if "northwest" not in avoid:
            avoid.append("northwest")
        from_approach = _port_approach(str(req.from_port_id)) if from_port else None
        to_approach = _port_approach(str(req.to_port_id)) if to_port else None
        route_from_lon = float(
            from_approach["longitude"] if from_approach else from_lon
        )
        route_from_lat = float(
            from_approach["latitude"] if from_approach else from_lat
        )
        route_to_lon = float(to_approach["longitude"] if to_approach else to_lon)
        route_to_lat = float(to_approach["latitude"] if to_approach else to_lat)
        baseline = _compute_curated_corridor(
            req.from_port_id, req.to_port_id, speed, avoid
        ) or _compute_route(
            route_from_lon, route_from_lat, route_to_lon, route_to_lat, speed, avoid
        )
        primary = baseline
        calm_sea_hours = primary["distance_nm"] / speed
        sea_margin_hours = calm_sea_hours * sea_margin_pct / 100.0
        sailing_hours = calm_sea_hours + sea_margin_hours
        total_hours = sailing_hours + port_time_hours + canal_delay_hours
        primary.update({
            "calm_sea_hours": round(calm_sea_hours, 2),
            "sea_margin_pct": round(sea_margin_pct, 1),
            "sea_margin_hours": round(sea_margin_hours, 2),
            "sailing_hours": round(sailing_hours, 2),
            "port_time_hours": round(port_time_hours, 2),
            "canal_delay_hours": round(canal_delay_hours, 2),
            "total_duration_hours": round(total_hours, 2),
            "total_duration_days": round(total_hours / 24.0, 2),
            "effective_speed_knots": round(
                primary["distance_nm"] / sailing_hours if sailing_hours else speed,
                2,
            ),
        })
        alt = None
        via_suez = "suez" in primary.get("passage_ids", [])
        if via_suez and "suez" not in avoid:
            try:
                alt = _compute_route(
                    route_from_lon,
                    route_from_lat,
                    route_to_lon,
                    route_to_lat,
                    speed,
                    avoid + ["suez"],
                )
            except Exception:
                alt = None

        coords = primary.get("coordinates") or []
        mid = coords[len(coords) // 2] if coords else [from_lon, from_lat]
        bunker, origin_weather, midpoint_weather, destination_weather = (
            await asyncio.gather(
                fetch_bunker_prices(),
                fetch_weather(route_from_lat, route_from_lon),
                fetch_weather(mid[1], mid[0]),
                fetch_weather(route_to_lat, route_to_lon),
            )
        )
        fuel = estimate_fuel_cost(
            primary["distance_nm"], primary["effective_speed_knots"],
            req.consumption_tpd or 25.0,
            0.0,
            bunker,
        )

        # Weather at origin, midpoint sample, destination
        weather = {
            "origin": origin_weather,
            "midpoint": midpoint_weather,
            "destination": destination_weather,
        }

        from_name = (from_port or {}).get("name") or req.from_name
        to_name = (to_port or {}).get("name") or req.to_name
        if primary.get("routing_profile") == "verified-approach-dense-corridor":
            warnings = [
                "Official sea-side approach references with an analytical densified open-sea corridor; not for navigation."
            ]
        else:
            warnings = [
                "Analytical shortest-path estimate on the searoute maritime network; not for navigation."
            ]
        if primary["route_confidence"] == "low":
            warnings.append(
                "A selected port is more than 20 nm from the nearest network node; review the connector leg."
            )
        result = {
            **primary,
            "from_name": from_name,
            "to_name": to_name,
            "from_port_id": str(req.from_port_id) if from_port else None,
            "to_port_id": str(req.to_port_id) if to_port else None,
            "coordinate_source": (
                "Verified sea-side port approaches"
                if from_approach and to_approach
                else "World Port Index catalogue"
                if from_port and to_port
                else "submitted map coordinates"
            ),
            "method": (
                "HRP verified-approach dense corridor"
                if primary.get("routing_profile")
                == "verified-approach-dense-corridor"
                else "searoute 1.6 maritime network + endpoint connector legs"
            ),
            "warnings": warnings,
            "fuel": fuel,
            "weather": weather,
            "route_ports": _route_reference_ports(
                primary.get("coordinates") or [],
                str(req.from_port_id) if from_port else None,
                str(req.to_port_id) if to_port else None,
                limit=5,
            ),
        }
        if alt and alt["distance_nm"] > primary["distance_nm"]:
            alt_calm_hours = alt["distance_nm"] / speed
            alt_total_hours = (
                alt_calm_hours * (1 + sea_margin_pct / 100.0)
                + port_time_hours
                + canal_delay_hours
            )
            result["alternate_cape_nm"] = alt["distance_nm"]
            result["alternate_cape_days"] = round(alt_total_hours / 24.0, 2)
            result["alternate_cape_via"] = alt.get("via")
        return result
    except Exception as e:
        raise HTTPException(400, f"Route error: {e}")

def _ais_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _ais_text(value: Any) -> str:
    return str(value or "").replace("@", " ").strip()


_last_ais_maintenance_at = 0.0


def _maintain_ais_observations(db: sqlite3.Connection, *, force: bool = False) -> None:
    """Bound raw AIS growth while retaining one current position per vessel."""
    global _last_ais_maintenance_at
    now = time.monotonic()
    if not force and now - _last_ais_maintenance_at < AIS_MAINTENANCE_INTERVAL_SECONDS:
        return
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=AIS_RAW_RETENTION_DAYS)
    ).isoformat()
    db.execute("DELETE FROM ais_observations WHERE observed_at < ?", (cutoff,))
    count = int(db.execute("SELECT COUNT(*) FROM ais_observations").fetchone()[0])
    excess = max(0, count - AIS_MAX_OBSERVATIONS)
    if excess:
        db.execute(
            "DELETE FROM ais_observations WHERE id IN "
            "(SELECT id FROM ais_observations ORDER BY id LIMIT ?)",
            (excess,),
        )
    _last_ais_maintenance_at = now


def _store_ais_observations(vessels: List[dict]) -> None:
    rows = []
    for vessel in vessels:
        mmsi = str(vessel.get("mmsi") or "")
        lat = _ais_number(vessel.get("lat"))
        lon = _ais_number(vessel.get("lon"))
        if not mmsi or lat is None or lon is None:
            continue
        observed_at = vessel.get("last_update") or datetime.now(timezone.utc).isoformat()
        rows.append(
            (
                mmsi,
                observed_at,
                lat,
                lon,
                _ais_number(vessel.get("sog_kn")),
                _ais_number(vessel.get("cog")),
                _ais_number(vessel.get("heading")),
                _ais_text(vessel.get("name")),
            )
        )
    if not rows:
        return
    with sqlite3.connect(AIS_TRAIL_DB_PATH) as db:
        for row in rows:
            previous = db.execute(
                """
                SELECT observed_at, latitude, longitude
                FROM ais_observations
                WHERE mmsi = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (row[0],),
            ).fetchone()
            if previous and (
                previous[0] == row[1]
                or (
                    abs(float(previous[1]) - row[2]) < 0.00001
                    and abs(float(previous[2]) - row[3]) < 0.00001
                )
            ):
                continue
            db.execute(
                """
                INSERT INTO ais_observations (
                    mmsi, observed_at, latitude, longitude, sog_kn, cog_deg,
                    heading_deg, vessel_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            db.execute(
                """
                INSERT INTO ais_latest_positions (
                    mmsi, observed_at, latitude, longitude, sog_kn, cog_deg,
                    heading_deg, vessel_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mmsi) DO UPDATE SET
                    observed_at=excluded.observed_at,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    sog_kn=excluded.sog_kn,
                    cog_deg=excluded.cog_deg,
                    heading_deg=excluded.heading_deg,
                    vessel_name=CASE WHEN excluded.vessel_name != ''
                        THEN excluded.vessel_name ELSE ais_latest_positions.vessel_name END
                """,
                row,
            )
        _maintain_ais_observations(db)


def _load_latest_ais_observations(limit: int = 20000) -> Dict[str, dict]:
    """Restore the latest received position for each MMSI after a restart."""
    with sqlite3.connect(AIS_TRAIL_DB_PATH) as db:
        rows = db.execute(
            """
            SELECT mmsi, observed_at, latitude, longitude, sog_kn, cog_deg,
                   heading_deg, vessel_name
            FROM ais_latest_positions
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 25000)),),
        ).fetchall()
    vessels: Dict[str, dict] = {}
    for row in rows:
        mmsi = str(row[0] or "")
        if not mmsi:
            continue
        vessels[mmsi] = {
            "mmsi": mmsi,
            "last_update": row[1],
            "lat": row[2],
            "lon": row[3],
            "sog_kn": row[4],
            "cog": row[5],
            "heading": row[6],
            "name": row[7] or "",
            "position_source": "retained",
        }
    return vessels


def _merge_ais_message(vessels: Dict[str, dict], msg: dict) -> Optional[dict]:
    meta = msg.get("MetaData") or msg.get("Metadata") or {}
    body = msg.get("Message") or {}
    message_type = msg.get("MessageType") or ""
    payload = body.get(message_type) or {}
    mmsi = str(
        meta.get("MMSI")
        or payload.get("UserID")
        or payload.get("UserId")
        or ""
    )
    if not mmsi:
        return None
    rec = vessels.setdefault(mmsi, {"mmsi": mmsi})
    rec["position_source"] = "live"
    name = _ais_text(meta.get("ShipName") or payload.get("Name"))
    if name:
        rec["name"] = name
    time_value = meta.get("time_utc") or meta.get("TimeUtc")
    rec["last_update"] = str(time_value or datetime.now(timezone.utc).isoformat())

    lat = meta.get("Latitude", meta.get("latitude"))
    lon = meta.get("Longitude", meta.get("longitude"))
    if lat is None:
        lat = payload.get("Latitude")
    if lon is None:
        lon = payload.get("Longitude")
    lat_number = _ais_number(lat)
    lon_number = _ais_number(lon)
    if lat_number is not None and lon_number is not None:
        rec["lat"] = lat_number
        rec["lon"] = lon_number

    field_map = {
        "Sog": "sog_kn",
        "Cog": "cog",
        "TrueHeading": "heading",
        "NavigationalStatus": "nav_status",
        "Type": "ship_type",
        "Destination": "destination",
        "Eta": "eta",
    }
    for source, target in field_map.items():
        if payload.get(source) is not None:
            rec[target] = payload.get(source)
    imo = payload.get("ImoNumber") or payload.get("IMO")
    if imo:
        rec["imo"] = str(imo)
    call_sign = _ais_text(payload.get("CallSign"))
    if call_sign:
        rec["call_sign"] = call_sign
    dimension = payload.get("Dimension") or {}
    length = (
        (_ais_number(dimension.get("A")) or 0)
        + (_ais_number(dimension.get("B")) or 0)
    )
    width = (
        (_ais_number(dimension.get("C")) or 0)
        + (_ais_number(dimension.get("D")) or 0)
    )
    if length:
        rec["length_m"] = length
    if width:
        rec["width_m"] = width
    return rec


async def _sample_ais(
    bounding_boxes: List[List[List[float]]],
    timeout_sec: float,
    max_vessels: int = 500,
    mmsis: Optional[List[str]] = None,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    if not AISSTREAM_API_KEY:
        return {"error": "No AISStream API key configured", "vessels": []}
    try:
        import websockets as wslib
    except ImportError:
        return {"error": "Server missing websockets package", "vessels": []}
    vessels: Dict[str, dict] = {}
    mmsi_set = set(str(m) for m in (mmsis or []))
    query_value = _ais_text(query).casefold()
    sub = {
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": bounding_boxes,
        "FilterMessageTypes": [
            "PositionReport",
            "ShipStaticData",
            "StaticDataReport",
            "StandardClassBPositionReport",
            "ExtendedClassBPositionReport",
        ],
    }
    if mmsi_set:
        sub["FiltersShipMMSI"] = list(mmsi_set)[:50]
    try:
        async with wslib.connect(
            "wss://stream.aisstream.io/v0/stream",
            open_timeout=15,
            ping_interval=None,
            max_size=2**22,
            close_timeout=5,
        ) as upstream:
            await upstream.send(json.dumps(sub))
            deadline = asyncio.get_event_loop().time() + max(
                2.0, min(timeout_sec, 25.0)
            )
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(upstream.recv(), timeout=max(0.5, remaining))
                except Exception:
                    break
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                rec = _merge_ais_message(vessels, msg)
                if not rec:
                    continue
                if len(vessels) >= max_vessels:
                    break
                if mmsi_set and all(
                    vessels.get(m, {}).get("lat") is not None for m in mmsi_set
                ):
                    break
    except Exception as e:
        return {"error": f"AIS sample failed: {e}", "vessels": list(vessels.values())}
    out = [v for v in vessels.values() if v.get("lat") is not None]
    if query_value:
        out = [
            v for v in out
            if query_value in _ais_text(v.get("name")).casefold()
            or query_value in str(v.get("mmsi") or "")
            or query_value in str(v.get("imo") or "")
            or query_value in _ais_text(v.get("call_sign")).casefold()
        ]
    _store_ais_observations(out)
    return {
        "vessels": out[:max_vessels],
        "queried_mmsi": list(mmsi_set),
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }


async def _sample_ais_for_ships(
    mmsis: List[str], imos: List[str], timeout_sec: float = 25.0
) -> Dict[str, Any]:
    # AISStream can filter directly by MMSI. IMO-only lookups require listening
    # for static messages, so they are sampled globally and may not resolve.
    query = imos[0] if imos and not mmsis else None
    result = await _sample_ais(
        [[[-90.0, -180.0], [90.0, 180.0]]],
        timeout_sec,
        max_vessels=100,
        mmsis=mmsis,
        query=query,
    )
    result["queried_imo"] = imos
    return result


class AisLiveManager:
    """One upstream AISStream connection with replaceable subscriptions."""

    def __init__(self) -> None:
        self.vessels: Dict[str, dict] = _load_latest_ais_observations()
        self.desired_subscription: Optional[dict] = None
        self.subscription_signature = ""
        self.subscription_event = asyncio.Event()
        self.data_event = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.stopping = False
        self.last_error: Optional[str] = None
        self.connected = False
        self.last_message_at: Optional[str] = None

    async def configure(
        self,
        boxes: List[List[List[float]]],
        mmsis: Optional[List[str]] = None,
    ) -> None:
        clean_mmsis = [
            str(value)
            for value in (mmsis or [])
            if len(str(value)) == 9 and str(value).isdigit()
        ][:50]
        subscription = {
            "APIKey": AISSTREAM_API_KEY,
            "BoundingBoxes": boxes,
            "FilterMessageTypes": [
                "PositionReport",
                "ShipStaticData",
                "StaticDataReport",
                "StandardClassBPositionReport",
                "ExtendedClassBPositionReport",
            ],
        }
        if clean_mmsis:
            subscription["FiltersShipMMSI"] = clean_mmsis
        signature = json.dumps(
            {key: value for key, value in subscription.items() if key != "APIKey"},
            sort_keys=True,
        )
        if signature != self.subscription_signature:
            self.desired_subscription = subscription
            self.subscription_signature = signature
            self.data_event.clear()
            self.subscription_event.set()
        if self.task is None or self.task.done():
            self.stopping = False
            self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            import websockets as wslib
        except ImportError:
            self.last_error = "Server missing websockets package"
            return
        retry_delay = 1.0
        while not self.stopping:
            if not self.desired_subscription:
                await asyncio.sleep(0.25)
                continue
            try:
                async with wslib.connect(
                    "wss://stream.aisstream.io/v0/stream",
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2**22,
                    max_queue=4096,
                    close_timeout=5,
                ) as upstream:
                    self.connected = True
                    self.last_error = None
                    self.subscription_event.clear()
                    await upstream.send(json.dumps(self.desired_subscription))
                    last_subscription_at = asyncio.get_event_loop().time()
                    retry_delay = 1.0
                    pending_observations: Dict[str, dict] = {}
                    last_flush = last_subscription_at
                    while not self.stopping:
                        receive_task = asyncio.create_task(upstream.recv())
                        update_task = asyncio.create_task(
                            self.subscription_event.wait()
                        )
                        done, pending = await asyncio.wait(
                            {receive_task, update_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        if update_task in done and update_task.result():
                            elapsed = (
                                asyncio.get_event_loop().time()
                                - last_subscription_at
                            )
                            if elapsed < 1.05:
                                await asyncio.sleep(1.05 - elapsed)
                            self.subscription_event.clear()
                            await upstream.send(
                                json.dumps(self.desired_subscription)
                            )
                            last_subscription_at = asyncio.get_event_loop().time()
                            continue
                        raw = receive_task.result()
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="ignore")
                        try:
                            message = json.loads(raw)
                        except Exception:
                            continue
                        if message.get("error"):
                            self.last_error = str(message["error"])
                            continue
                        record = _merge_ais_message(self.vessels, message)
                        if record and record.get("lat") is not None:
                            mmsi = str(record.get("mmsi") or "")
                            if mmsi:
                                pending_observations[mmsi] = dict(record)
                            self.last_message_at = datetime.now(
                                timezone.utc
                            ).isoformat()
                            self.data_event.set()
                        now = asyncio.get_event_loop().time()
                        if pending_observations and now - last_flush >= 5.0:
                            batch = list(pending_observations.values())
                            pending_observations.clear()
                            await asyncio.to_thread(
                                _store_ais_observations, batch
                            )
                            last_flush = now
                        if len(self.vessels) > 25000:
                            ordered = sorted(
                                self.vessels.items(),
                                key=lambda item: str(
                                    item[1].get("last_update") or ""
                                ),
                                reverse=True,
                            )
                            self.vessels = dict(ordered[:20000])
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.connected = False
                self.last_error = str(error)
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 2)
            finally:
                self.connected = False

    async def wait_for_data(self, timeout: float = 2.0) -> None:
        if self.data_event.is_set():
            return
        try:
            await asyncio.wait_for(
                self.data_event.wait(), timeout=max(0.25, min(timeout, 4.0))
            )
        except asyncio.TimeoutError:
            pass

    def snapshot(
        self,
        south: float,
        north: float,
        west: float,
        east: float,
        query: Optional[str],
        mmsis: Optional[List[str]],
        limit: int,
        boxes: Optional[List[List[List[float]]]] = None,
    ) -> List[dict]:
        query_value = _ais_text(query).casefold()
        mmsi_set = set(str(value) for value in (mmsis or []))
        output = []
        for vessel in self.vessels.values():
            lat = _ais_number(vessel.get("lat"))
            lon = _ais_number(vessel.get("lon"))
            if lat is None or lon is None:
                continue
            if not mmsi_set:
                candidate_boxes = boxes or [[[south, west], [north, east]]]
                in_region = False
                for box in candidate_boxes:
                    box_south, box_west = box[0]
                    box_north, box_east = box[1]
                    longitude_matches = (
                        box_west <= lon <= box_east
                        if box_west <= box_east
                        else lon >= box_west or lon <= box_east
                    )
                    if box_south <= lat <= box_north and longitude_matches:
                        in_region = True
                        break
                if not in_region:
                    continue
            if mmsi_set and str(vessel.get("mmsi") or "") not in mmsi_set:
                continue
            if query_value and not (
                query_value in _ais_text(vessel.get("name")).casefold()
                or query_value in str(vessel.get("mmsi") or "")
                or query_value in str(vessel.get("imo") or "")
                or query_value
                in _ais_text(vessel.get("call_sign")).casefold()
            ):
                continue
            output.append(dict(vessel))
        output.sort(
            key=lambda vessel: str(vessel.get("last_update") or ""),
            reverse=True,
        )
        if boxes and len(boxes) > 1 and not mmsi_set and len(output) > limit:
            buckets: List[List[dict]] = [[] for _ in boxes]
            for vessel in output:
                lat = float(vessel["lat"])
                lon = float(vessel["lon"])
                for index, box in enumerate(boxes):
                    box_south, box_west = box[0]
                    box_north, box_east = box[1]
                    longitude_matches = (
                        box_west <= lon <= box_east
                        if box_west <= box_east
                        else lon >= box_west or lon <= box_east
                    )
                    if box_south <= lat <= box_north and longitude_matches:
                        buckets[index].append(vessel)
                        break
            balanced: List[dict] = []
            bucket_index = 0
            while len(balanced) < limit and any(buckets):
                bucket = buckets[bucket_index % len(buckets)]
                if bucket:
                    balanced.append(bucket.pop(0))
                bucket_index += 1
            return balanced
        return output[:limit]

    async def stop(self) -> None:
        self.stopping = True
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


ais_live_manager = AisLiveManager()
imd_coastal_weather_manager = ImdCoastalWeatherManager(
    IMD_COASTAL_CACHE_PATH
)
bmkg_marine_weather_manager = BmkgMarineWeatherManager(
    BMKG_MARINE_CACHE_PATH
)
sea_marine_weather_manager = SeaMarineWeatherManager(SEA_MARINE_CACHE_PATH)
major_port_weather_manager = MajorPortWeatherManager(MAJOR_PORT_WEATHER_CACHE_PATH)
global_cyclone_manager = GlobalCycloneManager(
    GLOBAL_CYCLONE_CACHE_PATH, ports.ports
)
river_level_manager = RiverLevelManager(RIVER_LEVEL_CACHE_PATH)


@app.on_event("startup")
async def start_ais_background_collection():
    """Collect the priority Asia feed even when no browser is showing the layer."""
    if not AISSTREAM_API_KEY:
        return
    boxes: List[List[List[float]]] = []
    for region in AIS_BACKGROUND_REGION_IDS:
        boxes.extend(AIS_REGION_BOXES[region])
    await ais_live_manager.configure(boxes)


@app.on_event("startup")
async def start_imd_coastal_weather_collection():
    """Refresh official coastal bulletins without delaying app startup."""
    imd_coastal_weather_manager.start()


@app.on_event("startup")
async def start_bmkg_marine_weather_collection():
    """Refresh official Indonesian maritime forecasts in the background."""
    bmkg_marine_weather_manager.start()


@app.on_event("startup")
async def start_sea_marine_weather_collection():
    """Refresh official Southeast Asian marine forecasts in the background."""
    sea_marine_weather_manager.start()


@app.on_event("startup")
async def start_major_port_weather_collection():
    """Refresh keyless official forecasts for major dry-bulk ports worldwide."""
    major_port_weather_manager.start()


@app.on_event("startup")
async def start_global_cyclone_collection():
    """Refresh the global GDACS tropical-cyclone layer in the background."""
    global_cyclone_manager.start()


@app.on_event("startup")
async def start_river_level_collection():
    """Refresh official navigable-waterway gauges without delaying startup."""
    river_level_manager.start()


@app.on_event("shutdown")
async def stop_ais_live_manager():
    await ais_live_manager.stop()


@app.on_event("shutdown")
async def stop_imd_coastal_weather_collection():
    await imd_coastal_weather_manager.stop()


@app.on_event("shutdown")
async def stop_bmkg_marine_weather_collection():
    await bmkg_marine_weather_manager.stop()


@app.on_event("shutdown")
async def stop_sea_marine_weather_collection():
    await sea_marine_weather_manager.stop()


@app.on_event("shutdown")
async def stop_major_port_weather_collection():
    await major_port_weather_manager.stop()


@app.on_event("shutdown")
async def stop_global_cyclone_collection():
    await global_cyclone_manager.stop()


@app.on_event("shutdown")
async def stop_river_level_collection():
    await river_level_manager.stop()


def _imd_weather_payload(day: int) -> Dict[str, Any]:
    payload = dict(imd_coastal_weather_manager.payload)
    fetched_at = payload.get("fetched_at")
    try:
        fetched_time = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        if fetched_time.tzinfo is None:
            fetched_time = fetched_time.replace(tzinfo=timezone.utc)
        refresh_age_hours = max(
            0.0,
            round((datetime.now(timezone.utc) - fetched_time.astimezone(timezone.utc)).total_seconds() / 3600, 1),
        )
    except (TypeError, ValueError):
        refresh_age_hours = None
    raw_rows = [
        row for row in payload.get("rows", [])
        if int(row.get("day") or 0) == day
    ]
    payload["rows"] = normalize_coastal_weather_rows(
        expand_imd_records(raw_rows), fetched_at=payload.get("fetched_at")
    )
    payload["day"] = day
    payload["last_error"] = imd_coastal_weather_manager.last_error
    payload["refresh_age_hours"] = refresh_age_hours
    payload["stale"] = bool(refresh_age_hours is not None and refresh_age_hours > 36)
    return payload


COASTAL_QUALITY_EXPORT_FIELDS = [
    "record_grain", "data_class", "source_authority", "fetched_at",
    "freshness_status", "freshness_age_hours", "data_confidence",
    "quality_score", "quality_flags", "port_operational_status",
    "port_status_reported", "port_status_source", "port_status_updated_at",
    "operational_notice", "forecast_24h", "forecast_72h",
]


def _write_weather_rows(writer: csv.DictWriter, rows: List[Dict[str, Any]]) -> None:
    for value in rows:
        row = dict(value)
        for field in ("quality_flags", "operational_impacts", "affected_countries", "affected_ports"):
            if isinstance(row.get(field), (list, dict)):
                row[field] = json.dumps(row[field], ensure_ascii=False)
        writer.writerow(row)


@app.get("/api/imd/coastal-weather")
async def imd_coastal_weather(day: int = Query(1, ge=1, le=5)):
    if not imd_coastal_weather_manager.payload:
        try:
            await imd_coastal_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(
                503, f"IMD coastal weather is temporarily unavailable: {exc}"
            ) from exc
    return _imd_weather_payload(day)


@app.post("/api/imd/coastal-weather/refresh")
async def refresh_imd_coastal_weather(
    day: int = Query(1, ge=1, le=5),
):
    try:
        await imd_coastal_weather_manager.refresh(force=True)
    except Exception as exc:
        imd_coastal_weather_manager.last_error = str(exc)
        if not imd_coastal_weather_manager.payload:
            raise HTTPException(
                503, f"IMD coastal weather refresh failed: {exc}"
            ) from exc
    return _imd_weather_payload(day)


@app.get("/api/imd/coastal-weather/export.csv")
async def export_imd_coastal_weather_csv():
    if not imd_coastal_weather_manager.payload:
        try:
            await imd_coastal_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(
                503, f"IMD coastal weather is temporarily unavailable: {exc}"
            ) from exc
    fields = [
        "provider", "provider_code", "country", "location_type", "location_id",
        "location_name", "zone_id", "zone_name", "marine_area", "forecast_basis",
        "latitude", "longitude", "day", "valid_date", "issued_at", "valid_from",
        "weather_condition", "weather_description", "rainfall_category",
        "wind_speed_min_kmph", "wind_speed_max_kmph", "gust_kmph",
        "wave_height_min_m", "wave_height_max_m", "severity", "summary",
        "weather_risk_score", "weather_risk_level", "operational_impacts",
        "risk_methodology", "source_issue_time", "source_url",
        *COASTAL_QUALITY_EXPORT_FIELDS,
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    rows = normalize_coastal_weather_rows(
        expand_imd_records(imd_coastal_weather_manager.payload.get("rows", [])),
        fetched_at=imd_coastal_weather_manager.payload.get("fetched_at"),
    )
    _write_weather_rows(writer, rows)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="imd_coastal_weather_latest.csv"'
            )
        },
    )


@app.get("/api/bmkg/marine-weather")
async def bmkg_marine_weather(hours: int = Query(0, ge=0, le=96)):
    if not bmkg_marine_weather_manager.payload:
        try:
            await bmkg_marine_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(
                503, f"BMKG maritime weather is temporarily unavailable: {exc}"
            ) from exc
    payload = bmkg_marine_weather_manager.selected_payload(hours)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    return payload


@app.post("/api/bmkg/marine-weather/refresh")
async def refresh_bmkg_marine_weather(hours: int = Query(0, ge=0, le=96)):
    try:
        await bmkg_marine_weather_manager.refresh(force=True)
    except Exception as exc:
        if not bmkg_marine_weather_manager.payload:
            raise HTTPException(
                503, f"BMKG maritime weather refresh failed: {exc}"
            ) from exc
    payload = bmkg_marine_weather_manager.selected_payload(hours)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    return payload


@app.get("/api/bmkg/marine-weather/export.csv")
async def export_bmkg_marine_weather_csv():
    if not bmkg_marine_weather_manager.payload:
        try:
            await bmkg_marine_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(
                503, f"BMKG maritime weather is temporarily unavailable: {exc}"
            ) from exc
    fields = [
        "location_type", "location_id", "location_name", "port_type", "water_code",
        "latitude", "longitude", "issued_at", "valid_from", "valid_to",
        "weather_condition", "warning_description", "wind_direction_from",
        "wind_direction_to", "wind_speed_min_kn", "wind_speed_max_kn",
        "wave_category", "wave_height_min_m", "wave_height_max_m",
        "current_direction_from", "current_direction_to", "current_speed_min_source",
        "current_speed_max_source", "current_speed_documented_unit", "visibility_source",
        "visibility_documented_unit", "temperature_min_c",
        "temperature_max_c", "humidity_min_pct", "humidity_max_pct",
        "low_tide_height_m", "low_tide_time", "high_tide_height_m",
        "high_tide_time", "severity", "source_url",
        *COASTAL_QUALITY_EXPORT_FIELDS,
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    _write_weather_rows(writer, normalize_coastal_weather_rows(
        bmkg_marine_weather_manager.payload.get("rows", []),
        fetched_at=bmkg_marine_weather_manager.payload.get("fetched_at"),
    ))
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                'attachment; filename="bmkg_marine_weather_latest.csv"'
            )
        },
    )


@app.get("/api/sea/marine-weather")
async def sea_marine_weather(
    country: Optional[str] = Query(None), hours: int = Query(0, ge=0, le=96),
):
    if not sea_marine_weather_manager.payload:
        try:
            await sea_marine_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"SEA maritime weather is temporarily unavailable: {exc}") from exc
    payload = sea_marine_weather_manager.selected_payload(country, hours)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    return payload


@app.post("/api/sea/marine-weather/refresh")
async def refresh_sea_marine_weather(
    country: Optional[str] = Query(None), hours: int = Query(0, ge=0, le=96),
):
    try:
        await sea_marine_weather_manager.refresh(force=True)
    except Exception as exc:
        if not sea_marine_weather_manager.payload:
            raise HTTPException(503, f"SEA maritime weather refresh failed: {exc}") from exc
    payload = sea_marine_weather_manager.selected_payload(country, hours)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    return payload


@app.get("/api/sea/marine-weather/export.csv")
async def export_sea_marine_weather_csv(country: Optional[str] = Query(None)):
    if not sea_marine_weather_manager.payload:
        try:
            await sea_marine_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"SEA maritime weather is temporarily unavailable: {exc}") from exc
    rows = [row for row in sea_marine_weather_manager.payload.get("rows", []) if not country or str(row.get("country", "")).casefold() == country.casefold()]
    rows = normalize_coastal_weather_rows(
        rows, fetched_at=sea_marine_weather_manager.payload.get("fetched_at")
    )
    fields = [
        "provider", "provider_code", "country", "location_type", "location_id",
        "location_name", "marine_area", "forecast_basis", "latitude", "longitude",
        "issued_at", "valid_from", "valid_to", "weather_condition",
        "weather_description", "warning_description", "wind_direction_from",
        "wind_direction_to", "wind_speed_min_kn", "wind_speed_max_kn",
        "wind_speed_min_kmph", "wind_speed_max_kmph", "wave_category",
        "wave_height_min_m", "wave_height_max_m", "temperature_min_c",
        "temperature_max_c", "humidity_min_pct", "humidity_max_pct", "severity",
        "visibility_source", "visibility_documented_unit", "offshore_marine_area",
        "weather_risk_score", "weather_risk_level", "operational_impacts", "risk_methodology",
        "source_url",
        *COASTAL_QUALITY_EXPORT_FIELDS,
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader(); _write_weather_rows(writer, rows)
    suffix = re.sub(r"[^a-z0-9]+", "_", (country or "all").lower()).strip("_")
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="sea_marine_weather_{suffix}.csv"'
    })


@app.get("/api/major-port-weather")
async def major_port_weather(
    country: Optional[str] = Query(None), region: Optional[str] = Query(None), hours: int = Query(0, ge=0, le=96),
):
    if not major_port_weather_manager.payload:
        try:
            await major_port_weather_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"Major-port weather is temporarily unavailable: {exc}") from exc
    payload = major_port_weather_manager.selected_payload(country, hours, region)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    return payload


@app.post("/api/major-port-weather/refresh")
async def refresh_major_port_weather(
    country: Optional[str] = Query(None), region: Optional[str] = Query(None), hours: int = Query(0, ge=0, le=96),
):
    try:
        await major_port_weather_manager.refresh(force=True)
    except Exception as exc:
        if not major_port_weather_manager.payload:
            raise HTTPException(503, f"Major-port weather refresh failed: {exc}") from exc
    payload = major_port_weather_manager.selected_payload(country, hours, region)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    return payload


@app.get("/api/weather/cyclones")
async def global_cyclones():
    if not global_cyclone_manager.payload:
        try:
            await global_cyclone_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"Global cyclone data is temporarily unavailable: {exc}") from exc
    payload = dict(global_cyclone_manager.payload)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    payload["last_error"] = global_cyclone_manager.last_error
    return payload


@app.post("/api/weather/cyclones/refresh")
async def refresh_global_cyclones():
    try:
        await global_cyclone_manager.refresh(force=True)
    except Exception as exc:
        if not global_cyclone_manager.payload:
            raise HTTPException(503, f"Global cyclone refresh failed: {exc}") from exc
    payload = dict(global_cyclone_manager.payload)
    payload["rows"] = normalize_coastal_weather_rows(
        payload.get("rows", []), fetched_at=payload.get("fetched_at")
    )
    payload["last_error"] = global_cyclone_manager.last_error
    return payload


@app.get("/api/weather/cyclones/export.csv")
async def export_global_cyclones_csv():
    if not global_cyclone_manager.payload:
        try:
            await global_cyclone_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"Global cyclone data is temporarily unavailable: {exc}") from exc
    fields = [
        "provider", "source_agency", "location_id", "location_name", "event_id",
        "alert_level", "basin", "ocean_or_sea", "latitude", "longitude",
        "issued_at", "valid_from", "valid_to", "weather_condition",
        "max_wind_kmph", "max_wind_kn", "movement_direction",
        "movement_bearing_deg", "affected_countries", "possible_landfall",
        "impact_radius_km", "affected_port_count", "affected_ports",
        "impact_methodology", "source_url", "forecast_disclaimer",
        *COASTAL_QUALITY_EXPORT_FIELDS,
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    _write_weather_rows(writer, normalize_coastal_weather_rows(
        global_cyclone_manager.payload.get("rows", []),
        fetched_at=global_cyclone_manager.payload.get("fetched_at"),
    ))
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="global_active_cyclones.csv"'
    })


@app.get("/api/coastal-weather/export.csv")
async def export_coastal_weather_csv(
    source: str = Query("all", pattern="^(india|indonesia|malaysia|thailand|philippines|singapore|brunei|cambodia|myanmar|vietnam|china|sea|australia|united_states|canada|japan|europe|south_america|africa|middle_east|major_ports|cyclones|all|both)$"),
):
    rows: List[Dict[str, Any]] = []
    if source in {"india", "both", "all"}:
        if not imd_coastal_weather_manager.payload:
            try:
                await imd_coastal_weather_manager.refresh(force=True)
            except Exception as exc:
                if source == "india":
                    raise HTTPException(503, f"IMD coastal weather is unavailable: {exc}") from exc
        rows.extend(expand_imd_records(imd_coastal_weather_manager.payload.get("rows", [])))
    if source in {"indonesia", "both", "all"}:
        if not bmkg_marine_weather_manager.payload:
            try:
                await bmkg_marine_weather_manager.refresh(force=True)
            except Exception as exc:
                if source == "indonesia" or not rows:
                    raise HTTPException(503, f"BMKG maritime weather is unavailable: {exc}") from exc
        rows.extend(bmkg_marine_weather_manager.payload.get("rows", []))
    sea_countries = {
        "malaysia": "Malaysia", "thailand": "Thailand",
        "philippines": "Philippines", "singapore": "Singapore",
        "brunei": "Brunei", "cambodia": "Cambodia", "myanmar": "Myanmar",
        "vietnam": "Vietnam", "china": "China",
    }
    if source in {"sea", "all"} or source in sea_countries:
        if not sea_marine_weather_manager.payload:
            try:
                await sea_marine_weather_manager.refresh(force=True)
            except Exception as exc:
                if not rows:
                    raise HTTPException(503, f"SEA maritime weather is unavailable: {exc}") from exc
        country = sea_countries.get(source)
        sea_rows = sea_marine_weather_manager.payload.get("rows", [])
        rows.extend(row for row in sea_rows if not country or row.get("country") == country)
    major_countries = {
        "australia": "Australia", "united_states": "United States",
        "canada": "Canada", "japan": "Japan",
    }
    major_regions = {
        "europe": "Europe", "south_america": "South America",
        "africa": "Africa", "middle_east": "Middle East",
    }
    if source in {"major_ports", "all"} or source in major_countries or source in major_regions:
        if not major_port_weather_manager.payload:
            try:
                await major_port_weather_manager.refresh(force=True)
            except Exception as exc:
                if not rows:
                    raise HTTPException(503, f"Major-port weather is unavailable: {exc}") from exc
        country = major_countries.get(source)
        region = major_regions.get(source)
        major_rows = major_port_weather_manager.payload.get("rows", [])
        rows.extend(row for row in major_rows if (not country or row.get("country") == country) and (not region or row.get("region") == region))
    if source in {"cyclones", "all"}:
        if not global_cyclone_manager.payload:
            try:
                await global_cyclone_manager.refresh(force=True)
            except Exception as exc:
                if not rows:
                    raise HTTPException(503, f"Global cyclone data is unavailable: {exc}") from exc
        rows.extend(global_cyclone_manager.payload.get("rows", []))
    rows = normalize_coastal_weather_rows(rows)
    fields = [
        "provider", "country", "region", "location_type", "location_id", "location_name",
        "latitude", "longitude", "issued_at", "valid_from", "valid_to",
        "weather_condition", "warning_description", "wind_direction_from",
        "wind_direction_to", "wind_speed_min_kn", "wind_speed_max_kn",
        "wind_speed_min_kmph", "wind_speed_max_kmph", "gust_kmph",
        "wave_category", "wave_height_min_m", "wave_height_max_m",
        "current_direction_from", "current_direction_to", "current_speed_min_source",
        "current_speed_max_source", "current_speed_documented_unit", "visibility_source",
        "visibility_documented_unit", "temperature_min_c",
        "temperature_max_c", "humidity_min_pct", "humidity_max_pct", "rainfall_mm",
        "low_tide_height_m", "low_tide_time", "high_tide_height_m",
        "high_tide_time", "marine_area", "forecast_basis", "severity", "summary", "source_url",
        "offshore_marine_area", "weather_risk_score", "weather_risk_level",
        "operational_impacts", "risk_methodology",
        "source_agency", "event_id", "alert_level", "basin", "ocean_or_sea",
        "max_wind_kmph", "max_wind_kn", "movement_direction",
        "movement_bearing_deg", "affected_countries", "possible_landfall",
        "impact_radius_km", "affected_port_count", "affected_ports",
        "impact_methodology", "forecast_disclaimer",
        "record_grain", "data_class", "source_authority", "fetched_at",
        "freshness_status", "freshness_age_hours", "data_confidence",
        "quality_score", "quality_flags", "port_operational_status",
        "port_status_reported", "port_status_source", "port_status_updated_at",
        "operational_notice", "forecast_24h", "forecast_72h",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in rows:
        row = dict(item)
        for field in ("affected_countries", "affected_ports", "operational_impacts", "quality_flags"):
            if isinstance(row.get(field), (list, dict)):
                row[field] = json.dumps(row[field], ensure_ascii=False)
        writer.writerow(row)
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="coastal_weather_latest.csv"'},
    )


async def _current_port_weather_rows(source: str) -> List[Dict[str, Any]]:
    """Return one current official forecast per port for report-style exports."""
    rows: List[Dict[str, Any]] = []
    if source in {"india", "both", "all"}:
        if not imd_coastal_weather_manager.payload:
            try:
                await imd_coastal_weather_manager.refresh(force=True)
            except Exception as exc:
                if source == "india":
                    raise HTTPException(503, f"IMD coastal weather is unavailable: {exc}") from exc
        if imd_coastal_weather_manager.payload:
            rows.extend(_imd_weather_payload(1).get("rows", []))
    if source in {"indonesia", "both", "all"}:
        if not bmkg_marine_weather_manager.payload:
            try:
                await bmkg_marine_weather_manager.refresh(force=True)
            except Exception as exc:
                if source == "indonesia" or not rows:
                    raise HTTPException(503, f"BMKG maritime weather is unavailable: {exc}") from exc
        if bmkg_marine_weather_manager.payload:
            rows.extend(bmkg_marine_weather_manager.selected_payload(0).get("rows", []))
    sea_countries = {
        "malaysia": "Malaysia", "thailand": "Thailand", "philippines": "Philippines",
        "singapore": "Singapore", "brunei": "Brunei", "cambodia": "Cambodia",
        "myanmar": "Myanmar", "vietnam": "Vietnam", "china": "China",
    }
    if source in {"sea", "all"} or source in sea_countries:
        if not sea_marine_weather_manager.payload:
            try:
                await sea_marine_weather_manager.refresh(force=True)
            except Exception as exc:
                if not rows:
                    raise HTTPException(503, f"SEA maritime weather is unavailable: {exc}") from exc
        if sea_marine_weather_manager.payload:
            rows.extend(sea_marine_weather_manager.selected_payload(sea_countries.get(source), 0).get("rows", []))
    major_countries = {
        "australia": "Australia", "united_states": "United States",
        "canada": "Canada", "japan": "Japan",
    }
    major_regions = {
        "europe": "Europe", "south_america": "South America",
        "africa": "Africa", "middle_east": "Middle East",
    }
    if source in {"major_ports", "all"} or source in major_countries or source in major_regions:
        if not major_port_weather_manager.payload:
            try:
                await major_port_weather_manager.refresh(force=True)
            except Exception as exc:
                if not rows:
                    raise HTTPException(503, f"Major-port weather is unavailable: {exc}") from exc
        if major_port_weather_manager.payload:
            rows.extend(major_port_weather_manager.selected_payload(
                major_countries.get(source), 0, major_regions.get(source)
            ).get("rows", []))
    return [
        row for row in normalize_coastal_weather_rows(rows)
        if row.get("location_type") == "port"
    ]


def _weather_report_wind(row: Dict[str, Any]) -> str:
    parts: List[str] = []
    low_kn, high_kn = row.get("wind_speed_min_kn"), row.get("wind_speed_max_kn")
    low_kmh, high_kmh = row.get("wind_speed_min_kmph"), row.get("wind_speed_max_kmph")
    if low_kn is not None or high_kn is not None:
        low, high = low_kn if low_kn is not None else high_kn, high_kn if high_kn is not None else low_kn
        parts.append(f"{low:g}-{high:g} kt" if low != high else f"{low:g} kt")
    elif low_kmh is not None or high_kmh is not None:
        low, high = low_kmh if low_kmh is not None else high_kmh, high_kmh if high_kmh is not None else low_kmh
        parts.append(f"{low:g}-{high:g} km/h" if low != high else f"{low:g} km/h")
    if row.get("gust_kmph") is not None:
        parts.append(f"gust {float(row['gust_kmph']):g} km/h")
    direction = row.get("wind_direction_from")
    direction_to = row.get("wind_direction_to")
    if direction:
        parts.append(f"from {direction}" + (f" to {direction_to}" if direction_to and direction_to != direction else ""))
    return "; ".join(parts)


def _weather_report_issue(row: Dict[str, Any]) -> str:
    messages: List[str] = []
    for field in ("warning_description", "operational_notice", "station_remark"):
        value = str(row.get(field) or "").strip()
        if value and value.casefold() not in {message.casefold() for message in messages}:
            messages.append(value)
    status = str(row.get("port_operational_status") or "Not reported")
    if row.get("port_status_reported") and status not in {"Open", "Not reported"}:
        messages.append(f"Port operating status: {status}")
    return "; ".join(messages)


def _weather_report_port_name(value: Any) -> str:
    name = str(value or "Unknown").strip()
    cleaned = re.sub(
        r"\s+\(?(?:(?:coal|dry[- ]?bulk|container|oil|lng)\s+terminal)\)?\s*$",
        "", name, flags=re.I,
    ).rstrip(" (")
    return cleaned or name


@app.get("/api/coastal-weather/port-report.xlsx")
async def export_coastal_port_report_xlsx(
    source: str = Query("all", pattern="^(india|indonesia|malaysia|thailand|philippines|singapore|brunei|cambodia|myanmar|vietnam|china|sea|australia|united_states|canada|japan|europe|south_america|africa|middle_east|major_ports|all|both)$"),
):
    """Download current port weather in the supplied eight-column report format."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    rows = await _current_port_weather_rows(source)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("country") or "Other"), []).append(row)
    workbook = Workbook()
    workbook.remove(workbook.active)
    headers = [
        "PORT NAME", "WEATHER", "CURRENTLY PORT CLOSE", "AVERAGE TEMP (℃)",
        "WIND FORCE", "SPECIAL ISSUE IN PORT", "WEATHER FORECAST (1 DAY)",
        "WEATHER FORECAST (3 DAYS)",
    ]
    navy = "1C294A"
    pale_blue = "EAF2F7"
    pale_red = "FCE8EA"
    thin = Side(style="thin", color="CBD5DC")
    for country in sorted(grouped):
        sheet_name = re.sub(r"[\\/*?:\[\]]+", " ", country)[:31] or "Ports"
        sheet = workbook.create_sheet(sheet_name)
        country_rows = sorted(grouped[country], key=lambda row: (0 if _weather_report_issue(row) else 1, str(row.get("location_name") or "")))
        sheet.merge_cells("A1:H1")
        sheet["A1"] = f"DAILY WEATHER REPORT FOR MAIN {country.upper()} PORTS"
        sheet["A1"].font = Font(bold=True, color="FFFFFF", size=13)
        sheet["A1"].fill = PatternFill("solid", fgColor=navy)
        sheet["A1"].alignment = Alignment(horizontal="center")
        sheet.merge_cells("A2:H2")
        sheet["A2"] = "Official forecast data · port closure is shown only when separately reported by a port or maritime authority"
        sheet["A2"].font = Font(italic=True, color="526572", size=9)
        sheet["A2"].alignment = Alignment(horizontal="center")
        for column, header in enumerate(headers, 1):
            cell = sheet.cell(3, column, header)
            cell.font = Font(bold=True, color="FFFFFF", size=9)
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for index, row in enumerate(country_rows, 4):
            minimum = row.get("temperature_min_c")
            maximum = row.get("temperature_max_c")
            temperature = None
            if minimum is not None or maximum is not None:
                values = [float(value) for value in (minimum, maximum) if value is not None]
                temperature = round(sum(values) / len(values), 1)
            status = str(row.get("port_operational_status") or "Not reported")
            closure = "YES" if status == "Closed" else "NO" if status == "Open" else status.upper() if status == "Restricted" else "Not reported"
            issue = _weather_report_issue(row)
            one_day = row.get("forecast_24h") or row.get("weather_description") or row.get("summary") or ""
            values = [
                _weather_report_port_name(row.get("location_name")), row.get("weather_condition") or row.get("rainfall_category"),
                closure, temperature, _weather_report_wind(row), issue,
                one_day, row.get("forecast_72h") or "",
            ]
            for column, value in enumerate(values, 1):
                cell = sheet.cell(index, column, value)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
                cell.fill = PatternFill("solid", fgColor=pale_red if issue else (pale_blue if index % 2 == 0 else "FFFFFF"))
            if temperature is not None:
                sheet.cell(index, 4).number_format = "0.0"
        sheet.freeze_panes = "A4"
        sheet.auto_filter.ref = f"A3:H{max(3, sheet.max_row)}"
        sheet.row_dimensions[1].height = 24
        sheet.row_dimensions[3].height = 32
        widths = [24, 20, 20, 18, 25, 48, 52, 52]
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[chr(64 + column)].width = width
    if not grouped:
        sheet = workbook.create_sheet("No current port data")
        sheet["A1"] = "No current port-weather records are available for this selection."
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    suffix = re.sub(r"[^a-z0-9]+", "_", source.lower()).strip("_")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="coastal_port_weather_{suffix}.xlsx"'},
    )


@app.get("/api/coastal-weather/sources")
async def coastal_weather_sources():
    """Official-source inventory, including integrations still awaiting adapters."""
    live = sum(1 for item in COASTAL_WEATHER_SOURCE_CATALOG if str(item.get("integration", "")).startswith("live"))
    return {
        "sources": COASTAL_WEATHER_SOURCE_CATALOG,
        "count": len(COASTAL_WEATHER_SOURCE_CATALOG),
        "live_count": live,
        "methodology": (
            "Weather comes from the official meteorological authority. Port closure or "
            "restriction status is shown only when separately reported by a port or maritime authority."
        ),
    }


def _river_source_inventory(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prefix_to_source = {
        "noaa-": "noaa-nwps", "ana-": "ana-amazon",
        "pegel-": "pegelonline", "sihka-": "indonesia-sihka",
        "acp-": "acp-gatun",
        "china-": "three-gorges-watch",
    }
    active = {
        source_id
        for row in rows
        for prefix, source_id in prefix_to_source.items()
        if str(row.get("id") or "").startswith(prefix)
    }
    inventory = []
    for definition in SOURCE_CATALOG:
        item = dict(definition)
        item["integration_status"] = item.get("status")
        if item.get("status") == "connected":
            item["status"] = (
                "active" if item.get("id") in active else "no_current_record"
            )
            item["availability"] = (
                "Current records loaded" if item.get("id") in active
                else "Connector configured; no current record loaded"
            )
        else:
            item["availability"] = "Not connected to the current dashboard feed"
        inventory.append(item)
    return inventory


@app.get("/api/river-levels")
async def river_levels(
    waterway: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    waterbody_type: Optional[str] = Query(None, pattern="^(river|reservoir)$"),
    status: Optional[str] = Query(None),
    comparison_status: Optional[str] = Query(None, pattern="^(below_normal|normal|above_normal|unavailable)$"),
    history_limit: int = Query(120, ge=0, le=500),
):
    if not river_level_manager.payload:
        try:
            await river_level_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"Official river-level sources are temporarily unavailable: {exc}") from exc
    payload = dict(river_level_manager.payload)
    rows = list(payload.get("rows", []))
    if waterway:
        needle = waterway.casefold()
        rows = [row for row in rows if needle in str(row.get("waterbody") or "").casefold() or needle in str(row.get("basin") or "").casefold()]
    if waterbody_type:
        rows = [row for row in rows if row.get("waterbody_type") == waterbody_type]
    if country:
        rows = [row for row in rows if row.get("country") == country]
    if status:
        rows = [row for row in rows if row.get("status") == status]
    if comparison_status:
        rows = [row for row in rows if row.get("comparison_status") == comparison_status]
    compact_rows = []
    for source_row in rows:
        row = dict(source_row)
        history = list(row.get("history") or [])
        row["history_total_count"] = len(history)
        row["history"] = history[-history_limit:] if history_limit else []
        compact_rows.append(row)
    payload["rows"] = compact_rows
    payload["history_limit"] = history_limit
    payload["sources"] = _river_source_inventory(rows)
    payload["connected_source_count"] = sum(
        item["status"] == "active" for item in payload["sources"]
    )
    payload["last_error"] = river_level_manager.last_error
    return payload


@app.post("/api/river-levels/refresh")
async def refresh_river_levels():
    try:
        await river_level_manager.refresh(force=True)
    except Exception as exc:
        if not river_level_manager.payload:
            raise HTTPException(503, f"Official river-level refresh failed: {exc}") from exc
    payload = dict(river_level_manager.payload)
    compact_rows = []
    for source_row in payload.get("rows", []):
        row = dict(source_row)
        history = list(row.get("history") or [])
        row["history_total_count"] = len(history)
        row["history"] = history[-120:]
        compact_rows.append(row)
    payload["rows"] = compact_rows
    payload["history_limit"] = 120
    payload["sources"] = _river_source_inventory(
        list(river_level_manager.payload.get("rows", []))
    )
    payload["connected_source_count"] = sum(
        item["status"] == "active" for item in payload["sources"]
    )
    payload["last_error"] = river_level_manager.last_error
    return payload


@app.get("/api/river-levels/sources")
async def river_level_sources():
    rows = list(river_level_manager.payload.get("rows", []))
    sources = _river_source_inventory(rows)
    return {"sources": sources, "count": len(sources)}


@app.get("/api/river-levels/export.csv")
async def export_river_levels_csv():
    if not river_level_manager.payload:
        try:
            await river_level_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"Official river-level sources are temporarily unavailable: {exc}") from exc
    content = export_rows_csv(river_level_manager.payload.get("rows", []))
    return StreamingResponse(iter([content]), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="navigable_river_reservoir_levels.csv"'
    })


@app.get("/api/river-levels/export.xlsx")
async def export_river_levels_excel(
    waterway: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    waterbody_type: Optional[str] = Query(None, pattern="^(river|reservoir)$"),
    comparison_status: Optional[str] = Query(None, pattern="^(below_normal|normal|above_normal|unavailable)$"),
):
    if not river_level_manager.payload:
        try:
            await river_level_manager.refresh(force=True)
        except Exception as exc:
            raise HTTPException(503, f"Official river-level sources are temporarily unavailable: {exc}") from exc
    rows = list(river_level_manager.payload.get("rows", []))
    if waterway:
        rows = [row for row in rows if row.get("waterbody") == waterway]
    if country:
        rows = [row for row in rows if row.get("country") == country]
    if waterbody_type:
        rows = [row for row in rows if row.get("waterbody_type") == waterbody_type]
    if comparison_status:
        rows = [row for row in rows if row.get("comparison_status") == comparison_status]
    content = export_river_levels_xlsx(river_level_manager.payload, rows)
    return StreamingResponse(iter([content]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={
        "Content-Disposition": 'attachment; filename="navigable_river_reservoir_levels.xlsx"'
    })


@app.get("/api/ais/status")
async def ais_status():
    with sqlite3.connect(AIS_TRAIL_DB_PATH) as db:
        observations = db.execute(
            "SELECT COUNT(*) FROM ais_observations"
        ).fetchone()[0]
        vessels = db.execute(
            "SELECT COUNT(DISTINCT mmsi) FROM ais_observations"
        ).fetchone()[0]
    return {
        "configured": bool(AISSTREAM_API_KEY),
        "provider": "AISStream.io",
        "background_collection": bool(
            AISSTREAM_API_KEY and ais_live_manager.task
        ),
        "connected": ais_live_manager.connected,
        "last_message_at": ais_live_manager.last_message_at,
        "last_error": ais_live_manager.last_error,
        "trail_observations": observations,
        "trail_vessels": vessels,
    }


@app.post("/api/ais/snapshot")
async def ais_snapshot(req: AisSnapshotRequest):
    if not AISSTREAM_API_KEY:
        raise HTTPException(
            503,
            "AIS is not configured. Add AISSTREAM_API_KEY to the server environment.",
        )
    south = max(-90.0, min(90.0, float(req.south)))
    north = max(-90.0, min(90.0, float(req.north)))
    west = max(-180.0, min(180.0, float(req.west)))
    east = max(-180.0, min(180.0, float(req.east)))
    if south >= north:
        raise HTTPException(400, "AIS map bounds are invalid")
    current_boxes = (
        [[[south, west], [north, east]]]
        if west <= east
        else [[[south, west], [north, 180.0]], [[south, -180.0], [north, east]]]
    )
    selected_regions = [
        str(region)
        for region in (req.regions or [])
        if str(region) == "current" or str(region) in AIS_REGION_BOXES
    ]
    if "world" in selected_regions:
        boxes = AIS_REGION_BOXES["world"]
    elif selected_regions:
        boxes = []
        for region in selected_regions:
            boxes.extend(
                current_boxes if region == "current" else AIS_REGION_BOXES[region]
            )
    else:
        boxes = current_boxes
    query = _ais_text(req.query)
    mmsis = [
        str(value)
        for value in (req.mmsis or [])
        if len(str(value)) == 9 and str(value).isdigit()
    ][:50]
    digits = "".join(char for char in query if char.isdigit())
    if len(digits) == 9:
        if digits not in mmsis:
            mmsis.append(digits)
        boxes = [[[-90.0, -180.0], [90.0, 180.0]]]
    elif mmsis:
        boxes = [[[-90.0, -180.0], [90.0, 180.0]]]
    await ais_live_manager.configure(boxes, mmsis=mmsis)
    await ais_live_manager.wait_for_data(
        timeout=min(float(req.timeout_sec or 2.0), 3.0)
    )
    vessels = ais_live_manager.snapshot(
        south,
        north,
        west,
        east,
        query or None,
        mmsis,
        max(1, min(int(req.max_vessels), 1000)),
        boxes=boxes,
    )
    if ais_live_manager.last_error and not vessels:
        raise HTTPException(
            502, f"AIS live feed error: {ais_live_manager.last_error}"
        )
    return {
        "vessels": vessels,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "connected": ais_live_manager.connected,
        "cached_vessels": len(ais_live_manager.vessels),
    }


@app.get("/api/ais/trail/{mmsi}")
async def ais_trail(
    mmsi: str,
    hours: int = Query(default=168, ge=1, le=24 * 90),
    limit: int = Query(default=1000, ge=2, le=5000),
):
    digits = "".join(char for char in str(mmsi) if char.isdigit())
    if len(digits) != 9:
        raise HTTPException(400, "A valid 9-digit MMSI is required")
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with sqlite3.connect(AIS_TRAIL_DB_PATH) as db:
        rows = db.execute(
            """
            SELECT observed_at, latitude, longitude, sog_kn, cog_deg, heading_deg
            FROM ais_observations
            WHERE mmsi = ? AND observed_at >= ?
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            (digits, cutoff, limit),
        ).fetchall()
    points = [
        {
            "time": row[0],
            "lat": row[1],
            "lon": row[2],
            "sog_kn": row[3],
            "cog": row[4],
            "heading": row[5],
        }
        for row in reversed(rows)
    ]
    return {"mmsi": digits, "hours": hours, "points": points}

@app.post("/api/vessel/track")
async def track_vessels(req: VesselTrackRequest):
    raw_ids = []
    for x in req.ids or []:
        for part in str(x).replace(";", ",").split(","):
            p = part.strip()
            if p: raw_ids.append(p)
    mmsis, imos = [], []
    for p in raw_ids:
        digits = "".join(c for c in p if c.isdigit())
        if len(digits) == 9: mmsis.append(digits)
        elif len(digits) == 7: imos.append(digits)
        elif len(digits) > 7: imos.append(digits[:7])
    if not mmsis and not imos:
        raise HTTPException(400, "Provide at least one 9-digit MMSI or 7-digit IMO")
    result = await _sample_ais_for_ships(mmsis, imos, req.timeout_sec or 25.0)
    if result.get("error") and not result.get("vessels"):
        raise HTTPException(502, result["error"])
    return {"vessels": result.get("vessels", []), "queried_mmsi": result.get("queried_mmsi", []), "queried_imo": result.get("queried_imo", []), "error": result.get("error")}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    original_name = Path(file.filename or "upload")
    ext = original_name.suffix.lower()
    if ext not in {".xlsx", ".xls", ".csv", ".json"}:
        raise HTTPException(400, "Supported: Excel, CSV, JSON")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 50 MB)")
    uid = uuid.uuid4().hex[:8]
    safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", original_name.stem).strip("_")
    safe_name = f"{safe_stem or 'upload'}_{uid}"
    out_path = UPLOAD_DIR / f"{safe_name}.csv"
    try:
        if ext in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl", dtype=str)
        elif ext == ".csv":
            df = pd.read_csv(io.BytesIO(content), dtype=str)
        else:
            df = pd.read_json(io.BytesIO(content))
        df.columns = [str(c).strip() for c in df.columns]
        df.to_csv(out_path, index=False)
        user_datasets[safe_name] = out_path
        con.execute(f"CREATE OR REPLACE TABLE user_{safe_name.replace('-','_')} AS SELECT * FROM read_csv_auto('{out_path}')")
        return {"id": f"user_{safe_name}", "name": safe_name, "rows": len(df), "columns": list(df.columns), "message": f"Uploaded as user_{safe_name}"}
    except Exception as e:
        raise HTTPException(400, f"Parse error: {e}")

@app.get("/api/export/{tracker_id}")
async def export_excel(tracker_id: str, status: Optional[str] = None, country: Optional[str] = None):
    if tracker_id not in TRACKERS and not tracker_id.startswith("user_"):
        raise HTTPException(404, "Unknown tracker")
    where, params = _filters(status, country, None, None, None, None)
    try:
        df = con.execute(f"SELECT * FROM {tracker_id}{where}", params).fetchdf()
    except Exception as e:
        raise HTTPException(400, str(e))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    buf.seek(0)
    filename = f"{tracker_id}_export_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.post("/api/chat")
async def chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")
    xai_key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    reply = None
    if not reply and xai_key:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post("https://api.x.ai/v1/chat/completions",
                    json={"model": "grok-3", "messages": [{"role": "user", "content": message}], "temperature": 0.2},
                    headers={"Authorization": f"Bearer {xai_key}"})
                if r.status_code == 200:
                    reply = r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            reply = f"(Grok API error: {e})"
    if not reply:
        reply = "Ask about coal plants, terminals, ports, routes, ECA, bunker or weather."
    return {"reply": reply, "sql_result": None, "engine": "heuristic"}

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "trackers": list(TRACKERS.keys()),
        "ports": ports.summary,
        "ais_configured": bool(AISSTREAM_API_KEY),
        "version": "4.0.0",
        "storage": {
            "path": str(UPLOAD_DIR),
            "external_path_configured": bool(os.getenv("HRP_STORAGE_DIR")),
            "persistence_note": (
                "Persistent only when this path is backed by a mounted disk or durable volume."
            ),
        },
        "admin_write_protection": {
            "required": REQUIRE_ADMIN_TOKEN,
            "configured": bool(ADMIN_API_TOKEN),
        },
        "ais_retention_days": AIS_RAW_RETENTION_DAYS,
        "time": datetime.utcnow().isoformat(),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
