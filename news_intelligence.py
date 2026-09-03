"""Commercial dry-bulk news ingestion; commodity mentions alone are rejected."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import xml.etree.ElementTree as element_tree
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

NEWS_DATA_URL = "https://newsdata.io/api/1/latest"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
NEWS_API_URL = "https://newsapi.org/v2/everything"
NEWS_RULESET_VERSION = "commercial-dry-bulk-v2"
NEWS_DATA_QUERIES = ("dry bulk freight", "chartering freight", "port shipping disruption", "bulk carrier weather")
GDELT_QUERIES = (
    '"dry bulk" OR capesize OR panamax OR supramax OR handysize',
    'chartering OR fixture OR "freight rate" OR demurrage',
    '(port OR terminal OR canal) AND (congestion OR closure OR delay OR restriction)',
    '(cyclone OR typhoon OR storm) AND (port OR shipping OR vessel)',
)
GOOGLE_NEWS_QUERIES = ('"dry bulk" freight', "chartering freight vessel", "port congestion shipping disruption", "typhoon port shipping")
NEWS_API_QUERY = '("dry bulk" OR capesize OR panamax OR supramax OR handysize OR chartering OR fixture OR "freight rate" OR demurrage OR "bulk carrier")'
TOPIC_LABELS = (("chartering", "Chartering & freight"), ("dry_bulk", "Dry-bulk vessels"), ("ports", "Ports & operations"), ("cargo_trade", "Bulk cargo flows"), ("weather", "Navigational weather"))

CHARTERING_TERMS = ("chartering", "charterer", "charter party", "fixture", "fixtures", "freight rate", "freight rates", "freight market", "ffa", "forward freight", "demurrage", "laycan", "laytime", "ballast", "time charter", "voyage charter")
VESSEL_TERMS = ("dry bulk", "bulk carrier", "bulk vessel", "capesize", "panamax", "kamsarmax", "supramax", "ultramax", "handysize", "handymax", "ore carrier", "grain carrier")
PORT_TERMS = ("port", "terminal", "harbour", "harbor", "canal", "berth", "anchorage", "loadport", "discharge port")
PORT_IMPACT_TERMS = ("congestion", "congested", "closure", "closed", "delay", "delays", "disruption", "restricted", "restriction", "berth delay", "berth availability", "draft restriction", "dredging", "strike", "queue", "queuing", "navigation", "pilotage", "suspended", "shut down", "shutdown", "force majeure", "loading", "discharging")
CARGO_TERMS = ("iron ore", "coking coal", "metallurgical coal", "thermal coal", "coal shipment", "bauxite", "alumina", "grain", "wheat", "corn", "maize", "soybean", "soybeans", "fertiliser", "fertilizer", "steel scrap", "scrap cargo", "petcoke", "cement")
CARGO_FLOW_TERMS = ("shipment", "shipments", "cargo", "cargoes", "exports", "imports", "loading", "discharging", "tonnage", "voyage", "seaborne", "seaborne trade", "vessel")
WEATHER_TERMS = ("cyclone", "typhoon", "hurricane", "tropical storm", "storm surge", "gale", "heavy seas", "rough seas", "high waves", "monsoon", "flooding")
EXCLUDED_TERMS = ("airport", "passport", "sport", "sports", "portugal")


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = parsedate_to_datetime(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def _contains(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)]


def _commercial_relevance(text: str) -> dict[str, Any] | None:
    """Classify a commercial shipping signal, or reject broad commodity news."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or _contains(text, EXCLUDED_TERMS):
        return None
    chartering, vessel = _contains(text, CHARTERING_TERMS), _contains(text, VESSEL_TERMS)
    port, impact = _contains(text, PORT_TERMS), _contains(text, PORT_IMPACT_TERMS)
    cargo, cargo_flow, weather = _contains(text, CARGO_TERMS), _contains(text, CARGO_FLOW_TERMS), _contains(text, WEATHER_TERMS)
    topics, reasons, score = [], [], 0
    if chartering:
        topics.append("chartering"); reasons.append("Chartering / freight signal"); score += 4
    if vessel:
        topics.append("dry_bulk"); reasons.append("Dry-bulk vessel market"); score += 3
    if port and impact:
        topics.append("ports"); reasons.append("Port operational impact"); score += 3
    if cargo and (cargo_flow or vessel or chartering or (port and impact)):
        topics.append("cargo_trade"); reasons.append("Bulk cargo flow"); score += 2
    if weather and (port or vessel or chartering or cargo_flow):
        topics.append("weather"); reasons.append("Navigational weather impact"); score += 3
    # A commodity, power plant, policy or weather article without a market or
    # navigational consequence never gets into this feed.
    if not topics or not (chartering or vessel or (port and impact) or (cargo and cargo_flow) or (weather and (port or vessel or cargo_flow))):
        return None
    return {"topics": list(dict.fromkeys(topics)), "score": score, "reason": reasons[0]}


