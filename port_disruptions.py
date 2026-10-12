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


# Configured by app.py so the existing endpoint shares the background cache.
_NOTICE_MANAGER = None


def configure_notice_manager(manager):
    global _NOTICE_MANAGER
    _NOTICE_MANAGER = manager


async def port_disruption_payload() -> Dict[str, Any]:
    if _NOTICE_MANAGER is not None:
        return _NOTICE_MANAGER.snapshot(PORT_DISRUPTION_SOURCES)
    return {"fetched_at": None, "active_notices": [], "pending_notices": [],
            "sources": PORT_DISRUPTION_SOURCES, "source_count": len(PORT_DISRUPTION_SOURCES),
            "methodology": "Current restrictions require dated, attributable, scope-verified notices.",
            "disclaimer": "Notice collector has not yet been configured; status not reported."}
