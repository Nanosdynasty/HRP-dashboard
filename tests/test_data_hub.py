import tempfile
import unittest
from pathlib import Path

from data_hub import ApiConnectionRequest, DataHubStore, RelationshipRequest


class DataHubStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = DataHubStore(Path(self.temp_dir.name) / "provider_master.sqlite3")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upload_profiles_and_exports_rows(self):
        content = (
            "period,country,commodity,volume_mt\n"
            "2026-05-01,China,Coal,12.5\n"
            "2026-06-01,China,Coal,13.2\n"
        ).encode()
        dataset = self.store.add_dataset(
            "kpler", "China coal imports", "monthly", "imports.csv", content
        )
        self.assertEqual(dataset["row_count"], 2)
        self.assertIn("period", dataset["date_columns"])
        self.assertIn("volume_mt", dataset["numeric_columns"])
        self.assertEqual(self.store.rows(dataset["id"])[1]["volume_mt"], 13.2)
        self.assertEqual(self.store.summary()["totals"]["datasets"], 1)

    def test_compare_and_approve_relationship(self):
        left = self.store.add_dataset(
            "oceanbolt", "Port calls", "monthly", "calls.csv",
            b"period,country,port,volume_mt\n2026-06-01,China,Qingdao,10\n",
        )
        right = self.store.add_dataset(
            "custom", "Power burn", "monthly", "burn.csv",
            b"period,country,plant,coal_burn_mt\n2026-06-01,China,Plant A,8\n",
        )
        comparison = self.store.compare([left["id"], right["id"]])
        self.assertTrue(comparison["join_ready"])
        self.assertIn("country", comparison["shared_fields"])
        proposal = self.store.propose_relationship(RelationshipRequest(
            dataset_ids=[left["id"], right["id"]], question="Relate imports to burn"
        ))
        self.assertEqual(proposal["status"], "proposed")
        approved = self.store.approve_relationship(proposal["id"], True)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(
            approved["execution_status"], "proposal_only_not_materialized"
        )

    def test_dataset_without_reporting_date_has_unknown_freshness(self):
        dataset = self.store.add_dataset(
            "custom", "Undated asset register", "monthly", "assets.csv",
            b"asset,capacity_mt\nPlant A,4.2\nPlant B,5.1\n",
        )
        self.assertIsNone(dataset["data_end"])
        self.assertIsNone(dataset["next_due_at"])
        self.assertEqual(dataset["freshness"]["status"], "unknown")

    def test_api_key_is_masked_in_persisted_metadata(self):
        connection = self.store.save_connection(ApiConnectionRequest(
            provider="gtt", endpoint_url="https://example.test/api",
            api_key="secret-123456", connection_label="Research",
        ))
        self.assertEqual(connection["key_mask"], "••••3456")
        self.assertEqual(
            connection["operational_status"],
            "credentials_saved_mapping_required",
        )
        payload = self.store.summary()["providers"][0]["connection"]
        self.assertNotIn("secret-123456", str(payload))

    def test_trade_analytics_aggregate_quantity_without_mixing_currencies(self):
        dataset = self.store.add_dataset(
            "gtt", "Bilateral trade", "monthly", "trade.csv",
            (
                "reporting_period,reporter_country,partner_country,commodity,quantity_mt,trade_value_original,currency\n"
                "2026-01-01,China,India,Coal,10,100,CNY\n"
                "2026-01-01,India,China,Coal,20,200,INR\n"
                "2026-02-01,China,Japan,Coal,30,300,CNY\n"
            ).encode(),
        )
        analytics = self.store.analytics(dataset["id"])
        self.assertEqual(analytics["metrics"]["records"], 3)
        self.assertEqual(analytics["metrics"]["quantity_mt"], 60)
        self.assertEqual(analytics["metrics"]["currency_count"], 2)
        self.assertIsNone(analytics["metrics"]["trade_value"])
        self.assertEqual(analytics["trend"][0]["quantity_mt"], 30)
        self.assertEqual(analytics["top_reporters"][0], {"label": "China", "value": 40.0})
        self.assertIn("not summed across currencies", analytics["caveats"][0])


if __name__ == "__main__":
    unittest.main()
