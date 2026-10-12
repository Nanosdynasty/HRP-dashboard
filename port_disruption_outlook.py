"""Evidence-scoped dry-bulk planning outlook. No forecast creates operating status."""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import pycountry
from shapely.geometry import Point, shape
from berth_details import berth_detail_for_port
from port_cargo_profiles import cargo_profile
from coastal_weather_schema import _parse_time, normalize_coastal_weather_rows, COASTAL_WEATHER_SOURCE_CATALOG
from major_port_weather import PORTS

OPERATIONS = ("loading/discharge", "crane operations", "berthing", "pilotage", "anchorage", "approach")
ASSESSMENTS = ("Confirmed restriction", "Published limit exceeded", "Weather watch", "Not assessed", "No trigger identified")
WINDOWS = {"0-24": (0, 24), "24-72": (24, 72)}
RULE_VERSION = "screening-2026-09-28-v1"
# Reviewed aliases only. Catalog search_aliases contain unrelated terminals and
# must never be used as an operational join. Composite regions are not aliases.
ALIASES = {
    ("IN", "paradeep"): "paradip", ("IN", "chennai"): "chennai madras",
    ("IN", "madras"): "chennai madras", ("IN", "visakhapatnam"): "vishakhapatnam",
    ("IN", "vizag"): "vishakhapatnam", ("IN", "deendayal kandla"): "kandla",
    ("IN", "mumbai"): "mumbai bombay", ("IN", "jnpa nhava sheva"): "jawaharlal nehru port nhava shiva",
    ("IN", "kakinada"): "kakinada bay", ("IN", "kochi"): "kochi cochin",
    ("IN", "cochin"): "kochi cochin", ("IN", "v o chidambaranar tuticorin"): "tuticorin",
    ("IN", "karaikal"): "karaikal port", ("IN", "haldia"): "haldia port",
    ("IN", "kolkata"): "calcutta",
    ("AU", "cape lambert"): "port walcott", ("CA", "quebec"): "quebec",
    ("ZA", "richards bay coal terminal"): "richards bay",
    ("ID", "pelabuhan tanjung priok"): "jakarta",
    ("ID", "pelabuhan tanjung perak surabaya"): "surabaya",
    ("ID", "pelabuhan tanjung emas"): "semarang",
    ("ID", "pelabuhan cirebon cirebon"): "cirebon",
}


def key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]+", " ", text.encode("ascii", "ignore").decode().lower()).strip()


@lru_cache(maxsize=150)
def country_code(value: str) -> str:
    if len(value) == 2:
        return value.upper()
    try:
        return pycountry.countries.lookup(value).alpha_2
    except LookupError:
        return {"South Korea": "KR", "Vietnam": "VN"}.get(value, "")


class PortMatcher:
    def __init__(self, ports: list[dict]):
        self.index: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for port in ports:
            self.index[(country_code(str(port.get("country", ""))), key(port.get("name")))].append(port)

    def match(self, name: str, country: str) -> dict | None:
        code, name_key = country_code(country), key(name)
        name_key = ALIASES.get((code, name_key), name_key)
        candidates = self.index.get((code, name_key), [])
        return candidates[0] if len(candidates) == 1 else None


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def wind_kn(row: dict) -> float | None:
    value = number(row.get("wind_speed_max_kn"))
    if value is not None:
        return value
    for field, factor in (("wind_speed_max_kmph", 1 / 1.852), ("wind_speed_max_ms", 1.943844), ("wind_speed_max_mph", 0.868976)):
        value = number(row.get(field))
        if value is not None:
            return value * factor
    return None


def rain_signal(row: dict) -> bool | None:
    amount = number(row.get("rainfall_mm"))
    if amount is not None:
        return amount > 0
    text = str(row.get("rainfall_category") or row.get("weather_condition") or "").lower()
    text = re.sub(r"\b(?:no|without|nil|zero)\s+(?:significant\s+)?(?:rain(?:fall)?|precipitation|showers)\b|\brain(?:fall)?\s*[:=-]\s*(?:nil|none|0)\b", "", text)
    if re.search(r"\brain(?:fall|y)?\b|showers?|thunderstorms?|drizzle", text) or (row.get("rainfall_category") and re.fullmatch(r"heavy|moderate|light|very heavy", text)):
        return True
    if text != str(row.get("rainfall_category") or row.get("weather_condition") or "").lower():
        return False
    if re.search(r"sunny|fine|dry|clear|cloudy|no rain|nil", str(row.get("weather_condition") or row.get("rainfall_category") or ""), re.I):
        return False
    return None


