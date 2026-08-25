import unittest
import io
from unittest.mock import AsyncMock, patch

import pandas as pd
from fastapi.testclient import TestClient

from app import (
    AisLiveManager,
    NPP_CACHE_TTL_SECONDS,
    _compute_route,
    _compute_curated_corridor,
    _haversine_nm,
    _infer_passage,
    _route_with_endpoints,
    _transform_npp_power,
    app,
)


class PortApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_reports_port_catalog_and_secret_state(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], "4.0.0")
        self.assertGreaterEqual(payload["ports"]["total"], 3_600)
        self.assertIn("ais_configured", payload)

    def test_facets_and_filtered_port_list(self):
        facets = self.client.get("/api/ports/facets")
        self.assertEqual(facets.status_code, 200)
        self.assertGreater(facets.json()["summary"]["dry_bulk"], 300)

        response = self.client.get(
            "/api/ports",
            params={"categories": "dry_bulk", "min_channel_m": 10, "limit": 25},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertLessEqual(len(payload["data"]), 25)
        self.assertTrue(payload["data"])
        self.assertTrue(
            all("dry_bulk" in port["categories"] for port in payload["data"])
        )
        self.assertTrue(
            all(port["channel_depth_m"] >= 10 for port in payload["data"])
        )

    def test_port_detail_and_unknown_port(self):
        listing = self.client.get(
            "/api/ports", params={"categories": "dry_bulk", "limit": 1}
        ).json()
        port_id = listing["data"][0]["id"]
        detail = self.client.get(f"/api/ports/{port_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("sources", detail.json())
        self.assertIn("facilities", detail.json())

        missing = self.client.get("/api/ports/not-a-real-port")
        self.assertEqual(missing.status_code, 404)

    def test_invalid_export_tracker_is_rejected(self):
        response = self.client.get("/api/export/not-a-real-tracker")
        self.assertEqual(response.status_code, 404)

    def test_uploaded_bundle_map_layers_are_available(self):
        expected = {
            "coal_mines": 5_382,
            "iron_ore_mines": 949,
            "iron_ore_terminals": 46,
            "steel_plants": 1_293,
            "cement_plants": 3_513,
            "geothermal": 835,
            "bioenergy": 4_537,
            "coal_trade_terminals": 519,
        }
        for layer, count in expected.items():
            with self.subTest(layer=layer):
                response = self.client.get(
                    f"/api/map/{layer}", params={"limit": 150_000}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json()), count)

    def test_india_coal_plant_cards_expose_rich_and_official_fields(self):
        response = self.client.get(
            "/api/map/coal_plants",
            params={
                "country": "India",
                "status": "operating",
                "limit": 150_000,
            },
        )
        self.assertEqual(response.status_code, 200)
        wardha = next(
            item
            for item in response.json()
            if item["name"] == "Wardha Warora Power Plant"
        )
        self.assertEqual(wardha["plant_capacity"], 540)
        self.assertEqual(wardha["unit_count"], 4)
        self.assertEqual(wardha["state"], "Maharashtra")
        self.assertEqual(wardha["coal_source"], "Western Coalfields")
        self.assertTrue(wardha["cea_verified"])
        self.assertEqual(wardha["cea_capacity_mw"], 540)
        self.assertEqual(wardha["cea_commissioning"], "2010–2011")
        self.assertIn("cea.nic.in", wardha["cea_source_url"])
        self.assertIn("npp.gov.in", wardha["npp_source_url"])
        self.assertIn("coal.gov.in", wardha["ministry_coal_source_url"])

    def test_sidebar_workspace_and_route_ui_regressions(self):
        html = self.client.get("/").text
        javascript = self.client.get("/static/js/app.js").text
        self.assertNotIn('data-mode="ports" open', html)
        self.assertIn("state.routePorts[state.routePickIndex] = port", javascript)
        start_route = javascript.split("function startRoutePicking()", 1)[1]
        start_route = start_route.split("function updateRouteSelection()", 1)[0]
        self.assertNotIn("resetRoute(", start_route)
        self.assertIn(
            'document.querySelector(".voyage-section").open',
            javascript,
        )
        self.assertIn(
            "state.routePorts[state.routePickIndex] = port",
            javascript,
        )
        activate_mode = javascript.split("function activateMode(mode)", 1)[1]
        activate_mode = activate_mode.split("function loadAisPreferences()", 1)[0]
        self.assertIn(
            "[state.aisLayer, state.aisTrailLayer, state.routeLayer]",
            activate_mode,
        )

    def test_layer_facets_support_country_status_and_terminal_role_filters(self):
        energy = self.client.get(
            "/api/layer-facets",
            params={"trackers": "coal_plants,solar,wind,hydro,nuclear"},
        )
        self.assertEqual(energy.status_code, 200)
        energy_payload = energy.json()
        self.assertIn("India", {item["id"] for item in energy_payload["countries"]})
        self.assertIn(
            "operating", {item["id"] for item in energy_payload["statuses"]}
        )

        commodities = self.client.get(
            "/api/layer-facets",
            params={
                "trackers": "coal_mines,coal_trade_terminals,iron_ore_mines,iron_ore_terminals,steel_plants"
            },
        )
        self.assertEqual(commodities.status_code, 200)
        commodity_payload = commodities.json()
        countries = {item["id"] for item in commodity_payload["countries"]}
        terminal_types = {item["id"] for item in commodity_payload["asset_types"]}
        self.assertTrue({"Australia", "China", "India"}.issubset(countries))
        self.assertIn("Exports", terminal_types)
        self.assertIn("Imports", terminal_types)

    def test_iron_ore_terminals_filter_by_country_and_direction_metadata(self):
        india = self.client.get(
            "/api/map/iron_ore_terminals",
            params={"country": "India", "status": "operating", "limit": 150_000},
        )
        self.assertEqual(india.status_code, 200)
        rows = india.json()
        self.assertGreaterEqual(len(rows), 5)
        self.assertTrue(all(row["country"] == "India" for row in rows))
        self.assertTrue(all(row["product_type"] == "Iron ore" for row in rows))
        self.assertTrue(all(row["source_url"] for row in rows))
        self.assertTrue(
            {"Imports / Exports", "Exports"}.issubset(
                {row["asset_type"] for row in rows}
            )
        )

    def test_country_and_status_filters_are_applied_to_map_layers(self):
        response = self.client.get(
            "/api/map/coal_mines",
            params={"country": "India", "status": "operating", "limit": 150_000},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertTrue(rows)
        self.assertTrue(all(row["country"] == "India" for row in rows))
        self.assertTrue(all(row["status"].lower() == "operating" for row in rows))

    def test_route_helpers_preserve_distance_and_antimeridian_continuity(self):
        self.assertAlmostEqual(
            _haversine_nm([0.0, 0.0], [0.0, 1.0]),
            60.04,
            places=1,
        )
        coordinates = _route_with_endpoints(
            [151.2, -33.86],
            [[151.21, -33.85], [240.0, -45.0], [316.85, -22.93]],
            [-43.18, -22.9],
        )
        self.assertAlmostEqual(coordinates[-1][0], 316.82, places=2)
        self.assertTrue(
            all(
                abs(coordinates[index][0] - coordinates[index - 1][0]) <= 180
                for index in range(1, len(coordinates))
            )
        )
        self.assertEqual(
            _infer_passage(
                [[-5.5, 36.0], [32.5, 30.0], [43.0, 13.0], [102.0, 2.0]]
            ),
            "Strait of Gibraltar, Suez Canal, Bab el-Mandeb, Strait of Malacca",
        )

    def test_maritime_route_has_precision_breakdown_and_passages(self):
        route = _compute_route(
            72.866667,
            18.966667,
            103.85,
            1.283333,
            12,
            ["northwest"],
        )
        self.assertGreater(route["distance_nm"], route["great_circle_nm"])
        self.assertAlmostEqual(
            route["distance_nm"],
            route["network_distance_nm"]
            + route["origin_connector_nm"]
            + route["destination_connector_nm"],
            delta=1.0,
        )
        self.assertIn("Strait of Malacca", route["passages"])
        self.assertIn(route["route_confidence"], {"high", "medium", "low"})
        self.assertGreater(route["waypoint_count"], 10)

    def test_dar_es_salaam_port_qasim_uses_normal_maritime_network(self):
        baseline = _compute_route(
            39.3,
            -6.816667,
            67.35,
            24.766667,
            13,
            ["northwest"],
        )
        with (
            patch(
                "app.fetch_weather",
                new=AsyncMock(return_value={"source": "test"}),
            ),
            patch(
                "app.fetch_bunker_prices",
                new=AsyncMock(
                    return_value={
                        "vlsfo_usd_mt": 580,
                        "mgo_usd_mt": 820,
                        "source": "test",
                    }
                ),
            ),
        ):
            response = self.client.post(
                "/api/route",
                json={
                    "from_lon": 39.3,
                    "from_lat": -6.816667,
                    "to_lon": 67.35,
                    "to_lat": 24.766667,
                    "from_port_id": "47010",
                    "to_port_id": "48605",
                    "speed_knots": 13,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["routing_profile"], "maritime-network")
        self.assertEqual(
            payload["method"],
            "searoute 1.6 maritime network + endpoint connector legs",
        )
        self.assertAlmostEqual(payload["distance_nm"], baseline["distance_nm"], delta=1)
        self.assertNotIn("zones", payload)
        self.assertNotIn("risk_avoidance", payload)

    def test_nacala_yanbu_has_no_mandatory_risk_waypoints(self):
        route = _compute_route(
            40.68,
            -14.54,
            38.06,
            24.09,
            13,
            ["northwest"],
        )
        self.assertEqual(route["routing_profile"], "maritime-network")
        self.assertIn("Bab el-Mandeb", route["passages"])
        self.assertFalse(any(
            abs(point[0] - 56.2) < 0.05 and abs(point[1] - 22.8) < 0.05
            for point in route["coordinates"]
        ))

    def test_verified_paradip_richards_bay_corridor_matches_benchmark(self):
        route = _compute_curated_corridor(
            "49535", "46855", 13, ["northwest"]
        )
        self.assertIsNotNone(route)
        self.assertEqual(
            route["routing_profile"], "verified-approach-dense-corridor"
        )
        self.assertAlmostEqual(route["distance_nm"], 4496, delta=25)
        self.assertAlmostEqual(route["duration_days"], 14.41, delta=0.1)
        self.assertGreater(route["waypoint_count"], 150)
        self.assertLessEqual(route["origin_connector_nm"], 0)
        self.assertEqual(len(route["approach_sources"]), 2)
        rbct_route = _compute_curated_corridor(
            "49535",
            "gem-terminal-richards-bay-coal-terminal",
            13,
            ["northwest"],
        )
        self.assertIsNotNone(rbct_route)
        self.assertAlmostEqual(
            rbct_route["distance_nm"], route["distance_nm"], delta=0.1
        )
        with (
            patch(
                "app.fetch_weather",
                new=AsyncMock(return_value={"source": "test"}),
            ),
            patch(
                "app.fetch_bunker_prices",
                new=AsyncMock(
                    return_value={
                        "vlsfo_usd_mt": 580,
                        "mgo_usd_mt": 820,
                        "source": "test",
                    }
                ),
            ),
        ):
            response = self.client.post(
                "/api/route",
                json={
                    "from_lon": 0,
                    "from_lat": 0,
                    "to_lon": 0,
                    "to_lat": 1,
                    "from_port_id": "49535",
                    "to_port_id": "46855",
                    "speed_knots": 13,
                    "sea_margin_pct": 0,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertAlmostEqual(payload["distance_nm"], 4496, delta=25)
        self.assertNotIn("zones", payload)
        self.assertEqual(
            payload["coordinate_source"], "Verified sea-side port approaches"
        )
        self.assertEqual(payload["method"], "HRP verified-approach dense corridor")
        self.assertEqual(
            payload["routing_profile"], "verified-approach-dense-corridor"
        )
        self.assertEqual(len(payload["route_ports"]), 5)
        self.assertTrue(
            all(item["name"] for item in payload["route_ports"])
        )
        self.assertEqual(
            sorted(item["progress_pct"] for item in payload["route_ports"]),
            [item["progress_pct"] for item in payload["route_ports"]],
        )

    def test_route_api_uses_catalogue_ports_and_explicit_time_allowances(self):
        weather = {"source": "test"}
        bunker = {
            "vlsfo_usd_mt": 580,
            "mgo_usd_mt": 820,
            "source": "test",
        }
        with (
            patch("app.fetch_weather", new=AsyncMock(return_value=weather)),
            patch("app.fetch_bunker_prices", new=AsyncMock(return_value=bunker)),
        ):
            response = self.client.post(
                "/api/route",
                json={
                    "from_lon": 0,
                    "from_lat": 0,
                    "to_lon": 0,
                    "to_lat": 1,
                    "from_port_id": "48840",
                    "to_port_id": "50000",
                    "speed_knots": 12,
                    "sea_margin_pct": 10,
                    "port_time_hours": 24,
                    "canal_delay_hours": 6,
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["from_name"], "MUMBAI (BOMBAY)")
        self.assertEqual(payload["to_name"], "KEPPEL - (EAST SINGAPORE)")
        self.assertEqual(payload["coordinate_source"], "World Port Index catalogue")
        self.assertEqual(payload["sea_margin_pct"], 10)
        self.assertGreater(payload["total_duration_hours"], payload["sailing_hours"])
        self.assertAlmostEqual(
            payload["total_duration_hours"] - payload["sailing_hours"],
            30,
            places=1,
        )
        self.assertEqual(payload["fuel"]["consumption_tpd"], 25)
        self.assertIn("not for navigation", payload["warnings"][0].lower())

    def test_india_coal_workspace_uses_verified_assets_without_fake_metrics(self):
        summary = self.client.get("/api/coal/summary")
        self.assertEqual(summary.status_code, 200)
        payload = summary.json()
        self.assertEqual(payload["country"], "India")
        self.assertGreater(payload["map_assets"]["coal_mines"], 0)
        self.assertGreater(payload["map_assets"]["coal_trade_terminals"], 0)
        self.assertIn(payload["status"], {"awaiting_data", "ready"})
        self.assertIn("quality_note", payload)
        stock_cover = payload["metric_definitions"]["stock_cover_days"]
        self.assertEqual(stock_cover["unit"], "days")
        self.assertIn("average daily coal consumption", stock_cover["formula"])

        assets = self.client.get(
            "/api/coal/assets", params={"asset_kind": "coal_mines"}
        )
        self.assertEqual(assets.status_code, 200)
        asset_payload = assets.json()
        self.assertTrue(asset_payload["data"])
        self.assertTrue(
            all(row["country"] == "India" for row in asset_payload["data"])
        )

        operating = self.client.get(
            "/api/coal/assets", params={"status_group": "operating"}
        ).json()["data"]
        self.assertTrue(operating)
        self.assertTrue(all(row["status"] == "Operating" for row in operating))
        dhamra = next(
            row for row in operating
            if row["asset_kind"] == "coal_trade_terminals"
            and row["name"] == "Dhamra Port"
        )
        self.assertEqual(dhamra["status"], "Operating")
        self.assertGreater(dhamra["expansion_capacity"], 0)
        self.assertIn("Under construction", dhamra["expansion_status"])

        construction = self.client.get(
            "/api/coal/assets", params={"status_group": "construction"}
        ).json()["data"]
        self.assertTrue(construction)
        self.assertTrue(
            all(row["project_status"] == "Under construction" for row in construction)
        )
        self.assertFalse(
            any(
                str(row.get("source_status", "")).lower()
                in {"retired", "cancelled", "shelved", "mothballed"}
                for row in construction
            )
        )

    def test_india_coal_ports_have_consolidated_specifications(self):
        response = self.client.get("/api/coal/port-specifications")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["quality_summary"]["asset_rows"], 31)
        self.assertEqual(
            payload["quality_summary"]["matched_to_port_master"], 31
        )
        self.assertEqual(
            payload["quality_summary"]["with_official_website"], 31
        )
        self.assertEqual(
            payload["quality_summary"]["with_documented_draft"], 23
        )
        self.assertEqual(
            payload["quality_summary"]["with_documented_berths"], 30
        )
        self.assertEqual(
            payload["quality_summary"]["with_port_capacity"], 21
        )
        self.assertEqual(
            payload["quality_summary"]["with_facility_records"], 27
        )
        self.assertEqual(
            payload["quality_summary"]["with_commodity_flow_records"], 15
        )
        self.assertEqual(len(payload["berth_facilities"]), 41)
        self.assertEqual(len(payload["commodity_flows"]), 26)
        self.assertEqual(len(payload["research_sources"]), 25)
        self.assertEqual(
            len({item["asset_id"] for item in payload["ports"]}), 31
        )
        self.assertTrue(
            all(len(item["satellite_context"]["views"]) == 3 for item in payload["ports"])
        )
        paradip = next(
            item for item in payload["ports"]
            if item["asset_name"] == "Paradip Port"
        )
        detail = self.client.get(
            f"/api/coal/port-specifications/{paradip['asset_id']}"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["max_documented_draft_m"], 16)
        self.assertGreater(detail.json()["documented_berth_count"], 0)
        self.assertTrue(detail.json()["sources"])

        mundra = next(
            item for item in payload["ports"]
            if item["asset_name"] == "Mundra Port"
        )
        self.assertEqual(mundra["max_documented_draft_m"], 17.5)
        self.assertEqual(mundra["documented_berth_count"], 28)
        self.assertEqual(len(mundra["commodity_flows"]), 1)
        self.assertTrue(
            all(
                item["draft_type"] == "declared"
                for item in mundra["dry_bulk_facilities"]
            )
        )

        dahej = next(
            item for item in payload["ports"]
            if item["asset_name"] == "Dahej Port"
        )
        self.assertEqual(dahej["max_documented_draft_m"], 14)
        self.assertEqual(dahej["documented_dry_bulk_berth_count"], 2)
        self.assertEqual(
            {item["name"] for item in dahej["dry_bulk_facilities"]},
            {"North Berth", "South Berth"},
        )

        bedi = next(
            item for item in payload["ports"]
            if item["asset_name"] == "Bedi Port"
        )
        self.assertIsNone(bedi["max_documented_draft_m"])
        anchorage = next(
            item for item in bedi["dry_bulk_facilities"]
            if item["facility_type"] == "anchorage"
        )
        self.assertEqual(anchorage["draft_m"], 16)
        self.assertIn("not a berth limit", anchorage["draft_conditions"])

        terminals = self.client.get(
            "/api/coal/assets",
            params={
                "asset_kind": "coal_trade_terminals",
                "status_group": "operating",
            },
        ).json()["data"]
        self.assertEqual(len(terminals), 31)
        self.assertTrue(
            all(item["port_specification_available"] for item in terminals)
        )

        port_cards = self.client.get(
            "/api/coal/assets",
            params={
                "asset_kind": "coal_trade_terminals,dry_bulk_ports",
                "status_group": "operating",
                "limit": 20000,
            },
        ).json()["data"]
        canonical_ids = [
            item["canonical_port_id"] for item in port_cards
            if item.get("canonical_port_id")
        ]
        self.assertEqual(len(canonical_ids), len(set(canonical_ids)))
        card_names = {item["name"] for item in port_cards}
        self.assertIn("Bedi Port", card_names)
        self.assertIn("Haldia Port", card_names)
        self.assertIn("Kolkata Dock System Coal Terminal", card_names)
        self.assertNotIn("BEDI", card_names)
        self.assertNotIn("HALDIA PORT", card_names)
        self.assertNotIn("CALCUTTA", card_names)

        export = self.client.get("/api/coal/port-specifications/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn(
            "india_coal_port_specifications.csv",
            export.headers["content-disposition"],
        )
        self.assertIn("Max documented draft (m)", export.text)
        self.assertIn("Facility record count", export.text)
        self.assertIn("Coal flow record count", export.text)

    def test_iron_ore_and_steel_map_records_support_detail_cards(self):
        mines = self.client.get(
            "/api/map/iron_ore_mines",
            params={"status": "operating", "limit": 5000},
        )
        self.assertEqual(mines.status_code, 200)
        mine_rows = mines.json()
        self.assertTrue(mine_rows)
        self.assertTrue(any(row.get("owner") for row in mine_rows))
        self.assertTrue(any(row.get("source_url") for row in mine_rows))
        self.assertTrue(
            any(row.get("production_2024_ktpa") is not None for row in mine_rows)
        )

        steel = self.client.get(
            "/api/map/steel_plants",
            params={"status": "operating", "limit": 5000},
        )
        self.assertEqual(steel.status_code, 200)
        steel_rows = steel.json()
        self.assertTrue(steel_rows)
        self.assertTrue(any(row.get("owner") for row in steel_rows))
        self.assertTrue(any(row.get("source_url") for row in steel_rows))
        self.assertTrue(any(row.get("capacity") is not None for row in steel_rows))
        self.assertTrue(any(row.get("iron_ore_source") for row in steel_rows))

    def test_port_ui_does_not_advertise_unsupported_zero_categories(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('data-mode="coal"', html)
        self.assertNotIn("<span>Oil terminal</span>", html)
        self.assertNotIn("<span>Container</span>", html)
        self.assertNotIn("<span>Liquid bulk</span>", html)
        self.assertNotIn("<span>LNG</span>", html)
        self.assertIn("Stock cover", html)
        self.assertIn("Trade flows", html)
        self.assertIn('<option value="operating" selected>Operating</option>', html)
        self.assertIn("Coal-consuming industries", html)
        self.assertIn("India power", html)
        self.assertIn("Daily generation summary", html)
        self.assertIn("Coal stock availability", html)
        self.assertIn("Cumulative generation", html)
        self.assertIn("Sector-wise PLF", html)
        self.assertIn("app.js?v=20260825-river-levels-04", html)
        self.assertIn("Cargo + tankers + type pending", html)
        self.assertIn('id="ais-watchlist" class="ais-watchlist" hidden', html)
        self.assertIn("positions in the background", html)
        self.assertIn('id="ais-region-options"', html)
        self.assertIn('value="india" checked', html)
        self.assertIn('value="southeast_asia" checked', html)
        self.assertIn('value="world"', html)
        self.assertIn('id="route-from-input" type="search"', html)
        self.assertIn('id="route-to-input" type="search"', html)
        self.assertIn('list="route-port-options"', html)
        self.assertIn('id="route-port-options"', html)
        self.assertIn('id="map-skin"', html)
        self.assertNotIn('id="avoid-piracy"', html)
        self.assertNotIn('id="avoid-jwc"', html)
        self.assertNotIn("JWC area avoided", html)
        self.assertNotIn("JWC area traversable", html)
        self.assertNotIn('id="show-eca-zones"', html)
        self.assertNotIn('id="show-piracy-zones"', html)
        self.assertNotIn(">ECA<", html)
        self.assertNotIn("Security watch", html)

    def test_ais_status_and_trail_validation(self):
        status_response = self.client.get("/api/ais/status")
        self.assertEqual(status_response.status_code, 200)
        status = status_response.json()
        self.assertEqual(status["provider"], "AISStream.io")
        self.assertIn("configured", status)
        self.assertIn("trail_observations", status)
        self.assertIn("trail_vessels", status)

        invalid_trail = self.client.get("/api/ais/trail/not-an-mmsi")
        self.assertEqual(invalid_trail.status_code, 400)

    def test_ais_cache_filters_viewport_and_selected_mmsi(self):
        manager = AisLiveManager()
        manager.vessels = {
            "111111111": {
                "mmsi": "111111111",
                "name": "INDIA BULKER",
                "lat": 19.0,
                "lon": 72.0,
                "last_update": "2026-07-30T00:00:00+00:00",
            },
            "222222222": {
                "mmsi": "222222222",
                "name": "REMOTE VESSEL",
                "lat": -30.0,
                "lon": -40.0,
                "last_update": "2026-07-30T00:00:00+00:00",
            },
        }
        viewport = manager.snapshot(5, 35, 60, 100, None, [], 100)
        self.assertEqual([item["mmsi"] for item in viewport], ["111111111"])
        selected = manager.snapshot(
            5, 35, 60, 100, None, ["222222222"], 100
        )
        self.assertEqual([item["mmsi"] for item in selected], ["222222222"])
        multi_region = manager.snapshot(
            -90,
            90,
            -180,
            180,
            None,
            [],
            100,
            boxes=[
                [[5, 64], [31, 100]],
                [[-58, -92], [15, -30]],
            ],
        )
        self.assertEqual(
            {item["mmsi"] for item in multi_region},
            {"111111111", "222222222"},
        )

    def test_maritime_zone_overlays_disclose_source_and_boundary_quality(self):
        response = self.client.get("/api/zones")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        features = payload["features"]
        self.assertTrue(any(
            item["properties"]["zone_type"] == "jwc_listed_area"
            for item in features
        ))
        self.assertFalse(any(
            item["properties"]["zone_type"] == "piracy_watch"
            for item in features
        ))
        self.assertFalse(any(
            item["properties"]["zone_type"] == "ECA" for item in features
        ))
        self.assertIn("PK", payload["listed_country_codes"]["jwc"])
        self.assertEqual(
            payload["metadata"]["display_geometry"],
            "water-only polygons clipped against Natural Earth 1:50m land",
        )
        self.assertTrue(all(
            item["properties"].get("display_scope") == "water_only"
            for item in features
        ))
        self.assertTrue(all(
            item["properties"].get("source_url")
            and item["properties"].get("boundary_quality")
            for item in features
        ))

    def test_map_uses_only_explicit_english_labels(self):
        response = self.client.get("/static/js/app.js")
        self.assertEqual(response.status_code, 200)
        javascript = response.text
        self.assertIn('["Africa", 7, 20]', javascript)
        self.assertIn('["South America", -18, -59]', javascript)
        self.assertNotIn("World_Light_Gray_Reference", javascript)
        self.assertIn("formatFacilityPrimaryLine", javascript)
        self.assertIn("Coal flows by direction", javascript)
        self.assertNotIn("event.preventDefault()", javascript)
        self.assertIn("npp-history-point", javascript)
        self.assertIn("formatRefreshInterval", javascript)
        self.assertIn("showCoalPortDetails", javascript)
        self.assertIn("satelliteImageUrl", javascript)
        self.assertIn("World_Ocean_Base", javascript)
        self.assertIn("World_Ocean_Reference", javascript)
        self.assertIn("portVisibleAtZoom", javascript)
        self.assertNotIn("loadRiskZones", javascript)
        self.assertNotIn("avoid_jwc", javascript)
        self.assertNotIn("avoid_piracy", javascript)
        self.assertNotIn("risk_avoidance", javascript)
        self.assertNotIn("show-piracy-zones", javascript)

    def test_npp_transform_reconciles_requested_power_visuals(self):
        reporting_date = 1_720_000_000_000
        all_india = {
            "installed_Capacity": {
                "installed_capacity_thermal": 60,
                "installed_capacity_hydro": 20,
                "installed_capacity_nuclear": 5,
                "installed_capacity_res": 15,
                "reporting_date": reporting_date,
            },
            "monthlyAllIndiaGen": {
                "installed_capacity": 100,
                "monitored_capacity": 80,
                "online_capacity": 70,
                "under_maintenance_capacity": 10,
                "shutdown_capacity": 6,
                "unscheduled_capacity": 4,
                "reporting_date": reporting_date,
            },
            "installed_Capacity_List": [
                {"sector_name": "CENTRAL SECTOR", "installed_capacity": 30},
                {"sector_name": "STATE SECTOR", "installed_capacity": 25},
                {"sector_name": "PVT SECTOR", "installed_capacity": 45},
            ],
            "dailyDemmandCp": [
                {
                    "reporting_date": "01/07/2024",
                    "peak_requirement": 90,
                    "max_demand_met": 88,
                    "surplus_deficit": -2,
                }
            ],
        }
        history = {
            "linechartforCapacity": [
                {
                    "reporting_date": 1_600_000_000_000,
                    "installed_capacity_thermal": 50,
                    "installed_capacity_hydro": 18,
                    "installed_capacity_nuclear": 4,
                    "installed_capacity_res": 8,
                },
                {
                    "reporting_date": reporting_date,
                    "installed_capacity_thermal": 60,
                    "installed_capacity_hydro": 20,
                    "installed_capacity_nuclear": 5,
                    "installed_capacity_res": 15,
                },
            ]
        }
        generation = {
            "dailyPGen": {
                "generation_date": reporting_date,
                "generation_date_ly": 1_688_000_000_000,
                "generation_date_apr": 1_711_929_600_000,
                "generation_date_apr_ly": 1_680_307_200_000,
                "actual_generation": 4600,
                "program_generation": 4500,
                "pdeviation": 2.2,
                "actual_generation_ly": 4300,
                "actual_generation_cumulative": 500000,
                "program_generation_cumulative": 505000,
                "pdeviation_cumulative": -1,
                "actual_generation_cumulative_ly": 470000,
            },
            "dailyColeStock": [
                {
                    "mode_transport": "N",
                    "coal_date": reporting_date,
                    "coal_0_5": 10,
                    "coal_5_15": 20,
                    "coal_15_25": 30,
                    "coal_gt_25": 40,
                },
                {
                    "mode_transport": "P",
                    "coal_date": reporting_date,
                    "coal_0_5": 1,
                    "coal_5_15": 2,
                    "coal_15_25": 3,
                    "coal_gt_25": 4,
                },
            ],
            "plfMonthWise": [
                {
                    "fin_year": "2024-25",
                    "report_type": "Actual",
                    "month_period_end": reporting_date,
                    "plf_allindia": 70,
                    "plf_central": 72,
                    "plf_state": 65,
                    "plf_private": 75,
                },
                {},
                {
                    "fin_year": "2024-25",
                    "report_type": "Actual",
                    "month_period_end": reporting_date,
                    "plf_allindia": 85,
                    "plf_central": 85,
                },
            ],
        }
        payload = _transform_npp_power(all_india, history, generation)
        self.assertTrue(all(payload["quality_checks"].values()))
        self.assertTrue(all(payload["generation_quality_checks"].values()))
        self.assertEqual(payload["installed_capacity_mw"], 100)
        self.assertEqual(payload["daily_demand"][0]["demand_met_mw"], 88)
        self.assertEqual(payload["daily_generation"]["actual_mu"], 4600)
        self.assertEqual(payload["cumulative_generation"]["actual_mu"], 500000)
        self.assertEqual(
            payload["cumulative_generation"]["period_start"], "2024-04-01"
        )
        self.assertEqual(len(payload["coal_stock_availability"]["rows"]), 8)
        self.assertEqual(
            payload["sector_plf"]["thermal_current"]["central_percent"], 72
        )
        self.assertEqual(NPP_CACHE_TTL_SECONDS, 43_200)
        self.assertIn(
            "Historical growth of electricity consumption",
            payload["excluded_visuals"],
        )

    def test_plain_english_power_mix_research_is_source_backed(self):
        response = self.client.post(
            "/api/coal/research/query",
            json={
                "question": (
                    "What percentage of India electricity generation came "
                    "from coal in June 2026 versus June 2025?"
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["rows"]), 2)
        self.assertAlmostEqual(payload["rows"][-1]["coal_share_pct"], 65.7616, places=3)
        self.assertIn("NPP Monthly Actual", payload["sources"][0]["title"])

    def test_granular_export_rejects_unavailable_weekly_frequency(self):
        response = self.client.get(
            "/api/coal/export",
            params={
                "dataset_type": "imports",
                "frequency": "weekly",
                "coal_type": "coking",
                "period": "3y",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("monthly", response.json()["detail"].lower())

    def test_coal_dashboard_tabs_are_distinct_and_current(self):
        expected_titles = {
            "overview": "All-source electricity generation mix",
            "supply": "Period-on-period change",
            "trade": "Monthly coal imports by coal type",
            "power": "All-source generation mix",
            "stocks": "Pit-head closing stock",
        }
        seen = set()
        for tab, expected in expected_titles.items():
            response = self.client.get(
                "/api/coal/dashboard",
                params={"tab": tab, "start": "2023-05", "end": "2026-06", "frequency": "monthly"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            titles = tuple(chart["title"] for chart in payload["charts"])
            self.assertIn(expected, titles)
            self.assertNotIn(titles, seen)
            seen.add(titles)
        power = self.client.get(
            "/api/coal/dashboard",
            params={"tab": "power", "start": "2023-05", "end": "2026-06", "frequency": "monthly"},
        ).json()
        self.assertEqual(len(power["rows"]), 38)
        self.assertEqual(power["available_range"]["end"], "2026-06")
        all_source_chart = next(chart for chart in power["charts"] if chart["id"] == "power-all-source")
        series_keys = {series["key"] for series in all_source_chart["series"]}
        self.assertTrue({"wind_generation_gwh", "solar_generation_gwh", "other_renewables_total_gwh"}.issubset(series_keys))
        self.assertTrue(all_source_chart["rows"])
        latest_mix = all_source_chart["rows"][-1]
        self.assertAlmostEqual(latest_mix["coal_share_pct"], 65.7616, places=3)
        coal_share_kpi = next(kpi for kpi in power["kpis"] if kpi["label"] == "Coal share of all generation")
        self.assertAlmostEqual(coal_share_kpi["value"], 65.7616, places=3)
        self.assertNotAlmostEqual(coal_share_kpi["value"], 82.9, places=1)
        quarterly = self.client.get(
            "/api/coal/dashboard",
            params={"tab": "power", "start": "2024-07", "end": "2026-06", "frequency": "quarterly"},
        ).json()
        self.assertEqual(quarterly["rows"][-1]["period"], "2026Q2")
        self.assertNotIn("2027Q1", {row["period"] for row in quarterly["rows"]})

    def test_trade_dashboard_uses_latest_official_import_release(self):
        payload = self.client.get(
            "/api/coal/dashboard",
            params={"tab": "trade", "start": "2024-04", "end": "2026-06", "frequency": "monthly"},
        ).json()
        self.assertEqual(payload["available_range"]["end"], "2026-04")
        self.assertEqual(len(payload["rows"]), 25)
        latest = payload["rows"][-1]
        self.assertEqual(latest["period"], "2026-04")
        self.assertAlmostEqual(latest["total_coal_mt"], 21.13, places=2)
        self.assertAlmostEqual(latest["coking_coal_mt"], 6.01, places=2)
        self.assertAlmostEqual(latest["non_coking_coal_mt"], 15.11, places=2)
        annual_chart = next(chart for chart in payload["charts"] if chart["id"] == "trade-annual")
        self.assertEqual(annual_chart["rows"][-1]["period"], "2025-26")
        self.assertAlmostEqual(annual_chart["rows"][-1]["total_imports_mt"], 246.37, places=2)
        self.assertIn("Customs reporting country", payload["available_range"]["limitation"])

    def test_dashboard_measure_focus_controls_charts_rows_and_export(self):
        params = {
            "tab": "trade", "start": "2024-04", "end": "2026-04",
            "frequency": "monthly", "focus": "coking", "comparison": "previous_year",
        }
        payload = self.client.get("/api/coal/dashboard", params=params).json()
        self.assertEqual(payload["focus"], "coking")
        self.assertEqual(payload["comparison"], "previous_year")
        self.assertIn("coking_coal_mt", payload["columns"])
        self.assertNotIn("non_coking_coal_mt", payload["columns"])
        for chart in payload["charts"]:
            self.assertTrue(all("coking" in series["key"] for series in chart["series"]))
        exported = self.client.get(
            "/api/coal/dashboard/export", params={**params, "format": "xlsx"}
        )
        self.assertEqual(exported.status_code, 200)
        frame = pd.read_excel(io.BytesIO(exported.content), sheet_name="Filtered data")
        self.assertIn("coking_coal_mt", frame.columns)
        self.assertNotIn("non_coking_coal_mt", frame.columns)

    def test_three_year_monthly_export_matches_active_filter(self):
        params = {
            "tab": "supply", "start": "2023-07", "end": "2026-06",
            "frequency": "monthly", "format": "xlsx",
        }
        response = self.client.get("/api/coal/dashboard/export", params=params)
        self.assertEqual(response.status_code, 200)
        frame = pd.read_excel(io.BytesIO(response.content), sheet_name="Filtered data")
        self.assertEqual(len(frame), 36)
        self.assertEqual(frame.iloc[0]["period"], "2023-07")
        self.assertEqual(frame.iloc[-1]["period"], "2026-06")

        legacy = self.client.get(
            "/api/coal/export",
            params={"dataset_type": "production", "frequency": "monthly", "coal_type": "thermal", "period": "3y"},
        )
        self.assertEqual(legacy.status_code, 200)
        legacy_frame = pd.read_excel(io.BytesIO(legacy.content), sheet_name="Filtered official data")
        self.assertEqual(len(legacy_frame), 36)


if __name__ == "__main__":
    unittest.main()
