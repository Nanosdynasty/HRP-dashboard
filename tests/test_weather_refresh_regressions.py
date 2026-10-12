import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from coastal_weather_schema import normalize_coastal_weather_row
from imd_coastal_weather import _rain_category
from major_port_weather import MajorPortWeatherManager
from sea_marine_weather import SeaMarineWeatherManager


def test_recent_download_does_not_make_old_forecast_current():
    row = normalize_coastal_weather_row({
        "valid_from": "09 UTC of 2026-09-15", "provider_code": "imd",
    }, fetched_at="2026-09-28T10:00:00+00:00",
        now=datetime(2026, 9, 28, 11, tzinfo=timezone.utc))
    assert row["freshness_status"] == "stale"


def test_expired_validity_has_no_six_hour_grace_period():
    row = normalize_coastal_weather_row({
        "issued_at": "2026-09-28T09:00:00Z", "valid_to": "2026-09-28T10:00:00Z",
    }, now=datetime(2026, 9, 28, 11, tzinfo=timezone.utc))
    assert row["forecast_expired"] is True
    assert row["freshness_status"] == "stale"


def test_negative_rain_statement_is_not_a_rain_forecast():
    assert _rain_category("No rain. Wind 20 knots") is None
    assert _rain_category("No significant rainfall") is None
    assert _rain_category("No rain in north; scattered rain in south") == "Scattered rain"


@pytest.mark.parametrize("manager_class", [SeaMarineWeatherManager, MajorPortWeatherManager])
def test_all_source_failures_retain_last_success_time_and_rows(tmp_path, monkeypatch, manager_class):
    manager = manager_class(tmp_path / "weather.json")
    previous = {"fetched_at": "2026-09-15T00:00:00+00:00",
                "rows": [{"provider_code": "metno", "location_name": "Example"}]}
    manager.payload = previous
    methods = (["_fetch_provider"] if manager_class is SeaMarineWeatherManager else
               ["_fetch_bom", "_fetch_noaa", "_fetch_canada", "_fetch_jma", "_fetch_metno"])
    for method in methods:
        monkeypatch.setattr(manager, method, AsyncMock(side_effect=RuntimeError("unavailable")))
    with pytest.raises(RuntimeError):
        asyncio.run(manager.refresh(force=True))
    assert manager.payload is previous
    assert "unavailable" in manager.last_error
    assert not manager.cache_path.exists()
