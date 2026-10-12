# Voyage and AIS workspaces

## Repository inspection and staged plan (28 September 2026)

The existing app is FastAPI/Pydantic, static HTML/JavaScript and Leaflet. DuckDB holds bundled asset/trade tables; SQLite already holds AISStream observations and latest vessel positions. `PortCatalog` exposes stable WPI/GEM IDs, coordinates, country, enrichment and source records. `data/port_approaches.json` holds a small reviewed sea-approach catalogue and existing corridor fixtures. Port coordinates without dated review retain a null `last_checked`; loading a catalogue is not a location verification.

The existing Docker/Render service uses one worker and `HRP_STORAGE_DIR`. Administrative uploads follow the existing `X-Admin-Token` middleware; production disables admin writes until `APP_ADMIN_TOKEN` is set. The new upload route is added to that protection, rather than introducing a separate login. Read-only calculations follow the existing API access model.

The AIS adapter already receives decoded AISStream JSON. Its SQLite history has MMSI, observation time, position, speed, course, heading and name, with configurable 90-day retention and an observation cap. Receiver coverage is partial and collection start is not historic global coverage. There is no documented complete dry-bulk/DWT registry; those fields stay unknown for collected history. GTT and Kpler providers are not newly accessed. The previously removed GTT navigation is not restored.

Implementation stages:

1. Reuse the installed route engine and existing curated corridor; add reusable scenario arithmetic, source-aware coordinate catalogue, inland rejection, own screened graph retry, manual passage distances and route caching. Add the sidebar workspace, origin comparison and CSV.
2. Add an atomic decoded-CSV adapter to bounded SQLite storage, plus an adapter for the already collected history. Apply documented polygons and gap-aware event rules, expose audited trajectories, weekly polygon activity, stops, filters and frozen export.
3. Show the existing official annual coal country imports as separate supply context. Do not join national totals to selected discharge ports or label hypothetical tonne-miles as observed trade. Other requested comparisons remain unavailable until compatible port/period/OD data exists.
4. Test calculations, quality and API/JS contracts, benchmark a historical sample, restart the local service and provide this walkthrough. No deployment or new paid feed is included.

## Voyage walkthrough

Open **Voyage & Tonne-Miles** in the existing sidebar. The default Richards Bay → Paradip scenario uses 75,000 tonnes, 12 knots laden, 13 knots ballast and two total port days. Calculate to show the final route line, approximately 4,509 nm and approximately 338 million tonne-nautical-miles. The final polyline controls distance; connectors are included once. Nothing is rounded before tonne-mile/time arithmetic.

Use the catalogue origin input to append a country-qualified port. Enter additional origins on separate lines, or use **Coal → India** for Indonesian, Australian, South African and Russian candidates. Unsupported candidates show their own error and are retained as unsuccessful rows in CSV; other origins still calculate. The current Vostochny catalogue point fails generalized inland screening and requires a reviewed sea approach or a separately sourced manual distance. Do not silently shift an inland coordinate out to sea.

**Iron ore → China** selects Port Hedland → Qingdao Gang, Capesize and 180,000 tonnes. The screened route is approximately 3,574 nm. Input `longitude,latitude` to use analyst coordinates. An optional intermediate port creates two laden legs, each included once. The vessel segment is descriptive: it does not determine draft clearance, consumption or port feasibility.

Supported passage controls exclude Suez, Panama or Malacca graph edges. The Cape option excludes Suez and requires the analyst to inspect the actual reported passages; it cannot promise a forced Cape transit. Required Suez/Panama transits use a **manual verified distance** and source/reference. Manual routes have no invented map line. The analyst's reference is retained but is not independently certified by the app.

Equations: tonnes × laden nm = tonne-nautical-miles; nm ÷ knots ÷ 24 = sea days. Ballast return uses the same distance in reverse and contributes no cargo tonne-miles. Round trip adds both sea legs and port days once. A 24-hour, 256-entry per-process cache stores route geometry, independent of speed and cargo. Comparisons are bounded to eight origins.

The Natural Earth 1:50m land snapshot is public-domain cartographic data, not an official hydrographic chart. Hash and source are in `data/voyage_land_provenance.json`. The inland screen uses a 0.025-degree coast tolerance; ports, islands, river channels and terminal approaches can be generalized or missing. The graph retry removes detected inland-crossing edges from a private copy and attaches exact endpoints only through screened connectors within 100 nm. Narrow Suez/Panama network corridor exceptions do not establish current canal access. The older voyage tool and shared route graph are preserved. This module cannot claim water depth, current restrictions, weather avoidance, piracy avoidance or an actual sailed/commercial track.

## AIS setup and walkthrough

