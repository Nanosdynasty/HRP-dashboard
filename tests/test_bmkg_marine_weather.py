import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import app, bmkg_marine_weather_manager
import httpx
from bmkg_marine_weather import BmkgMarineWeatherManager, normalize_port, normalize_water, select_forecast_rows


class BmkgRefreshRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_file_is_retried_without_listing_change(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = BmkgMarineWeatherManager(Path(directory) / 'cache.json')
            files = [{'name': 'port.json', 'file_date': 'new'}]
            previous = [{'source_file': 'port.json', 'weather_condition': 'Old'}]
            calls = []

            def handler(request):
                calls.append(request)
                if len(calls) == 1:
                    return httpx.Response(503)
                return httpx.Response(200, json={'weather': 'New'})

            def normalizer(payload, filename):
                return [{'source_file': filename, 'weather_condition': payload['weather']}]

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                rows, dates, errors = await manager._fetch_changed(
                    client, files, 'https://example.test/{file_name}', normalizer, previous, {'port.json': 'old'})
                self.assertEqual(rows, previous)
                self.assertEqual(dates['port.json'], 'old')
                self.assertTrue(errors)
                rows, dates, errors = await manager._fetch_changed(
                    client, files, 'https://example.test/{file_name}', normalizer, rows, dates)
                self.assertEqual(len(calls), 2)
                self.assertEqual(rows[0]['weather_condition'], 'New')
                self.assertEqual(dates['port.json'], 'new')
                self.assertFalse(errors)

    async def test_missing_rows_are_fetched_even_when_timestamp_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = BmkgMarineWeatherManager(Path(directory) / 'cache.json')
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={'ok': True}))) as client:
                rows, dates, errors = await manager._fetch_changed(
                    client, [{'name': 'port.json', 'file_date': 'new'}],
                    'https://example.test/{file_name}',
                    lambda payload, filename: [{'source_file': filename}], [], {'port.json': 'new'})
                self.assertEqual(len(rows), 1)
                self.assertFalse(errors)

    def test_old_cache_is_marked_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = BmkgMarineWeatherManager(Path(directory) / 'cache.json')
            manager.payload = {'fetched_at': '2000-01-01T00:00:00Z', 'rows': []}
            self.assertTrue(manager.selected_payload()['stale'])
            self.assertGreater(manager.selected_payload()['refresh_age_hours'], 3)

    def test_seed_cache_is_loaded_when_runtime_cache_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / 'seed.json'
            seed.write_text(
                '{"schema_version":3,"fetched_at":"2026-08-04T00:00:00+00:00","rows":[{"location_id":"bmkg-port-1"}]}',
                encoding='utf-8',
            )
            manager = BmkgMarineWeatherManager(Path(directory) / 'cache.json', seed_path=seed)
            self.assertEqual(manager.payload['rows'][0]['location_id'], 'bmkg-port-1')


class BmkgMarineWeatherNormalizationTests(unittest.TestCase):
    def test_normalizes_rich_port_forecast(self):
        rows = normalize_port(
            {
                "port_id": "0088", "name": "Sintete", "latitude": 1.2,
                "longitude": 109.05, "type": "utama",
                "data": [{
                    "issued": "2026-08-03 23:47 UTC",
                    "valid_from": "2026-08-04 00:00 UTC",
                    "valid_to": "2026-08-04 12:00 UTC",
                    "weather": "Hujan Lebat", "warning_desc": "Waspada gelombang",
                    "wind_from": "Timur", "wind_to": "Utara",
                    "wind_speed_min": 7, "wind_speed_max": 18,
                    "wave_cat": "Sedang", "wave_desc": "1.25 - 2.5 m",
                    "current_from": "Timur Laut", "current_to": "Timur",
                    "current_speed_min": 0.13, "current_speed_max": 0.38,
                    "visibility": 1434, "rh_min": 89, "rh_max": 100,
                    "temp_min": 25, "temp_max": 29,
                    "low_tide": -0.62, "low_tide_time": "2026-08-04 07:00 UTC",
                    "high_tide": 0.84, "high_tide_time": "2026-08-04 12:00 UTC",
                }],
            },
            "0088_Sintete.json",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["location_id"], "bmkg-port-0088")
        self.assertEqual(rows[0]["wave_height_max_m"], 2.5)
        self.assertEqual(rows[0]["wind_speed_max_kn"], 18)
        self.assertEqual(rows[0]["weather_condition"], "Heavy rain")
        self.assertEqual(rows[0]["wind_direction_from"], "East")
        self.assertIn("Warning:", rows[0]["warning_description"])
        self.assertIn("winds 7–18 kt from East", rows[0]["weather_description"])
        self.assertEqual(rows[0]["severity"], "warning")
        self.assertEqual(rows[0]["current_speed_documented_unit"], "cm/s")
        self.assertIsNone(rows[0]["visibility_documented_unit"])

    def test_water_geometry_and_time_selection(self):
        geometry = {"type": "Polygon", "coordinates": [[[100, 0], [101, 0], [100, 0]]]}
        rows = normalize_water(
            {
                "code": "R.07", "name": "Perairan Merauke", "issued": "2026-08-04 00:00 UTC",
                "data": [
                    {"valid_from": "2026-08-04 00:00 UTC", "valid_to": "2026-08-04 12:00 UTC", "weather": "Berawan", "wave_desc": "0.5 - 1.25 m"},
                    {"valid_from": "2026-08-04 12:00 UTC", "valid_to": "2026-08-05 00:00 UTC", "weather": "Hujan", "wave_desc": "1.25 - 2.5 m"},
                ],
            },
            "R.07_Perairan Merauke.json",
            {"R.07": geometry},
        )
        selected = select_forecast_rows(
            rows, 13, now=datetime(2026, 8, 4, tzinfo=timezone.utc)
        )
        self.assertEqual(selected[0]["weather_condition"], "Rain")
        self.assertTrue(selected[0]["location_name"].startswith("Waters"))
        self.assertEqual(selected[0]["geometry"], geometry)


class BmkgMarineWeatherApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = bmkg_marine_weather_manager.payload
        bmkg_marine_weather_manager.payload = {
            "provider": "BMKG", "provider_code": "bmkg",
            "fetched_at": "2026-08-04T00:00:00+00:00",
            "inventory": {"ports": 1, "waters": 0},
            "rows": [{
                "provider": "BMKG", "provider_code": "bmkg", "country": "Indonesia",
                "location_type": "port", "location_id": "bmkg-port-1",
                "location_name": "Test Port", "source_file": "1_Test.json",
                "valid_from": "2026-08-04 00:00 UTC", "valid_to": "2026-08-05 00:00 UTC",
                "wind_speed_max_kn": 12, "wave_height_max_m": 1.2,
            }],
        }
        self.client = TestClient(app)

    def tearDown(self):
        bmkg_marine_weather_manager.payload = self.previous

    def test_forecast_endpoint_and_csv_export(self):
        response = self.client.get("/api/bmkg/marine-weather?hours=12")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"][0]["location_name"], "Test Port")
        export = self.client.get("/api/bmkg/marine-weather/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("Test Port", export.text)


if __name__ == "__main__":
    unittest.main()
