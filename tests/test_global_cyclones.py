import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import app, global_cyclone_manager
from global_cyclones import build_cyclone_records


class GlobalCycloneNormalizationTests(unittest.TestCase):
    def test_builds_track_landfall_context_and_affected_ports(self):
        events = {
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [80.0, 15.0]},
                "properties": {
                    "eventid": 1001, "episodeid": 4, "eventname": "TEST-26",
                    "name": "Tropical Cyclone TEST-26", "description": "Tropical Cyclone TEST-26",
                    "iscurrent": "true", "fromdate": "2026-08-10T00:00:00",
                    "todate": "2026-08-13T00:00:00", "datemodified": "2026-08-11T06:00:00",
                    "alertlevel": "Orange", "alertscore": 2, "source": "RSMC New Delhi",
                    "affectedcountries": [{"countryname": "India"}],
                    "severitydata": {"severity": 148.0, "severitytext": "Tropical Cyclone (148 km/h)"},
                    "url": {"report": "https://gdacs.test/report", "geometry": "https://gdacs.test/geometry"},
                },
            }]
        }
        geometry = {
            "1001": {"features": [
                {"geometry": {"type": "LineString", "coordinates": [[78.0, 14.0], [80.0, 15.0]]}, "properties": {"forecast": False}},
                {"geometry": {"type": "LineString", "coordinates": [[80.0, 15.0], [82.0, 16.0]]}, "properties": {"forecast": True, "countryonland": "India"}},
                {"geometry": {"type": "LineString", "coordinates": [[82.0, 16.0], [84.0, 17.0]]}, "properties": {"forecast": True, "countryonland": "India"}},
                {"geometry": {"type": "Polygon", "coordinates": [[[79.0, 14.0], [85.0, 14.0], [85.0, 18.0], [79.0, 18.0], [79.0, 14.0]]]}, "properties": {"polygonlabel": "Uncertainty Cones"}},
            ]}
        }
        ports = [
            {"id": "near", "name": "Near Port", "country": "India", "lat": 16.1, "lon": 82.1},
            {"id": "gem-terminal-near", "name": "Near Port Coal Terminal", "country": "India", "lat": 16.1, "lon": 82.1, "specialist_terminal": True},
            {"id": "another-terminal", "name": "Nearby Trans-shipment Terminal", "country": "India", "lat": 16.2, "lon": 82.2},
            {"id": "far", "name": "Far Port", "country": "India", "lat": 30.0, "lon": 60.0},
        ]
        rows = build_cyclone_records(events, geometry, ports, datetime(2026, 8, 11, 8, tzinfo=timezone.utc))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["alert_level"], "Orange")
        self.assertEqual(row["ocean_or_sea"], "Bay of Bengal")
        self.assertEqual(row["forecast_track"], [[15.0, 80.0], [16.0, 82.0], [17.0, 84.0]])
        self.assertEqual(row["movement_direction"], "northeast")
        self.assertIn("India", row["possible_landfall"])
        self.assertEqual([port["port_name"] for port in row["affected_ports"]], ["Near Port"])
        self.assertIsNotNone(row["forecast_cone"])

    def test_excludes_expired_current_flag(self):
        events = {"features": [{
            "geometry": {"type": "Point", "coordinates": [130, 20]},
            "properties": {"eventid": 9, "iscurrent": "true", "todate": "2026-08-01T00:00:00"},
        }]}
        rows = build_cyclone_records(events, {}, [], datetime(2026, 8, 11, tzinfo=timezone.utc))
        self.assertEqual(rows, [])


class GlobalCycloneApiTests(unittest.TestCase):
    def setUp(self):
        self.previous = global_cyclone_manager.payload
        global_cyclone_manager.payload = {
            "provider": "GDACS", "fetched_at": "2026-08-11T08:00:00+00:00",
            "rows": [{
                "provider": "Global Disaster Alert and Coordination System",
                "source_agency": "JTWC", "location_type": "storm",
                "location_id": "gdacs-tc-1001", "location_name": "Tropical Cyclone TEST-26",
                "event_id": "1001", "alert_level": "Orange", "basin": "Northwest Pacific Ocean",
                "ocean_or_sea": "Western Pacific", "latitude": 20.0, "longitude": 140.0,
                "issued_at": "2026-08-11T08:00:00", "valid_from": "2026-08-10T00:00:00",
                "valid_to": "2026-08-13T00:00:00", "weather_condition": "Typhoon",
                "max_wind_kmph": 160, "max_wind_kn": 86.4, "movement_direction": "northwest",
                "movement_bearing_deg": 315, "affected_countries": ["Japan"],
                "possible_landfall": "Possible coastal impact or landfall area: Japan.",
                "impact_radius_km": 320, "affected_port_count": 1,
                "affected_ports": [{"port_name": "Tokyo", "country": "Japan", "distance_to_forecast_track_km": 95}],
                "impact_methodology": "Proximity estimate", "source_url": "https://www.gdacs.org/",
                "forecast_disclaimer": "Not for navigation.",
            }],
        }
        self.client = TestClient(app)

    def tearDown(self):
        global_cyclone_manager.payload = self.previous

    def test_cyclone_api_and_csv(self):
        response = self.client.get("/api/weather/cyclones")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"][0]["affected_port_count"], 1)
        exported = self.client.get("/api/weather/cyclones/export.csv")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("Tropical Cyclone TEST-26", exported.text)
        self.assertIn("Tokyo", exported.text)


if __name__ == "__main__":
    unittest.main()
