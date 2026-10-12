import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from authority_notices import ADAPTERS, AuthorityNoticeManager, enrich_document, parse_listing
from port_disruption_outlook import OutlookEngine, PortMatcher, filter_outlook, interval, notice_active, outlook_csv, rain_signal, rule_result, screen, scope_matches, wind_kn

NOW = datetime(2026, 9, 28, 6, tzinfo=timezone.utc)
PORT = {"id": "1", "name": "NEWCASTLE", "country": "AU", "country_name": "Australia", "lat": -32.92, "lon": 151.79, "categories": ["dry_bulk"], "search_aliases": ["Port Hedland"]}


def forecast(**changes):
    return {"country": "Australia", "location_name": "Newcastle", "location_type": "port", "issued_at": NOW.isoformat(), "fetched_at": NOW.isoformat(), "valid_from": NOW.isoformat(), "valid_to": (NOW + timedelta(hours=72)).isoformat(), "provider_code": "bom", "provider": "BOM", "source_url": "https://www.bom.gov.au/test", "wind_speed_max_kn": 12, "wave_height_max_m": 1, "weather_condition": "No Rain", **changes}


def notice(**changes):
    return {"notice_id": "n1", "port_name": "Newcastle", "country": "Australia", "issued_at": NOW.isoformat(), "fetched_at": NOW.isoformat(), "effective_from": NOW.isoformat(), "effective_to": (NOW + timedelta(hours=24)).isoformat(), "verified_scope": True, "scope_type": "port", "lifecycle": "active", "summary": "Pilotage suspended", "operations": ["pilotage"], "source_url": "https://authority.example/notice", **changes}


def build(rows=None, notices=None, rules=None):
    return OutlookEngine([PORT], rules).build(rows or [], notices or [], now=NOW)


def select(payload, operation="loading/discharge", window="0-24", berth=None):
    return next(r for r in payload["rows"] if r["operation"] == operation and r["forecast_window"] == window and r["berth_id"] == berth)


def test_country_qualified_unique_matching_ignores_catalog_aliases():
    other = {**PORT, "id": "2", "country": "GB"}
    matcher = PortMatcher([PORT, other])
    assert matcher.match("Newcastle", "Australia")["id"] == "1"
    assert matcher.match("Newcastle", "GB")["id"] == "2"
    assert matcher.match("Port Hedland", "Australia") is None
    assert matcher.match("Newcastle", "") is None
    assert PortMatcher([PORT, {**PORT, "id": "3"}]).match("Newcastle", "AU") is None


@pytest.mark.parametrize("text,expected", [("No Rain", False), ("without rainfall", False), ("nil rainfall", False), ("Rain: nil", False), ("Cloudy", False), ("Light snow", None), ("Light rain", True), ("Isolated thunderstorms", True), ("No rain in the morning; showers later", True)])
def test_affirmative_rain_and_negations(text, expected):
    assert rain_signal({"weather_condition": text}) is expected


def test_unit_conversion_and_separate_operations():
    assert wind_kn({"wind_speed_max_kmph": 40.744}) == pytest.approx(22)
    assert wind_kn({"wind_speed_max_ms": 11.317}) == pytest.approx(22, abs=.01)
    assert not screen(forecast(wave_height_max_m=3), "loading/discharge")[0]
    assert screen(forecast(wave_height_max_m=3), "approach")[0]
    assert screen(forecast(weather_condition="Rain"), "loading/discharge")[0]
    assert not screen(forecast(weather_condition="Rain"), "pilotage")[0]


def test_weather_watch_does_not_create_actual_restriction():
    payload = build([forecast(wind_speed_max_kn=23)])
    row = select(payload)
    assert row["assessment"] == "Weather watch"
    assert row["actual_operating_status"] == "Not reported"
    assert row["potential_windows"][0]["start"] == NOW.isoformat()


def test_complete_and_partial_horizons_honest_labels():
    assert select(build([forecast()]))["assessment"] == "No trigger identified"
    payload = build([forecast(valid_to=(NOW + timedelta(hours=12)).isoformat())])
    assert select(payload)["assessment"] == "Not assessed"
    assert not select(payload)["freshness"]["complete_horizon"]
    assert select(build([forecast(wave_height_max_m=None)]), "approach")["assessment"] == "Not assessed"
    assert select(build([]))["assessment"] == "Not assessed"


