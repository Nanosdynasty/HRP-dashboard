# Global dry-bulk port disruption outlook

Open Weather → Outlook. The inventory starts with existing catalog dry-bulk classifications and uniquely matched ports in the existing major-port weather registry. Documented berth/facility groups have deterministic IDs derived from the stable port ID and published name. A group is not split into invented individual berths. A port-wide facility catalogue is not assigned an invented terminal ID.

## Evidence and assessments

- **Weather watch:** affirmative general screening evidence. Wind ≥22 kt applies to operation checks; wave height ≥2.5 m applies to vessel access. Rain applies to loading/discharge checks only. These thresholds are not published shutdown limits.
- **Published limit exceeded:** a documented numerical rule matches port, terminal/berth, operation, equipment/conditions, measurement location/resolution, units and source/version/date. Forecast exceedance is planning evidence, not reported operating status.
- **Confirmed restriction:** a dated authority notice with fresh successful retrieval, verified location/operation and explicit effective validity. Current status and upcoming restrictions are separate.
- **No trigger identified:** the required screening measurements cover the full selected horizon. Missing operating limits remain a coverage gap.
- **Not assessed:** missing, stale, expired, unlinked or incomplete evidence prevents a negative conclusion for the horizon. A positive watch can still be shown with its missing-data limitations.

Cargo handling and vessel access remain separate operation rows. Consecutive overlapping intervals of the same assessment and timing resolution merge; gaps are never filled. No delay duration or probability is estimated. Rain-related commodity damage or shutdown is not inferred from commodity names; handling arrangements and sensitivity must be documented first.

## Matching and freshness

`port_disruption_outlook.PortMatcher` joins exact normalized canonical names with country codes, plus a small reviewed country-qualified alias registry. General catalog search aliases, nearest-port proximity and composite regional labels are deliberately excluded. Existing IMD coastal mappings are area forecasts, not berth instruments. Atmospheric MET Norway forecasts have no wave fields, so vessel-access negative conclusions remain unavailable.

Weather managers refresh every three hours with five-minute failure retries. Notice collection checks every fifteen minutes, with five-minute retry after source failure. The open weather view polls every minute. Failed sources preserve their last successful data timestamp. Expired forecasts are excluded from current risk and remain accessible through the historical view.

## Official rules and notices

The versioned rules catalogue is `data/port_operating_rules.json`. The current verified Port Hedland handbook provides weather-warning context, not a numerical berthing/loading shutdown rule: [April 2026 handbook](https://www.pilbaraports.com.au/about-pilbara-ports/publications/forms-and-publications/forms-and-publications/handbook/2026/april/port-of-port-hedland-port-handbook), section 7.20. It is kept as a qualitative instruction. A numerical limit must not be inferred from BOM warning categories or an older superseded handbook.

The notice adapters read Pilbara marine-notice cards, [Paradip's dated circular table](https://paradipport.gov.in/circulars-notices/), [DGLL's Indian port notice table](https://dgll.nic.in/notice-to-mariners), and the existing MPA integration. PDF documents are bounded in size/page count. Access challenges, TLS failures and oversized/unparseable documents are recorded honestly. Generic cyclone FAQs and tender/administrative rows do not create current restriction records.

Date-only validity is labelled and requires confirmation of effective hours/timezone. Unresolved local-area/berth scope is not promoted to whole-port scope. Corrected/replaced notices suppress predecessors; same-document changes retain document hashes and revision lineage. Withdrawal/reopening ends restriction eligibility. A notice disappearing from a listing is not treated as reopening. Only notices with a last successful check within thirty minutes can confirm current restrictions. Other authorities remain explicit source links.

No numerical dry-bulk equipment limit is currently promoted in the initial catalogue. Published-limit evaluation is implemented and tested, but insufficient location/equipment measurements must remain a gap rather than a fabricated limit exceedance. Public notice parsing is intentionally conservative; some documents require manual confirmation and therefore cannot enter confirmed alerts.

## API and exports

`GET /api/port-disruption-outlook` accepts `port`, `country`, `commodity`, `operation`, `assessment`, `forecast_window` (`0-24`, `24-72`), `sort`, `direction`, and `historical`. Optional `limit` (≤500) / `offset` paginate operation rows while `map_markers` represents all filtered ports, prioritizing their highest-severity filtered scope. Default API responses retain complete filtered rows. The UI requests fifty rows per page to avoid loading all operation detail on mobile.

`GET /api/port-disruption-outlook/export.csv` takes the same filters and the displayed `snapshot_id`. It exports all exact filtered rows in the selected sort order, including provenance, timestamps, gaps and rules. If a displayed snapshot is no longer cached, it returns 409 instead of silently exporting changed evidence. Existing weather and `/api/port-disruptions` routes remain compatible.

Checks: `tests/test_port_outlook.py`, `tests/test_port_outlook_api.py`, `tests/test_port_outlook_frontend.cjs`, plus existing weather schema/adapter/refresh and frontend-symbol regressions. Forecasts remain analytical planning aids. No external notifications or automatic operational actions are installed.

Indonesia feed repair (28 September 2026): BMKG now publishes maritime forecasts at `marine2026-data`, documented at https://maritim.bmkg.go.id/apidoc. Province indexes provide 659 port points and 375 marine areas; 658 port endpoints and all marine endpoints downloaded successfully during verification, with XZ017 returning 404. Hourly / three-hourly grids retain UTC intervals, current speed in knots, visibility in kilometres, and zero wave heights. Official marine polygons are stored once and reattached on cache load. The outlook maps an Indonesian inventory port to an area only when its coordinate is contained in that official polygon, and labels shared marine-area resolution. Reviewed general-port aliases also require consistent coordinates; distinct terminal names are not promoted to whole-port evidence. Nine major source port points remain visible at country zoom; other points appear when zoomed in. Source failures retain actual previous successful timestamps.

Cyclone display repair (28 September 2026): GDACS event `todate` is retained as `source_last_observed_at`, separately from forecast validity. A source-listed current event is eligible only with an event time within 36 hours; the same freshness constraint applies dynamically to cached records and the successful source check. No forecast expiry is invented when unavailable. Current position is labelled latest reported position, and track timing limitations are visible. Inactive or outdated source records remain hidden. A successful empty cyclone feed is a valid empty result. Cache publication is atomic; failed refreshes retain the previous successful snapshot and retry after five minutes. Documentation: https://www.gdacs.org/gdacsapi/swagger/index.html and https://www.gdacs.org/feed_reference.aspx.
