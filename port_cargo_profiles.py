"""Reviewed port-authority cargo capabilities, never inferred throughput shares."""
import re

PROFILES = [
    {"country": "AU", "names": ["port hedland", "hedland"], "cargoes": ["Iron ore", "Salt", "Manganese ore", "Copper concentrates", "Spodumene concentrate"], "basis": "Cargo categories reported by the port authority; November 2025 destination/origin report", "source_url": "https://www.pilbaraports.com.au/pilbaraportsauthority/media/documents/port%20of%20port%20hedland/about%20the%20port%20of%20port%20hedland/port%20statistics%20and%20reports/cargo%20by%20destination/2025/cargo-stats-by-destination_origin_november-2025.pdf"},
    {"country": "NL", "names": ["rotterdam", "europoort"], "cargoes": ["Iron ore", "Coal", "Grain", "Biomass", "Industrial minerals"], "basis": "Port authority dry-bulk handling capabilities; no cargo share implied", "source_url": "https://www.portofrotterdam.com/en/logistics/cargo/dry-bulk"},
    {"country": "IN", "names": ["paradip", "paradeep"], "cargoes": ["Thermal coal", "Coking coal", "Iron ore", "Iron ore pellets", "Steel", "Limestone", "Fertiliser", "Clinker", "Gypsum", "Manganese ore"], "basis": "Port authority cargo handling catalogue; no cargo share implied", "source_url": "https://paradipport.gov.in/know-your-port/"},
    {"country": "AU", "names": ["newcastle"], "cargoes": ["Coal", "Wheat"], "basis": "Historical port trade report, October 2021; current mix requires a newer report", "source_url": "https://www.portofnewcastle.com.au/wp-content/uploads/2021/11/20211001-Trade-Report-Oct-2021.pdf"},
]

def cargo_profile(port):
    country = str(port.get("country") or "").upper()
    name = re.sub(r"[^a-z0-9 ]", " ", str(port.get("name") or "").lower())
    name = " ".join(name.split())
    for profile in PROFILES:
        if country == profile["country"] and any(name == alias or name == "port " + alias for alias in profile["names"]):
            return {**profile, "reviewed_at": "2026-09-07", "classification": "reported cargo categories", "throughput_share": None}
    return None