Open **AIS & Port Activity**. Either select collected AISStream history (where available) or upload an authorized decoded CSV. Administrator uploads are protected by the app's existing admin-token policy. No proprietary scraping or provider credentials are introduced. Data is stored in `HRP_STORAGE_DIR/_port_activity/activity.sqlite3`; Render needs a persistent disk to preserve uploads. Bundled code/data is included by the existing Docker `COPY . .`.

CSV columns:

| Column | Meaning |
|---|---|
| `mmsi` | Nine-digit MMSI, not vessel name as an identifier |
| `timestamp` | ISO 8601 with offset, normalized to UTC; naive times rejected |
| `lon`, `lat` | WGS84 decimal longitude then latitude |
| `sog_kn` | Optional observed speed in knots |
| `dwt` | Optional supplied vessel DWT in tonnes |
| `segment` | Optional supplied segment; no inference from AIS destination/type |
| `name` | Optional vessel name |
| `data_class` | `synthetic` for test rows; disables real congestion aggregation |

Max upload is 20 MB/100,000 positions. Source, permitted-use attestation and coverage description are required. Source coverage confirmation is separately entered only with supporting provider evidence. Identical MMSI/time/position duplicates are removed; conflicting positions at the same MMSI/time are all excluded. Invalid MMSIs, coordinates, quantities and timestamps are reported. Failed parsing never publishes a partial dataset. Different MMSIs are not automatically merged into one vessel.

Download the **synthetic test sample** for a demonstration: upload with source “Synthetic sample”, coverage “Synthetic test only” and permitted-use checked. Load **Synthetic sample polygons**, then analyze. Five synthetic vessels produce ten inferred visits, five anchorage and five port. These illustrative rectangles are not harbour limits and are never auto-applied to real data. Synthetic rows stay labeled and cannot produce real congestion estimates.

For real analysis, upload a JSON array of reviewed zones. Each entry needs `id`, stable `port_id`, `name`, `kind` (`port` or `anchorage`), GeoJSON Polygon/MultiPolygon in longitude/latitude, and `source`. The bundled sample illustrates the contract. Zone IDs must be unique; invalid/self-intersecting/world-spanning geometry is rejected. Port filters require a matching polygon. Optional UTC dates, segment, DWT and latest polygon status filters apply to map, table and audit export together. Missing DWT/segment excludes a vessel from those specific filters.

Rules displayed beside the analysis:

- Entry requires two consecutive inside observations and uses the first inside time. Already-inside positions at the window/track start are left-censored, not arrivals.
- Exit requires two consecutive outside observations and uses the first outside time. Silence never becomes departure.
- A gap greater than the configurable maximum (default six hours) splits the track and leaves unfinished visits right-censored. Map trajectories never bridge such gaps.
- Anchorage duration means polygon occupancy, not confirmed queue time. The minimum stay defaults to 0.5 hours; shorter visits remain in the audit with a flag.
- Basic stop detection requires observed speed ≤0.5 kn, cumulative path ≤0.5 nm and the selected minimum duration. This is a transparent heuristic, not a berth/cargo-operation determination.
- Weekly arrivals/departures are inferred events in the supplied sample, separated by port and zone kind. They are not total port traffic. Mean anchorage occupancy appears only with confirmed source coverage, at least three filtered vessels, no transmission gaps and at least three distinct completed anchorage vessels in that port/week.

The map shows historical AIS-observed positions with observation times/age; trajectories and polygon visits are inferred. No future arrival forecast is added. Charts/table retain unassessed waiting estimates as null. The visit table displays up to 500 rows and CSV exports all filtered visits, including censoring, rules, polygon/source and timestamp metadata. A 20-minute frozen analysis snapshot ensures that newly collected live data cannot change the CSV. Eight snapshots are retained per process; expired ones require a new analysis.

The synthetic 30,000-row/1,250-vessel benchmark is saved in `docs/ais-performance-check.json`: import ~0.7 s, SQLite read ~0.15 s, rule analysis ~1.1 s on this machine. It demonstrates bounded sample processing, not multi-million-row production performance or satellite completeness. SQLite is appropriate for this first bounded adapter; larger historical ingestion needs a separate evidence-backed storage decision. The live-history query applies UTC date filters before its 100,000-row limit. The workspace automatically selects collected history and loads the latest hour when available. Selecting collected history initializes the date range to the latest hour; choosing an uploaded dataset clears that preset. AISStream nanosecond UTC timestamps are explicitly normalized. Larger windows request a smaller date range or authorized export.

## Package/source review

Upstream README, dependency manifest, licence and relevant route/decoder/database/stop source were inspected at the commits below. `docs/package-review-evidence.json` records file URLs/hashes and review date. All five repositories were unarchived at inspection. The existing repository has no root licence file; no new upstream code was vendored. The selected runtime dependency remains the installed package, pinned to `searoute==1.6.0`.