def _article_topics(text: str) -> list[str]:
    hit = _commercial_relevance(text)
    return list(hit["topics"]) if hit else []


class NewsIntelligenceManager:
    def __init__(self, cache_path: Path, ttl_seconds: int = 1800) -> None:
        self.cache_path, self.ttl_seconds = cache_path, max(300, ttl_seconds)
        self.payload = self._read_cache()
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        self._last_forced_refresh_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return True  # GDELT and Google News RSS do not need a private key.

    def _read_cache(self) -> dict[str, Any]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _write_cache(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _is_fresh(self) -> bool:
        fetched = _parse_date(self.payload.get("fetched_at"))
        return bool(
            self.payload.get("ruleset_version") == NEWS_RULESET_VERSION
            and fetched
            and datetime.now(timezone.utc) - fetched < timedelta(seconds=self.ttl_seconds)
        )

    def _provider_status(self) -> list[dict[str, Any]]:
        saved = {str(item.get("id")): item for item in self.payload.get("providers", []) if isinstance(item, dict)}
        config = (("newsdata", "NewsData.io", bool(os.getenv("NEWS_DATA_API_KEY", "").strip())), ("gdelt", "GDELT", True), ("google_news", "Google News RSS", True), ("newsapi", "NewsAPI", bool(os.getenv("NEWS_API_KEY", "").strip())))
        return [{"id": key, "label": label, "connected": connected, **saved.get(key, {})} for key, label, connected in config]

    def response(self, topic: str = "all", query: str = "") -> dict[str, Any]:
        rows = list(self.payload.get("rows") or [])
        if topic != "all":
            rows = [row for row in rows if topic in row.get("topics", [])]
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in " ".join(str(row.get(key) or "") for key in ("title", "description", "source_name", "provider_name", "relevance_reason")).casefold()]
        return {"configured": self.configured, "fetched_at": self.payload.get("fetched_at"), "cache_ttl_seconds": self.ttl_seconds, "fresh": self._is_fresh(), "last_error": self.last_error, "providers": self._provider_status(), "topics": [{"id": key, "label": label} for key, label in TOPIC_LABELS], "total": len(rows), "rows": rows}

    @staticmethod
    def _normalise(provider_id: str, provider_name: str, *, title: Any, description: Any = "", link: Any = "", published_at: Any = "", image_url: Any = "", source_name: Any = "", countries: Any = None, categories: Any = None) -> dict[str, Any] | None:
        clean_title = str(title or "").strip()
        clean_description = re.sub(r"<[^>]+>", " ", str(description or "")).strip()
        match = _commercial_relevance(f"{clean_title} {clean_description}")
        if not clean_title or not match:
            return None
        clean_link = str(link or "").strip()
        identity = f"{provider_id}-{hashlib.sha1(f'{clean_link}|{clean_title.casefold()}'.encode()).hexdigest()[:20]}"
        date = _parse_date(published_at)
        return {"id": identity, "title": clean_title, "description": re.sub(r"\s+", " ", clean_description)[:520], "link": clean_link, "image_url": str(image_url or "").strip(), "source_name": str(source_name or "News source").strip(), "provider_id": provider_id, "provider_name": provider_name, "published_at": date.isoformat() if date else str(published_at or ""), "topics": match["topics"], "relevance_score": match["score"], "relevance_reason": match["reason"], "countries": countries if isinstance(countries, list) else [], "categories": categories if isinstance(categories, list) else []}

    async def _fetch_newsdata(self, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], str | None]:
        key = os.getenv("NEWS_DATA_API_KEY", "").strip()
        if not key: return [], None
        rows = []
        try:
            for query in NEWS_DATA_QUERIES:
                response = await client.get(NEWS_DATA_URL, params={"apikey": key, "q": query, "language": "en"}); response.raise_for_status()
                for item in response.json().get("results") or []:
                    row = self._normalise("newsdata", "NewsData.io", title=item.get("title"), description=item.get("description"), link=item.get("link"), published_at=item.get("pubDate") or item.get("pubDateTZ"), image_url=item.get("image_url") or item.get("imageurl"), source_name=item.get("source_name") or item.get("source_id"), countries=item.get("country"), categories=item.get("category"))
                    if row: rows.append(row)
        except (httpx.HTTPError, ValueError): return rows, "NewsData.io is temporarily unavailable"
        return rows, None

    async def _fetch_gdelt(self, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], str | None]:
        rows = []
        try:
            for query in GDELT_QUERIES:
                response = await client.get(GDELT_DOC_URL, params={"query": query, "mode": "ArtList", "format": "json", "maxrecords": 40, "timespan": "7d"}); response.raise_for_status()
                for item in response.json().get("articles") or []:
                    row = self._normalise("gdelt", "GDELT", title=item.get("title"), description=item.get("description"), link=item.get("url"), published_at=item.get("seendate"), image_url=item.get("socialimage"), source_name=item.get("domain") or item.get("sourcecountry"), countries=[item.get("sourcecountry")] if item.get("sourcecountry") else [])
                    if row: rows.append(row)
        except (httpx.HTTPError, ValueError): return rows, "GDELT is temporarily unavailable"
        return rows, None

    async def _fetch_google_news(self, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], str | None]:
        rows = []
        try:
            for query in GOOGLE_NEWS_QUERIES:
                response = await client.get(f"{GOOGLE_NEWS_RSS_URL}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"); response.raise_for_status()
                root = element_tree.fromstring(response.content)
                for item in root.findall("./channel/item"):
                    source, title = item.find("source"), item.findtext("title") or ""
                    if source is not None and source.text and title.endswith(f" - {source.text}"): title = title[:-(len(source.text) + 3)]
                    row = self._normalise("google_news", "Google News RSS", title=title, description=item.findtext("description") or "", link=item.findtext("link") or "", published_at=item.findtext("pubDate") or "", source_name=source.text if source is not None else "Google News")
                    if row: rows.append(row)
        except (httpx.HTTPError, element_tree.ParseError, ValueError): return rows, "Google News RSS is temporarily unavailable"
        return rows, None

    async def _fetch_newsapi(self, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], str | None]:
        key = os.getenv("NEWS_API_KEY", "").strip()
        if not key: return [], None
        try:
            response = await client.get(NEWS_API_URL, params={"q": NEWS_API_QUERY, "language": "en", "sortBy": "publishedAt", "pageSize": 50}, headers={"X-Api-Key": key}); response.raise_for_status()
            rows = []
            for item in response.json().get("articles") or []:
                source = item.get("source") if isinstance(item.get("source"), dict) else {}
                row = self._normalise("newsapi", "NewsAPI", title=item.get("title"), description=item.get("description") or item.get("content"), link=item.get("url"), published_at=item.get("publishedAt"), image_url=item.get("urlToImage"), source_name=source.get("name"))
                if row: rows.append(row)
            return rows, None
        except (httpx.HTTPError, ValueError): return [], "NewsAPI is temporarily unavailable"

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            if force and self._last_forced_refresh_at and self.payload.get("rows") and datetime.now(timezone.utc) - self._last_forced_refresh_at < timedelta(minutes=5): return self.response()
            if not force and self._is_fresh(): return self.response()
            if force: self._last_forced_refresh_at = datetime.now(timezone.utc)
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "DryBulkMarketIntelligence/1.0"}) as client:
                results = await asyncio.gather(self._fetch_newsdata(client), self._fetch_gdelt(client), self._fetch_google_news(client), self._fetch_newsapi(client))
            merged, providers = {}, []
            specs = (("newsdata", "NewsData.io"), ("gdelt", "GDELT"), ("google_news", "Google News RSS"), ("newsapi", "NewsAPI"))
            for (key, label), (rows, error) in zip(specs, results):
                for row in rows:
                    dedupe = re.sub(r"\W+", "", row["title"].casefold())[:220]
                    if dedupe and dedupe not in merged: merged[dedupe] = row
                providers.append({"id": key, "label": label, "fetched": len(rows), "error": error})
            ordered = sorted(merged.values(), key=lambda item: (_parse_date(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc), item.get("relevance_score", 0)), reverse=True)
            errors = [item["error"] for item in providers if item.get("error")]
            if ordered:
                self.payload = {"ruleset_version": NEWS_RULESET_VERSION, "fetched_at": datetime.now(timezone.utc).isoformat(), "rows": ordered[:60], "providers": providers}; self._write_cache(self.payload); self.last_error = "; ".join(errors) if errors else None
            elif errors: self.last_error = "; ".join(errors)
            return self.response()
