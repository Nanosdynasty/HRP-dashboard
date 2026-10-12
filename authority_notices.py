"""Conservative, cached official notice adapters; publication is never fetch time."""
from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader
from port_disruption_outlook import _parse_time, notice_active

ADAPTERS = [
    {"id": "pilbara-hedland", "country": "Australia", "ports": ["Port Hedland"], "authority": "Pilbara Ports", "url": "https://www.pilbaraports.com.au/ports/port-of-port-hedland/safety-and-security/local-marine-notices", "kind": "pilbara", "latitude": -20.31, "longitude": 118.58},
    {"id": "pilbara-dampier", "country": "Australia", "ports": ["Dampier"], "authority": "Pilbara Ports", "url": "https://www.pilbaraports.com.au/ports/port-of-dampier/", "kind": "pilbara", "latitude": -20.65, "longitude": 116.71},
    {"id": "india-paradip", "country": "India", "ports": ["Paradip"], "authority": "Paradip Port Authority", "url": "https://paradipport.gov.in/circulars-notices/", "kind": "table", "latitude": 20.27, "longitude": 86.68},
    {"id": "india-dgll", "country": "India", "ports": ["Chennai", "Visakhapatnam", "Kandla", "Cochin"], "authority": "Directorate General of Lighthouses and Lightships", "url": "https://dgll.nic.in/notice-to-mariners", "kind": "table"},
    {"id": "singapore-mpa", "country": "Singapore", "ports": ["Singapore"], "authority": "Maritime and Port Authority of Singapore", "url": "https://www.mpa.gov.sg/home?level=1", "kind": "mpa", "latitude": 1.2644, "longitude": 103.82},
]


def text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value))).strip()


DATE_PATTERN = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+,?\s+\d{4})"


def date_value(value: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return None


def parse_listing(body: str, source: dict, fetched_at: str) -> list[dict]:
    if re.search(r"_Incapsula_Resource|captcha|Access Denied", body, re.I):
        raise ValueError("Authority page returned an access challenge; no successful notice download")
    if source["kind"] == "table":
        blocks = re.findall(r"<tr\b[^>]*>.*?</tr>", body, re.S | re.I)
    elif source["kind"] == "pilbara":
        # Notice card headings with their following document link. Do not parse
        # cyclone FAQs, navigation menus, news or undated policy handbooks.
        blocks = re.findall(r"<h[234]\b[^>]*>.*?</h[234]>.*?(?:</article>|(?=<h[234]\b)|$)", body, re.S | re.I)
    else:
        blocks = re.findall(r"<a\b[^>]*>.*?</a>", body, re.S | re.I)
    notices = []
    for block in blocks:
        plain = text(block)
        if not re.search(r"notice to mariners|marine notice|\b[HD]\d{1,3}[-/]20\d{2}\b|pilot ladders|berth.*clos|port.*clos", plain, re.I):
            continue
        links = re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"']", block, re.I)
        urls = [urljoin(source["url"], html.unescape(u)) for u in links]
        urls = [u for u in urls if urlparse(u).scheme == "https" and urlparse(u).hostname == urlparse(source["url"]).hostname or urlparse(u).scheme == "https" and urlparse(u).hostname == "www.paradipport.gov.in"]
        document = next((u for u in urls if ".pdf" in u.lower()), None)
        if not document:
            continue
        dates = re.findall(DATE_PATTERN, plain)
        issued = date_value(dates[0]) if dates else None
        port = source["ports"][0] if len(source["ports"]) == 1 else next((p for p in source["ports"] if p.lower() in plain.lower()), None)
        if not port:
            continue
        headline = text((re.findall(r"<h[234]\b[^>]*>(.*?)</h[234]>", block, re.S | re.I) or re.findall(r"<td\b[^>]*>(.*?)</td>", block, re.S | re.I)[1:2] or [plain])[0])[:700]
        notices.append({"notice_id": source["id"] + ":" + hashlib.sha256(document.encode()).hexdigest()[:18], "port_name": port, "country": source["country"], "latitude": source.get("latitude"), "longitude": source.get("longitude"), "summary": headline, "source_url": document, "listing_url": source["url"], "source_name": source["authority"], "evidence_type": "Authority notice", "issued_at": issued, "publication_date_resolution": "Calendar date; publication hour not supplied", "fetched_at": fetched_at, "status": "Requires confirmation", "severity": "amber", "cause": "Authority marine notice", "operational_effect": "Review the dated source for the exact location, operation and effective dates", "source_freshness": "Successful listing retrieval", "is_port_closure": False, "verified_scope": False, "review_required": True, "scope_type": "local_area", "effective_from": None, "effective_to": None, "lifecycle": "pending_confirmation", "operations": [], "adapter_id": source["id"]})
    return list({n["notice_id"]: n for n in notices}.values())[:25]


