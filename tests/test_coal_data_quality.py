import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "india_coal_master" / "canonical"
UI = ROOT / "data" / "india_coal_master" / "ui"


def test_monthly_periods_are_unique_and_measures_non_negative():
    for name in ("coal_monthly_official.csv", "coal_imports_monthly.csv", "india_power_generation_monthly.csv"):
        frame = pd.read_csv(CANONICAL / name)
        assert frame["period"].is_unique, name
        numeric = frame.select_dtypes(include="number").drop(columns=[c for c in frame.columns if "ytd" in c], errors="ignore")
        checked = numeric.drop(columns=[c for c in numeric.columns if "yoy" in c], errors="ignore")
        assert (checked.fillna(0) >= 0).all().all(), name


def test_import_components_reconcile_when_total_is_present():
    frame = pd.read_csv(CANONICAL / "coal_imports_monthly.csv")
    components = frame[["coking_coal_mt", "non_coking_coal_mt", "total_coal_mt"]].dropna()
    assert ((components.coking_coal_mt + components.non_coking_coal_mt - components.total_coal_mt).abs() <= 0.05).all()


def test_freshness_manifest_matches_canonical_latest_periods():
    freshness = json.loads((UI / "coal_data_freshness.json").read_text(encoding="utf-8"))
    imports = pd.read_csv(CANONICAL / "coal_imports_monthly.csv")
    production = pd.read_csv(CANONICAL / "coal_monthly_official.csv")
    by_file = {row["file"]: row for row in freshness["datasets"]}
    assert by_file["coal_imports_monthly.csv"]["latest_period"] == imports.period.max()
    assert by_file["coal_monthly_official.csv"]["latest_period"] <= production.period.max()
