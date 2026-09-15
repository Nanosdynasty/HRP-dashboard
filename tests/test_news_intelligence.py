import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datetime import datetime, timedelta, timezone

from news_intelligence import NewsIntelligenceManager, _article_topics, _commercial_relevance, _news_age_limit_hours, _within_news_window


class NewsIntelligenceTests(unittest.TestCase):
    def test_relevance_gate_rejects_commodity_or_power_only_headlines(self):
        self.assertEqual(_article_topics("Coal-fired power output rises after a new policy"), [])
        self.assertEqual(_article_topics("Iron ore and steel prices move on China demand"), [])
        self.assertEqual(_article_topics("Airport expansion wins sports award"), [])

    def test_relevance_gate_keeps_chartering_bulk_cargo_and_port_impacts(self):
        chartering = _commercial_relevance("Capesize fixtures strengthen on Brazil-China iron ore demand")
        self.assertIn("chartering", chartering["topics"])
        self.assertIn("dry_bulk", chartering["topics"])
        port = _commercial_relevance("Port Hedland berth delays disrupt bulk carrier iron ore loading")
        self.assertIn("ports", port["topics"])
        self.assertIn("cargo_trade", port["topics"])

    def test_relevance_gate_requires_weather_to_have_a_shipping_consequence(self):
        self.assertEqual(_article_topics("Typhoon rains expected to hit coastal provinces"), [])
        weather = _commercial_relevance("Typhoon closes coal loading terminal and delays vessels")
        self.assertIn("weather", weather["topics"])
        self.assertIn("ports", weather["topics"])

    def test_public_sources_remain_available_without_private_keys(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"NEWS_DATA_API_KEY": "", "NEWS_API_KEY": ""}, clear=False):
            manager = NewsIntelligenceManager(Path(directory) / "news.json")
            payload = manager.response()
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["rows"], [])
        self.assertNotIn("apikey", str(payload).casefold())

    def test_publication_window_is_24_hours_on_weekdays_and_72_hours_on_monday(self):
        monday = datetime(2026, 9, 7, 10, tzinfo=timezone.utc)
        tuesday = datetime(2026, 9, 8, 10, tzinfo=timezone.utc)
        self.assertEqual(_news_age_limit_hours(monday), 72)
        self.assertEqual(_news_age_limit_hours(tuesday), 24)
        self.assertTrue(_within_news_window(monday - timedelta(hours=71), monday))
        self.assertFalse(_within_news_window(monday - timedelta(hours=73), monday))
        self.assertFalse(_within_news_window(tuesday - timedelta(hours=25), tuesday))


if __name__ == "__main__":
    unittest.main()
