import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_intelligence import NewsIntelligenceManager, _article_topics


class NewsIntelligenceTests(unittest.TestCase):
    def test_topic_classifier_keeps_market_relevance_and_drops_false_port_hits(self):
        topics = _article_topics("Iron ore shipments disrupted at Port Hedland after cyclone warning")
        self.assertIn("iron_steel", topics)
        self.assertIn("ports", topics)
        self.assertIn("weather", topics)
        self.assertEqual(_article_topics("Airport expansion wins sports award"), [])

    def test_topic_classifier_keeps_transport_context(self):
        topics = _article_topics("Dry bulk transport faces port congestion")
        self.assertIn("dry_bulk", topics)
        self.assertIn("ports", topics)

    def test_unconfigured_response_never_contains_a_credential(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"NEWS_DATA_API_KEY": ""}, clear=False):
            manager = NewsIntelligenceManager(Path(directory) / "news.json")
            payload = manager.response()
        self.assertFalse(payload["configured"])
        self.assertEqual(payload["rows"], [])
        self.assertNotIn("apikey", str(payload).casefold())


if __name__ == "__main__":
    unittest.main()