def enrich_document(notice: dict, document_text: str) -> dict:
    result = dict(notice)
    result["source_document_hash"] = hashlib.sha256(document_text.encode()).hexdigest()
    # Date-only limits retain day resolution. No inferred lifetime or open-ended
    # current restriction from an old document saying 'until further notice'.
    issued = re.search(r"\bDate\s*:\s*(" + DATE_PATTERN + ")", document_text, re.I)
    if issued:
        result["issued_at"] = date_value(issued[1])
    effective = re.search(r"(?:effective from|date of effect|from)\s*:?\s*(" + DATE_PATTERN + r")\s+(?:to|until|through)\s*(" + DATE_PATTERN + ")", document_text, re.I)
    if effective:
        result["effective_from"], result["effective_to"] = date_value(effective[1]), date_value(effective[2])
        result["effective_interval_resolution"] = "Calendar dates only; effective hours and timezone require confirmation"
    timestamp_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})"
    precise_effective = re.search(r"(?:effective from|from)\s*:?\s*(" + timestamp_pattern + r")\s+(?:to|until|through)\s*(" + timestamp_pattern + ")", document_text, re.I)
    if precise_effective:
        result["effective_from"], result["effective_to"] = precise_effective[1], precise_effective[2]
        result["effective_interval_resolution"] = "Explicit effective timestamps with timezone"
    lifecycle = "withdrawn" if re.search(r"(?:this notice|notice\s+\S+)\s+(?:is |has been )?(?:withdrawn|cancelled)", document_text, re.I) else "reopened" if re.search(r"(?:port|berth|terminal).*?\b(?:has reopened|is reopened|restriction lifted)\b", document_text, re.I) else "pending_confirmation"
    result["lifecycle"] = lifecycle
    # Only explicit whole-port statements can confirm whole-port status.
    # Berth/local-area documents remain review-required until IDs are documented.
    sentences = re.split(r"[.!?\n]", document_text)
    whole_port = any(re.search(r"(?:all (?:shipping|vessel movements) (?:are|will be) suspended|(?:the port|port of [A-Za-z ]+) (?:is|will be) closed|pilotage (?:is|will be) suspended)", sentence, re.I) and not re.search(r"\bno\b|\bnot\b|\bif\b|\bwhen\b|\bmay\b|\bunless\b", sentence, re.I) for sentence in sentences)
    local_scope = re.search(r"\bberth|terminal|road|wharf|anchorage|area bounded|position\b", document_text, re.I)
    if whole_port and not local_scope and (effective or precise_effective) and result["issued_at"] and lifecycle == "pending_confirmation":
        ops = ["pilotage"] if re.search(r"pilotage (?:is|will be) suspended", document_text, re.I) and not re.search(r"all vessel movements|port.*? closed", document_text, re.I) else ["berthing", "pilotage", "approach"]
        result.update(scope_type="port", verified_scope=True, review_required=not bool(precise_effective), lifecycle="active" if precise_effective else "pending_confirmation", status="Restricted" if precise_effective else "Requires confirmation", operations=ops, is_port_closure=False)
    previous = re.search(r"(?:supersedes|replaces|former notice)\s*:?\s*([HD]\d{1,3}[/\-]\d{4})", document_text, re.I)
    result["supersedes_reference"] = previous[1] if previous else None
    reference = re.search(r"\b[HD]\d{1,3}[/\-]\d{4}\b", document_text)
    result["notice_reference"] = reference[0].replace("-", "/") if reference else None
    if re.search(r"amended|corrected|revised", result["summary"], re.I):
        result["correction"] = True
    return result


