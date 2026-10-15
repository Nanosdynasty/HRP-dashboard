# NPP and India Coal master database

The local file `npp_master.duckdb` is built from the supplied `npp_data/master` CSVs by
[`scripts/build_npp_master_database.py`](../../scripts/build_npp_master_database.py).
The build reads the supplied files without modifying them, checks the core keys and
national coal quantities, then atomically replaces the database. The database and
its local-path manifest are ignored by Git. Rebuild on another machine with:

```powershell
.\.venv\Scripts\python.exe scripts\build_npp_master_database.py --source "C:\path\to\npp_data"
```

The incremental daily refresh is `scripts/update_npp_daily.py`. It reads dates
advertised by NPP, validates the new fuel and DGR1 reports, and writes the
chart-ready canonical CSVs plus `ui/npp_daily_refresh.json` source lineage.
Run it before rebuilding the database. In this snapshot the national fuel series
reaches **13 October 2026** and corrected DGR thermal generation reaches
**12 October 2026**. DGR XLS reports stop on 5 October; later DGR1 PDFs are
reconciled from the five regional thermal rows. October sums are incomplete.

The database contains these groups:

| Status | Tables | Intended use |
| --- | --- | --- |
| Validated | `daily_coal_national`, `daily_generation_dgr1` | National fuel stock, receipts, coal burn and corrected daily generation. |
| Derived from an official report | `station_stock_cover_latest` | Per-station stock divided by reported daily requirement at 85% PLF; the four bands are an app calculation, not NPP dashboard categories. |
| Derived | `rainfall_station_daily`, `rainfall_station_monthly`, `monsoon_daily`, `monsoon_monthly`, `monsoon_season`, `monsoon_coal_daily`, `monsoon_coal_yearly`, `monsoon_generation_yearly` | Seasonal context and joins. Rainfall is Open-Meteo ERA5 reanalysis averaged across selected locations; it is **not** an official, area-weighted India rainfall total. |
| Partial | `monthly_generation_summary` | Parsed monthly reports represented in the supplied master only. The larger raw report archive does not imply these rows cover every archived month. |
| Raw evidence | `monthly_fuel_source_rows`, `daily_coal_plant_source_rows`, `daily_generation_raw_rows` | Auditing and future parsers. The old plant-level coal master has misaligned numeric columns and must not be used as a validated station-stock series. Generic DGR rows contain report cells, not normalized measures. |
| Provenance | `source_files`, `archive_files`, `quality_checks` | Source hashes, observed coverage, original report inventory and validation results. |

Useful views: `coal_month_end`, `india_daily_generation`, and `india_monsoon_coal`.
The authenticated `GET /api/coal/master/coverage` endpoint reports dataset coverage,
quality checks and the archive inventory without exposing local source paths.
`coal_month_end.stock_000t` is the last **observed** national stock in each month;
`observed_days` indicates how complete that month is. Monthly fuel and generation
source rows preserve the original `month` value and add `period_start` for chronological queries.

Example queries:

```sql
SELECT * FROM source_files ORDER BY table_name;
SELECT * FROM quality_checks WHERE failed_rows > 0;
SELECT * FROM coal_month_end ORDER BY month DESC LIMIT 12;
SELECT date, category, today_actual_mu
FROM india_daily_generation WHERE date >= DATE '2026-09-01'
ORDER BY date DESC, category;
SELECT date, rain_india_mm, coal_cons_000t
FROM india_monsoon_coal ORDER BY date DESC LIMIT 30;
```

The 2017–2021 daily fuel archive includes sheets using the `dailyCoal1` filename
for unrelated reports. The validated national coal series begins in November 2021;
its latest date depends on the supplied master. The corrected DGR1 series supersedes
`06b_daily_generation_DGR1_summary.csv`, whose old parser read shifted columns.
The supplied monthly rainfall field `rain_days_over25mm` counts days with **at least
2.5 mm**, despite its misleading column name. The final September 2026 rainfall
month is partial through 27 September in this snapshot. No correlation in the
supplied analysis is treated as causal evidence.

The current dashboard's Ministry production and imports series remain separate
official releases. Building this NPP database does not relabel those measures as
NPP data or overwrite them. The latest loaded Ministry production/dispatch month
is July 2026; the last comparable monthly customs imports are March 2026. The
61.89 MT Apr–Jun 2026 import release is cumulative and is not a June monthly
observation. The Coal workspace's Compare datasets tab aligns two to six series
by reporting month and uses the first shared reported month as index 100.
