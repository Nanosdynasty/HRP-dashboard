"""The ECA line, exposure and bundled water geometry must agree."""
import json
import unittest
from pathlib import Path

from shapely.geometry import Point, box, mapping, shape
from shapely.ops import unary_union

from maritime_extras import _haversine_nm, _split_route_eca, analyze_route_zones


def feature(zone_id, polygon):
    return {"type": "Feature", "geometry": mapping(polygon),
            "properties": {"id": zone_id, "risk_family": "eca", "zone_type": "ECA"}}


class EcaRouteSegmentTests(unittest.TestCase):
    def test_entry_exit_multiple_areas_and_continuity(self):
        zones = [feature("first", box(1, -1, 2, 1)),
                 feature("second", box(3, -1, 4, 1))]
        parts = _split_route_eca([[0, 0], [5, 0]], zones)
        self.assertEqual([part["zone_ids"] for part in parts],
                         [[], ["first"], [], ["second"], []])
        self.assertEqual(parts[0]["coordinates"][0], [0.0, 0.0])
        self.assertEqual(parts[-1]["coordinates"][-1], [5.0, 0.0])
        for left, right in zip(parts, parts[1:]):
            self.assertEqual(left["coordinates"][-1], right["coordinates"][0])
        green = sum(part["distance_nm"] for part in parts if part["in_eca"])
        self.assertAlmostEqual(green, 2 * _haversine_nm([0, 0], [1, 0]), delta=0.005)

    def test_route_starting_inside_and_missing_boundary(self):
        parts = _split_route_eca([[1.5, 0], [3, 0]],
                                 [feature("first", box(1, -1, 2, 1))])
        self.assertEqual([part["in_eca"] for part in parts], [True, False])
        self.assertEqual(parts[0]["coordinates"][0], [1.5, 0.0])
        unknown = _split_route_eca([[0, 0], [1, 0]], [])
        self.assertEqual(unknown[0]["boundary_status"], "unverified")
        self.assertFalse(unknown[0]["in_eca"])

    def test_bundled_eca_areas_are_water_only_and_green_distance_matches(self):
        root = Path(__file__).resolve().parents[1]
        snapshot = json.loads((root / "data/imo_eca_verified.geojson").read_text(encoding="utf-8"))
        land_json = json.loads((root / "data/voyage_land_50m.geojson").read_text(encoding="utf-8"))
        land = unary_union([shape(item["geometry"]) for item in land_json["features"]])
        self.assertEqual(len(snapshot["features"]), 7)
        for item in snapshot["features"]:
            geometry = shape(item["geometry"])
            self.assertTrue(geometry.is_valid, item["properties"]["id"])
            self.assertLess(geometry.intersection(land).area, 1e-7)
            self.assertGreater(len(str(item["geometry"])), 1000)  # no screening rectangles
            self.assertTrue(item["properties"]["source_url"].startswith("https://"))
        summary = analyze_route_zones([[-6, 55], [0, 55], [3, 55]])
        self.assertEqual([s["in_eca"] for s in summary["eca_segments"]], [False, True])
        self.assertAlmostEqual(summary["eca_distance_nm"],
                               sum(s["distance_nm"] for s in summary["eca_segments"] if s["in_eca"]),
                               delta=0.05)
        self.assertTrue(summary["requires_mgo"])
        self.assertFalse(land.contains(Point(0, 55)))


if __name__ == "__main__":
    unittest.main()