class AuthorityNoticeManager:
    def __init__(self, path: Path):
        self.path, self.task = path, None
        self.lock = asyncio.Lock()
        try:
            self.payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.payload = {"notices": [], "source_status": {}}

    async def refresh_source(self, source: dict) -> tuple[list[dict], str]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "HRP-Official-Notice-Outlook/1.0"}) as client:
            response = await client.get(source["url"])
            response.raise_for_status()
            fetched = datetime.now(timezone.utc).isoformat()
            notices = parse_listing(response.text, source, fetched)
            semaphore = asyncio.Semaphore(3)
            async def enrich_one(notice):
                try:
                    async with semaphore:
                        document_response = await client.get(notice["source_url"])
                    document_response.raise_for_status()
                    if len(document_response.content) > 8_000_000:
                        raise ValueError("Document exceeds parser size limit")
                    def read_pdf():
                        reader = PdfReader(io.BytesIO(document_response.content))
                        if len(reader.pages) > 12:
                            raise ValueError("Long document requires manual scope review")
                        return "\n".join(p.extract_text() or "" for p in reader.pages)
                    parsed = await asyncio.to_thread(read_pdf)
                    notice.update(enrich_document(notice, parsed))
                except Exception as exc:
                    notice["document_error"] = type(exc).__name__ + ": " + str(exc)[:200]
            await asyncio.gather(*(enrich_one(n) for n in notices[:8]))
            return notices, fetched

    async def refresh(self):
        async with self.lock:
            results = await asyncio.gather(*(self.refresh_source(s) for s in ADAPTERS), return_exceptions=True)
            previous = self.payload.get("notices", [])
            notices, statuses = [], dict(self.payload.get("source_status", {}))
            for source, result in zip(ADAPTERS, results):
                prior = [n for n in previous if n.get("adapter_id") == source["id"]]
                if isinstance(result, BaseException):
                    notices.extend(prior)
                    statuses[source["id"]] = {**statuses.get(source["id"], {}), "error": str(result)[:250], "checked_at": datetime.now(timezone.utc).isoformat(), "status": "source_error; last successful snapshot retained"}
                else:
                    fresh, fetched = result
                    fresh_ids = {n["notice_id"] for n in fresh}
                    prior_by_id = {n["notice_id"]: n for n in prior}
                    for n in fresh:
                        old = prior_by_id.get(n["notice_id"])
                        if old and n.get("document_error"):
                            error = n["document_error"]
                            n.update({**old, "last_listing_check": fetched, "document_error": error, "review_required": True, "status": "Requires confirmation"})
                        if old and old.get("source_document_hash") and n.get("source_document_hash") and n["source_document_hash"] != old["source_document_hash"]:
                            revision_id = old["notice_id"] + ":revision:" + old["source_document_hash"][:12]
                            notices.append({**old, "notice_id": revision_id, "lifecycle": "superseded", "review_required": True, "superseded_by": n["notice_id"]})
                            n["previous_document_hash"] = old["source_document_hash"]
                            n["correction"] = True
                    # Disappearing notices are not assumed reopened or withdrawn.
                    notices.extend([{**n, "lifecycle": "missing_from_latest_listing", "review_required": True} for n in prior if n["notice_id"] not in fresh_ids])
                    notices.extend(fresh)
                    statuses[source["id"]] = {"last_success_at": fetched, "checked_at": fetched, "error": None, "status": "listing parsed; document scope/validity checks applied", "notice_count": len(fresh)}
            refs = {(n.get("adapter_id"), n.get("notice_reference")): n["notice_id"] for n in notices if n.get("notice_reference")}
            for n in notices:
                ref = str(n.get("supersedes_reference") or "").replace("-", "/")
                n["supersedes"] = refs.get((n.get("adapter_id"), ref))
                if n["supersedes"] == n["notice_id"]:
                    n["supersedes"] = None
            snapshot = {"notices": notices[-500:], "source_status": statuses, "checked_at": datetime.now(timezone.utc).isoformat()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
            self.payload = snapshot

    def snapshot(self, sources: list[dict]) -> dict:
        now = datetime.now(timezone.utc)
        superseded = {n.get("supersedes") for n in self.payload["notices"] if n.get("supersedes")}
        active = [n for n in self.payload["notices"] if notice_active(n, now) and n["notice_id"] not in superseded]
        inactive = [n for n in self.payload["notices"] if n not in active]
        catalog = {s["id"]: {**s, "status": "Authority source link; no structured adapter"} for s in sources}
        for s in ADAPTERS:
            catalog[s["id"]] = {**catalog.get(s["id"], {}), **s, "feed_kind": "Structured official notice adapter", "evidence_type": "Authority notice", "coverage": "Stated scope only; ambiguous validity requires confirmation", "region": "Australia" if s["country"] == "Australia" else "Asia", "adapter": True, **self.payload.get("source_status", {}).get(s["id"], {"status": "Not yet checked"})}
        return {"fetched_at": max((s.get("last_success_at") for s in self.payload.get("source_status", {}).values() if s.get("last_success_at")), default=None), "checked_at": self.payload.get("checked_at"), "active_notices": active, "pending_notices": [n for n in inactive if n.get("review_required") and n.get("lifecycle") not in {"withdrawn", "reopened", "missing_from_latest_listing"}], "historical_notices": [n for n in inactive if n not in [x for x in inactive if x.get("review_required") and x.get("lifecycle") not in {"withdrawn", "reopened", "missing_from_latest_listing"}]], "all_notices": self.payload["notices"], "sources": list(catalog.values()), "source_status": self.payload.get("source_status", {}), "source_count": len({r["id"] for r in sources + ADAPTERS}), "methodology": "Dated, attributable, fresh notices with verified scope and effective validity are required for confirmed restrictions. Forecasts never create closure status.", "disclaimer": "Other authorities remain source links. Undated, local-area, unresolved berth and ambiguous notices require confirmation; disappearance is not reopening."}

    async def _run(self):
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(300)
                continue
            failed = any(s.get("error") for s in self.payload.get("source_status", {}).values())
            await asyncio.sleep(300 if failed else 900)

    def start(self):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
