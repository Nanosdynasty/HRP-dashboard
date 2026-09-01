"""Normalized, source-aware port catalogue for the maritime dashboard.

The application can read both the small legacy WPI extract bundled with the
prototype and the official NGA World Port Index column names.  The normalized
contract keeps UI/API code stable when a richer monthly WPI file is supplied.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from maritime_extras import DEPTH_CODE, HARBOR_SIZE, HARBOR_TYPE, MAX_VESSEL

try:
    import pycountry
except ImportError:  # pragma: no cover - deployment requirements include it
    pycountry = None


WPI_SOURCE_URL = "https://msi.nga.mil/Publications/WPI"
GEM_COAL_TERMINALS_URL = (
    "https://globalenergymonitor.org/projects/global-coal-terminals-tracker/"
)
OFFICIAL_TERMINAL_POINTS: Dict[str, Dict[str, Any]] = {
    "richardsbaycoalterminal": {
        "lat": -28.818,
        "lon": 32.052,
        "source": {
            "name": "Richards Bay Coal Terminal",
            "url": "https://rbct.co.za/operations-2/",
            "role": "official terminal name and GPS location",
        },
    }
}

COUNTRY_NAME_OVERRIDES = {
    "bolivia": "BO", "brunei": "BN", "china": "CN", "congo": "CG",
    "democratic republic of the congo": "CD", "iran": "IR",
    "laos": "LA", "north korea": "KP", "russia": "RU",
    "south korea": "KR", "syria": "SY", "taiwan": "TW",
    "tanzania": "TZ", "turkey": "TR", "venezuela": "VE",
    "vietnam": "VN",
}


def _country_identity(value: Any) -> tuple[Optional[str], Optional[str]]:
    """Return one ISO code and one English display name for a country value."""
    raw = str(_clean(value) or "").strip()
    if not raw:
        return None, None
    code = raw.upper() if len(raw) == 2 and raw.isalpha() else None
    if not code:
        code = COUNTRY_NAME_OVERRIDES.get(raw.casefold())
    country = None
    if pycountry is not None:
        try:
            country = pycountry.countries.get(alpha_2=code) if code else pycountry.countries.lookup(raw)
        except LookupError:
            country = None
    if country is not None:
        code = country.alpha_2
        return code, str(country.name)
    return code or raw, raw


FIELD_ALIASES: Dict[str, List[str]] = {
    "id": ["INDEX_NO", "World Port Index Number", "wpinumber"],
    "name": ["Plant name", "Main Port Name", "main_port_name"],
    "alternate_name": ["Alternate Port Name", "alternate_name"],
    "unlocode": ["UN/LOCODE", "unlocode"],
    "country": ["Country/Area", "Country Code", "wpi_cc"],
    "lat": ["Latitude", "latitude"],
    "lon": ["Longitude", "longitude"],
    "harbor_size": ["HARBORSIZE", "Harbor Size", "harbor_size_code"],
    "harbor_type": ["HARBORTYPE", "Harbor Type", "harbor_type_code", "Unit name"],
    "harbor_use": ["Harbor Use", "harbor_use_code"],
    "shelter": ["Shelter Afforded", "shelter_afforded_code"],
    "channel_depth": ["CHAN_DEPTH", "Channel Depth (m)", "channel_depth"],
    "anchorage_depth": ["Anchorage Depth (m)", "anchorage_depth"],
    "cargo_depth": ["CARGODEPTH", "Cargo Pier Depth (m)", "cargo_pier_depth"],
    "oil_depth": ["Oil Terminal Depth (m)", "oil_terminal_depth"],
    "lng_depth": ["Liquified Natural Gas Terminal Depth (m)", "lng_terminal_depth"],
    "max_vessel": ["MAX_VESSEL", "Maximum Size Vessel"],
    "max_vessel_length": ["Maximum Vessel Length (m)", "maxvessellength"],
    "max_vessel_beam": ["Maximum Vessel Beam (m)", "maxvesselbeam"],
    "max_vessel_draft": ["Maximum Vessel Draft (m)", "maxvesseldraft"],
    "tidal_range": ["Tidal Range (m)", "tidal_range"],
    "entrance_width": ["Entrance Width (m)", "entrance_width"],
    "fac_wharves": ["Facilities - Wharves", "fac_wharves"],
    "fac_anchorage": ["Facilities - Anchorage", "fac_anchor"],
    "fac_solid_bulk": ["Facilities - Solid Bulk", "fac_solidbulk"],
    "fac_liquid_bulk": ["Facilities - Liquid Bulk", "fac_liquidbulk"],
    "fac_container": ["Facilities - Container", "fac_container"],
    "fac_breakbulk": ["Facilities - Breakbulk", "fac_breakbulk"],
    "fac_oil_terminal": ["Facilities - Oil Terminal", "fac_oilterm"],
    "fac_lng_terminal": ["Facilities - LNG Terminal", "fac_lngterm"],
    "fac_roro": ["Facilities - Ro-Ro", "fac_roro"],
    "pilotage_compulsory": ["Pilotage - Compulsory", "pilotage_compulsory"],
    "pilotage_available": ["Pilotage - Available", "pilotage_avail"],
    "tugs_assistance": ["Tugs - Assistance", "tugs_assist"],
    "cranes_fixed": ["Cranes - Fixed", "crane_fixed"],
    "cranes_mobile": ["Cranes - Mobile", "crane_mobile"],
    "cranes_container": ["Cranes - Container", "cranes_container"],
    "railway": ["Railway", "railway"],
    "repairs": ["Repairs", "repair_code"],
    "dry_dock": ["Dry Dock", "dry_dock"],
}


def _normal_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _number(value: Any) -> Optional[float]:
    value = _clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group(0)) if match else None


def _flag(value: Any) -> Optional[bool]:
    value = _clean(value)
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"y", "yes", "true", "1", "available", "present"}:
        return True
    if text in {"n", "no", "false", "0", "unavailable", "none"}:
        return False
    return None


def _decode_depth(value: Any) -> Dict[str, Any]:
    value = _clean(value)
    if value is None:
        return {"display": "Unknown", "minimum_m": None, "raw": None}
    numeric = _number(value)
    if not isinstance(value, str) or re.search(r"\d", str(value)):
        if numeric is not None:
            return {
                "display": f"{numeric:g} m",
                "minimum_m": numeric,
                "raw": value,
            }
    code = str(value).strip().upper()
    display = DEPTH_CODE.get(code, code)
    lower = _number(display)
    return {"display": display, "minimum_m": lower, "raw": code}


def _decode_lookup(value: Any, mapping: Dict[str, str]) -> str:
    value = _clean(value)
    if value is None:
        return "Unknown"
    code = str(value).strip().upper()
    return mapping.get(code, str(value))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _name_key(value: Any) -> str:
    text = str(_clean(value) or "").lower()
    text = re.sub(
        r"\b(coal|bulk|export|import|terminal|terminals|port|harbour|harbor)\b",
        " ",
        text,
    )
    return re.sub(r"[^a-z0-9]+", "", text)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class PortCatalog:
    """Build a compact normalized catalogue from loaded DuckDB tracker tables."""

    def __init__(self, connection: Any):
        self.connection = connection
        self.ports: List[Dict[str, Any]] = []
        self.by_id: Dict[str, Dict[str, Any]] = {}
        self.facets: Dict[str, Any] = {}
        self.summary: Dict[str, Any] = {}

    def _tables(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _columns(self, table: str) -> List[str]:
        rows = self.connection.execute(
            f"PRAGMA table_info({_quoted(table)})"
        ).fetchall()
        return [str(row[1]) for row in rows]

    @staticmethod
    def _select_expr(columns: Iterable[str], semantic: str) -> str:
        by_key = {_normal_key(column): column for column in columns}
        for alias in FIELD_ALIASES[semantic]:
            match = by_key.get(_normal_key(alias))
            if match:
                return f"{_quoted(match)} AS {_quoted(semantic)}"
        return f"NULL AS {_quoted(semantic)}"

    def _load_world_ports(self) -> List[Dict[str, Any]]:
        columns = self._columns("world_ports")
        semantics = list(FIELD_ALIASES)
        select_list = ", ".join(
            self._select_expr(columns, semantic) for semantic in semantics
        )
        frame = self.connection.execute(
            f"SELECT {select_list} FROM world_ports"
        ).fetchdf()
        return frame.to_dict(orient="records")

    def _load_coal_terminals(self) -> List[Dict[str, Any]]:
        if "coal_terminals" not in self._tables():
            return []
        columns = self._columns("coal_terminals")
        by_key = {_normal_key(column): column for column in columns}

        def column(*aliases: str) -> str:
            for alias in aliases:
                match = by_key.get(_normal_key(alias))
                if match:
                    return _quoted(match)
            return "NULL"

        sql = (
            "SELECT "
            f"{column('asset_id', 'Project ID')} AS asset_id, "
            f"{column('Plant name')} AS name, "
            f"{column('Location')} AS location, "
            f"{column('Country/Area')} AS country, "
            f"{column('Status')} AS status, "
            f"{column('Capacity (MW)', 'Capacity (Mt)')} AS capacity, "
            f"{column('Owner')} AS owner, "
            f"{column('Wiki URL')} AS wiki_url, "
            f"{column('Parent port', 'parent_port')} AS parent_port, "
            f"{column('Source text', 'source_text')} AS source_text, "
            f"{column('Latitude')} AS lat, "
            f"{column('Longitude')} AS lon "
            "FROM coal_terminals"
        )
        return self.connection.execute(sql).fetchdf().to_dict(orient="records")

    @staticmethod
    def _terminal_search_aliases(terminal: Dict[str, Any]) -> List[str]:
        """Return useful shipping-market aliases without inventing assets."""
        name = str(_clean(terminal.get("name")) or "")
        aliases = [
            str(value)
            for value in (
                _clean(terminal.get("location")),
                _clean(terminal.get("parent_port")),
            )
            if value
        ]
        aliases.extend(
            {
                "richardsbaycoalterminal": ["RBCT", "Richards Bay"],
                "tanjungbaracoalterminal": [
                    "TBCT",
                    "Tanjung Bara",
                    "Kalimantan",
                ],
                "muaraberauanchoragecoalterminal": [
                    "Muara Berau",
                    "Kalimantan",
                ],
                "adangbayanchoragecoalterminal": ["Adang Bay", "Kalimantan"],
                "taboneoanchoragebanjamarsinport": [
                    "Taboneo",
                    "Banjarmasin",
                    "Kalimantan",
                ],
                "bunatiport": ["Bunati", "Kalimantan"],
                "pulaulautcoalterminal": ["Pulau Laut", "Kalimantan"],
            }.get(_normal_key(name), [])
        )
        return sorted(
            {
                alias.strip()
                for alias in aliases
                if alias and alias.strip().lower() != name.strip().lower()
            }
        )

    @staticmethod
    def _specialist_terminal_port(
        terminal: Dict[str, Any], port_id: str
    ) -> Dict[str, Any]:
        """Expose an operating GEM terminal as a searchable map location."""
        name = str(_clean(terminal.get("name")) or "Coal terminal")
        capacity = _number(terminal.get("capacity"))
        official = OFFICIAL_TERMINAL_POINTS.get(_normal_key(name))
        lat = (
            float(official["lat"])
            if official
            else _number(terminal.get("lat"))
        )
        lon = (
            float(official["lon"])
            if official
            else _number(terminal.get("lon"))
        )
        country_code, country_name = _country_identity(terminal.get("country"))
        terminal_record = {
            "id": "gem-coal-" + str(
                _clean(terminal.get("asset_id")) or _slug(name)
            ),
            "name": name,
            "location": _clean(terminal.get("location")),
            "status": _clean(terminal.get("status")),
            "capacity_mtpa": capacity,
            "owner": _clean(terminal.get("owner")),
            "wiki_url": _clean(terminal.get("wiki_url")),
            "lat": lat,
            "lon": lon,
            "distance_km": 0.0,
            "match_confidence": "high",
            "coordinate_confidence": "source_coordinate",
        }
        return {
            "id": port_id,
            "name": name,
            "alternate_name": (
                _clean(terminal.get("parent_port"))
                or _clean(terminal.get("location"))
            ),
            "search_aliases": PortCatalog._terminal_search_aliases(terminal),
            "unlocode": None,
            "country": country_code,
            "country_name": country_name,
            "lat": lat,
            "lon": lon,
            "harbor_size": "Unknown",
            "harbor_type": "Specialist coal terminal / anchorage",
            "harbor_use": "Coal",
            "shelter": "Unknown",
            "channel_depth": "Unknown",
            "channel_depth_m": None,
            "anchorage_depth": "Unknown",
            "anchorage_depth_m": None,
            "cargo_depth": "Unknown",
            "cargo_depth_m": None,
            "oil_depth": "Unknown",
            "lng_depth": "Unknown",
            "max_vessel": "Unknown",
            "max_vessel_length_m": None,
            "max_vessel_beam_m": None,
            "max_vessel_draft_m": None,
            "tidal_range_m": None,
            "entrance_width_m": None,
            "facilities": {
                "wharves": None,
                "anchorage": "anchorage" in name.lower(),
                "solid_bulk": True,
                "liquid_bulk": None,
                "container": None,
                "breakbulk": None,
                "oil_terminal": None,
                "lng_terminal": None,
                "roro": None,
            },
            "navigation": {
                "pilotage_compulsory": None,
                "pilotage_available": None,
                "tugs_assistance": None,
            },
            "services": {
                "cranes_fixed": None,
                "cranes_mobile": None,
                "cranes_container": None,
                "railway": None,
                "repairs": None,
                "dry_dock": None,
            },
            "categories": ["coal", "dry_bulk"],
            "coal_terminals": [terminal_record],
            "sources": (
                [{
                    "name": "Global Coal Terminals Tracker",
                    "url": GEM_COAL_TERMINALS_URL,
                    "role": (
                        "terminal operating status, capacity and source context"
                        if official
                        else "terminal name, operating status, capacity and coordinates"
                    ),
                }]
                + ([official["source"]] if official else [])
            ),
            "specialist_terminal": True,
            "terminal_status": _clean(terminal.get("status")),
            "terminal_capacity_mtpa": capacity,
            "source_text": _clean(terminal.get("source_text")),
            "data_completeness_pct": 25,
            "coal_terminal_count": 1,
            "coal_capacity_mtpa": capacity or 0.0,
        }

    @staticmethod
    def _terminal_matches(
        port: Dict[str, Any], terminals: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        port_names = {
            key
            for key in (
                _name_key(port.get("name")),
                _name_key(port.get("alternate_name")),
            )
            if key
        }
        for terminal in terminals:
            lat = _number(terminal.get("lat"))
            lon = _number(terminal.get("lon"))
            if lat is None or lon is None:
                continue
            distance = _haversine_km(port["lat"], port["lon"], lat, lon)
            terminal_names = {
                key
                for key in (
                    _name_key(terminal.get("name")),
                    _name_key(terminal.get("location")),
                )
                if key
            }
            exact_name = bool(
                port_names
                and terminal_names
                and any(
                    left == right or left in right or right in left
                    for left in port_names
                    for right in terminal_names
                    if len(left) >= 4 and len(right) >= 4
                )
            )
            # A name resemblance never overrides geography.  Generic maritime
            # words (for example "anchorage" or "coal point") otherwise create
            # convincing but globally incorrect joins.
            if distance > 50 or (not exact_name and distance > 18):
                continue
            confidence = "high" if exact_name and distance <= 25 else "medium"
            matches.append(
                {
                    "id": "gem-coal-" + _slug(str(terminal.get("name") or "")),
                    "name": _clean(terminal.get("name")),
                    "location": _clean(terminal.get("location")),
                    "status": _clean(terminal.get("status")),
                    "capacity_mtpa": _number(terminal.get("capacity")),
                    "owner": _clean(terminal.get("owner")),
                    "wiki_url": _clean(terminal.get("wiki_url")),
                    "lat": lat,
                    "lon": lon,
                    "distance_km": round(distance, 1),
                    "match_confidence": confidence,
                }
            )
        return sorted(matches, key=lambda item: item["distance_km"])

    def refresh(self) -> None:
        if "world_ports" not in self._tables():
            self.ports = []
            self.by_id = {}
            self.facets = {"categories": [], "countries": []}
            self.summary = {"total": 0, "classified": 0, "dry_bulk": 0}
            return

        terminals = self._load_coal_terminals()
        output: List[Dict[str, Any]] = []
        seen_ids: Counter[str] = Counter()
        facility_keys = [
            "fac_wharves",
            "fac_anchorage",
            "fac_solid_bulk",
            "fac_liquid_bulk",
            "fac_container",
            "fac_breakbulk",
            "fac_oil_terminal",
            "fac_lng_terminal",
            "fac_roro",
        ]
        for index, raw in enumerate(self._load_world_ports()):
            name = _clean(raw.get("name"))
            lat = _number(raw.get("lat"))
            lon = _number(raw.get("lon"))
            if not name or lat is None or lon is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue

            raw_id = _clean(raw.get("id"))
            if isinstance(raw_id, float) and raw_id.is_integer():
                raw_id = int(raw_id)
            base_id = str(raw_id or f"{_slug(str(name))}-{index + 1}")
            seen_ids[base_id] += 1
            port_id = (
                base_id
                if seen_ids[base_id] == 1
                else f"{base_id}-{seen_ids[base_id]}"
            )

            facilities = {
                key.removeprefix("fac_"): _flag(raw.get(key))
                for key in facility_keys
            }
            categories: List[str] = []
            category_map = {
                "solid_bulk": "dry_bulk",
                "liquid_bulk": "liquid_bulk",
                "container": "container",
                "breakbulk": "breakbulk",
                "oil_terminal": "oil",
                "lng_terminal": "lng",
                "roro": "roro",
                "anchorage": "anchorage",
            }
            for key, category in category_map.items():
                if facilities.get(key) is True:
                    categories.append(category)

            channel = _decode_depth(raw.get("channel_depth"))
            anchorage = _decode_depth(raw.get("anchorage_depth"))
            cargo = _decode_depth(raw.get("cargo_depth"))
            oil = _decode_depth(raw.get("oil_depth"))
            lng = _decode_depth(raw.get("lng_depth"))
            country_code, country_name = _country_identity(raw.get("country"))
            port: Dict[str, Any] = {
                "id": port_id,
                "name": str(name),
                "alternate_name": _clean(raw.get("alternate_name")),
                "search_aliases": [],
                "unlocode": _clean(raw.get("unlocode")),
                "country": country_code,
                "country_name": country_name,
                "lat": lat,
                "lon": lon,
                "harbor_size": _decode_lookup(raw.get("harbor_size"), HARBOR_SIZE),
                "harbor_type": _decode_lookup(raw.get("harbor_type"), HARBOR_TYPE),
                "harbor_use": _clean(raw.get("harbor_use")) or "Unknown",
                "shelter": _clean(raw.get("shelter")) or "Unknown",
                "channel_depth": channel["display"],
                "channel_depth_m": channel["minimum_m"],
                "anchorage_depth": anchorage["display"],
                "anchorage_depth_m": anchorage["minimum_m"],
                "cargo_depth": cargo["display"],
                "cargo_depth_m": cargo["minimum_m"],
                "oil_depth": oil["display"],
                "lng_depth": lng["display"],
                "max_vessel": _decode_lookup(raw.get("max_vessel"), MAX_VESSEL),
                "max_vessel_length_m": _number(raw.get("max_vessel_length")),
                "max_vessel_beam_m": _number(raw.get("max_vessel_beam")),
                "max_vessel_draft_m": _number(raw.get("max_vessel_draft")),
                "tidal_range_m": _number(raw.get("tidal_range")),
                "entrance_width_m": _number(raw.get("entrance_width")),
                "facilities": facilities,
                "navigation": {
                    "pilotage_compulsory": _flag(raw.get("pilotage_compulsory")),
                    "pilotage_available": _flag(raw.get("pilotage_available")),
                    "tugs_assistance": _flag(raw.get("tugs_assistance")),
                },
                "services": {
                    "cranes_fixed": _flag(raw.get("cranes_fixed")),
                    "cranes_mobile": _flag(raw.get("cranes_mobile")),
                    "cranes_container": _flag(raw.get("cranes_container")),
                    "railway": _flag(raw.get("railway")),
                    "repairs": _clean(raw.get("repairs")),
                    "dry_dock": _clean(raw.get("dry_dock")),
                },
                "categories": categories,
                "coal_terminals": [],
                "sources": [
                    {
                        "name": "NGA World Port Index",
                        "url": WPI_SOURCE_URL,
                        "role": "port specifications",
                    }
                ],
            }
            matched = self._terminal_matches(port, terminals)
            if matched:
                if "dry_bulk" not in port["categories"]:
                    port["categories"].append("dry_bulk")
                port["categories"].append("coal")
                port["coal_terminals"] = matched
                matched_names = {
                    str(item.get("name") or "").strip().lower()
                    for item in matched
                }
                port["search_aliases"] = sorted(
                    {
                        alias
                        for terminal in terminals
                        if str(_clean(terminal.get("name")) or "").strip().lower()
                        in matched_names
                        for alias in (
                            [str(_clean(terminal.get("name")) or "")]
                            + self._terminal_search_aliases(terminal)
                        )
                        if alias
                    }
                )
                port["sources"].append(
                    {
                        "name": "Global Coal Terminals Tracker",
                        "url": GEM_COAL_TERMINALS_URL,
                        "role": "coal terminal capacity and status",
                    }
                )

            core_values = [
                port["unlocode"],
                port["harbor_size"] != "Unknown",
                port["harbor_type"] != "Unknown",
                port["channel_depth_m"],
                port["anchorage_depth_m"],
                port["cargo_depth_m"],
                port["max_vessel_draft_m"],
                any(value is not None for value in facilities.values()),
            ]
            complete = sum(
                value not in (None, False, "", "Unknown") for value in core_values
            )
            port["data_completeness_pct"] = round(complete / len(core_values) * 100)
            port["categories"] = sorted(set(port["categories"]))
            port["coal_terminal_count"] = len(port["coal_terminals"])
            port["coal_capacity_mtpa"] = round(
                sum(
                    item.get("capacity_mtpa") or 0
                    for item in port["coal_terminals"]
                    if str(item.get("status") or "").lower() == "operating"
                ),
                1,
            )
            output.append(port)

        # WPI covers ports but not every named loading terminal or offshore
        # anchorage. Add operating GEM locations as explicit searchable
        # records, preserving their source status and leaving unknown marine
        # specifications unknown.
        terminal_ids: Counter[str] = Counter()
        terminal_seen: set[tuple[str, float, float]] = set()
        for terminal in terminals:
            if str(_clean(terminal.get("status")) or "").lower() != "operating":
                continue
            lat = _number(terminal.get("lat"))
            lon = _number(terminal.get("lon"))
            name = _clean(terminal.get("name"))
            if not name or lat is None or lon is None:
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            identity = (_normal_key(str(name)), round(lat, 5), round(lon, 5))
            if identity in terminal_seen:
                continue
            terminal_seen.add(identity)
            raw_terminal_id = str(
                _clean(terminal.get("asset_id")) or _slug(str(name))
            )
            base_terminal_id = f"gem-terminal-{raw_terminal_id}"
            terminal_ids[base_terminal_id] += 1
            terminal_port_id = (
                base_terminal_id
                if terminal_ids[base_terminal_id] == 1
                else f"{base_terminal_id}-{terminal_ids[base_terminal_id]}"
            )
            output.append(
                self._specialist_terminal_port(terminal, terminal_port_id)
            )

        self.ports = sorted(output, key=lambda item: item["name"].lower())
        self.by_id = {item["id"]: item for item in self.ports}
        category_counts = Counter(
            category for item in self.ports for category in item["categories"]
        )
        country_counts = Counter(
            str(item["country"]) for item in self.ports if item.get("country")
        )
        country_labels = {
            str(item["country"]): str(item.get("country_name") or item["country"])
            for item in self.ports if item.get("country")
        }
        self.facets = {
            "categories": [
                {"id": key, "label": key.replace("_", " ").title(), "count": value}
                for key, value in sorted(category_counts.items())
            ],
            "countries": [
                {"id": key, "label": country_labels.get(key, key), "count": value}
                for key, value in sorted(country_counts.items())
            ],
            "harbor_sizes": [
                {"id": key, "label": key, "count": value}
                for key, value in sorted(
                    Counter(
                        item["harbor_size"]
                        for item in self.ports
                        if item["harbor_size"] != "Unknown"
                    ).items()
                )
            ],
        }
        self.summary = {
            "total": len(self.ports),
            "classified": sum(bool(item["categories"]) for item in self.ports),
            "dry_bulk": category_counts.get("dry_bulk", 0),
            "coal": category_counts.get("coal", 0),
            "with_channel_depth": sum(
                item["channel_depth_m"] is not None for item in self.ports
            ),
            "with_cargo_depth": sum(
                item["cargo_depth_m"] is not None for item in self.ports
            ),
        }

    def filtered(
        self,
        *,
        q: Optional[str] = None,
        categories: Optional[Iterable[str]] = None,
        countries: Optional[Iterable[str]] = None,
        harbor_sizes: Optional[Iterable[str]] = None,
        min_channel_m: Optional[float] = None,
        min_cargo_m: Optional[float] = None,
        min_anchorage_m: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        query = (q or "").strip().lower()
        category_set = {item.strip().lower() for item in categories or [] if item}
        country_set = {item.strip().lower() for item in countries or [] if item}
        harbor_set = {item.strip().lower() for item in harbor_sizes or [] if item}
        output = []
        for port in self.ports:
            if query:
                haystack = " ".join(
                    [
                        str(port.get(key) or "")
                        for key in (
                            "name",
                            "alternate_name",
                            "unlocode",
                            "country",
                            "country_name",
                        )
                    ]
                    + [
                        str(alias)
                        for alias in port.get("search_aliases", [])
                    ]
                ).lower()
                if query not in haystack:
                    continue
            if category_set and not category_set.intersection(port["categories"]):
                continue
            port_country_values = {
                str(port.get("country") or "").lower(),
                str(port.get("country_name") or "").lower(),
            }
            if country_set and not country_set.intersection(port_country_values):
                continue
            if harbor_set and port["harbor_size"].lower() not in harbor_set:
                continue
            if min_channel_m is not None and (
                port["channel_depth_m"] is None
                or port["channel_depth_m"] < min_channel_m
            ):
                continue
            if min_cargo_m is not None and (
                port["cargo_depth_m"] is None or port["cargo_depth_m"] < min_cargo_m
            ):
                continue
            if min_anchorage_m is not None and (
                port["anchorage_depth_m"] is None
                or port["anchorage_depth_m"] < min_anchorage_m
            ):
                continue
            output.append(port)
        return output

    @staticmethod
    def compact(port: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: port.get(key)
            for key in (
                "id",
                "name",
                "alternate_name",
                "search_aliases",
                "unlocode",
                "country",
                "country_name",
                "lat",
                "lon",
                "categories",
                "harbor_size",
                "harbor_type",
                "channel_depth",
                "channel_depth_m",
                "anchorage_depth",
                "anchorage_depth_m",
                "cargo_depth",
                "cargo_depth_m",
                "max_vessel",
                "max_vessel_draft_m",
                "specialist_terminal",
                "terminal_status",
                "terminal_capacity_mtpa",
                "coal_terminal_count",
                "coal_capacity_mtpa",
                "data_completeness_pct",
            )
        }
