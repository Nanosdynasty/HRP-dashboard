River and canal repair — 28 September 2026

The river view now fits all filtered gauge coordinates, including Indonesia; changing country clears incompatible waterway/type/status filters and focuses the selected region. The open view polls the API every minute. Source refresh runs every five minutes and retains each failed source’s last observation with its original observation time and an explicit source error.

Panama canal profile links the available Gatún lake elevation, observation date, published maximum drafts and surcharge as separate indicators. The lake PDF’s date uses Panama local time (UTC−5) with day precision. Canal queue and delay counts remain unavailable; lake elevation is never represented as navigable depth. Official source: https://evtms-rpts.pancanal.com/eng/h2o/index.html.

The Indonesian SIHKA Kapuas/Sukalanting station remains visible with no fabricated level when the official asset payload supplies no telemetry. Musi and Barito observations retain their timestamps; Indonesian history timestamps use the same interpretation as the current record. Source: https://sihka.sda.pu.go.id/.

Checks: tests/test_river_visibility.py, tests/test_river_levels.py and tests/test_river_visibility.cjs.
