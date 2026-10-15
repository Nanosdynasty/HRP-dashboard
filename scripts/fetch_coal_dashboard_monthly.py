"""Build official month-level coal and power dashboard datasets.

Source PDFs/workbooks are processed in memory and are never stored.  Only the
chart-ready CSV plus a compact quality manifest are written to the repository.
"""

from __future__ import annotations

import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pandas as pd
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "india_coal_master" / "canonical"
UI = ROOT / "data" / "india_coal_master" / "ui"
COAL_ARCHIVE = "https://coal.gov.in/public-information/monthly-statistics-at-glance"
NPP_BASE = "https://npp.gov.in/public-reports/cea/monthly/generation/18_col_act"
START_PERIOD = pd.Period("2023-05", freq="M")
# Keep the requested horizon explicit so a refresh cannot silently stop at an
# old release.  The NPP monthly reports currently extend through September
# 2026; missing releases are retained in the quality manifest rather than
# fabricated.
END_PERIOD = pd.Period("2026-09", freq="M")


def get(client: httpx.Client, url: str) -> bytes:
    error: Exception | None = None
    for attempt in range(4):
        try:
            response = client.get(url, timeout=90, follow_redirects=True)
            response.raise_for_status()
            if len(response.content) < 1_000:
                raise RuntimeError(f"Unexpectedly small official response: {url}")
            return response.content
        except (httpx.HTTPError, RuntimeError) as exc:
            error = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"Official source unavailable: {url}") from error


def archive_links(client: httpx.Client) -> dict[pd.Period, str]:
    links: dict[pd.Period, str] = {}
    for page in range(3):
        html = get(client, f"{COAL_ARCHIVE}?page={page}").decode("utf-8", "ignore")
        for href in re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, re.I):
            name = href.rsplit("/", 1)[-1].lower()
            match = re.search(
                r"(?:msg|monthly)[-_]?(jan|feb|mar|april|apr|may|june|jun|july|jul|aug|sept|setp|sep|oct|nov|dec)[a-z-]*?(\d{2})(?:\D|$)",
                name,
            )
            if not match:
                continue
            aliases = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "april": 4,
                       "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                       "aug": 8, "sep": 9, "sept": 9, "setp": 9, "oct": 10,
                       "nov": 11, "dec": 12}
            period = pd.Period(year=2000 + int(match.group(2)), month=aliases[match.group(1)], freq="M")
            if START_PERIOD <= period <= END_PERIOD:
                links[period] = urljoin(COAL_ARCHIVE, href)
    return links


