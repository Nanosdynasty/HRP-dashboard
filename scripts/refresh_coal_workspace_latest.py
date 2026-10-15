"""Refresh the latest official Coal India workspace aggregates.

PDFs are downloaded and parsed in memory. Only the small chart-ready CSV/JSON
outputs are retained. Detailed country/port tables are not promoted beyond the
last official Coal Directory release because customs reporting country is not
the same thing as physical mine origin.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "india_coal_master" / "canonical"
QUALITY = ROOT / "data" / "india_coal_master" / "ui" / "coal_data_freshness.json"

MINISTRY_PAGE = "https://coal.gov.in/major-statistics/production-and-supplies"
QUARTERLY_PDF = "https://coal.gov.in/sites/default/files/2025-09/29-06-2026a-qety.pdf"


def fetch_text(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def fetch_pdf_text(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    reader = PdfReader(io.BytesIO(response.content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_fy_2025_26_monthly(text: str) -> list[dict]:
    block_match = re.search(
        r"Quarter Month Coking\s+Coal Non-Coking Coal Total(?P<body>.*?)"
        r"Table 33: Month and Quarter Wise Import of Coal during FY 2025-26",
        text,
        flags=re.DOTALL,
    )
    if not block_match:
        raise ValueError("Official FY2025-26 monthly import table was not found")
    rows = []
    month_pattern = re.compile(
        r"(?P<month>Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Jan|Feb|Mar)-(?P<year>25|26)\s+"
        r"(?P<coking>\d+(?:\.\d+)?)\s+(?P<non_coking>\d+(?:\.\d+)?)\s+(?P<total>\d+(?:\.\d+)?)"
    )
    month_numbers = {
        name: index for index, name in enumerate(
            ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
            start=1,
        )
    }
    for match in month_pattern.finditer(block_match.group("body")):
        rows.append({
            "period": f"20{match.group('year')}-{month_numbers[match.group('month')]:02d}",
            "financial_year": "2025-26",
            "coking_coal_mt": float(match.group("coking")),
            "non_coking_coal_mt": float(match.group("non_coking")),
            "total_coal_mt": float(match.group("total")),
            "coke_products_mt": None,
            "status": "provisional",
            "source_url": QUARTERLY_PDF,
        })
    if len(rows) != 12:
        raise ValueError(f"Expected 12 FY2025-26 monthly rows, found {len(rows)}")
    return rows


def parse_latest_ministry_imports(html: str) -> dict:
    plain = re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"\s+", " ", plain)
    if not re.search(r"Import\s+upto\s+Apr-26\s*-\s*June?-26", plain, re.IGNORECASE):
        raise ValueError("Current Ministry import reporting period changed; inspect before publishing")
    patterns = {
        "coking_coal_mt": r"Coking Coal\s+57\.16\s+56\.05\s+58\.81\s+57\.58\s+66\.33\s+(\d+(?:\.\d+)?)",
        "non_coking_coal_mt": r"Non-Coking Coal\s+151\.77\s+181\.62\s+205\.72\s+186\.05\s+180\.04\s+(\d+(?:\.\d+)?)",
        "total_coal_mt": r"Total Coal Import\s+208\.93\s+237\.67\s+264\.53\s+243\.63\s+246\.37\s+(\d+(?:\.\d+)?)",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, plain, flags=re.IGNORECASE)
        if not match:
            raise ValueError(f"Latest Ministry import value not found for {key}")
        result[key] = float(match.group(1))
    return result


def refresh_imports(client: httpx.Client) -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly_path = CANONICAL / "coal_imports_monthly.csv"
    monthly = pd.read_csv(monthly_path)
    monthly = monthly.loc[monthly["period"].astype(str) <= "2025-03"].copy()
    monthly["reporting_basis"] = "monthly"
    if "source_url" not in monthly:
        monthly["source_url"] = "https://coal.gov.in/major-statistics/coal-statistics"
    quarterly_rows = parse_fy_2025_26_monthly(fetch_pdf_text(client, QUARTERLY_PDF))
    for row in quarterly_rows:
        row["reporting_basis"] = "monthly"
    monthly = pd.concat([monthly, pd.DataFrame(quarterly_rows)], ignore_index=True)
    ytd = parse_latest_ministry_imports(fetch_text(client, MINISTRY_PAGE))
    ytd.update({
        "period": "2026-06",
        "financial_year": "2026-27",
        "coke_products_mt": None,
        "status": "provisional",
        "source_url": MINISTRY_PAGE,
        "reporting_basis": "financial_year_to_date",
    })
    monthly = pd.concat([monthly, pd.DataFrame([ytd])], ignore_index=True)
    monthly = monthly.sort_values("period").drop_duplicates("period", keep="last")
    monthly.to_csv(monthly_path, index=False)

    annual_path = CANONICAL / "coal_india_annual.csv"
    annual = pd.read_csv(annual_path)
    annual = annual.loc[annual["period"].astype(str) != "2025-26"].copy()
    coal_monthly = pd.read_csv(CANONICAL / "coal_monthly_official.csv")
    fy_months = coal_monthly.loc[(coal_monthly["period"] >= "2025-04") & (coal_monthly["period"] <= "2026-03")]
    production = float(fy_months["production_mt"].sum())
    dispatch = float(fy_months["dispatch_mt"].sum())
    prior = annual.sort_values("period").iloc[-1]
    current = {
        "period": "2025-26",
        "production_mt": production,
        "total_imports_mt": 246.37,
        "coking_imports_mt": 66.33,
        "non_coking_imports_mt": 180.04,
        "offtake_mt": dispatch,
        "closing_stock_mt": None,
        "production_yoy_pct": (production / float(prior["production_mt"]) - 1) * 100,
        "imports_yoy_pct": (246.37 / float(prior["total_imports_mt"]) - 1) * 100,
        "import_dependency_pct": 246.37 / (production + 246.37) * 100,
        "status": "provisional",
        "source_url": MINISTRY_PAGE,
    }
    if "status" not in annual:
        annual["status"] = "final"
    else:
        annual["status"] = annual["status"].fillna("final")
    if "source_url" not in annual:
        annual["source_url"] = "https://coal.gov.in/major-statistics/coal-statistics"
    annual = pd.concat([annual, pd.DataFrame([current])], ignore_index=True).sort_values("period")
    annual.to_csv(annual_path, index=False)
    return monthly, annual


def write_freshness(monthly: pd.DataFrame, annual: pd.DataFrame) -> None:
    monthly_only = monthly.loc[monthly.reporting_basis == "monthly"]
    cumulative = monthly.loc[monthly.reporting_basis == "financial_year_to_date"]
    production = pd.read_csv(CANONICAL / "coal_monthly_official.csv")
    generation = pd.read_csv(CANONICAL / "india_power_generation_monthly.csv")
    npp_fuel = pd.read_csv(CANONICAL / "npp_daily_coal_national.csv") if (CANONICAL / "npp_daily_coal_national.csv").exists() else pd.DataFrame()
    npp_dgr = pd.read_csv(CANONICAL / "npp_daily_generation_dgr1.csv") if (CANONICAL / "npp_daily_generation_dgr1.csv").exists() else pd.DataFrame()
    datasets = [
        {"dataset": "National coal imports — monthly", "file": "coal_imports_monthly.csv", "latest_period": str(monthly_only.period.max()), "status": "latest comparable monthly release", "release_status": "provisional", "source": QUARTERLY_PDF},
        {"dataset": "National coal imports — FY-to-date", "file": "coal_imports_monthly.csv", "latest_period": str(cumulative.period.max()) if not cumulative.empty else None, "status": "Apr–Jun FY2026-27 cumulative; not a June monthly total", "release_status": "provisional", "source": MINISTRY_PAGE},
        {"dataset": "National coal imports — annual", "file": "coal_india_annual.csv", "latest_period": str(annual.period.max()), "status": "current", "release_status": "provisional", "source": MINISTRY_PAGE},
        {"dataset": "Coal production and dispatch — monthly", "file": "coal_monthly_official.csv", "latest_period": str(production.period.max()), "status": "latest loaded bulletin", "release_status": "provisional", "source": "https://coal.gov.in/public-information/monthly-statistics-at-glance"},
        {"dataset": "Electricity generation — monthly", "file": "india_power_generation_monthly.csv", "latest_period": str(generation.period.max()), "status": "NPP conventional series", "release_status": "official reported/tentative by period", "source": "https://npp.gov.in/publishedReports", "limitation": "All-source CEA renewable mix has separate coverage; tentative months remain labelled."},
        {"dataset": "Coal imports by reported country", "file": "coal_imports_by_origin.csv", "latest_period": "2024-25", "status": "latest granular official release", "release_status": "final", "limitation": "Customs reporting country is not treated as physical mine origin."},
        {"dataset": "Coal imports by Indian port", "file": "coal_imports_by_port.csv", "latest_period": "2024-25", "status": "latest granular official release", "release_status": "final"},
        {"dataset": "Coal production by coal type — monthly", "file": "coal_production_monthly.csv", "latest_period": "2024-12", "status": "historical only", "release_status": "final", "limitation": "No later compatible all-India coking/non-coking monthly series has been loaded."},
        {"dataset": "Coal off-take by consuming sector", "file": "coal_offtake_by_sector.csv", "latest_period": "2024-25", "status": "latest granular official release", "release_status": "final"},
        {"dataset": "Plant-level coking coal consumption", "file": "steel_plant_coking_coal.csv", "latest_period": "2018-19", "status": "historical only", "release_status": "final", "limitation": "Not used for current-period claims."},
    ]
    if not npp_fuel.empty:
        datasets.append({"dataset": "NPP daily station fuel and stock", "file": "npp_daily_coal_national.csv", "latest_period": str(npp_fuel.date.max()), "status": "daily reported", "source": "https://npp.gov.in/dailyCoalReports"})
    if not npp_dgr.empty:
        datasets.append({"dataset": "NPP corrected daily generation", "file": "npp_daily_generation_dgr1.csv", "latest_period": str(npp_dgr.date.max()), "status": "daily reported", "source": "https://npp.gov.in/dgrReports"})
    QUALITY.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "policy": "Official observations only; missing periods are never interpolated and stale granular tables are labelled at their true coverage.",
        "datasets": datasets,
    }, indent=2), encoding="utf-8")


def main() -> None:
    with httpx.Client(timeout=90, follow_redirects=True, headers={"User-Agent": "HRP-Coal-Dashboard/1.0"}) as client:
        monthly, annual = refresh_imports(client)
    write_freshness(monthly, annual)
    print(json.dumps({
        "monthly_rows": len(monthly),
        "monthly_latest": str(monthly.loc[monthly.reporting_basis == "monthly", "period"].max()),
        "cumulative_ytd_latest": str(monthly.loc[monthly.reporting_basis == "financial_year_to_date", "period"].max()),
        "annual_latest": str(annual.period.max()),
        "fy_2025_26_total_mt": float(monthly.loc[monthly.financial_year == "2025-26", "total_coal_mt"].sum()),
    }, indent=2))


if __name__ == "__main__":
    main()
