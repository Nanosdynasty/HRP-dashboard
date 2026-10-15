"""Reviewed monthly series from the India Coal and supplied NPP archives.

Different measures keep their original units and provenance.  In particular the
June 2026 import observation is a financial-year-to-date total, not a month.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd


CATALOG = {
    "production": ("Domestic coal production", "MT", "coal_monthly_official.csv", "production_mt", "Ministry of Coal monthly bulletin", "https://coal.gov.in/public-information/monthly-statistics-at-glance"),
    "dispatch": ("Domestic coal dispatch", "MT", "coal_monthly_official.csv", "dispatch_mt", "Ministry of Coal monthly bulletin", "https://coal.gov.in/public-information/monthly-statistics-at-glance"),
    "imports": ("Coal imports (monthly)", "MT", "coal_imports_monthly.csv", "total_coal_mt", "Ministry of Coal / DGCI&S monthly observations", "https://coal.gov.in/major-statistics/production-and-supplies"),
    "coal_generation": ("Coal-fired generation", "GWh", "india_power_generation_monthly.csv", "coal_generation_gwh", "NPP monthly generation report", "https://npp.gov.in/publishedReports"),
    "station_stock": ("Power-station coal stock, last report in period", "000 tonnes", "npp_daily_coal_national.csv", "coal_stock_000t", "Supplied NPP daily national coal master", "https://npp.gov.in/publishedReports"),
    "station_consumption": ("Power-station coal consumption", "000 tonnes", "npp_daily_coal_national.csv", "coal_cons_000t", "Supplied NPP daily national coal master", "https://npp.gov.in/publishedReports"),
    "station_receipts": ("Power-station coal receipts", "000 tonnes", "npp_daily_coal_national.csv", "coal_receipt_000t", "Supplied NPP daily national coal master", "https://npp.gov.in/publishedReports"),
    "thermal_generation_daily": ("NPP DGR thermal generation", "GWh", "npp_daily_generation_dgr1.csv", "today_actual_mu", "Supplied corrected NPP DGR1 daily summary", "https://npp.gov.in/publishedReports"),
    "rainfall": ("14-location mean daily rainfall", "mm/day", "npp_monsoon_india_monthly.csv", "rain_mm", "Supplied Open-Meteo ERA5 reanalysis", "https://open-meteo.com/en/docs/historical-weather-api"),
}


def _monthly(base: Path, metric: str) -> pd.DataFrame:
    _, _, filename, column, _, _ = CATALOG[metric]
    path = base / filename
    if not path.exists():
        return pd.DataFrame(columns=["period", "value", "observed_days", "last_observation"])
    frame = pd.read_csv(path, low_memory=False)
    if metric == "imports":
        # FY2026-27 June=61.89 MT is April–June combined; it is not June trade.
        if "reporting_basis" in frame:
            frame = frame.loc[frame.reporting_basis.fillna("monthly") == "monthly"].copy()
        else:
            frame = frame.loc[frame["financial_year"].astype(str) != "2026-27"].copy()
    if metric in {"station_stock", "station_consumption", "station_receipts", "thermal_generation_daily"}:
        if metric == "thermal_generation_daily":
            frame = frame.loc[(frame.region == "ALL INDIA") & (frame.category == "THERMAL")].copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date")
        frame["period"] = frame.date.dt.to_period("M").astype(str)
        grouped = frame.groupby("period", sort=True)
        if metric == "station_stock":
            values = grouped[column].last()
        else:
            values = grouped[column].sum(min_count=1)
        result = pd.DataFrame({"period": values.index, "value": values.values,
                               "observed_days": grouped.date.nunique().values,
                               "last_observation": grouped.date.max().dt.strftime("%Y-%m-%d").values})
        return result
    if metric == "rainfall":
        frame = frame.rename(columns={"month": "period"})
    result = frame[["period", column]].rename(columns={column: "value"}).copy()
    result["observed_days"] = None
    result["last_observation"] = None
    return result


def metric_catalog(base: Path) -> list[dict]:
    items = []
    for key, (label, unit, _, _, source, url) in CATALOG.items():
        rows = _monthly(base, key)
        latest_date = (str(rows.iloc[-1].last_observation) if not rows.empty and pd.notna(rows.iloc[-1].last_observation) else None)
        partial = bool(latest_date and latest_date[:7] == str(rows.iloc[-1].period) and
                       pd.Timestamp(latest_date).day < pd.Timestamp(latest_date).days_in_month)
        items.append({"id": key, "label": label, "unit": unit, "source": source,
                      "source_url": url, "first": str(rows.period.min()) if not rows.empty else None,
                      "last": str(rows.period.max()) if not rows.empty else None,
                      "latest_observation": latest_date, "latest_month_partial": partial,
                      "rows": len(rows), "available": not rows.empty})
    return items


def compare(base: Path, metrics: list[str], start: str, end: str) -> dict:
    if len(metrics) < 2 or len(metrics) > 6 or len(set(metrics)) != len(metrics) or any(m not in CATALOG for m in metrics):
        raise ValueError("Select two to six different available measures")
    if start > end:
        raise ValueError("From must be before Through")
    periods = pd.period_range(start, end, freq="M").astype(str)
    joined = pd.DataFrame({"period": periods})
    metadata = []
    catalog = {item["id"]: item for item in metric_catalog(base)}
    for metric in metrics:
        rows = _monthly(base, metric)
        joined = joined.merge(rows[["period", "value"]].rename(columns={"value": metric}), on="period", how="left", validate="one_to_one")
        metadata.append(catalog[metric])
    common = joined.dropna(subset=metrics)
    baseline = str(common.iloc[0].period) if not common.empty else None
    result = []
    for row in joined.itertuples(index=False):
        item = {"period": row.period}
        for metric in metrics:
            value = getattr(row, metric)
            item[metric] = None if pd.isna(value) else float(value)
            basis = float(common.iloc[0][metric]) if baseline else None
            item[metric + "_index"] = (float(value) / basis * 100) if basis and pd.notna(value) else None
        result.append(item)
    return {"metrics": metadata, "rows": result, "baseline_period": baseline,
            "note": "Index = 100 in the first month where every selected series is reported. Gaps remain blank; differently sourced measures are descriptive, not causal."}