def test_expired_and_stale_forecasts_remain_outside_current_alerts():
    expired = forecast(valid_from=(NOW - timedelta(hours=24)).isoformat(), valid_to=(NOW - timedelta(hours=1)).isoformat(), wind_speed_max_kn=50)
    payload = build([expired])
    assert payload["historical_forecasts"]
    assert all(r["assessment"] == "Not assessed" for r in payload["rows"])
    payload = build([forecast(issued_at=(NOW - timedelta(hours=40)).isoformat(), wind_speed_max_kn=50)])
    assert all(r["assessment"] == "Not assessed" for r in payload["rows"])


def test_consecutive_windows_merge_but_never_bridge_missing_intervals():
    rows = [forecast(wind_speed_max_kn=25, valid_from=(NOW + timedelta(hours=s)).isoformat(), valid_to=(NOW + timedelta(hours=e)).isoformat()) for s,e in [(0,2),(2,4),(5,6)]]
    windows = select(build(rows))["potential_windows"]
    assert len(windows) == 2
    assert windows[0]["end"] == (NOW + timedelta(hours=4)).isoformat()


def test_imd_daily_resolution_is_not_an_hourly_claim():
    start,end,resolution = interval({"provider_code": "imd", "valid_date": "28.09.2026"})
    assert start.hour == 18 and start.day == 27
    assert end - start == timedelta(days=1)
    assert "Daily" in resolution


def test_numeric_rule_provenance_units_and_exact_scope():
    rule = {"id": "r", "port_id": "1", "kind": "numeric_limit", "terminal_id": "t1", "operations": ["crane operations"], "metric": "wind", "unit": "kt", "threshold": 25, "source_url": "https://authority.example/rule", "publication_date": "2026-09-01", "version": "v1", "required_resolution": "terminal forecast"}
    assert not rule_result(rule, forecast(wind_speed_max_kn=30), {"terminal_id":"t1"}, "crane operations")[0]
    assert rule_result(rule, forecast(wind_speed_max_kmph=55.56, wind_speed_max_kn=None, weather_resolution="terminal forecast"), {"terminal_id":"t1"}, "crane operations")[0]
    assert not rule_result(rule, forecast(wind_speed_max_kn=30, weather_resolution="terminal forecast"), {"terminal_id":"t2"}, "crane operations")[0]
    assert not rule_result({**rule,"version":None}, forecast(), {"terminal_id":"t1"}, "crane operations")[0]
    port_rule = {**rule,"terminal_id":None,"operations":["berthing"],"required_resolution":None}
    assert select(build([forecast(wind_speed_max_kn=30)], rules=[port_rule]),"berthing")["assessment"] == "Published limit exceeded"
    assert rule_result({**port_rule,"unit":"km/h","threshold":50},forecast(wind_speed_max_kn=30),{},"berthing")[0]
    assert rule_result({**port_rule,"metric":"wave","unit":"ft","threshold":8},forecast(wave_height_max_m=2.5),{},"berthing")[0]


def test_berth_notice_never_becomes_port_wide():
    engine = OutlookEngine([PORT])
    preview = engine.build([forecast()], [], now=NOW)
    berth = next(r["berth_id"] for r in preview["rows"] if r["berth_id"])
    n = notice(berth_id=berth, scope_type="berth", operations=["berthing"])
    payload = engine.build([forecast()], [n], now=NOW)
    assert select(payload, "berthing")["assessment"] == "No trigger identified"
    assert select(payload, "berthing", berth=berth)["assessment"] == "Confirmed restriction"
    assert not scope_matches(notice(scope_type="berth", berth_id=None), {}, "pilotage")


@pytest.mark.parametrize("changes", [{"issued_at":None},{"lifecycle":"withdrawn"},{"lifecycle":"reopened"},{"review_required":True},{"effective_to":NOW.isoformat()},{"fetched_at":(NOW-timedelta(hours=1)).isoformat()}])
def test_invalid_notice_lifecycle_never_confirms(changes):
    assert not notice_active(notice(**changes), NOW)
    assert select(build([forecast()], [notice(**changes)]),"pilotage")["assessment"] == "No trigger identified"


