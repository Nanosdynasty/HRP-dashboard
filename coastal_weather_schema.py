"""Shared coastal-weather schema, provenance and data-quality rules.

Meteorological agencies normally publish weather for a station or marine area.
Port authorities publish operational restrictions separately.  This module keeps
those concepts separate so an absent closure notice is never rendered as "Open".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional


COASTAL_WEATHER_SOURCE_CATALOG: List[Dict[str, Any]] = [
    {"country": "China", "weather_agency": "CMA / National Meteorological Centre", "weather_url": "https://www.nmc.cn/publish/marine/", "operations_agency": "China Maritime Safety Administration", "operations_url": "https://www.msa.gov.cn/", "integration": "live", "coverage": "port-mapped coastal and offshore forecast"},
    {"country": "India", "weather_agency": "India Meteorological Department", "weather_url": "https://mausam.imd.gov.in/responsive/coastal_forecast.php", "operations_agency": "Directorate General of Shipping / port authorities", "operations_url": "https://www.dgshipping.gov.in/", "integration": "live", "coverage": "coastal areas mapped to trading ports"},
    {"country": "Indonesia", "weather_agency": "BMKG Maritime", "weather_url": "https://maritim.bmkg.go.id/", "operations_agency": "Directorate General of Sea Transportation / port authorities", "operations_url": "https://hubla.dephub.go.id/", "integration": "live", "coverage": "port and marine-area forecast"},
    {"country": "Malaysia", "weather_agency": "METMalaysia", "weather_url": "https://www.met.gov.my/forecast/marine/shipping/", "operations_agency": "Marine Department Malaysia", "operations_url": "https://www.marine.gov.my/", "integration": "live", "coverage": "shipping areas mapped to ports"},
    {"country": "Thailand", "weather_agency": "Thai Meteorological Department", "weather_url": "https://www.tmd.go.th/en/weather/ship-forecast", "operations_agency": "Marine Department Thailand", "operations_url": "https://www.md.go.th/", "integration": "live", "coverage": "shipping areas mapped to ports"},
    {"country": "Philippines", "weather_agency": "PAGASA", "weather_url": "https://bagong.pagasa.dost.gov.ph/marine/gale-warning", "operations_agency": "Philippine Ports Authority / Coast Guard", "operations_url": "https://www.ppa.com.ph/", "integration": "live-warning", "coverage": "official gale-warning areas mapped to ports"},
    {"country": "Singapore", "weather_agency": "Meteorological Service Singapore", "weather_url": "https://www.weather.gov.sg/weather-forecast-24hrforecast/", "operations_agency": "Maritime and Port Authority of Singapore", "operations_url": "https://www.mpa.gov.sg/", "integration": "live", "coverage": "regional forecast mapped to Singapore port waters"},
    {"country": "Vietnam", "weather_agency": "National Center for Hydro-Meteorological Forecasting", "weather_url": "https://nchmf.gov.vn/", "operations_agency": "Vietnam Maritime Administration", "operations_url": "https://vinamarine.gov.vn/", "integration": "live", "coverage": "marine areas mapped to ports"},
    {"country": "Brunei", "weather_agency": "Brunei Darussalam Meteorological Department / METMalaysia regional context", "weather_url": "https://www.met.gov.bn/", "operations_agency": "Maritime and Port Authority of Brunei Darussalam", "operations_url": "https://mpabd.gov.bn/", "integration": "live-regional", "coverage": "official regional marine forecast mapped to Muara; Brunei adapter pending"},
    {"country": "Cambodia", "weather_agency": "Ministry of Water Resources and Meteorology / TMD Gulf context", "weather_url": "https://www.mowram.gov.kh/", "operations_agency": "Sihanoukville Autonomous Port", "operations_url": "https://www.pas.gov.kh/", "integration": "live-regional", "coverage": "official Gulf forecast mapped to Sihanoukville; Cambodia adapter pending"},
    {"country": "Myanmar", "weather_agency": "Department of Meteorology and Hydrology / TMD Andaman context", "weather_url": "https://www.moezala.gov.mm/", "operations_agency": "Myanma Port Authority", "operations_url": "https://www.mpa.gov.mm/", "integration": "live-regional", "coverage": "official Andaman forecast mapped to Yangon and Thilawa; Myanmar adapter pending"},
    {"country": "Timor-Leste", "weather_agency": "Direção Nacional de Meteorologia e Geofísica", "weather_url": "https://www.gov.tl/", "operations_agency": "Port Authority of Timor-Leste", "operations_url": "https://www.aportil.gov.tl/", "integration": "catalogued", "coverage": "official stable marine feed not yet identified"},
    {"country": "Japan", "weather_agency": "Japan Meteorological Agency", "weather_url": "https://www.jma.go.jp/bosai/forecast/", "operations_agency": "Japan Coast Guard", "operations_url": "https://www.kaiho.mlit.go.jp/e/index_e.htm", "integration": "live", "coverage": "prefectural coastal wind, weather and wave forecasts mapped to major dry-bulk ports"},
    {"country": "South Korea", "weather_agency": "Korea Meteorological Administration", "weather_url": "https://www.weather.go.kr/w/index.do", "operations_agency": "Ministry of Oceans and Fisheries", "operations_url": "https://www.mof.go.kr/en/index.do", "integration": "catalogued", "coverage": "official marine forecast; adapter pending"},
    {"country": "Australia", "weather_agency": "Bureau of Meteorology", "weather_url": "https://www.bom.gov.au/marine/", "operations_agency": "Australian Maritime Safety Authority / state ports", "operations_url": "https://www.amsa.gov.au/", "integration": "live", "coverage": "official coastal-waters wind, sea, swell and weather forecasts mapped to major dry-bulk ports"},
    {"country": "United States", "weather_agency": "NOAA / National Weather Service", "weather_url": "https://www.weather.gov/marine/", "operations_agency": "United States Coast Guard", "operations_url": "https://homeport.uscg.mil/", "integration": "live", "coverage": "official coastal marine grids and active alerts at major dry-bulk port approaches"},
    {"country": "Canada", "weather_agency": "Environment and Climate Change Canada", "weather_url": "https://weather.gc.ca/marine/index_e.html", "operations_agency": "Canadian Coast Guard", "operations_url": "https://www.ccg-gcc.gc.ca/", "integration": "live", "coverage": "official marine forecasts, waves and warnings mapped to major dry-bulk ports"},
    {"country": "New Zealand", "weather_agency": "MetService", "weather_url": "https://www.metservice.com/marine", "operations_agency": "Maritime New Zealand", "operations_url": "https://www.maritimenz.govt.nz/", "integration": "catalogued", "coverage": "official marine forecasts and warnings; adapter pending"},
    {"country": "Brazil", "weather_agency": "Brazilian Navy Hydrographic Center", "weather_url": "https://www.marinha.mil.br/chm/dados-do-smm-meteoromarinha", "operations_agency": "ANTAQ / port authorities", "operations_url": "https://www.gov.br/antaq/", "integration": "catalogued", "coverage": "official METAREA V and coastal products; adapter pending"},
    {"country": "Pakistan", "weather_agency": "Pakistan Meteorological Department", "weather_url": "https://www.pmd.gov.pk/", "operations_agency": "Karachi Port, Port Qasim and Gwadar authorities", "operations_url": "https://kpt.gov.pk/", "integration": "catalogued", "coverage": "official marine products and separate port notices; adapter pending"},
    {"country": "Bangladesh", "weather_agency": "Bangladesh Meteorological Department", "weather_url": "https://www.bmd.gov.bd/", "operations_agency": "Chattogram / Mongla port authorities", "operations_url": "https://cpa.gov.bd/", "integration": "catalogued", "coverage": "official maritime warnings and separate port notices; adapter pending"},
    {"country": "Sri Lanka", "weather_agency": "Department of Meteorology Sri Lanka", "weather_url": "https://www.meteo.gov.lk/", "operations_agency": "Sri Lanka Ports Authority", "operations_url": "https://www.slpa.lk/", "integration": "catalogued", "coverage": "official sea-area forecast; adapter pending"},
    {"country": "United Arab Emirates", "weather_agency": "National Center of Meteorology", "weather_url": "https://www.ncm.ae/", "operations_agency": "National and emirate port authorities", "operations_url": "https://www.moei.gov.ae/", "integration": "catalogued", "coverage": "official marine forecast; adapter pending"},
    {"country": "South Africa", "weather_agency": "South African Weather Service", "weather_url": "https://www.weathersa.co.za/", "operations_agency": "Transnet National Ports Authority", "operations_url": "https://www.transnetnationalportsauthority.net/", "integration": "catalogued", "coverage": "official marine forecast plus separate port notices; adapter pending"},
    {"country": "Global oceans", "weather_agency": "WMO WWMIWS / METAREA coordinators", "weather_url": "https://wwmiws.wmo.int/", "operations_agency": "Relevant national port authority", "operations_url": None, "integration": "catalogued-fallback", "coverage": "official high-seas warnings; not port operating status"},
]


def _parse_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _port_status(row: Dict[str, Any]) -> tuple[str, bool]:
    raw = row.get("port_operational_status") or row.get("currently_port_close") or row.get("port_status")
    if raw is None or str(raw).strip().casefold() in {"", "unknown", "n/a", "na", "not available", "not reported"}:
        return "Not reported", False
    text = str(raw).strip()
    lowered = text.casefold()
    if lowered in {"yes", "closed", "close", "closure"} or "closed" in lowered:
        return "Closed", True
    if any(token in lowered for token in ("restrict", "limited", "suspend", "condition zulu", "condition yankee", "condition x-ray")):
        return "Restricted", True
    if lowered in {"no", "open", "normal", "operational"}:
        return "Open", True
    return text, True


def normalize_coastal_weather_row(
    value: Dict[str, Any], *, fetched_at: Any = None, now: Optional[datetime] = None
) -> Dict[str, Any]:
    row = dict(value)
    now = now or datetime.now(timezone.utc)
    status, status_reported = _port_status(row)
    row["port_operational_status"] = status
    row["port_status_reported"] = status_reported
    row.setdefault("port_status_source", None)
    row.setdefault("port_status_updated_at", None)

    location_type = str(row.get("location_type") or "water")
    basis = str(row.get("forecast_basis") or "").casefold()
    provider_code = str(row.get("provider_code") or "").casefold()
    if location_type == "storm":
        data_class = "official_warning"
        grain = "cyclone_alert"
    elif location_type == "port":
        grain = "port_forecast"
        if provider_code == "bmkg" and "mapped" not in basis and "area" not in basis:
            data_class = "official_port_forecast"
        else:
            data_class = "official_area_mapped_forecast"
    else:
        grain = "marine_area_forecast"
        data_class = "official_area_forecast"
    row["record_grain"] = grain
    row["data_class"] = data_class
    row["source_authority"] = row.get("source_agency") or row.get("provider")
    row["fetched_at"] = row.get("fetched_at") or fetched_at

    issued_time = _parse_time(row.get("issued_at")) or _parse_time(fetched_at) or _parse_time(row.get("valid_from"))
    valid_to = _parse_time(row.get("valid_to"))
    age_hours = max(0.0, round((now - issued_time.astimezone(timezone.utc)).total_seconds() / 3600, 1)) if issued_time else None
    row["freshness_age_hours"] = age_hours
    expired = bool(valid_to and now > valid_to.astimezone(timezone.utc) + timedelta(hours=6))
    row["freshness_status"] = "unknown" if age_hours is None else ("stale" if expired or age_hours > 36 else "current")

    quality_flags: List[str] = []
    if not row.get("source_url"):
        quality_flags.append("missing_source_url")
    if not row.get("issued_at"):
        quality_flags.append("missing_issue_time")
    if not row.get("valid_from") and not row.get("valid_date"):
        quality_flags.append("missing_valid_time")
    if location_type == "port" and data_class == "official_area_mapped_forecast":
        quality_flags.append("area_forecast_mapped_to_port")
    if location_type == "port" and not status_reported:
        quality_flags.append("port_status_not_reported")
    if row["freshness_status"] == "stale":
        quality_flags.append("stale_forecast")
    row["quality_flags"] = quality_flags
    score = max(0, 100 - 15 * len([flag for flag in quality_flags if flag != "port_status_not_reported"]) - (10 if "port_status_not_reported" in quality_flags else 0))
    row["quality_score"] = score
    row["data_confidence"] = "High" if score >= 85 else ("Medium" if score >= 65 else "Low")

    row.setdefault("operational_notice", row.get("station_remark") or row.get("warning_description"))
    row.setdefault("forecast_24h", row.get("forecast_1_day"))
    row.setdefault("forecast_72h", row.get("forecast_3_days"))
    return row


def normalize_coastal_weather_rows(
    rows: Iterable[Dict[str, Any]], *, fetched_at: Any = None, now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    return [normalize_coastal_weather_row(row, fetched_at=fetched_at, now=now) for row in rows]
