# Global Energy & Maritime Intelligence Dashboard

An interactive FastAPI dashboard combining Global Energy Monitor assets with a
normalized port catalog and an analytical voyage-distance tool.

The current interface is map-first: a fixed world map and one clean left panel
with Energy, Ports, Commodities, and port-to-port voyage controls. It uses the
official Howe Robinson Partners logo and its blue, navy, red, and dark-red
palette.

---

## Features

- Separate Energy, Ports, and Commodities map workspaces, so unrelated layers
  do not remain visible when the user changes section
- Country and operating-status filters across energy and commodity assets
- Renewable-energy grouping for solar, wind, hydro, geothermal, and bioenergy,
  with fossil energy and nuclear kept separate
- Commodity layers for coal mines, coal trade terminals, iron ore mines, iron and
  steel plants, and cement plants
- Import, export, and domestic role filters for 519 GEM coal trade terminals
- 3,669 normalized World Port Index records with country, harbor, depth, vessel,
  navigation, service, and facility fields where present
- Every port is rendered as a small individual map dot—there are no numbered
  clusters
- Port filters for country, harbor size, and source-supported port categories
- Compact hover labels and click-through port/asset detail cards
- Geographically guarded enrichment from the GEM Global Coal Terminals Tracker
- Searchable port routing with selectable origin/destination, map picking,
  route confidence, passage and canal avoidance, vessel speed, sea margin,
  operational delays, and a visible route polyline
- Map-only extracts from the uploaded GEM workbook bundle:
  5,382 coal mines, 519 coal trade terminals, 949 iron ore mines, 46 reviewed
  major iron ore terminals, 1,293 steel plants, 3,513 cement plants, 835
  geothermal assets, and 4,537 bioenergy assets

### Voyage-calculation method

The calculator resolves selected IDs against the bundled World Port Index
catalogue. When a reviewed sea-side approach exists in
`data/port_approaches.json`, routing starts at that point instead of an inland
catalogue centroid. Paradip uses the official Port Authority Fairway Buoy and
Richards Bay uses the CSIR operational offshore buoy reference. The initial
Paradip-Richards Bay corridor clears Sri Lanka and Madagascar and is densified
to a maximum analytical graph edge of 25 nautical miles. Its 4,509 nm result is
within 0.3% of the supplied 4,496 nm NETPAS benchmark.

Routes without a curated corridor continue to use the `searoute` 1.6 maritime
network. Great-circle, network-only, connector-leg, and detour calculations are
retained internally for quality control but are no longer shown in the
calculator result card.

Time is broken into calm-sea sailing time, a user-entered sea-margin percentage,
port time, and canal delay. Passage-avoidance controls currently cover Suez,
Panama, and Malacca. Results are analytical shortest-path estimates and are not
safe for navigation, berth clearance, charter-party performance claims, or
substitution for commercial routing tools and official charts.

---

## Quick start (local)

### Easiest — one-click scripts

**macOS / Linux**
```bash
cd gem-dashboard
chmod +x start.sh
./start.sh
```

**Windows**
```
Double-click start.bat
```
(or open a terminal in the folder and run `start.bat`)

The script will:
1. Create a virtual environment (if needed)
2. Install dependencies
3. Start the server
4. Open http://localhost:8000 in your browser

### Manual start

```bash
cd gem-dashboard
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000

### Environment variables

Copy `.env.example` values into your deployment environment. Important variables:

- `AISSTREAM_API_KEY`: optional live AIS vessel tracking. Never commit this value.
- `ALLOWED_ORIGINS`: comma-separated trusted browser origins.
- `XAI_API_KEY`: optional Grok chat integration.
- `APP_ADMIN_TOKEN`: protects uploads, manual refreshes and Data Hub approvals. The UI asks for it only when an administrator action is attempted.
- `HRP_STORAGE_DIR`: runtime data directory. Point this to a persistent Render disk (for example `/var/data/hrp`) in production.
- `AIS_RAW_RETENTION_DAYS`: raw AIS trail retention, default `90`; the latest position per vessel is retained separately.
- `AIS_MAX_OBSERVATIONS`: hard cap for raw AIS observations, default `2000000`.

If an AIS credential was previously committed, revoke it at the provider and
replace it with a newly issued environment-only key.

## Deploy on Render.com

### Option A – Blueprint (recommended)

1. Push this folder to a GitHub repo.
2. In Render → New → Blueprint → connect the repo.
3. Render will read `render.yaml` and create the web service.
4. After deploy, go to Environment and add:
   - `XAI_API_KEY` = your xAI / Grok key (optional but recommended)

### Option B – Manual Docker

1. New → Web Service → connect repo.
2. Runtime: Docker
3. Plan: Free (or Starter)
4. Health check path: `/api/health`
5. Add env var `XAI_API_KEY` if desired.

The free tier sleeps after inactivity; first request may take ~30 s.

---

## Data included

| Tracker       | Rows   | Operating capacity (approx) |
|---------------|--------|-----------------------------|
| Coal Plants   | 14 509 | ~2 200 GW                   |
| Solar         | 103 940| ~1 268 GW                   |
| Wind          | 33 248 | ~1 128 GW                   |
| Hydropower    | 6 772  | ~1 275 GW                   |
| Nuclear       | 1 749  | ~401 GW                     |

Source: Global Energy Monitor trackers (January–March 2026 releases). Attribution required under CC BY 4.0.

The port layer uses the repository's bundled World Port Index extract and GEM
coal-terminal data. The normalizer accepts richer official WPI column aliases,
so a future official refresh can add fields without changing the front-end API.
Unknown values—including berth count—remain unknown and are never converted to
zero. Port-to-terminal links are enrichment candidates based on name and
distance, expose match confidence, and are not authoritative facility joins.

Bauxite and limestone are not yet presented as operational mine layers. The
reviewed sources currently available do not safely distinguish active mines
from deposits, prospects, occurrences, and historical records at global scale.

## Verification

```bash
python -m unittest discover -s tests -v
node --check static/js/app.js
node --check static/js/app-map.js
```

---

## Project layout

```
gem-dashboard/
├── app.py              # FastAPI backend + DuckDB
├── data/               # Pre-processed CSV.GZ trackers
├── static/             # Frontend (HTML/CSS/JS)
├── uploads/            # User-uploaded files
├── start.sh            # One-click start (macOS / Linux)
├── start.bat           # One-click start (Windows)
├── Dockerfile
├── render.yaml
├── requirements.txt
└── README.md
```

---

## Color palette

- Howe Robinson blue `#003671`
- Howe Robinson navy `#1c294a`
- Howe Robinson red `#db2f34`
- Howe Robinson dark red `#b52a2a`

---

Built for deployment on Render.com · Data © Global Energy Monitor