def interval(row: dict) -> tuple[datetime, datetime, str] | None:
    start, end = _parse_time(row.get("valid_from")), _parse_time(row.get("valid_to"))
    resolution = "Published forecast interval"
    if not start:
        # IMD daily bulletins state a local calendar date, not an hourly forecast.
        try:
            start = datetime.strptime(str(row.get("valid_date") or row.get("valid_from")), "%d.%m.%Y").replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            resolution = "Daily coastal bulletin (IST calendar day)"
        except ValueError:
            return None
    if not end and row.get("provider_code") == "imd":
        end = start + timedelta(days=1)
        resolution = "Daily coastal bulletin (IST calendar day)"
    if not end or end <= start:
        return None
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), resolution


def weather_resolution(row: dict) -> str:
    if row.get("weather_resolution") in {"berth observation", "terminal forecast", "port-point forecast"}:
        return row["weather_resolution"]
    basis = str(row.get("forecast_basis") or "").lower()
    if row.get("provider_code") == "metno" or row.get("data_class") == "official_port_forecast":
        return "port-point forecast"
    if "point" in basis and "area" not in basis:
        return "port-point forecast"
    return "marine-area forecast mapped to a port"


def scope_matches(evidence: dict, scope: dict, operation: str) -> bool:
    if evidence.get("operations") and operation not in evidence["operations"]:
        return False
    for field in ("terminal_id", "berth_id"):
        if evidence.get(field) and str(evidence[field]) != str(scope.get(field)):
            return False
    # A textual unresolved berth/terminal can never be expanded to port scope.
    if evidence.get("scope_type") in {"berth", "terminal", "local_area"} and not (evidence.get("berth_id") or evidence.get("terminal_id")):
        return False
    return True


def notice_active(notice: dict, now: datetime) -> bool:
    start, end = _parse_time(notice.get("effective_from")), _parse_time(notice.get("effective_to"))
    checked = _parse_time(notice.get("fetched_at"))
    issued = _parse_time(notice.get("issued_at"))
    return bool(notice.get("verified_scope") and notice.get("source_url") and issued and issued <= now and notice.get("operations")
                and start and end and start <= now < end and checked and timedelta(0) <= now - checked <= timedelta(minutes=30)
                and notice.get("lifecycle", "active") == "active" and not notice.get("review_required"))


def rule_result(rule: dict, row: dict, scope: dict, operation: str) -> tuple[bool, str]:
    if not rule.get("operations"):
        return False, "published operation scope unavailable"
    if not scope_matches(rule, scope, operation):
        return False, "outside rule scope"
    if not all(rule.get(field) for field in ("source_url", "publication_date", "version")):
        return False, "rule provenance incomplete"
    if rule.get("kind") != "numeric_limit":
        return False, "qualitative operating instruction; numerical limit not published"
    # Berth instruments and port-area forecasts are not interchangeable.
    if rule.get("required_resolution") and weather_resolution(row) != rule["required_resolution"]:
        return False, "forecast resolution does not satisfy published measurement location"
    if rule.get("equipment_id") and rule["equipment_id"] != scope.get("equipment_id"):
        return False, "equipment specification unavailable"
    if rule.get("conditions"):
        if any(scope.get(k) != v for k, v in rule["conditions"].items()):
            return False, "vessel / handling conditions unverified"
    field, unit = rule.get("metric"), rule.get("unit")
    wind_factors = {"kt": 1, "kn": 1, "knots": 1, "km/h": 1.852, "m/s": 1 / 1.943844, "mph": 1 / .868976}
    wave_factors = {"m": 1, "ft": 3.280839895}
    raw = wind_kn(row) if field == "wind" else number(row.get("wave_height_max_m")) if field == "wave" else None
    factor = wind_factors.get(unit) if field == "wind" else wave_factors.get(unit) if field == "wave" else None
    value = raw * factor if raw is not None and factor is not None else None
    threshold = number(rule.get("threshold"))
    if value is None or threshold is None:
        return False, "required measurement unavailable"
    exceeded = value > threshold if rule.get("operator", ">") == ">" else value >= threshold
    return exceeded, f"{field} {value:.1f} {unit}; published {rule.get('operator', '>')} {threshold:g} {unit}"


