"""Commercial dry-bulk news ingestion; commodity mentions alone are rejected."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from intelligence_archive import IntelligenceArchive, canonical_url
from official_intelligence_reports import collect_reports
import re
import xml.etree.ElementTree as element_tree
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx

NEWS_DATA_URL = "https://newsdata.io/api/1/latest"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
NEWS_API_URL = "https://newsapi.org/v2/everything"
NEWS_RULESET_VERSION = "commercial-intelligence-v5"
NEWS_MARKET_TIMEZONE = ZoneInfo("Asia/Kolkata")
NEWS_TARGET_COUNT = 50
MAX_NEWS_ROWS = 100
NEWS_DATA_QUERIES = ("dry bulk freight", "chartering freight", "port shipping disruption", "bulk carrier weather")
GDELT_QUERIES = (
    '"dry bulk" OR capesize OR panamax OR supramax OR handysize',
    'chartering OR fixture OR "freight rate" OR demurrage',
    '(port OR terminal OR canal) AND (congestion OR closure OR delay OR restriction)',
    '(cyclone OR typhoon OR storm) AND (port OR shipping OR vessel)',
)
GOOGLE_NEWS_QUERIES = (
    '"dry bulk" freight', "chartering freight vessel", "port congestion shipping disruption",
    "typhoon port shipping", "iron ore bulk carrier", "coal seaborne freight",
    "grain freight vessel", "bulk carrier newbuild sale purchase",
)
GOOGLE_NEWS_QUERIES += ("Indonesia coal production exports", "India coal imports stockpiles", "China steel iron ore demand", "Australia coal iron ore port", "Brazil grain harvest exports", "South Africa coal Richards Bay", "Guinea bauxite exports", "fertilizer petcoke cement trade", "Panama canal draft restrictions", "Suez Red Sea shipping regulation", "coal mining company production results", "Indonesian batubara ekspor pelabuhan", "中国 煤炭 铁矿石 港口", "Brasil exportação soja porto")
NEWS_API_QUERY = '("dry bulk" OR capesize OR panamax OR supramax OR handysize OR chartering OR fixture OR "freight rate" OR demurrage OR "bulk carrier" OR "bulk carrier newbuild" OR "sale and purchase")'
TOPIC_LABELS = (
    ("chartering", "Chartering & freight"), ("dry_bulk", "Dry-bulk vessels"),
    ("ports", "Ports & operations"), ("cargo_trade", "Bulk cargo flows"),
    ("fleet_snp", "Newbuild & S&P"), ("weather", "Navigational weather"),
)
COMMODITY_GROUP_LABELS = (
    ("coal", "Coal"), ("iron_steel", "Iron ore & steel"),
    ("bauxite_alumina", "Bauxite & alumina"), ("grains_agri", "Grains & agri"),
    ("minor_bulks", "Minor bulks"),
)
PUBLIC_RSS_FEEDS = (
    ("gcaptain", "gCaptain", "https://gcaptain.com/feed/"),
    ("splash247", "Splash 247", "https://splash247.com/feed/"),
    ("hellenic_shipping", "Hellenic Shipping News", "https://www.hellenicshippingnews.com/feed/"),
    ("freightwaves", "FreightWaves", "https://www.freightwaves.com/feed"),
    ("maritime_executive", "The Maritime Executive", "https://www.maritime-executive.com/rss"),
)

CHARTERING_TERMS = ("chartering", "charterer", "charter party", "fixture", "fixtures", "freight rate", "freight rates", "freight market", "ffa", "forward freight", "demurrage", "laycan", "laytime", "ballast", "time charter", "voyage charter")
VESSEL_TERMS = ("dry bulk", "bulk carrier", "bulk vessel", "bulker", "bulk fleet", "capesize", "panamax", "kamsarmax", "supramax", "ultramax", "handysize", "handymax", "ore carrier", "grain carrier")
PORT_TERMS = ("port", "terminal", "harbour", "harbor", "canal", "berth", "anchorage", "loadport", "discharge port")
PORT_IMPACT_TERMS = ("congestion", "congested", "closure", "closed", "delay", "delays", "disruption", "restricted", "restriction", "berth delay", "berth availability", "draft restriction", "dredging", "expansion", "capacity", "throughput", "investment", "strike", "queue", "queuing", "navigation", "pilotage", "suspended", "shut down", "shutdown", "force majeure", "loading", "discharging")
CARGO_TERMS = ("coal", "steel", "iron ore", "pellet", "pellets", "coking coal", "metallurgical coal", "thermal coal", "steam coal", "coal shipment", "bauxite", "alumina", "grain", "wheat", "corn", "maize", "soybean", "soybeans", "barley", "sorghum", "fertiliser", "fertilizer", "steel scrap", "scrap cargo", "petcoke", "cement", "clinker", "salt", "sugar", "forest products", "woodchip", "logs", "manganese ore", "nickel ore", "copper concentrate", "zinc concentrate", "phosphate rock", "limestone")
CARGO_FLOW_TERMS = ("shipment", "shipments", "cargo", "cargoes", "exports", "imports", "loading", "discharging", "tonnage", "voyage", "seaborne", "seaborne trade", "vessel")
WEATHER_TERMS = ("cyclone", "typhoon", "hurricane", "tropical storm", "storm surge", "gale", "heavy seas", "rough seas", "high waves", "monsoon", "flooding")
FLEET_SNP_TERMS = ("newbuild", "newbuilding", "newbuildings", "newbuild order", "shipyard order", "orderbook", "sale and purchase", "s&p", "secondhand sale", "vessel sale", "resale", "demolition", "scrapping")
COMMODITY_GROUP_TERMS = {
    "coal": ("coal", "coking coal", "metallurgical coal", "thermal coal", "steam coal"),
    "iron_steel": ("iron ore", "pellet", "pellets", "steel", "steel scrap", "scrap cargo"),
    "bauxite_alumina": ("bauxite", "alumina"),
    "grains_agri": ("grain", "wheat", "corn", "maize", "soybean", "soybeans", "barley", "sorghum", "sugar"),
    "minor_bulks": ("fertiliser", "fertilizer", "petcoke", "cement", "clinker", "salt", "forest products", "woodchip", "logs", "manganese ore", "nickel ore", "copper concentrate", "zinc concentrate", "phosphate rock", "limestone"),
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
    try:
        parsed = parsedate_to_datetime(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def _news_age_limit_hours(now: datetime | None = None) -> int:
    """Use a wider publication window only across the weekend.

    Monday preserves the Friday-to-Monday market handover. Saturday and Sunday
    use the same window so the weekend screen is not needlessly blank.
    """
    local_now = (now or datetime.now(timezone.utc)).astimezone(NEWS_MARKET_TIMEZONE)
    return 72 if local_now.weekday() in (0, 5, 6) else 24


def _within_news_window(value: Any, now: datetime | None = None) -> bool:
    published = _parse_date(value)
    if not published:
        return False
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = reference - published
    return timedelta(0) <= age <= timedelta(hours=_news_age_limit_hours(reference))


def _contains(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)]


def _commodity_groups(text: str) -> list[str]:
    """Return the dry-bulk cargo groups materially mentioned by a headline."""
    return [group_id for group_id, terms in COMMODITY_GROUP_TERMS.items() if _contains(text, terms)]


def _commercial_relevance(text: str) -> dict[str, Any] | None:
    """Classify a commercial shipping signal, or reject broad commodity news."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or _contains(text, EXCLUDED_TERMS):
        return None
    chartering, vessel = _contains(text, CHARTERING_TERMS), _contains(text, VESSEL_TERMS)
    port, impact = _contains(text, PORT_TERMS), _contains(text, PORT_IMPACT_TERMS)
    cargo, cargo_flow, weather = _contains(text, CARGO_TERMS), _contains(text, CARGO_FLOW_TERMS), _contains(text, WEATHER_TERMS)
    fleet_snp, commodity_groups = _contains(text, FLEET_SNP_TERMS), _commodity_groups(text)
    topics, reasons, score = [], [], 0
    if chartering:
        topics.append("chartering"); reasons.append("Chartering / freight signal"); score += 4
    if vessel:
        topics.append("dry_bulk"); reasons.append("Dry-bulk vessel market"); score += 3
    if port and impact:
        topics.append("ports"); reasons.append("Port operational impact"); score += 3
    if cargo and (cargo_flow or vessel or chartering or (port and impact)):
        topics.append("cargo_trade"); reasons.append("Bulk cargo flow"); score += 2
    if fleet_snp and (vessel or cargo or chartering):
        topics.append("fleet_snp"); reasons.append("Dry-bulk newbuild / S&P"); score += 3
    if weather and (port or vessel or chartering or cargo_flow):
        topics.append("weather"); reasons.append("Navigational weather impact"); score += 3
    if cargo and _contains(text, ("production", "demand", "supply", "price", "prices", "stock", "inventory", "consumption", "power", "steel", "mine", "harvest", "output", "policy", "export", "import")):
        if "cargo_trade" not in topics: topics.append("cargo_trade"); reasons.append("Commodity supply, demand or trade context"); score += 2
    policy = _contains(text, ("sanction", "sanctions", "policy", "regulation", "marpol", "emission", "emissions", "export ban", "import ban", "tariff", "trade policy")) and (cargo or vessel or port or chartering)
    if policy: topics.append("policy"); reasons.append("Maritime or commodity policy"); score += 2
    # A commodity, power plant, policy or weather article without a market or
    # navigational consequence never gets into this feed.
    if not topics and re.search(r"batubara|煤炭|铁矿石|soja.*export", text, re.I):
        topics.append("cargo_trade"); reasons.append("Original-language commodity coverage"); score += 2
        commodity_groups += ["coal"] if re.search(r"batubara|煤炭", text, re.I) else ["iron_steel"] if "铁矿石" in text else ["grains_agri"]
    if not topics:
        return None
    return {"topics": list(dict.fromkeys(topics)), "commodity_groups": commodity_groups, "score": score, "reason": reasons[0]}


