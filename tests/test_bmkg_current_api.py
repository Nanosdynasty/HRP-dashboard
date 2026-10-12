import asyncio
import json
from pathlib import Path

import httpx
import pytest

from bmkg_marine_weather import BmkgMarineWeatherManager, SCHEMA_VERSION, modern_inventory, normalize_modern
from port_disruption_outlook import OutlookEngine

META = {'id': 'XJ001', 'name': 'Pelabuhan Tanjung Priok', 'lat': -6.1, 'lon': 106.9}
PORT = {'id': '50970', 'name': 'JAKARTA', 'country': 'ID', 'country_name': 'Indonesia', 'lat': -6.1, 'lon': 106.9, 'categories': ['dry_bulk']}


def document():
    sample = {'weather': 'Hujan Ringan', 'wind_speed': 12, 'wind_gust': 24, 'wave_height': 0, 'current_speed': 1.5, 'visibility': 10, 'tides': .4}
    return {'code': 'XJ001', 'name': META['name'], 'issued': '2026-09-27 12:00 UTC', 'valid_to': '2026-09-28 06:00 UTC', 'forecast_day1': [{**sample, 'time': f'2026-09-28 {h:02}:00 UTC'} for h in [0, 1, 3, 6]]}


def test_modern_grid_units_and_endpoint_boundary():
    rows = normalize_modern(document(), META, 'port')
    assert len(rows) == 3
    assert rows[0]['valid_to'] == rows[1]['valid_from']
    assert rows[-1]['valid_to'] == '2026-09-28T06:00:00+00:00'
    assert rows[0]['wave_height_max_m'] == 0
    assert rows[0]['current_speed_documented_unit'] == 'kt'
    assert rows[0]['visibility_documented_unit'] == 'km'
    assert rows[0]['gust_kmph'] == pytest.approx(44.448, abs=.01)
    assert rows[0]['weather_condition'] == 'Light rain'
    assert rows[0]['source_url'].endswith('/marine2026-data/pelabuhan/XJ001.json')
    assert rows[0]['port_visibility_tier'] == 1
    assert 'high_tide_height_m' not in rows[0]


def test_missing_grid_samples_do_not_invent_coverage():
    payload = document()
    payload['forecast_day1'] = [payload['forecast_day1'][0], payload['forecast_day1'][-1]]
    assert normalize_modern(payload, META, 'port') == []
    with pytest.raises(ValueError, match='does not match'):
        normalize_modern(payload, {**META, 'id': 'OTHER'}, 'port')


def test_province_inventory_and_compact_geometry_cache(tmp_path):
    assert modern_inventory({'data': [{'province': 'Jakarta', 'ports': [META]}]}, 'port')[0]['province'] == 'Jakarta'
    geometry = {'type': 'Polygon', 'coordinates': [[[106, -7], [107, -7], [107, -6], [106, -6], [106, -7]]]}
    cache = tmp_path / 'bmkg.json'
    cache.write_text(json.dumps({'schema_version': SCHEMA_VERSION, 'water_geometries': {'M.1': geometry}, 'rows': [{'location_type': 'water', 'water_code': 'M.1'}]}))
    assert BmkgMarineWeatherManager(cache).payload['rows'][0]['geometry'] == geometry


def test_partial_download_failure_preserves_actual_success_timestamp(tmp_path):
    manager = BmkgMarineWeatherManager(tmp_path / 'bmkg.json')
    old = {'source_file': 'port/FAIL.json', 'fetched_at': '2026-09-15T00:00:00Z'}
    manager.payload = {'rows': [old]}
    def transport(request):
        return httpx.Response(404) if 'FAIL' in request.url.path else httpx.Response(200, json=document())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await manager._fetch_modern(client, [META, {**META, 'id': 'FAIL'}], 'port', {})
    rows, errors, successes = asyncio.run(run())
    assert successes == 1 and len(errors) == 1
    assert old in rows and old['fetched_at'] == '2026-09-15T00:00:00Z'
    assert any(r.get('fetched_at') != old['fetched_at'] for r in rows)


def test_indonesian_point_matching_is_country_and_scope_safe():
    engine = OutlookEngine([PORT])
    row = normalize_modern(document(), META, 'port')[0]
    assert engine.match_weather_port(row)['id'] == PORT['id']
    assert engine.match_weather_port({**row, 'latitude': 4, 'longitude': 95}) is None
    assert engine.match_weather_port({**row, 'location_name': 'Pelabuhan Kariangau, Balikpapan'}) is None
    assert engine.match_weather_port({**row, 'country': 'Australia'}) is None


def test_official_area_contains_port_without_neighbouring_terminal_join():
    engine = OutlookEngine([PORT, {**PORT, 'id': 'outside', 'name': 'OUTSIDE', 'lon': 108}, {**PORT, 'id': 'au', 'country': 'AU'}])
    row = {'provider_code': 'bmkg', 'country': 'Indonesia', 'location_type': 'water', 'location_id': 'bmkg-water-M.1', 'location_name': 'Official marine area', 'geometry': {'type': 'Polygon', 'coordinates': [[[106, -7], [107, -7], [107, -6], [106, -6], [106, -7]]]}}
    mapped = engine.map_bmkg_areas([row])
    assert len(mapped) == 1
    assert mapped[0]['catalog_port_id'] == PORT['id']
    assert mapped[0]['weather_resolution'] == 'marine-area forecast mapped to a port'
    assert engine.match_weather_port(mapped[0])['id'] == PORT['id']
