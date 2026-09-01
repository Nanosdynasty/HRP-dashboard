import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import app
from river_levels import (
    _amazon_records, _gatun_record, _noaa_record, _three_gorges_record,
    _three_gorges_yichang_record, SOURCE_CATALOG, commercial_trade_role,
    export_river_levels_xlsx,
)


class RiverLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_cached_api_exposes_levels_sources_and_guardrail(self):
        response = self.client.get("/api/river-levels")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["rows"]), 15)
        self.assertIn("Gauge height is not navigable depth", payload["disclaimer"])
        waterways = {row["waterbody"] for row in payload["rows"]}
        self.assertIn("Mississippi River", waterways)
        self.assertIn("Amazon River", waterways)
        self.assertIn("Rhine", waterways)
        self.assertTrue(any(row["waterbody_type"] == "reservoir" for row in payload["rows"]))
        self.assertTrue(all(len(row.get("history", [])) <= 120 for row in payload["rows"]))
        self.assertTrue(all("history_total_count" in row for row in payload["rows"]))
        self.assertTrue(all(row.get("trade_relevance") for row in payload["rows"]))
        self.assertTrue(all(row["country"] not in {"Bangladesh", "India"} for row in payload["rows"]))
        self.assertTrue(all(commercial_trade_role(row) for row in payload["rows"]))

    def test_source_directory_is_official_and_actionable(self):
        response = self.client.get("/api/river-levels/sources")
        self.assertEqual(response.status_code, 200)
        sources = response.json()["sources"]
        self.assertEqual(len(sources), len(SOURCE_CATALOG))
        ids = {source["id"] for source in sources}
        self.assertTrue({"noaa-nwps", "ana-amazon", "pegelonline", "acp-gatun", "mrc-mekong", "three-gorges-watch"}.issubset(ids))
        self.assertTrue({"bangladesh-ffwc", "india-cwc", "india-iwai-lad", "usbr-rise"}.isdisjoint(ids))
        self.assertTrue(all(source["region"] not in {"Bangladesh", "India"} for source in sources))
        self.assertTrue(all(source["url"].startswith("https://") for source in sources))
        connected = [source for source in sources if source["integration_status"] == "connected"]
        self.assertTrue(all(source["status"] in {"active", "no_current_record"} for source in connected))

    def test_csv_export_contains_comparable_level_fields(self):
        response = self.client.get("/api/river-levels/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("station,waterbody,basin,country,waterbody_type", response.text)
        self.assertIn("normal_level", response.text)
        self.assertIn("difference_from_normal", response.text)
        self.assertIn("trade_relevance", response.text.splitlines()[0])
        self.assertNotIn(",Bangladesh,", response.text)
        self.assertNotIn(",India,", response.text)
        self.assertNotIn("forecast_level", response.text.splitlines()[0])
        self.assertIn("source_name", response.text)

    def test_excel_export_has_analysis_sheets(self):
        response = self.client.get("/api/river-levels/export.xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"PK"))
        self.assertIn("spreadsheetml", response.headers["content-type"])

    def test_noaa_record_does_not_call_stage_navigation_depth(self):
        row = _noaa_record({
            "lid": "TEST", "name": "Test River", "latitude": 1, "longitude": 2,
            "status": {"observed": {"primary": 8.2, "primaryUnit": "ft", "validTime": "2026-08-25T00:00:00Z", "floodCategory": "no_flooding"}},
        })
        self.assertEqual(row["level"], 8.2)
        self.assertIn("not channel depth", row["navigation_note"].lower())
        self.assertEqual(row["navigation_status"], "Not assessed by this feed")

    def test_three_gorges_workbook_produces_china_reservoir_and_river_records(self):
        reservoir = _three_gorges_record()
        river = _three_gorges_yichang_record()
        self.assertEqual(reservoir["country"], "China")
        self.assertEqual(reservoir["waterbody_type"], "reservoir")
        self.assertEqual(reservoir["observed_at"], "2026-07-31T00:00:00+08:00")
        self.assertAlmostEqual(reservoir["level"], 151.22)
        self.assertEqual(reservoir["normal_basis"], "Historical July distribution, 2020–2025")
        self.assertGreater(len(reservoir["history"]), 2200)
        self.assertEqual(river["waterbody"], "Yangtze River")
        self.assertEqual(river["waterbody_type"], "river")
        self.assertAlmostEqual(river["level"], 43.41)
        self.assertIn("Yichang", river["quality_note"])


if __name__ == "__main__":
    unittest.main()
