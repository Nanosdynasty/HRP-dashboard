"""Source-backed berth detail for the main port card.

Counts always retain their published scope. A facility row is not counted as a
berth unless its source identifies it as one.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


INDIA_SPECS = Path(__file__).resolve().parent / "data" / "india_coal_port_specs.json"
PARADIP_BERTH_SOURCE = "https://paradipport.gov.in/berth-specifications/"
PARADIP_USE = {
    "iron ore berth iron ore": "Iron ore loading",
    "fertiliser berth i": "Phosphates and sulphur",
    "fertiliser berth ii": "Phosphates and sulphur",
    "coal berth i": "Thermal coal loading",
    "coal berth ii": "Thermal coal loading",
    "new coal import berth": "Coking coal import",
}
VISAKHAPATNAM_BERTH_SOURCE = "https://www.vizagport.com/admin_assets/uploads/1640237145_Berth%20Details.pdf"


def _name(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    words = [word for word in text.split() if word not in {"port", "authority", "of", "the"}]
    aliases = {"vishakhapatnam": "visakhapatnam", "paradeep": "paradip"}
    return " ".join(aliases.get(word, word) for word in words)


def _cargoes(row: dict[str, Any]) -> list[str]:
    labels = {
        "thermal_coal": "Thermal coal", "coking_coal": "Coking coal",
        "iron_ore": "Iron ore", "iron_ore_pellets": "Iron ore pellets",
        "other_dry_bulk": "Other dry bulk", "fertilizer": "Fertiliser",
        "fertiliser": "Fertiliser", "grain": "Grain", "salt": "Salt",
        "limestone": "Limestone", "clinker": "Clinker",
    }
    cargoes = [labels.get(str(item), str(item).replace("_", " ").title()) for item in row.get("cargo_types") or []]
    if cargoes:
        return cargoes
    name = str(row.get("name") or "").lower()
    reported_in_name = (("iron ore", "Iron ore"), ("coking coal", "Coking coal"),
                        ("steam coal", "Steam coal"), ("fertiliser", "Fertiliser"))
    return [label for term, label in reported_in_name if term in name]


def _india_detail(port: dict[str, Any]) -> dict[str, Any] | None:
    if str(port.get("country") or "").upper() != "IN" or not INDIA_SPECS.exists():
        return None
    try:
        specifications = json.loads(INDIA_SPECS.read_text(encoding="utf-8")).get("ports", [])
    except (OSError, ValueError):
        return None
    port_name = _name(port.get("name"))
    names_to_match = {port_name, port_name.removesuffix(" coal terminal")}
    candidates = [item for item in specifications if port_name and names_to_match.intersection({
        _name(item.get("asset_name")), _name(item.get("official_port_name"))
    })]
    if not candidates:
        return None
    item = candidates[0]
    rows = item.get("dry_bulk_facilities") or []
    berths = []
    for row in rows:
        if str(row.get("facility_type") or "").lower() == "anchorage":
            continue
        cargoes = _cargoes(row)
        asset_name = _name(item.get("asset_name"))
        published_use = PARADIP_USE.get(_name(row.get("name"))) if asset_name == "paradip" else None
        vizag_bulk = asset_name == "visakhapatnam" and "vgcb" in str(row.get("name") or "").lower()
        if vizag_bulk:
            published_use = "Mechanised coal import and general bulk cargo"
        role = str(row.get("import_export_role") or "").lower()
        role_label = {"load": "loading", "loading": "loading", "export": "export loading",
                      "discharge": "discharge", "import": "import discharge"}.get(role)
        cargo_use = ", ".join(cargoes) if cargoes else "Dry bulk facility; cargo not specified"
        berths.append({
            "name": row.get("name"), "cargoes": cargoes,
            "use": published_use or (f"{cargo_use} · {role_label}" if role_label else cargo_use),
            "facility_type": row.get("facility_type"),
            "draft_m": row.get("draft_m"),
            "source_url": (VISAKHAPATNAM_BERTH_SOURCE if vizag_bulk else PARADIP_BERTH_SOURCE if published_use else
                           next((source.get("url") for source in item.get("sources") or [] if source.get("url")), item.get("official_website"))),
            "source_as_of": "2026-02-23" if asset_name == "paradip" and published_use else row.get("as_of") or item.get("source_as_of"),
        })
    return {
        "scope": item.get("official_port_name") or item.get("asset_name"),
        "scope_type": "port", "total_berths": item.get("documented_berth_count"),
        "dry_bulk_berths": item.get("documented_dry_bulk_berth_count"),
        "berths": berths,
        "coverage_note": "Named rows are documented dry-bulk facilities. They may cover fewer berths than the published port total.",
        "source_as_of": item.get("source_as_of"),
        "sources": [{"title": source.get("title") or "Port source", "url": source.get("url")}
                    for source in item.get("sources") or [] if source.get("url")],
    }


GLOBAL_DRY_BULK = [
    {
        "country": "ZA", "names": {"richards bay", "richards bay coal terminal"},
        "scope": "Richards Bay Coal Terminal", "scope_type": "terminal",
        "total_berths": 6, "dry_bulk_berths": 6,
        "berths": [{"name": "RBCT coal berths (6)", "use": "Coal export loading", "cargoes": ["Coal"],
                    "facility_type": "berth group", "draft_m": None,
                    "source_url": "https://rbct.co.za/operations/"}],
        "coverage_note": "Terminal count only; the source does not assign separate cargo roles to individual RBCT berths.",
        "source_as_of": "2026-09-24",
        "sources": [{"title": "Richards Bay Coal Terminal operations", "url": "https://rbct.co.za/operations/"}],
    },
    {
        "country": "AU", "names": {"hedland"},
        "scope": "Port of Port Hedland", "scope_type": "port",
        "total_berths": 19, "dry_bulk_berths": None,
        "berths": [
            {"name": "PH No. 3", "use": "Bulk salt; also general cargo", "cargoes": ["Salt"], "draft_m": 13.6},
            {"name": "PH No. 4 / Utah Point", "use": "Multi-user bulk minerals, mainly iron ore; also manganese and spodumene", "cargoes": ["Iron ore", "Manganese", "Spodumene"], "draft_m": 14.7},
            {"name": "BHP Nelson Point NPC–NPD", "use": "Iron ore export loading", "cargoes": ["Iron ore"], "draft_m": 19.2},
            {"name": "BHP Finucane Island FIA–FID", "use": "Iron ore export loading", "cargoes": ["Iron ore"], "draft_m": None},
            {"name": "Fortescue Anderson Point AP1–AP5", "use": "Iron ore export loading", "cargoes": ["Iron ore"], "draft_m": 19.8},
            {"name": "Roy Hill Stanley Point SP1–SP2", "use": "Iron ore export loading", "cargoes": ["Iron ore"], "draft_m": 19.8},
        ],
        "coverage_note": "Selected dry-bulk berth groups; the 19-berth count includes other cargo facilities.",
        "source_as_of": "2026-09-24",
        "sources": [
            {"title": "Pilbara Ports facilities", "url": "https://www.pilbaraports.com.au/ports/port-of-port-hedland/port-operations/port-facilities"},
            {"title": "Pilbara Ports dust management", "url": "https://www.pilbaraports.com.au/ports/port-of-port-hedland/environment-and-community/dust-management-at-the-port-of-port-hedland"},
        ],
    },
    {
        "country": "AU", "names": {"newcastle"},
        "scope": "Port of Newcastle", "scope_type": "port",
        "total_berths": 20, "dry_bulk_berths": None,
        "berths": [
            {"name": "Dyke 4–5 (2 berths)", "use": "Coal export loading", "cargoes": ["Coal"], "draft_m": 16.5},
            {"name": "Kooragang 4–7 (4 berths)", "use": "Coal export loading · Port Waratah", "cargoes": ["Coal"], "draft_m": 16.5},
            {"name": "Kooragang 8–10 (3 berths)", "use": "Coal export loading · NCIG", "cargoes": ["Coal"], "draft_m": 16.5},
            {"name": "Kooragang 2", "use": "Common-user bulk cargo and bulk liquids", "cargoes": ["Bulk cargo"], "draft_m": 11.6},
            {"name": "Kooragang 3", "use": "Common-user bulk cargo discharge", "cargoes": ["Bulk cargo"], "draft_m": 13.5},
            {"name": "Dyke 2", "use": "Mineral concentrates and grain loading", "cargoes": ["Mineral concentrates", "Grain"], "draft_m": 12.8},
        ],
        "coverage_note": "The 20-berth port total includes other cargo facilities. Named dry-bulk groups use the port's published berth information; individual assignments can change.",
        "source_as_of": "2024-12",
        "sources": [
            {"title": "Port of Newcastle berth information", "url": "https://www.portofnewcastle.com.au/wp-content/uploads/2020/05/2020-Berth-information.pdf"},
            {"title": "Port of Newcastle maintenance dredging plan", "url": "https://www.portofnewcastle.com.au/wp-content/uploads/2024/12/LTMMP-2022-2032_updated-121124.pdf"},
        ],
    },
]


def berth_detail_for_port(port: dict[str, Any]) -> dict[str, Any] | None:
    for entry in GLOBAL_DRY_BULK:
        if str(port.get("country") or "").upper() == entry["country"] and _name(port.get("name")) in entry["names"]:
            detail = {key: value for key, value in entry.items() if key not in {"country", "names"}}
            source_url = detail["sources"][0]["url"]
            detail["berths"] = [{**row, "facility_type": row.get("facility_type", "berth group"),
                                 "source_url": row.get("source_url", source_url),
                                 "source_as_of": detail["source_as_of"]} for row in entry["berths"]]
            return detail
    return _india_detail(port)