| Candidate | Inspected commit / latest commit date | Licence | Decision |
|---|---|---|---|
| [searoute-py](https://github.com/genthalili/searoute-py) | `4446009a4ce0c79bcf67616c05f28820fbdc7e08` / 2026-05-17 | Apache-2.0 | Keep installed 1.6.0. Python/networkx/geojson fits the app; route source supports nautical units, restrictions and own graph. Preserve licence/notices on distribution. Reviewed HEAD is separate from the installed version. |
| [Eurostat searoute](https://github.com/eurostat/searoute) | `88a2e568a8e0144d1f5a81c3931a7bc2bcce6901` / 2022-01-10 | EUPL-1.2 | Not installed. Java/Maven with geospatial/graph dependencies adds a second service, older inspected maintenance and copyleft obligations; no demonstrated passage advantage for this FastAPI app. |
| [AISdb](https://github.com/MAPS-Lab/AISdb) | `13773b3bba430f16accd31b63a1a4170622dd908` / 2026-09-05 | AGPL-3.0-or-later in manifest | Not installed. Rust/maturin plus scientific/geospatial/psycopg dependencies and SQLite/TimescaleDB support are unnecessary for bounded decoded uploads. AGPL network-source obligations also need deliberate fit before commercial integration. It supplies processing tools, not an AIS feed. |
| [MovingPandas](https://github.com/movingpandas/movingpandas) | `17640c6b95a0541c3cfba9b447376f51ae7d8ff3` / 2026-09-13 | BSD-3-Clause | Deferred. Maintained trajectory/diameter-duration stop support is a suitable future optional tool; GeoPandas/geospatial dependency stack is not needed for polygon visits and basic speed/path stops here. BSD permits commercial/internal use with retained notices. Current stops are explicitly our heuristic, not MovingPandas results. |
| [pyais](https://github.com/M0r13n/pyais) | `4e4950ac726db26937202f9d51abbb09203c2c8c` / 2026-09-27 | MIT | Not installed. Maintained multipart AIS/NMEA decoder, but both adapters consume already decoded positions. Add only if raw AIVDM/AIVDO input is introduced. MIT requires retaining its notice if adopted. |

Natural Earth usage terms: [public-domain terms](https://www.naturalearthdata.com/about/terms-of-use/). Existing GEM/WPI attribution stays in the port catalogue. Neither open-source software licences nor an API key automatically grants rights to a commercial AIS dataset; the uploader supplies permitted data.

## Market comparison boundaries

The observed annual FY2024-25 India import context covers Indonesia, Australia, South Africa and Russia in million metric tonnes with final status, canonical file lineage and snapshot generation timestamp. The selected-voyage quantity remains a separate scenario input. No selected-port allocation, historical tonne-mile trend, port-volume/call correlation, cargo/shipper deduction or congestion/availability relationship is fabricated. Activate those only with licensed OD/port/period-grain records and compatible vessel coverage. Existing coal and freight features remain intact.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_voyage_analysis.py tests/test_port_activity.py tests/test_voyage_activity_api.py -q -p no:cacheprovider
node --test tests/test_voyage_activity_frontend.cjs
node --check static/js/voyage-activity.js
node --check static/js/app.js
```

Browser visual automation was unavailable in this session; API checks and JS contract tests are not a substitute for a rendered visual review. This walkthrough describes the controls for a manual screen check. Mobile forms reduce to one column and wide tables scroll horizontally; map containers retain a usable minimum height.

Verification completed: 186 Python tests and eight subtests passed, plus 17 JavaScript checks (six new workspace checks and eleven existing intelligence/outlook/river/weather checks). Python compilation, JavaScript syntax and whitespace checks passed. Coal and iron-ore API acceptance routes passed. Rendered browser inspection was not performed.

AIS map visibility repair: the initial collected-history map now loads automatically, uses Canvas rendering, and sits near the top of the workspace. If the preset exceeds the bounded analysis limit, automatic loading halves the window (up to three retries), updates the visible UTC dates and reports the actual displayed period. Manual filter requests do not silently change dates. A live acceptance check returned 25,096 vessel positions from 60,339 observations in the latest-hour window. The frontend regression checks that opening the workspace requests analysis and adds vessel markers.

Vessel search repair: the original Live AIS Find & add control now searches all retained latest positions plus the live cache through GET /api/ais/search, independently of map regions. Explicit search results are pinned across type/region filters and centered on the map; search also enables the display when its toggle was off. Static IMO/call-sign metadata is retained alongside MMSI for future restart-safe lookup. Seven-digit IMO queries match IMO exactly, not substrings of MMSI. Missing static data or missing observed positions produce a precise no-record result. No external tracking positions are imported. For user example IMO 9713466, neither the current cache nor the retained position database had a match at the check time.