def screen(row: dict, operation: str) -> tuple[list[str], bool]:
    wind, wave, rain = wind_kn(row), number(row.get("wave_height_max_m")), rain_signal(row)
    reasons = []
    if wind is not None and wind >= 22:
        reasons.append(f"Wind {wind:.1f} kt meets 22 kt indicative screening trigger")
    if operation == "loading/discharge" and rain:
        reasons.append("Affirmative rain forecast: check cargo-handling arrangements; cargo sensitivity not inferred")
    if operation not in {"loading/discharge", "crane operations"} and wave is not None and wave >= 2.5:
        reasons.append(f"Waves {wave:.1f} m meet 2.5 m indicative screening trigger")
    complete = wind is not None and (rain is not None if operation == "loading/discharge" else True if operation == "crane operations" else wave is not None)
    return reasons, complete


def merge_windows(intervals: list[dict]) -> list[dict]:
    result = []
    for item in sorted(intervals, key=lambda x: (x["start"], x["end"])):
        if result and item["start"] <= result[-1]["end"] and item["assessment"] == result[-1]["assessment"] and item["resolution"] == result[-1]["resolution"]:
            result[-1]["end"] = max(item["end"], result[-1]["end"])
            result[-1]["basis"] = sorted(set(result[-1]["basis"] + item["basis"]))
        else:
            result.append({**item, "basis": list(item["basis"])})
    return [{**r, "start": r["start"].isoformat(), "end": r["end"].isoformat()} for r in result]