def test_correction_suppresses_predecessor_and_upcoming_status_is_separate():
    corrected = notice(notice_id="n2", supersedes="n1", lifecycle="withdrawn")
    assert select(build([forecast()], [notice(), corrected]),"pilotage")["assessment"] == "No trigger identified"
    upcoming = notice(effective_from=(NOW+timedelta(hours=30)).isoformat(),effective_to=(NOW+timedelta(hours=40)).isoformat())
    row = select(build([forecast()], [upcoming]),"pilotage","24-72")
    assert row["assessment"] == "Confirmed restriction"
    assert row["actual_operating_status"] == "Not reported"


def test_listing_publication_date_is_not_download_date_and_stable_ids():
    source = ADAPTERS[2]
    body = '<table><tr><td>1</td><td>Temporary Notice to Mariners: anchor lost</td><td>22 September, 2026</td><td><a href="/uploads/anchor.pdf">View</a></td></tr></table>'
    parsed = parse_listing(body, source, NOW.isoformat())
    assert len(parsed) == 1
    assert parsed[0]["issued_at"].startswith("2026-09-22")
    assert parsed[0]["notice_id"] == parse_listing(body, source, (NOW+timedelta(days=1)).isoformat())[0]["notice_id"]
    assert parsed[0]["review_required"]
    assert not notice_active(parsed[0], NOW)
    undated = parse_listing(body.replace('22 September, 2026',''),source,NOW.isoformat())[0]
    assert undated["issued_at"] is None
    with pytest.raises(ValueError):
        parse_listing('<iframe src="/_Incapsula_Resource">',ADAPTERS[0],NOW.isoformat())


def test_local_document_and_withdrawal_are_conservative():
    n = notice(verified_scope=False,review_required=True,lifecycle="pending_confirmation")
    parsed = enrich_document(n,"Date: 28/09/2026 From 28/09/2026 until 29/09/2026 Berth 3 is closed. Other berths unaffected.")
    assert parsed["review_required"]
    assert not parsed["verified_scope"]
    assert enrich_document(n,"This notice has been withdrawn.")["lifecycle"] == "withdrawn"
    assert enrich_document(n,"From 28/09/2026 until 29/09/2026. No port closure is in effect.")["review_required"]
    assert enrich_document(n,"From 28/09/2026 until 29/09/2026. Pilotage is suspended.")["verified_scope"]
    assert enrich_document(n,"From 28/09/2026 until 29/09/2026. Pilotage is suspended.")["review_required"]
    precise = enrich_document(n,"From 2026-09-28T06:00:00Z until 2026-09-29T06:00:00Z. Pilotage is suspended.")
    assert precise["operations"] == ["pilotage"]
    assert not precise["review_required"]


def test_failed_refresh_preserves_success_timestamp_and_snapshot(tmp_path):
    manager = AuthorityNoticeManager(tmp_path/'notices.json')
    manager.payload={"notices":[{**notice(),"adapter_id":"pilbara-hedland"}],"source_status":{"pilbara-hedland":{"last_success_at":NOW.isoformat()}}}
    manager.refresh_source=AsyncMock(side_effect=RuntimeError("source unavailable"))
    asyncio.run(manager.refresh())
    assert manager.payload["notices"][0]["issued_at"] == NOW.isoformat()
    assert manager.payload["source_status"]["pilbara-hedland"]["last_success_at"] == NOW.isoformat()
    assert manager.payload["source_status"]["pilbara-hedland"]["error"]


def test_filters_and_export_are_exact_same_rows_with_provenance():
    payload = filter_outlook(build([forecast(weather_condition="Rain")]), country="AU", operation="loading/discharge", forecast_window="0-24", assessment="Weather watch")
    records = list(csv.DictReader(io.StringIO(outlook_csv(payload))))
    assert [r["row_id"] for r in records] == [r["row_id"] for r in payload["rows"]]
    assert all(r["provenance"] and r["freshness"] for r in records)
    assert not filter_outlook(payload, country="GB")["rows"]


def test_unmatched_neighbouring_terminal_forecast_is_not_promoted():
    payload = build([forecast(location_name="Newcastle Coal Neighbour Terminal",wind_speed_max_kn=50)])
    assert payload["unmatched_records"]
    assert all(r["assessment"] == "Not assessed" for r in payload["rows"])
