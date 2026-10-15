from pathlib import Path

import pandas as pd

from coal_comparison import _monthly, compare, metric_catalog
from scripts.update_npp_daily import fuel_row, dgr_xls_rows


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "india_coal_master" / "canonical"


def test_import_ytd_is_not_a_monthly_observation():
    rows = _monthly(DATA, "imports")
    assert str(rows.period.max()) == "2026-03"
    assert not (rows.period == "2026-06").any()


def test_latest_npp_days_are_partial_and_stock_is_a_last_observation():
    catalog = {row["id"]: row for row in metric_catalog(DATA)}
    assert catalog["station_stock"]["latest_observation"] >= "2026-10-13"
    assert catalog["station_stock"]["latest_month_partial"]
    stock = _monthly(DATA, "station_stock")
    daily = pd.read_csv(DATA / "npp_daily_coal_national.csv")
    assert stock.iloc[-1].value == daily.iloc[-1].coal_stock_000t


def test_comparison_uses_common_baseline_and_preserves_gaps():
    result = compare(DATA, ["production", "station_consumption", "thermal_generation_daily"], "2024-01", "2026-10")
    assert result["baseline_period"] == "2024-01"
    baseline = next(row for row in result["rows"] if row["period"] == "2024-01")
    assert all(abs(baseline[key + "_index"] - 100) < 1e-9 for key in ("production", "station_consumption", "thermal_generation_daily"))
    october = result["rows"][-1]
    assert october["production"] is None
    assert october["station_consumption"] is not None


def test_incremental_parsers_reproduce_supplied_validated_day():
    archive = Path(r"C:\Users\deepak\Documents\Default Project\npp_data\full_archive")
    fuel = archive / "daily_coal/2026/09/27-09-2026/dailyCoal1-2026-09-27.xls"
    dgr = archive / "daily_generation/2026/09/26-09-2026/dgr1-2026-09-26.xls"
    if not fuel.exists() or not dgr.exists():
        return
    parsed = fuel_row(fuel.read_bytes(), "2026-09-27")
    assert parsed["n_plants"] == 190
    assert abs(parsed["coal_cons_000t"] - 2396.2) < .01
    thermal = next(row for row in dgr_xls_rows(dgr.read_bytes(), "2026-09-26") if row["category"] == "THERMAL")
    assert abs(thermal["today_actual_mu"] - 3355.02) < .01