def signed_number(text: str) -> float | None:
    match = re.search(r"([▲▼+-]?)\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    value = float(match.group(2))
    return -value if match.group(1) in {"▼", "-"} else value


def metric_candidate(tokens: list[str]) -> dict[str, float | None]:
    values = [signed_number(token) for token in tokens]
    return {
        "current_mt": values[1], "prior_mt": values[3], "yoy_pct": values[4],
        "ytd_current_mt": values[5], "ytd_prior_mt": values[6], "ytd_yoy_pct": values[7],
    }


def grand_total_metrics(text: str, heading: str) -> dict[str, float | None]:
    """Read the national total despite two PDF layout variants.

    Older bulletins print values after ``Grand Total``; newer chart layouts put
    them immediately before it.  A national monthly coal total must be in the
    40–130 MT range, which rejects company and coking-coal rows.
    """
    candidates: list[dict[str, float | None]] = []
    for heading_match in re.finditer(re.escape(heading), text, re.I):
        window_end = min(len(text), heading_match.start() + 8_000)
        window = text[heading_match.start():window_end]
        for total_match in re.finditer(r"grand\s*total", window, re.I):
            before = re.sub(r"\s+", " ", window[max(0, total_match.start() - 900):total_match.start()])
            after = re.sub(r"\s+", " ", window[total_match.end():total_match.end() + 360])
            before_tokens = re.findall(r"[▲▼+-]?\s*\d+(?:\.\d+)?", before)
            after_tokens = re.findall(r"[▲▼+-]?\s*\d+(?:\.\d+)?", after)
            if len(before_tokens) >= 8:
                candidates.append(metric_candidate(before_tokens[-8:]))
            if len(after_tokens) >= 8:
                candidates.append(metric_candidate(after_tokens[:8]))
    for candidate in candidates:
        current, prior = candidate.get("current_mt"), candidate.get("prior_mt")
        if current is not None and prior is not None and 40 <= current <= 130 and 40 <= prior <= 130:
            return candidate
    return {}


def narrative_metrics(text: str, metric: str) -> dict[str, float | None]:
    flat = re.sub(r"\s+", " ", text)
    match = re.search(
        rf"India.?s\s+coal\s+{metric}.{{0,220}}?(increased|decreased).{{0,80}}?"
        r"(?:by\s+)?([0-9]+(?:\.[0-9]+)?)%\s+to\s+([0-9]+(?:\.[0-9]+)?)\s*MT\s+"
        r"from\s+([0-9]+(?:\.[0-9]+)?)\s*MT",
        flat,
        re.I,
    )
    if not match:
        return {}
    direction, change, current, prior = match.groups()
    yoy = float(change) * (-1 if direction.lower() == "decreased" else 1)
    return {"current_mt": float(current), "prior_mt": float(prior), "yoy_pct": yoy}


def six_value_total_metrics(text: str, heading: str) -> dict[str, float | None]:
    """Fallback for newer bulletins whose national total is a six-number row."""
    candidates: list[dict[str, float | None]] = []
    for heading_match in re.finditer(re.escape(heading), text, re.I):
        window = re.sub(r"\s+", " ", text[heading_match.start():heading_match.start() + 10_000])
        tokens = re.findall(r"[▲▼+-]?\s*\d+(?:\.\d+)?", window)
        values = [signed_number(token) for token in tokens]
        for index in range(len(values) - 5):
            current, prior, yoy, ytd_current, ytd_prior, ytd_yoy = values[index:index + 6]
            if None in {current, prior, yoy, ytd_current, ytd_prior, ytd_yoy}:
                continue
            if not (40 <= current <= 130 and 40 <= prior <= 130):
                continue
            expected_yoy = (current / prior - 1) * 100
            expected_ytd_yoy = (ytd_current / ytd_prior - 1) * 100 if ytd_prior else 0
            if ytd_current < current or ytd_prior < prior:
                continue
            if abs(expected_yoy - yoy) > 0.35 or abs(expected_ytd_yoy - ytd_yoy) > 0.35:
                continue
            candidates.append({
                "current_mt": current, "prior_mt": prior, "yoy_pct": yoy,
                "ytd_current_mt": ytd_current, "ytd_prior_mt": ytd_prior,
                "ytd_yoy_pct": ytd_yoy,
            })
    return max(candidates, key=lambda item: item["current_mt"], default={})


def parse_coal_pdf(period: pd.Period, url: str, content: bytes) -> dict:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    production = {**grand_total_metrics(text, "Coal Production"), **narrative_metrics(text, "production")}
    dispatch = grand_total_metrics(text, "Coal Dispatch") or grand_total_metrics(text, "Coal Despatch")
    dispatch = {**dispatch, **(narrative_metrics(text, "dispatch") or narrative_metrics(text, "despatch"))}
    if dispatch.get("current_mt") is None:
        dispatch = six_value_total_metrics(text, "Coal Dispatch") or six_value_total_metrics(text, "Coal Despatch")
    return {
        "period": str(period),
        "status": "provisional",
        "production_mt": production.get("current_mt"),
        "production_prior_year_mt": production.get("prior_mt"),
        "production_yoy_pct": production.get("yoy_pct"),
        "production_ytd_mt": production.get("ytd_current_mt"),
        "dispatch_mt": dispatch.get("current_mt"),
        "dispatch_prior_year_mt": dispatch.get("prior_mt"),
        "dispatch_yoy_pct": dispatch.get("yoy_pct"),
        "dispatch_ytd_mt": dispatch.get("ytd_current_mt"),
        "source_url": url,
    }


def npp_url(period: pd.Period, report: int) -> str:
    mon = period.strftime("%b").upper()
    return f"{NPP_BASE}//{period.year}/{mon}/18_col_act-{report}_{period.year}-{mon}.xls"


def npp_tentative_url(period: pd.Period, report: int) -> str:
    mon = period.strftime("%b").upper()
    base = NPP_BASE.replace("18_col_act", "18_col_ten")
    return f"{base}//{period.year}/{mon}/18_col_ten-{report}_{period.year}-{mon}.xls"


def numeric(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def parse_npp(period: pd.Period, overview_bytes: bytes, fuel_bytes: bytes, tentative: bool = False) -> dict:
    overview = pd.read_excel(io.BytesIO(overview_bytes), header=None)
    fuel = pd.read_excel(io.BytesIO(fuel_bytes), header=None)
    header_row = next(
        (overview.iloc[index] for index in range(min(14, len(overview)))
         if overview.iloc[index].astype(str).str.strip().str.upper().str.contains("ACTUAL", regex=False).any()),
        None,
    )
    if header_row is None:
        raise ValueError(f"NPP ACTUAL column not found for {period}")
    actual_column = next(
        index for index, value in enumerate(header_row)
        if "ACTUAL" in str(value).strip().upper()
    )
    conventional: dict[str, float] = {}
    for _, row in overview.iterrows():
        label = str(row.iloc[0] or "").strip().lower()
        if label in {"thermal", "nuclear", "hydro", "bhutan imp", "total"}:
            value = numeric(row.iloc[actual_column])
            if value is not None:
                conventional[label] = value
    fuels: dict[str, float] = {}
    for _, row in fuel.iterrows():
        label = str(row.iloc[0] or "").strip().upper()
        if label in {"TOTAL COAL BASED", "TOTAL LIGNITE BASED"}:
            value = numeric(row.iloc[4])
            if value is not None:
                fuels[label] = value
    total = conventional.get("total")
    coal = fuels.get("TOTAL COAL BASED")
    return {
        "period": str(period), "status": "tentative" if tentative else "final", "coal_generation_gwh": coal,
        "lignite_generation_gwh": fuels.get("TOTAL LIGNITE BASED"),
        "thermal_generation_gwh": conventional.get("thermal"),
        "nuclear_generation_gwh": conventional.get("nuclear"),
        "large_hydro_generation_gwh": conventional.get("hydro"),
        "bhutan_import_gwh": conventional.get("bhutan imp"),
        "conventional_generation_gwh": total,
        "coal_share_conventional_pct": coal / total * 100 if coal and total else None,
        "npp_source_url": npp_tentative_url(period, 1) if tentative else npp_url(period, 1), "npp_fuel_source_url": npp_tentative_url(period, 11) if tentative else npp_url(period, 11),
    }


def main() -> None:
    CANONICAL.mkdir(parents=True, exist_ok=True)
    UI.mkdir(parents=True, exist_ok=True)
    expected = list(pd.period_range(START_PERIOD, END_PERIOD, freq="M"))
    with httpx.Client(headers={"User-Agent": "HRP-Dashboard/1.0 official-data-research"}) as client:
        try:
            links = archive_links(client)
            archive_error = None
        except Exception as exc:
            # The NPP reports are an independent source.  Preserve the last
            # validated Ministry snapshot if its archive is unavailable.
            links = {}
            archive_error = str(exc)
        coal_rows, coal_errors = [], []
        for period in expected:
            url = links.get(period)
            if not url:
                coal_errors.append({"period": str(period), "error": "archive link not found"})
                continue
            try:
                coal_rows.append(parse_coal_pdf(period, url, get(client, url)))
            except Exception as exc:
                coal_errors.append({"period": str(period), "error": str(exc)})
        if archive_error:
            coal_errors.insert(0, {"period": "archive", "error": archive_error})

        power_rows, power_errors = [], []
        for period in expected:
            try:
                try:
                    power_rows.append(parse_npp(period, get(client, npp_url(period, 1)), get(client, npp_url(period, 11))))
                except Exception:
                    # NPP publishes a tentative monthly report before the
                    # actual report. Keep it explicitly provisional.
                    power_rows.append(parse_npp(period, get(client, npp_tentative_url(period, 1)), get(client, npp_tentative_url(period, 11)), tentative=True))
            except Exception as exc:
                power_errors.append({"period": str(period), "error": str(exc)})

    coal = pd.DataFrame(coal_rows)
    existing_coal_path = CANONICAL / "coal_monthly_official.csv"
    if existing_coal_path.exists():
        existing_coal = pd.read_csv(existing_coal_path)
        coal = pd.concat([existing_coal, coal], ignore_index=True)
    if not coal.empty:
        coal = coal.sort_values("period").drop_duplicates("period", keep="last")
    power = pd.DataFrame(power_rows).sort_values("period")
    if not coal.empty:
        coal.to_csv(existing_coal_path, index=False, encoding="utf-8-sig")
    power.to_csv(CANONICAL / "india_power_generation_monthly.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_range": [str(START_PERIOD), str(END_PERIOD)],
        "coal": {"rows": len(coal), "latest": coal.period.max() if len(coal) else None,
                 "missing_or_failed": coal_errors,
                 "nulls": coal.isna().sum().to_dict() if len(coal) else {}},
        "power": {"rows": len(power), "latest": power.period.max() if len(power) else None,
                  "missing_or_failed": power_errors,
                  "nulls": power.isna().sum().to_dict() if len(power) else {}},
        "sources": [COAL_ARCHIVE, "https://npp.gov.in/publishedReports"],
        "storage_note": "Source PDF/XLS files were processed in memory and not retained.",
    }
    (UI / "coal_dashboard_quality.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"coal_rows": len(coal), "power_rows": len(power),
                      "coal_errors": len(coal_errors), "power_errors": len(power_errors),
                      "coal_latest": manifest["coal"]["latest"], "power_latest": manifest["power"]["latest"]}))


if __name__ == "__main__":
    main()
