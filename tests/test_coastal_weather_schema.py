from datetime import datetime, timezone

from coastal_weather_schema import (
    COASTAL_WEATHER_SOURCE_CATALOG,
    normalize_coastal_weather_row,
)


NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def test_area_forecast_mapped_to_port_is_labelled_and_status_is_not_inferred():
    row = normalize_coastal_weather_row({
        "provider": "CMA / NMC",
        "provider_code": "cma",
        "location_type": "port",
        "location_name": "Shanghai",
        "forecast_basis": "Official coastal-area forecast mapped to port location",
        "issued_at": "2026-08-25T00:00:00+00:00",
        "valid_from": "2026-08-25T00:00:00+00:00",
        "valid_to": "2026-08-26T00:00:00+00:00",
        "source_url": "https://www.nmc.cn/publish/marine/",
    }, now=NOW)

    assert row["data_class"] == "official_area_mapped_forecast"
    assert row["port_operational_status"] == "Not reported"
    assert row["port_status_reported"] is False
    assert "area_forecast_mapped_to_port" in row["quality_flags"]
    assert "port_status_not_reported" in row["quality_flags"]


def test_explicit_port_closure_is_preserved_as_reported_status():
    row = normalize_coastal_weather_row({
        "provider": "Port authority",
        "location_type": "port",
        "currently_port_close": "Yes",
        "issued_at": "2026-08-25T08:00:00+00:00",
        "valid_from": "2026-08-25T08:00:00+00:00",
        "source_url": "https://example.gov/notice",
    }, now=NOW)

    assert row["port_operational_status"] == "Closed"
    assert row["port_status_reported"] is True
    assert "port_status_not_reported" not in row["quality_flags"]


def test_old_forecast_is_flagged_stale():
    row = normalize_coastal_weather_row({
        "provider": "Official agency",
        "location_type": "water",
        "issued_at": "2026-08-20T00:00:00+00:00",
        "valid_from": "2026-08-20T00:00:00+00:00",
        "valid_to": "2026-08-21T00:00:00+00:00",
        "source_url": "https://example.gov/forecast",
    }, now=NOW)

    assert row["freshness_status"] == "stale"
    assert row["freshness_age_hours"] == 132.0
    assert "stale_forecast" in row["quality_flags"]


def test_source_catalog_separates_weather_and_operations_authorities():
    china = next(item for item in COASTAL_WEATHER_SOURCE_CATALOG if item["country"] == "China")
    united_states = next(item for item in COASTAL_WEATHER_SOURCE_CATALOG if item["country"] == "United States")

    assert china["weather_agency"] != china["operations_agency"]
    assert united_states["integration"] == "live"
    assert "marine grids" in united_states["coverage"]
    assert len(COASTAL_WEATHER_SOURCE_CATALOG) >= 20
