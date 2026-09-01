"""Verified port-disruption source registry.

This is deliberately a registry, not a weather-derived closure model.  A port
is only rendered as disrupted when a future connector supplies a dated notice
from an authority, terminal, or carrier.  The initial release surfaces the
official monitoring sources and the major ports they cover without inventing a
current closure or delay.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from typing import Any, Dict, List


PORT_DISRUPTION_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "singapore-mpa", "country": "Singapore", "region": "Southeast Asia",
        "authority": "Maritime and Port Authority of Singapore", "evidence_type": "Authority notice",
        "url": "https://www.mpa.gov.sg/home?level=1", "feed_kind": "Port marine notices",
        "ports": ["Singapore"], "coverage": "navigation restrictions, works and port-marine notices",
    },
    {
        "id": "china-msa", "country": "China", "region": "East Asia",
        "authority": "China Maritime Safety Administration", "evidence_type": "Authority notice",
        "url": "https://www.msa.gov.cn/page/outter/weather.jsp", "feed_kind": "Navigation warnings",
        "ports": ["Qingdao", "Rizhao", "Tangshan / Caofeidian", "Tianjin", "Shanghai", "Ningbo-Zhoushan", "Guangzhou", "Shenzhen"],
        "coverage": "navigation warnings and coastal safety restrictions",
    },
    {
        "id": "shanghai-msa", "country": "China", "region": "East Asia",
        "authority": "Shanghai Maritime Safety Administration", "evidence_type": "Authority notice",
        "url": "https://www.sh.msa.gov.cn/aqyyjxx/index.jhtml", "feed_kind": "Safety and emergency information",
        "ports": ["Shanghai"], "coverage": "local waterway safety and emergency notices",
    },
    {
        "id": "hong-kong-mardep", "country": "Hong Kong", "region": "East Asia",
        "authority": "Hong Kong Marine Department", "evidence_type": "Authority notice",
        "url": "https://www.mardep.gov.hk/en/pub_services/ocean.html", "feed_kind": "Marine notices and tropical cyclone information",
        "ports": ["Hong Kong"], "coverage": "marine department and typhoon-related port notices",
    },
    {
        "id": "philippines-ppa", "country": "Philippines", "region": "Southeast Asia",
        "authority": "Philippine Ports Authority", "evidence_type": "Authority notice",
        "url": "https://www.ppa.com.ph/", "feed_kind": "Port advisories",
        "ports": ["Manila", "Subic", "Batangas", "Cebu", "Davao", "Cagayan de Oro"],
        "coverage": "port advisories and weather-related operating restrictions",
    },
    {
        "id": "thailand-pat", "country": "Thailand", "region": "Southeast Asia",
        "authority": "Port Authority of Thailand", "evidence_type": "Authority notice",
        "url": "https://www.port.co.th/", "feed_kind": "Port authority announcements",
        "ports": ["Laem Chabang", "Bangkok", "Map Ta Phut", "Songkhla"],
        "coverage": "port operations and navigation announcements",
    },
    {
        "id": "vietnam-vinamarine", "country": "Vietnam", "region": "Southeast Asia",
        "authority": "Vietnam Maritime Administration", "evidence_type": "Authority notice",
        "url": "https://vinamarine.gov.vn/", "feed_kind": "Maritime safety notices",
        "ports": ["Hai Phong", "Cai Mep", "Ho Chi Minh City", "Da Nang", "Quy Nhon"],
        "coverage": "maritime safety and navigation notifications",
    },
    {
        "id": "malaysia-pka", "country": "Malaysia", "region": "Southeast Asia",
        "authority": "Port Klang Authority", "evidence_type": "Authority notice",
        "url": "https://www.pka.gov.my/", "feed_kind": "Port Klang notices",
        "ports": ["Port Klang", "Tanjung Pelepas", "Kuantan", "Bintulu"],
        "coverage": "operational notices and vessel scheduling context",
    },
    {
        "id": "indonesia-pelindo", "country": "Indonesia", "region": "Southeast Asia",
        "authority": "Pelindo", "evidence_type": "Terminal / port notice",
        "url": "https://www.pelindo.co.id/", "feed_kind": "Port operator updates",
        "ports": ["Tanjung Priok", "Tanjung Perak", "Balikpapan", "Tarahan", "Taboneo", "Dumai"],
        "coverage": "operator updates; BMKG remains the independent weather source",
    },
    {
        "id": "maersk-advisories", "country": "Multi-country", "region": "Global",
        "authority": "Maersk", "evidence_type": "Carrier service impact",
        "url": "https://www.maersk.com/news/customer-advisories", "feed_kind": "Customer advisories",
        "ports": ["Shanghai", "Ningbo-Zhoushan", "Singapore", "Tanjung Pelepas", "Port Klang", "Manila", "Laem Chabang", "Hai Phong"],
        "coverage": "service delays, omissions and carrier contingency updates; not port status",
    },
    {
        "id": "hapag-lloyd-ops", "country": "Multi-country", "region": "Global",
        "authority": "Hapag-Lloyd", "evidence_type": "Carrier service impact",
        "url": "https://www.hapag-lloyd.com/en/services-information/operational-updates.html", "feed_kind": "Operational updates",
        "ports": ["Qingdao", "Shanghai", "Ningbo-Zhoushan", "Singapore", "Tanjung Pelepas", "Port Klang", "Manila", "Cai Mep"],
        "coverage": "carrier service impact and recovery notices; not port status",
    },
]


_MPA_URL = "https://www.mpa.gov.sg/home?level=1"
_NOTICE_PATTERN = re.compile(r"<a\b[^>]*>(.*?)</a>", re.I | re.S)
_INCIDENT_TERMS = re.compile(r"maintenance|survey|works|restriction|suspend|closure|closed|typhoon|cyclone|delay|disruption", re.I)


async def _mpa_notices() -> List[Dict[str, Any]]:
    """Extract current operational MPA headlines without inferring a closure."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": "HRP-Port-Disruption-Monitor/1.0"}) as client:
            response = await client.get(_MPA_URL)
            response.raise_for_status()
    except Exception:
        return []
    matches = []
    for raw in _NOTICE_PATTERN.findall(response.text):
        headline = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip(" -:\u00a0")
        if not re.search(r"PORT\s+MARINE\s+NOTICE", headline, re.I):
            continue
        if not _INCIDENT_TERMS.search(headline):
            continue
        lower = headline.lower()
        status = "Suspended" if re.search(r"suspend|closure|closed", lower) else "Restricted" if "restriction" in lower else "Advisory"
        cause = "Port-marine notice"
        if "maintenance" in lower:
            cause = "Planned system or marine maintenance"
        elif "survey" in lower or "works" in lower:
            cause = "Marine works or survey activity"
        effect = (
            "Use the authority notice for local navigation and operational instructions. This is not a port closure."
            if status == "Advisory" else "Operating restriction reported by the port authority; verify the notice before voyage decisions."
        )
        matches.append({
            "notice_id": f"mpa-{abs(hash(headline))}", "port_name": "Singapore", "country": "Singapore",
            "latitude": 1.2644, "longitude": 103.8200, "status": status, "severity": "amber" if status != "Suspended" else "red",
            "cause": cause, "summary": headline, "operational_effect": effect,
            "issued_at": datetime.now(timezone.utc).isoformat(), "evidence_type": "Authority notice",
            "source_name": "Maritime and Port Authority of Singapore", "source_url": _MPA_URL,
            "source_freshness": "Live page check", "is_port_closure": False,
        })
        if len(matches) >= 3:
            break
    return matches


async def port_disruption_payload() -> Dict[str, Any]:
    """Return active attributable notices and the transparent source inventory."""
    active = await _mpa_notices()
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "active_notices": active,
        "sources": PORT_DISRUPTION_SOURCES,
        "source_count": len(PORT_DISRUPTION_SOURCES),
        "methodology": (
            "An active disruption requires a dated, attributable authority, terminal, or carrier notice. "
            "Weather alerts and proximity models do not create a port closure or restriction."
        ),
        "disclaimer": (
            "Only the live Singapore MPA connector is currently machine-parsed. Other listed sources are "
            "authoritative watch sources pending their feed-specific adapters; no closure is inferred from weather."
        ),
    }
