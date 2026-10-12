"""Explicit section policy. Unknown data operations fail closed."""
import re

SECTIONS = {
    "voyage_analysis": "Voyage & Tonne-Miles", "port_activity": "AIS & Port Activity History",
    "energy": "Energy", "ports": "Ports", "india_coal": "India Coal",
    "commodities": "Commodities", "news": "News & Intelligence", "live_ais": "Live AIS",
    "weather": "Weather & Disruption Outlook", "rivers": "Rivers, Reservoirs & Canals",
    "voyage_distance": "Voyage Distance",
}
LEVELS = {"hidden": 0, "view": 1, "edit": 2}
TRACKER_SECTIONS = dict.fromkeys(["coal_plants", "solar", "wind", "hydro", "nuclear", "geothermal", "bioenergy"], "energy")
TRACKER_SECTIONS.update(dict.fromkeys(["coal_mines", "coal_terminals", "coal_trade_terminals", "iron_ore_mines", "iron_ore_terminals", "steel_plants", "cement_plants"], "commodities"))
TRACKER_SECTIONS["world_ports"] = "ports"
READ_POSTS = {"/api/route", "/api/voyage/calculate", "/api/voyage/export", "/api/port-activity/analyze",
              "/api/port-activity/export", "/api/ais/snapshot", "/api/vessel/track", "/api/coal/research/query"}
PREFIXES = {
    "/api/voyage/": "voyage_analysis", "/api/port-activity/": "port_activity",
    "/api/ports": "ports", "/api/coal/": "india_coal", "/api/npp/": "india_coal",
    "/api/india/sources": "india_coal", "/api/news": "news", "/api/ais/": "live_ais",
    "/api/vessel/": "live_ais", "/api/river-levels": "rivers",
    "/api/imd/": "weather", "/api/bmkg/": "weather", "/api/sea/": "weather",
    "/api/major-port-weather": "weather", "/api/coastal-weather/": "weather",
    "/api/port-disruptions": "weather", "/api/port-disruption-outlook": "weather",
    "/api/weather": "weather", "/api/routing/": "voyage_distance",
    "/api/route": "voyage_distance", "/api/zones": "voyage_distance", "/api/bunker": "voyage_distance",
}
# Executable shell assets only; data-bearing static paths never inherit this permission.
SHELL_ASSETS = {
    "/static/index.html", "/static/css/style.css", "/static/css/styles.css",
    "/static/css/voyage-activity.css",
    "/static/js/app.js", "/static/js/broker-tools.js", "/static/js/port-outlook.js",
    "/static/js/intelligence-desk.js", "/static/js/voyage-activity.js",
    "/static/auth/access-v2.js",
}

def can(user, section, edit=False):
    return LEVELS.get(user.get("permissions", {}).get(section, "hidden"), 0) >= (2 if edit else 1)

def requirements(path, method, query):
    """Return (sections, edit), or None for a denied/unclassified route."""
    edit = method not in {"GET", "HEAD"} and path not in READ_POSTS
    edit = edit or query.get("force", "").lower() in {"true", "1", "yes"}
    if path == "/static/data/ais_sample_zones.json":
        return (["port_activity"], False)
    if path == "/api/voyage/market-context":
        return (["voyage_analysis", "india_coal"], False)
    match = re.fullmatch(r"/api/(?:data|map|kpis|countries|export)/([^/]+)", path)
    if match:
        section = TRACKER_SECTIONS.get(match[1])
        return ([section], edit) if section else None
    if path == "/api/layer-facets":
        trackers = query.get("trackers", "").split(",")
        if not trackers or any(t not in TRACKER_SECTIONS for t in trackers):
            return None
        return ([TRACKER_SECTIONS[t] for t in trackers], edit)
    for prefix, section in PREFIXES.items():
        if path == prefix.rstrip("/") or path.startswith(prefix if prefix.endswith("/") else prefix + "/"):
            return ([section], edit)
    return None
