"""Focused news ingestion for the maritime and dry-bulk intelligence workspace.

The NewsData credential stays in the server environment.  Only normalized,
project-relevant metadata is cached and returned to the browser.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


NEWS_DATA_URL = "https://newsdata.io/api/1/latest"
DEFAULT_QUERIES = (
    ("coal", "Coal & power"),
    ("shipping", "Shipping & ports"),
    ("iron ore", "Iron ore & steel"),
    ("cyclone", "Weather risk"),
)
TOPIC_RULES = {
    "coal": ("coal", "coking", "thermal coal", "metallurgical coal", "coke"),
    "dry_bulk": ("dry bulk", "bulk carrier", "capesize", "panamax", "supramax", "freight", "baltic dry", "shipping"),
    "ports": (" port ", "ports", "terminal", "harbour", "harbor", "canal", "congestion", "disruption"),
    "iron_steel": ("iron ore", "steel", "rebar", "pig iron"),
    "weather": ("cyclone", "typhoon", "hurricane", "tropical storm", "monsoon", "storm surge", "flooding"),
    "energy": ("power plant", "electricity", "renewable", "thermal power", "hydropower"),
}
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
    return None


def _article_topics(text: str) -> list[str]:
    haystack = f" {text.casefold()} "
    # Match whole words so, for example, "transport" is not discarded because
    # it happens to contain the letters in "sport".
    if any(re.search(rf"\b{re.escape(term)}\b", haystack) for term in EXCLUDED_TERMS):
        return []
    return [topic for topic, terms in TOPIC_RULES.items() if any(term in haystack for term in terms)]


class NewsIntelligenceManager:
    def __init__(self, cache_path: Path, ttl_seconds: int = 1800) -> None:
        self.cache_path = cache_path
        self.ttl_seconds = max(300, ttl_seconds)
        self.payload: dict[str, Any] = self._read_cache()
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        self._last_forced_refresh_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return bool(os.getenv("NEWS_DATA_API_KEY", "").strip())

    def _read_cache(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _write_cache(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _is_fresh(self) -> bool:
        fetched = _parse_date(self.payload.get("fetched_at"))
        return bool(fetched and datetime.now(timezone.utc) - fetched < timedelta(seconds=self.ttl_seconds))

    def response(self, topic: str = "all", query: str = "") -> dict[str, Any]:
        rows = list(self.payload.get("rows") or [])
        if topic and topic != "all":
            rows = [row for row in rows if topic in row.get("topics", [])]
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in " ".join([
                str(row.get("title") or ""), str(row.get("description") or ""),
                str(row.get("source_name") or ""), " ".join(row.get("topics") or []),
            ]).casefold()]
        return {
            "configured": self.configured,
            "provider": "NewsData.io",
            "fetched_at": self.payload.get("fetched_at"),
            "cache_ttl_seconds": self.ttl_seconds,
            "fresh": self._is_fresh(),
            "last_error": self.last_error,
            "topics": [{"id": key, "label": label} for key, label in (
                ("coal", "Coal & power"), ("dry_bulk", "Dry bulk freight"),
                ("ports", "Ports & logistics"), ("iron_steel", "Iron ore & steel"),
                ("weather", "Weather risk"), ("energy", "Energy transition"),
            )],
            "total": len(rows),
            "rows": rows,
        }

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        if not self.configured:
            self.last_error = "NewsData API key is not configured on this service."
            return self.response()
        async with self._lock:
            # The refresh button is deliberately rate-limited: a public
            # dashboard should not allow a burst of clicks to exhaust a
            # provider quota. The cached result remains immediately usable.
            if (
                force
                and self._last_forced_refresh_at
                and self.payload.get("rows")
                and datetime.now(timezone.utc) - self._last_forced_refresh_at < timedelta(minutes=5)
            ):
                return self.response()
            if not force and self._is_fresh():
                return self.response()
            if force:
                self._last_forced_refresh_at = datetime.now(timezone.utc)
            api_key = os.getenv("NEWS_DATA_API_KEY", "").strip()
            articles: dict[str, dict[str, Any]] = {}
            errors: list[str] = []
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for query, query_label in DEFAULT_QUERIES:
                    try:
                        response = await client.get(NEWS_DATA_URL, params={
                            "apikey": api_key, "q": query, "language": "en",
                        })
                        if response.status_code != 200:
                            errors.append(f"{query_label}: source unavailable ({response.status_code})")
                            continue
                        payload = response.json()
                        for item in payload.get("results") or []:
                            title = str(item.get("title") or "").strip()
                            description = str(item.get("description") or "").strip()
                            topics = _article_topics(f"{title} {description}")
                            if not title or not topics:
                                continue
                            link = str(item.get("link") or "").strip()
                            identity = str(item.get("article_id") or link or title.casefold())
                            published = _parse_date(item.get("pubDate") or item.get("pubDateTZ"))
                            articles[identity] = {
                                "id": identity,
                                "title": title,
                                "description": description[:520],
                                "link": link,
                                "image_url": str(item.get("image_url") or item.get("imageurl") or "").strip(),
                                "source_name": str(item.get("source_name") or item.get("source_id") or "News source").strip(),
                                "source_id": str(item.get("source_id") or "").strip(),
                                "published_at": published.isoformat() if published else str(item.get("pubDate") or ""),
                                "topics": topics,
                                "countries": item.get("country") if isinstance(item.get("country"), list) else [],
                                "categories": item.get("category") if isinstance(item.get("category"), list) else [],
                            }
                    except (httpx.HTTPError, ValueError) as exc:
                        errors.append(f"{query_label}: source request failed")
            ordered = sorted(
                articles.values(), key=lambda item: _parse_date(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True
            )
            if ordered:
                self.payload = {"fetched_at": datetime.now(timezone.utc).isoformat(), "rows": ordered[:40]}
                self._write_cache(self.payload)
                self.last_error = "; ".join(errors) if errors else None
            elif errors:
                self.last_error = "; ".join(errors)
            return self.response()