class OutlookEngine:
    def __init__(self, ports: list[dict], rules: list[dict] | None = None):
        self.matcher = PortMatcher(ports)
        major_ids = {str(p["id"]) for n, v in PORTS.items() if (p := self.matcher.match(n, v["country"]))}
        self.ports = [p for p in ports if "dry_bulk" in (p.get("categories") or []) or str(p["id"]) in major_ids]
        self.details = {str(p["id"]): berth_detail_for_port(p) for p in self.ports}
        self.rules = rules or []

    def map_bmkg_areas(self, records: list[dict]) -> list[dict]:
        """Explicit official marine-area containment, never nearest-terminal joins."""
        areas = defaultdict(list)
        for row in records:
            if row.get("provider_code") == "bmkg" and row.get("location_type") == "water" and row.get("geometry"):
                areas[row["location_id"]].append(row)
        mapped = []
        for area_id, rows in areas.items():
            try:
                polygon = shape(rows[0]["geometry"])
                if not polygon.is_valid:
                    continue
                for port in self.ports:
                    if port.get("country") != "ID" or port.get("lon") is None or port.get("lat") is None:
                        continue
                    if not polygon.covers(Point(port["lon"], port["lat"])):
                        continue
                    for row in rows:
                        mapped.append({**row, "location_type": "port", "location_id": f"{area_id}:catalog:{port['id']}", "catalog_port_id": str(port["id"]), "location_name": port["name"], "latitude": port["lat"], "longitude": port["lon"], "geometry": None, "marine_area": row["location_name"], "weather_resolution": "marine-area forecast mapped to a port", "forecast_basis": "Official BMKG marine-area polygon contains catalog port point; shared marine-area forecast, not a port or berth instrument"})
            except (ValueError, TypeError):
                continue
        return mapped

    def match_weather_port(self, row: dict) -> dict | None:
        port = self.matcher.match(str(row.get("location_name", "")), str(row.get("country", "")))
        if row.get("catalog_port_id"):
            # This identifier is set only by the explicit official-area adapter.
            port = next((p for p in self.ports if str(p["id"]) == str(row["catalog_port_id"]) and p.get("country") == country_code(str(row.get("country", "")))), None)
        if row.get("provider_code") != "bmkg" or row.get("catalog_port_id"):
            return port
        if not port and key(row.get("location_name")).startswith("pelabuhan "):
            port = self.matcher.match(key(row["location_name"])[10:], str(row.get("country", "")))
        # Reviewed general-port names must agree spatially as well. A source
        # with inconsistent coordinates or a different named terminal stays out.
        if port and all(v is not None for v in (row.get("latitude"),row.get("longitude"),port.get("lat"),port.get("lon"))):
            dy = float(row["latitude"]) - float(port["lat"])
            dx = (float(row["longitude"]) - float(port["lon"])) * math.cos(math.radians(float(port["lat"])))
            if math.hypot(dx, dy) * 111.2 > 15:
                return None
        return port

    def build(self, records: list[dict], notices: list[dict], *, now: datetime | None = None, errors: dict | None = None, sources: list[dict] | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        by_port: dict[str, list[dict]] = defaultdict(list)
        unmatched, historical = [], []
        records = records + self.map_bmkg_areas(records)
        for row in normalize_coastal_weather_rows(records, now=now):
            if row.get("location_type") != "port":
                continue
            port = self.match_weather_port(row)
            if not port:
                unmatched.append({"name": row.get("location_name"), "country": row.get("country"), "reason": "No unique reviewed country-qualified port match"})
                continue
            times = interval(row)
            if times and times[1] <= now:
                historical.append({"port_id": str(port["id"]), "port_name": port["name"], "valid_from": times[0].isoformat(), "valid_to": times[1].isoformat(), "source_url": row.get("source_url"), "label": "Expired forecast; historical only"})
                continue
            by_port[str(port["id"])].append(row)
        notice_by_port = defaultdict(list)
        superseded = {n.get("supersedes") for n in notices if n.get("supersedes")}
        for notice in notices:
            port = self.matcher.match(str(notice.get("port_name", "")), str(notice.get("country", "")))
            if port and notice.get("notice_id") not in superseded:
                notice_by_port[str(port["id"])].append(notice)
        output = []
        for port in self.ports:
            pid = str(port["id"])
            detail = self.details[pid]
            cargo = cargo_profile(port)
            port_cargoes = sorted(set((cargo or {}).get("cargoes", [])) | {c for b in (detail or {}).get("berths", []) for c in b.get("cargoes", [])})
            authority_sources = [s for s in sources or [] if any((matched := self.matcher.match(str(n), str(s.get("country", "")))) and str(matched["id"]) == pid for n in s.get("ports", []))]
            country_sources = [s for s in COASTAL_WEATHER_SOURCE_CATALOG if country_code(s["country"]) == port.get("country")]
            scopes = [{"terminal_id": None, "berth_id": None, "scope_type": "port", "scope_name": port["name"], "commodities": port_cargoes or ["Dry bulk (inventory classification)"], "role": "Berth roles listed separately" if detail else "Not documented", "cargo_provenance": cargo, "specification_sources": (detail or {}).get("sources", []), "specification_date": (detail or {}).get("source_as_of")}]
            if detail:
                for berth in detail.get("berths", []):
                    bid = pid + ":" + hashlib.sha256(berth["name"].encode()).hexdigest()[:12]
                    scopes.append({"terminal_id": pid + ":" + key(detail["scope"]).replace(" ", "-") if detail.get("scope_type") == "terminal" else None, "berth_id": bid, "scope_type": berth.get("facility_type") or "berth / documented facility", "scope_name": berth["name"], "commodities": berth.get("cargoes") or [], "role": berth.get("use") or "Not documented", "cargo_provenance": None, "specification_sources": detail.get("sources", []), "specification_date": berth.get("source_as_of") or detail.get("source_as_of")})
            for scope in scopes:
                # Berth forecasts are shared port evidence unless explicitly scoped.
                for operation in OPERATIONS if not scope["berth_id"] else ("loading/discharge", "crane operations", "berthing"):
                    for window, (low, high) in WINDOWS.items():
                        start, end = now + timedelta(hours=low), now + timedelta(hours=high)
                        pieces, provenance, gaps, matched_rules = [], [], [], []
                        covered = []
                        rows = by_port.get(pid, [])
                        for row in rows:
                            if (row.get("terminal_id") or row.get("berth_id")) and not scope_matches(row, scope, operation):
                                continue
                            times = interval(row)
                            if not times or times[1] <= start or times[0] >= end:
                                continue
                            issued = _parse_time(row.get("issued_at")) or _parse_time(row.get("fetched_at"))
                            if not issued or now - issued > timedelta(hours=36) or issued > now + timedelta(minutes=5):
                                gaps.append("Forecast issue / successful retrieval time missing or stale")
                                continue
                            if not row.get("source_url"):
                                gaps.append("Forecast provenance missing")
                                continue
                            reasons, complete = screen(row, operation)
                            assessment = "Weather watch" if reasons else "No trigger identified" if complete else "Not assessed"
                            if not complete:
                                gaps.append("Required screening measurements incomplete")
                            for rule in self.rules:
                                if str(rule.get("port_id")) != pid or not scope_matches(rule, scope, operation):
                                    continue
                                exceeded, basis = rule_result(rule, row, scope, operation)
                                matched_rules.append({**rule, "evaluation": basis, "exceeded": exceeded})
                                if exceeded:
                                    assessment = "Published limit exceeded"
                                    reasons.append(basis)
                            s, e = max(start, times[0]), min(end, times[1])
                            if complete:
                                covered.append((s, e))
                            pieces.append({"start": s, "end": e, "assessment": assessment, "basis": reasons, "resolution": row.get("forecast_timing_resolution") or times[2]})
                            provenance.append({"source_url": row.get("source_url"), "authority": row.get("provider"), "issued_at": row.get("issued_at"), "fetched_at": row.get("fetched_at"), "valid_from": times[0].isoformat(), "valid_to": times[1].isoformat(), "weather_resolution": weather_resolution(row), "marine_area": row.get("marine_area"), "source_error": (errors or {}).get(row.get("provider_code"))})
                        notices_here = []
                        for notice in notice_by_port.get(pid, []):
                            if not scope_matches(notice, scope, operation):
                                continue
                            notices_here.append(notice)
                            # Only fresh, dated, explicitly scoped restrictions enter outlook.
                            effective_start, effective_end = _parse_time(notice.get("effective_from")), _parse_time(notice.get("effective_to"))
                            # Assess upcoming confirmed restrictions without claiming
                            # that the operation is already restricted now.
                            upcoming = effective_start and effective_end and effective_start > now and notice_active({**notice, "effective_from": now.isoformat()}, now)
                            if notice_active(notice, now) or upcoming:
                                s, e = max(start, effective_start), min(end, effective_end)
                                if s < e:
                                    pieces.append({"start": s, "end": e, "assessment": "Confirmed restriction", "basis": [notice["summary"]], "resolution": "Authority stated effective interval"})
                        coverage_end = start
                        for s, e in sorted(covered):
                            if s > coverage_end:
                                break
                            coverage_end = max(coverage_end, e)
                        full_coverage = coverage_end >= end
                        assessment = min((p["assessment"] for p in pieces), key=ASSESSMENTS.index, default="Not assessed")
                        if assessment == "No trigger identified" and not full_coverage:
                            assessment = "Not assessed"
                        if not full_coverage:
                            gaps.append("Forecast coverage incomplete for selected horizon")
                        if not scope["berth_id"] and not detail:
                            gaps.append("Documented berth specifications unavailable")
                        if scope["berth_id"] and not any(p["weather_resolution"] in {"berth observation", "terminal forecast"} for p in provenance):
                            gaps.append("Berth shares port-area forecast; no berth measurement")
                        if not any(r.get("kind") == "numeric_limit" for r in matched_rules):
                            gaps.append("Applicable published numerical operating limits unavailable")
                        if not any(s.get("adapter") for s in authority_sources):
                            gaps.append("Authority notices are source links; structured port notice coverage unavailable")
                        elif any(s.get("error") for s in authority_sources):
                            gaps.append("Authority notice source error; latest restrictions may be unavailable")
                        actual = [n for n in notices_here if notice_active(n, now)]
                        source_urls = sorted({p["source_url"] for p in provenance} | {n["source_url"] for n in notices_here if n.get("source_url")})
                        source_urls = sorted(set(source_urls) | {s["url"] for s in authority_sources if s.get("url")} | {s[field] for s in country_sources for field in ("weather_url", "operations_url") if s.get(field)})
                        if cargo and cargo.get("source_url"):
                            source_urls = sorted(set(source_urls) | {cargo["source_url"]})
                        output.append({"row_id": f"{pid}:{scope['berth_id'] or 'port'}:{operation}:{window}", "port_id": pid, "port_name": port["name"], "country": port.get("country"), "country_name": port.get("country_name"), "latitude": port.get("lat"), "longitude": port.get("lon"), **scope, "operation": operation, "operation_group": "Cargo handling" if operation in OPERATIONS[:2] else "Vessel access", "forecast_window": window, "horizon_start": start.isoformat(), "horizon_end": end.isoformat(), "assessment": assessment, "actual_operating_status": "Restriction reported for stated scope" if actual else "Not reported", "potential_windows": merge_windows([p for p in pieces if p["assessment"] in ASSESSMENTS[:3]]), "assessment_basis": sorted({b for p in pieces for b in p["basis"]}), "weather_resolution": sorted({p["weather_resolution"] for p in provenance}), "forecast_intervals": sorted({p["valid_from"] + ' / ' + p["valid_to"] for p in provenance}), "applicable_rules": list({r["id"]: r for r in matched_rules}.values()), "notices": notices_here, "source_links": source_urls, "provenance": list({str(p): p for p in provenance}.values()), "freshness": {"assessed_at": now.isoformat(), "complete_horizon": full_coverage, "latest_successful_forecast_download": max((p["fetched_at"] for p in provenance if p.get("fetched_at")), default=None)}, "coverage_limitations": sorted(set(gaps))})
        return {"rows": output, "inventory_count": len(self.ports), "generated_at": now.isoformat(), "rule_version": RULE_VERSION, "unmatched_records": list({str(r): r for r in unmatched}.values()), "historical_forecasts": historical, "sources": sources or [], "source_errors": errors or {}, "methodology": "22 kt wind and 2.5 m waves are indicative watches, not shutdown rules. Rain prompts a cargo-handling check. No trigger identified applies only to complete screening coverage. Operating status requires a fresh, scoped authority notice. No delay hours or probabilities are estimated."}


def filter_outlook(payload: dict, **filters: str) -> dict:
    rows = payload["rows"]
    for field in ("port", "country", "commodity", "operation", "assessment", "forecast_window"):
        value = filters.get(field, "")
        if not value:
            continue
        if field == "port":
            exact_id = any(value == r["port_id"] for r in payload["rows"])
            rows = [r for r in rows if value == r["port_id"] or not exact_id and key(value) in key(r["port_name"])]
        elif field == "country":
            rows = [r for r in rows if country_code(value) == r["country"]]
        elif field == "commodity":
            rows = [r for r in rows if any(key(value) in key(c) for c in r["commodities"])]
        else:
            rows = [r for r in rows if r[field] == value]
    sort = filters.get("sort") or "assessment"
    if sort not in {"assessment", "port_name", "country", "operation", "forecast_window"}:
        sort = "assessment"
    rows = sorted(rows, key=lambda r: (ASSESSMENTS.index(r[sort]) if sort == "assessment" else str(r.get(sort, "")), r["port_name"], r["row_id"]), reverse=filters.get("direction") == "desc")
    return {**payload, "rows": rows, "total": len(rows), "filtered_port_count": len({r["port_id"] for r in rows}), "filters": filters}


def outlook_csv(payload: dict) -> str:
    import json
    output = io.StringIO()
    fields = list(dict.fromkeys(k for row in payload["rows"] for k in row)) if payload["rows"] else ["port_id", "port_name", "assessment", "operation", "forecast_window", "provenance"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in payload["rows"]:
        # Neutralise spreadsheet formulas in downloaded text without losing raw API evidence.
        values = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()}
        writer.writerow({k: "'" + v if isinstance(v, str) and v[:1] in {"=", "+", "-", "@"} else v for k, v in values.items()})
    return output.getvalue()
