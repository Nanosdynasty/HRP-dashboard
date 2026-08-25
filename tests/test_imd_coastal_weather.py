import unittest

from fastapi.testclient import TestClient

from app import app, imd_coastal_weather_manager
from imd_coastal_weather import (
    discover_pdf_urls,
    expand_imd_records,
    latest_document_date,
    merge_records,
    parse_coastal_bulletin_html,
    parse_five_day_warning_text,
)


class ImdCoastalWeatherParserTests(unittest.TestCase):
    def test_discovers_only_official_asset_pdfs(self):
        page = """
        <a href=../../backend/assets/cwc_pdf/current.pdf>Current</a>
        <a href="https://example.com/not-official.pdf">Other</a>
        <a href="/Forecast/unrelated.pdf">Wrong directory</a>
        """
        self.assertEqual(
            discover_pdf_urls(page),
            [
                "https://mausam.imd.gov.in/backend/assets/"
                "cwc_pdf/current.pdf"
            ],
        )

    def test_parses_current_coastal_html_values(self):
        page = """
        <p>Coastal Weather Bulletin DAILY TWO Bulletin Valid for 12 hrs
        from 22 UTC of 2026-07-30 to 10 UTC of 2026-07-31</p>
        <table><tr><td>North Kerala coast</td><td>Wind</td>
        <td>WEST, 15 - 20 KNOTS GUSTING TO 30 KNOTS</td></tr>
        <tr><td>Weather</td><td>WIDESPREAD RAIN / THUNDERSTORM</td></tr>
        <tr><td>Storm Surge/Tidal Warning</td>
        <td>HIGH WAVES IN THE RANGE OF 2.8 - 3.4 METERS</td></tr></table>
        <p>Time of Issue 21:18 IST of 2026-07-30</p>
        """
        rows = parse_coastal_bulletin_html(page, "https://imd.test/current")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["zone_id"], "north_kerala")
        self.assertEqual(row["wind_speed_max_kmph"], 37.0)
        self.assertEqual(row["gust_kmph"], 55.6)
        self.assertEqual(row["wave_height_max_m"], 3.4)
        self.assertEqual(row["rainfall_category"], "Widespread rain")

    def test_parses_wrapped_five_day_warning_text(self):
        text = """
        Time of Issue: 1730 IST
        DAY 2- Squally Weather with wind speed 50-60 kmph gusting to
        70 kmph is likely to prevail along & off North Gujarat coast
        adjoining South Gujarat coast.
        DAY 3- Squally weather with wind speed 40-50 kmph gusting to
        60 kmph along and off Karnataka coast.
        """
        rows = parse_five_day_warning_text(text, "https://imd.test/five-day.pdf")
        merged = merge_records(rows)
        north = next(
            row for row in merged
            if row["zone_id"] == "north_gujarat" and row["day"] == 2
        )
        south = next(
            row for row in merged
            if row["zone_id"] == "south_gujarat" and row["day"] == 2
        )
        karnataka = next(
            row for row in merged
            if row["zone_id"] == "karnataka" and row["day"] == 3
        )
        self.assertEqual(north["gust_kmph"], 70)
        self.assertEqual(south["wind_speed_max_kmph"], 60)
        self.assertEqual(karnataka["wind_speed_min_kmph"], 40)

    def test_detects_latest_document_date_for_stale_source_guard(self):
        latest = latest_document_date(
            "Issued 18-06-2024. Forecast valid 31/07/2026 to 02.08.2026."
        )
        self.assertEqual(latest.date().isoformat(), "2026-08-02")

    def test_expands_imd_zone_to_shared_area_and_port_cards(self):
        record = {
            "zone_id": "north_gujarat", "zone_name": "North Gujarat coast", "day": 1,
            "rainfall_category": "Widespread rain", "wind_speed_min_kmph": 40,
            "wind_speed_max_kmph": 55, "gust_kmph": 65,
            "wave_height_min_m": 2.5, "wave_height_max_m": 3.2,
            "severity": "advisory", "summary": "Widespread rain · 40–55 km/h",
            "source_issue_time": "1730 IST", "source_url": "https://mausam.imd.gov.in/test.pdf",
            "valid_date": "2026-08-11", "geometry": {"type": "Polygon", "coordinates": []},
        }
        rows = expand_imd_records([record])
        self.assertEqual({row["location_type"] for row in rows}, {"water", "port"})
        self.assertEqual(
            {row["location_name"] for row in rows if row["location_type"] == "port"},
            {"Deendayal (Kandla)", "Mundra"},
        )
        port = next(row for row in rows if row["location_type"] == "port")
        self.assertEqual(port["country"], "India")
        self.assertIn("not a port observation", port["forecast_basis"])
        self.assertEqual(port["weather_risk_level"], "High")

    def test_does_not_create_empty_india_weather_cards(self):
        rows = expand_imd_records([{
            "zone_id": "north_gujarat", "zone_name": "North Gujarat coast", "day": 2,
            "rainfall_category": None, "wind_speed_min_kmph": None,
            "wind_speed_max_kmph": None, "gust_kmph": None,
            "wave_height_min_m": None, "wave_height_max_m": None,
        }])
        self.assertEqual(rows, [])


class ImdCoastalWeatherApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = imd_coastal_weather_manager.payload
        imd_coastal_weather_manager.payload = {
            "provider": "India Meteorological Department",
            "fetched_at": "2026-07-31T00:00:00+00:00",
            "rows": [
                {
                    "zone_id": "north_gujarat",
                    "zone_name": "North Gujarat coast",
                    "day": 1,
                    "rainfall_category": "Heavy",
                    "wind_speed_min_kmph": 40,
                    "wind_speed_max_kmph": 50,
                    "gust_kmph": 60,
                    "wave_height_min_m": 2.5,
                    "wave_height_max_m": 3.2,
                    "severity": "warning",
                    "summary": "Heavy · 40–50 km/h",
                    "source_issue_time": "1730 IST",
                    "source_url": "https://mausam.imd.gov.in/test.pdf",
                    "valid_date": "2026-07-31",
                    "geometry": {"type": "Polygon", "coordinates": []},
                },
                {
                    "zone_id": "north_gujarat",
                    "zone_name": "North Gujarat coast",
                    "day": 2,
                    "rainfall_category": None,
                },
            ],
        }
        self.client = TestClient(app)

    def tearDown(self):
        imd_coastal_weather_manager.payload = self.previous

    def test_day_filter_and_csv_download(self):
        response = self.client.get("/api/imd/coastal-weather?day=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["rows"]), 3)
        self.assertEqual({row["location_type"] for row in response.json()["rows"]}, {"water", "port"})
        self.assertTrue(all(row["day"] == 1 for row in response.json()["rows"]))

        export = self.client.get("/api/imd/coastal-weather/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.headers["content-type"])
        self.assertIn("North Gujarat coast", export.text)
        self.assertIn("Deendayal (Kandla)", export.text)


if __name__ == "__main__":
    unittest.main()