def _article_topics(text: str) -> list[str]:
    hit = _commercial_relevance(text)
    return list(hit["topics"]) if hit else []


class NewsIntelligenceManager:
    def __init__(self, cache_path: Path, ttl_seconds: int = 1800) -> None:
        self.cache_path, self.ttl_seconds = cache_path, max(300, ttl_seconds)
        self.payload = self._read_cache()
        self.archive = IntelligenceArchive(cache_path.with_suffix(".sqlite3"))
        self.archive.ingest(self.payload.get("rows") or [])
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        self._last_forced_refresh_at: datetime | None = None
        self._task = None

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
        config = (
            ("newsdata", "NewsData.io", bool(os.getenv("NEWS_DATA_API_KEY", "").strip())),
            ("gdelt", "GDELT", True), ("google_news", "Google News RSS", True),
            ("newsapi", "NewsAPI", bool(os.getenv("NEWS_API_KEY", "").strip())),
            *((key, label, True) for key, label, _ in PUBLIC_RSS_FEEDS),
        )
        urls={key:url for key, label, url in PUBLIC_RSS_FEEDS}
        return [{"id": key, "label": label, "connected": connected, "url": urls.get(key), **saved.get(key, {})} for key, label, connected in config]

    def response(self, topic="all", commodity_group="all", query="", page=1, page_size=25, **filters):
        rows = self.archive.query(topic=topic, commodity_group=commodity_group, query=query, **filters)
        all_rows = self.archive.all()
        facets = {field: sorted({str(v) for row in all_rows for v in (row.get(field) or [])}) for field in ("countries", "ports", "vessel_classes", "topics", "commodity_groups")}
        facets["publishers"] = sorted({r.get("source_name", "") for r in all_rows})
        facets["languages"] = sorted({r.get("language", "original; not translated") for r in all_rows})
        providers=self._provider_status()
        for provider in providers:
            provider["status"] = "not configured" if not provider["connected"] else "failed" if provider.get("error") else "healthy with no results" if provider.get("fetched")==0 else "healthy" if provider.get("fetched") else "not checked"
        count=len(rows);page=max(1,min(page,max(1,(count+page_size-1)//page_size)))
        snapshot=self.archive.snapshot(rows)
        groups={}
        for row in rows:groups.setdefault(row["event_id"],[]).append(row)
        page_rows=[{**r,"related_coverage_count":len(groups[r["event_id"]])} for r in rows[(page-1)*page_size:page*page_size]]
        return {"configured":self.configured,"fetched_at":self.payload.get("fetched_at"),"fresh":self._is_fresh(),"last_error":self.last_error,"providers":providers,"topics":[{"id":k,"label":v} for k,v in TOPIC_LABELS]+[{"id":"policy","label":"Policy & regulation"}],"commodity_groups":[{"id":k,"label":v} for k,v in COMMODITY_GROUP_LABELS],"publication_window_hours":filters.get("days",7)*24,"total":count,"rows":page_rows,"page":page,"page_size":page_size,"pages":max(1,(count+page_size-1)//page_size),"snapshot_id":snapshot,"facets":facets,"event_count":len(groups),"archive_total":len(all_rows),"archive_start":min((r["published_at"] for r in all_rows if r.get("published_at")),default=None),"audit":self.payload.get("audit",{}),"reports_sources":self.payload.get("reports_sources",[]),"coverage_note":"Archive begins with successfully collected material. Undated reports remain labelled; no complete historical coverage is claimed."}

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
        return {"id": identity, "title": clean_title, "description": re.sub(r"\s+", " ", clean_description)[:520], "link": clean_link, "image_url": str(image_url or "").strip(), "source_name": str(source_name or "News source").strip(), "provider_id": provider_id, "provider_name": provider_name, "published_at": date.isoformat() if date else str(published_at or ""), "topics": match["topics"], "commodity_groups": match["commodity_groups"], "relevance_score": match["score"], "relevance_reason": match["reason"], "countries": countries if isinstance(countries, list) else [], "categories": categories if isinstance(categories, list) else []}

    async def _fetch_newsdata(self, client):
        key=os.getenv("NEWS_DATA_API_KEY", "").strip()
        if not key:return [],None
        rows=[]
        try:
            for query in NEWS_DATA_QUERIES:
                cursor=None
                for page in range(2):
                    params={"apikey":key,"q":query,"language":"en"}
                    if cursor:params["page"]=cursor
                    response=await client.get(NEWS_DATA_URL,params=params);response.raise_for_status();payload=response.json()
                    if payload.get("status")=="error":raise ValueError("Provider rejected query")
                    for item in payload.get("results") or []:
                        row=self._normalise("newsdata","NewsData.io",title=item.get("title"),description=item.get("description"),link=item.get("link"),published_at=item.get("pubDate"),source_name=item.get("source_name") or item.get("source_id"),countries=item.get("country"))
                        if row:rows.append(row)
                    cursor=payload.get("nextPage")
                    if not cursor:break
        except Exception:return rows,"NewsData query unavailable; retained successful pages"
        return rows,None

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

    async def _fetch_google_news(self, client):
        semaphore=asyncio.Semaphore(4)
        async def one(query):
            rows=[]
            try:
                async with semaphore:
                    response=await client.get(f"{GOOGLE_NEWS_RSS_URL}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en");response.raise_for_status()
                root=element_tree.fromstring(response.content)
                for item in root.findall("./channel/item"):
                    source=item.find("source");title=item.findtext("title") or ""
                    if source is not None and source.text and title.endswith(f" - {source.text}"):title=title[:-(len(source.text)+3)]
                    row=self._normalise("google_news","Google News RSS",title=title,description=item.findtext("description"),link=item.findtext("link"),published_at=item.findtext("pubDate"),source_name=source.text if source is not None else "Google News")
                    if row:rows.append(row)
                return rows,None
            except Exception:return rows,"Query unavailable"
        results=await asyncio.gather(*(one(q) for q in GOOGLE_NEWS_QUERIES))
        failures=sum(bool(error) for _,error in results)
        return [r for rows,_ in results for r in rows],f"{failures} Google News queries failed" if failures else None

    async def _fetch_public_rss(self, client: httpx.AsyncClient, provider_id: str, provider_name: str, url: str) -> tuple[list[dict[str, Any]], str | None]:
        """Read a publisher's public RSS metadata only; article pages are never scraped."""
        rows: list[dict[str, Any]] = []
        try:
            response = await client.get(url); response.raise_for_status()
            root = element_tree.fromstring(response.content)
            items = root.findall("./channel/item") or root.findall(".//item")
            for item in items[:80]:
                row = self._normalise(
                    provider_id, provider_name,
                    title=item.findtext("title") or "",
                    description=item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "",
                    link=item.findtext("link") or item.findtext("{http://www.w3.org/2005/Atom}link") or "",
                    published_at=item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or "",
                    source_name=provider_name,
                )
                if row: rows.append(row)
        except (httpx.HTTPError, element_tree.ParseError, ValueError):
            return rows, f"{provider_name} RSS is temporarily unavailable"
        return rows, None

    async def _fetch_newsapi(self, client):
        key=os.getenv("NEWS_API_KEY", "").strip()
        if not key:return [],None
        rows=[]
        try:
            for page in range(1,3):
                response=await client.get(NEWS_API_URL,params={"q":NEWS_API_QUERY,"language":"en","sortBy":"publishedAt","pageSize":100,"page":page},headers={"X-Api-Key":key});response.raise_for_status();payload=response.json()
                for item in payload.get("articles") or []:
                    row=self._normalise("newsapi","NewsAPI",title=item.get("title"),description=item.get("description"),link=item.get("url"),published_at=item.get("publishedAt"),source_name=(item.get("source") or {}).get("name"))
                    if row:rows.append(row)
                if page*100>=payload.get("totalResults",0):break
        except Exception:return rows,"NewsAPI query unavailable; retained successful pages"
        return rows,None

    async def refresh(self, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            if force and self._last_forced_refresh_at and self.payload.get("rows") and datetime.now(timezone.utc) - self._last_forced_refresh_at < timedelta(minutes=5): return self.response()
            if not force and self._is_fresh(): return self.response()
            if force: self._last_forced_refresh_at = datetime.now(timezone.utc)
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "DryBulkMarketIntelligence/1.0 (+public-RSS-metadata)"}) as client:
                specs = [
                    ("newsdata", "NewsData.io", self._fetch_newsdata(client)),
                    ("gdelt", "GDELT", self._fetch_gdelt(client)),
                    ("google_news", "Google News RSS", self._fetch_google_news(client)),
                    ("newsapi", "NewsAPI", self._fetch_newsapi(client)),
                    *((key, label, self._fetch_public_rss(client, key, label, url)) for key, label, url in PUBLIC_RSS_FEEDS),
                ]
                results = await asyncio.gather(*(job for _, _, job in specs))
            reports, report_sources = await collect_reports()
            self.archive.ingest(reports)
            merged, providers = {}, []
            for (key, label, _), (rows, error) in zip(specs, results):
                for row in rows:
                    dedupe = canonical_url(row.get("link")) or row["id"]
                    if dedupe and dedupe not in merged: merged[dedupe] = row
                providers.append({"id": key, "label": label, "fetched": len(rows), "error": error})
            ordered = sorted((row for row in merged.values() if _parse_date(row.get("published_at")) and timedelta(0) <= datetime.now(timezone.utc)-_parse_date(row.get("published_at")) <= timedelta(days=365)), key=lambda item: (_parse_date(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc), item.get("relevance_score", 0)), reverse=True)
            errors = [item["error"] for item in providers if item.get("error")]
            if ordered or not errors:
                self.payload = {"ruleset_version": NEWS_RULESET_VERSION, "fetched_at": datetime.now(timezone.utc).isoformat(), "rows": ordered, "providers": providers, "reports_sources": report_sources, "audit": {"provider_items": sum(len(items) for items, _ in results), "unique_retained": len(ordered), "reports_discovered": len(reports)}}; self._write_cache(self.payload); self.archive.ingest(ordered); self.last_error = "; ".join(errors) if errors else None
            elif errors: self.last_error = "; ".join(errors)
            return self.response()


    def start(self):
        if not self._task or self._task.done():self._task=asyncio.create_task(self._run())

    async def _run(self):
        while True:
            try:await self.refresh()
            except asyncio.CancelledError:raise
            except Exception:self.last_error="Source collection failed; archive retained"
            await asyncio.sleep(300 if self.last_error else self.ttl_seconds)

    async def stop(self):
        if self._task and not self._task.done():
            self._task.cancel();await asyncio.gather(self._task,return_exceptions=True)
