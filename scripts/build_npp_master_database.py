"""Build an inspectable NPP/coal DuckDB from the supplied parsed master archive.

The source archive is read only. A complete, validated temporary database replaces
the prior output only after all critical checks pass.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO / "data" / "india_coal_master" / "npp_master.duckdb"

# The two v1 masters are retained for audit, never used for headline measures.
SPECS = {
    "daily_coal_national": ("daily_coal_national.csv", "validated", "date", "date", "date", ["coal_cons_000t", "coal_receipt_000t", "coal_stock_000t", "capacity_mw", "n_plants"]),
    "daily_generation_dgr1": ("dgr1_summary_FIXED.csv", "validated", "date + region + category", "date", "date, region, category", ["installed_mw", "monitored_mw", "annual_target_mu", "today_prog_mu", "today_actual_mu", "fy_prog_mu", "fy_actual_mu"]),
    "monthly_fuel_source_rows": ("02_monthly_fuel_MASTER.csv", "raw_parsed", "month + kind + plant + source row", "month", None, ["capacity_mw", "c3", "c4", "c5", "c6", "c7", "c8", "c9_total"]),
    "monthly_generation_summary": ("08_monthly_generation_summary_MASTER.csv", "partial", "month + kind + region", "month", "month, kind, region", ["monitored_mw", "month_target_mu", "month_gen_mu", "month_plf_pct", "fy_target_mu", "fy_gen_mu", "fy_plf_pct"]),
    "daily_coal_plant_source_rows": ("01_daily_coal_MASTER.csv", "unvalidated_v1", "source row", "date", None, ["capacity_mw", "norm_stock_days", "daily_req_000t", "norm_stock_000t", "actual_stock_000t", "stock_days"]),
    "rainfall_station_daily": ("rainfall_MASTER.csv", "derived_era5", "date + station", "date", "date, station", ["rain_mm", "coal_belt"]),
    "rainfall_station_monthly": ("rainfall_monthly_MASTER.csv", "derived_era5", "month + station", "month", "month, station", ["rain_mm", "rainy_days", "coal_belt"]),
    "monsoon_daily": ("monsoon_india_daily.csv", "derived_era5", "date", "date", "date", ["rain_india_mm", "rain_coalbelt_mm"]),
    "monsoon_monthly": ("monsoon_india_monthly.csv", "derived_era5", "month", "month", "month", ["rain_mm", "rain_days_over25mm"]),
    "monsoon_season": ("monsoon_india_season.csv", "derived_era5", "year + monsoon", None, "year, monsoon", ["year", "days", "rain_mean", "rain_total"]),
    "monsoon_coal_daily": ("monsoon_coal_link.csv", "derived_join", "date", "date", "date", ["rain_india_mm", "rain_coalbelt_mm", "gen_hydro_mu", "gen_nuclear_mu", "gen_thermal_mu", "gen_total_mu", "n_plants", "coal_cons_000t", "coal_receipt_000t", "coal_stock_000t", "capacity_mw"]),
    "monsoon_coal_yearly": ("monsoon_vs_coal_yearly.csv", "derived_era5", "year + monsoon", None, "year, monsoon", ["year", "days", "rain_mm_day", "coal_cons_000t_day", "thermal_mu_day", "hydro_mu_day"]),
    "monsoon_generation_yearly": ("monsoon_vs_generation_yearly.csv", "derived_era5", "year + monsoon", None, "year, monsoon", ["year", "days", "rain", "thermal", "hydro"]),
    "daily_generation_raw_rows": ("06_daily_generation_ALL_DGR_MASTER.csv", "raw_parsed", "source row", "date", None, []),
}


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(source: Path, output: Path, *, include_raw_dgr: bool = True) -> dict:
    master = source / "master" if (source / "master").is_dir() else source
    if not master.is_dir():
        raise FileNotFoundError(f"NPP master directory is missing: {master}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(output.name + ".building")
    if staged.exists():
        staged.unlink()
    connection = duckdb.connect(str(staged))
    summary = {"built_at": datetime.now(timezone.utc).isoformat(), "database": str(output), "source": str(master), "tables": {}, "warnings": []}
    try:
        connection.execute("CREATE TABLE source_files (table_name VARCHAR, file_name VARCHAR, source_path VARCHAR, sha256 VARCHAR, bytes BIGINT, reliability VARCHAR, grain VARCHAR, rows BIGINT, first_period VARCHAR, last_period VARCHAR)")
        connection.execute("CREATE TABLE quality_checks (check_name VARCHAR, severity VARCHAR, failed_rows BIGINT, explanation VARCHAR)")
        for table, (filename, reliability, grain, period_col, key, numeric) in SPECS.items():
            if table == "daily_generation_raw_rows" and not include_raw_dgr:
                continue
            path = master / filename
            # A validated incremental NPP refresh may extend the supplied
            # archive without mutating the user's original master directory.
            incremental = {
                "daily_coal_national": REPO / "data/india_coal_master/canonical/npp_daily_coal_national.csv",
                "daily_generation_dgr1": REPO / "data/india_coal_master/canonical/npp_daily_generation_dgr1.csv",
            }.get(table)
            if incremental and incremental.is_file():
                path = incremental
                filename = incremental.name
            if not path.is_file() or not path.stat().st_size:
                if table == "daily_generation_raw_rows":
                    summary["warnings"].append(f"{filename}: raw generic table unavailable")
                    continue
                raise FileNotFoundError(f"Required source is missing or empty: {path}")
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                columns = next(csv.reader(handle))
            typed = []
            for column in columns:
                name = quoted(column)
                if column == "date":
                    typed.append(f"TRY_CAST({name} AS DATE) AS {name}")
                elif column == "year":
                    typed.append(f"TRY_CAST(NULLIF({name}, '') AS INTEGER) AS {name}")
                elif column in numeric:
                    typed.append(f"TRY_CAST(NULLIF({name}, '') AS DOUBLE) AS {name}")
                else:
                    typed.append(name)
            if period_col == "month":
                typed.append("COALESCE(TRY_STRPTIME(month, '%Y-%b'), TRY_STRPTIME(month, '%Y-%m'))::DATE AS period_start")
            period_expr = "CAST(period_start AS VARCHAR)" if period_col == "month" else (f"CAST({quoted(period_col)} AS VARCHAR)" if period_col else "CAST(year AS VARCHAR)" if "year" in columns else "NULL")
            connection.execute(f"CREATE TABLE {quoted(table)} AS SELECT {', '.join(typed)} FROM read_csv(?, header=true, all_varchar=true)", [str(path)])
            rows, first, last = connection.execute(f"SELECT COUNT(*), MIN({period_expr}), MAX({period_expr}) FROM {quoted(table)}").fetchone()
            if not rows:
                raise ValueError(f"Required source has no parsed rows: {filename}")
            if period_col == "date":
                bad = connection.execute(f"SELECT COUNT(*) FROM {quoted(table)} WHERE date IS NULL").fetchone()[0]
                connection.execute("INSERT INTO quality_checks VALUES (?, ?, ?, ?)", [f"{table}.valid_date", "critical", bad, "Invalid source date would break time joins."])
                if bad:
                    raise ValueError(f"{table} has {bad} invalid dates")
            elif period_col == "month":
                bad = connection.execute(f"SELECT COUNT(*) FROM {quoted(table)} WHERE period_start IS NULL").fetchone()[0]
                connection.execute("INSERT INTO quality_checks VALUES (?, ?, ?, ?)", [f"{table}.valid_month", "warning", bad, "Unparseable source reporting months remain available as raw rows."])
                if bad:
                    summary["warnings"].append(f"{table}: {bad} unparseable months")
            if key:
                duplicate = connection.execute(f"SELECT COUNT(*)-COUNT(DISTINCT ({key})) FROM {quoted(table)}").fetchone()[0]
                severity = "critical" if reliability == "validated" else "warning"
                connection.execute("INSERT INTO quality_checks VALUES (?, ?, ?, ?)", [f"{table}.unique_key", severity, duplicate, grain])
                if duplicate and severity == "critical":
                    raise ValueError(f"{table} has {duplicate} duplicate keys")
                if duplicate:
                    summary["warnings"].append(f"{table}: {duplicate} duplicate source keys; rows retained")
            connection.execute("INSERT INTO source_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [table, filename, str(path), file_hash(path), path.stat().st_size, reliability, grain, rows, str(first) if first is not None else None, str(last) if last is not None else None])
            summary["tables"][table] = {"rows": rows, "first": str(first) if first is not None else None, "last": str(last) if last is not None else None, "reliability": reliability}
        cover = REPO / "data/india_coal_master/canonical/npp_station_stock_cover_latest.csv"
        if cover.is_file():
            connection.execute("CREATE TABLE station_stock_cover_latest AS SELECT TRY_CAST(date AS DATE) date, band, TRY_CAST(station_count AS INTEGER) station_count, method FROM read_csv(?, header=true, all_varchar=true)", [str(cover)])
            rows, first, last = connection.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM station_stock_cover_latest").fetchone()
            if rows < 4 or connection.execute("SELECT COUNT(*) FROM station_stock_cover_latest WHERE station_count < 0 OR date IS NULL").fetchone()[0]:
                raise ValueError("Latest station stock-cover bands are invalid")
            connection.execute("INSERT INTO source_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ["station_stock_cover_latest", cover.name, str(cover), file_hash(cover), cover.stat().st_size,
                 "derived_from_official", "date + band", rows, str(first), str(last)])
            summary["tables"]["station_stock_cover_latest"] = {"rows": rows, "first": str(first), "last": str(last), "reliability": "derived_from_official"}
        connection.execute("CREATE TABLE archive_files (relative_path VARCHAR, section VARCHAR, format VARCHAR, bytes BIGINT)")
        archive = source / "full_archive" if (source / "full_archive").is_dir() else master.parent / "full_archive"
        if archive.is_dir():
            entries = []
            for path in archive.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".xls", ".xlsx", ".pdf"}:
                    relative = path.relative_to(archive)
                    entries.append((str(relative).replace("\\", "/"), relative.parts[0], path.suffix.lower().lstrip("."), path.stat().st_size))
            frame = pd.DataFrame(entries, columns=["relative_path", "section", "format", "bytes"])
            connection.register("archive_catalog_source", frame)
            connection.execute("INSERT INTO archive_files SELECT * FROM archive_catalog_source")
            summary["tables"]["archive_files"] = {"rows": len(entries), "first": None, "last": None, "reliability": "source_inventory"}
            connection.unregister("archive_catalog_source")
        else:
            summary["warnings"].append("Full source archive unavailable; only parsed masters were indexed")
        bad_coal = connection.execute("SELECT COUNT(*) FROM daily_coal_national WHERE n_plants < 50 OR coal_cons_000t < 500 OR coal_cons_000t > 4500 OR coal_stock_000t < 0 OR coal_cons_000t IS NULL OR coal_stock_000t IS NULL").fetchone()[0]
        connection.execute("INSERT INTO quality_checks VALUES ('daily_coal_national.plausible', 'critical', ?, 'National NPP coal consumption, stock and plant-count checks.')", [bad_coal])
        if bad_coal:
            raise ValueError(f"National coal daily series has {bad_coal} implausible rows")
        missing_link = connection.execute("SELECT COUNT(*) FROM monsoon_coal_daily m LEFT JOIN daily_coal_national c USING (date) WHERE c.date IS NULL").fetchone()[0]
        connection.execute("INSERT INTO quality_checks VALUES ('monsoon_coal_daily.npp_join', 'critical', ?, 'Every linked monsoon/coal day must exist in national NPP coal observations.')", [missing_link])
        if missing_link:
            raise ValueError(f"Monsoon/coal link contains {missing_link} dates absent from NPP coal")
        connection.execute("CREATE VIEW coal_month_end AS SELECT date_trunc('month', date)::DATE AS month, arg_max(coal_stock_000t, date) AS stock_000t, MAX(date) AS last_report_date, SUM(coal_cons_000t) AS consumption_000t, SUM(coal_receipt_000t) AS receipts_000t, COUNT(*) AS observed_days FROM daily_coal_national GROUP BY 1")
        connection.execute("CREATE VIEW india_daily_generation AS SELECT date, category, today_actual_mu, monitored_mw FROM daily_generation_dgr1 WHERE region = 'ALL INDIA'")
        connection.execute("CREATE VIEW india_monsoon_coal AS SELECT date, rain_india_mm, rain_coalbelt_mm, coal_cons_000t, coal_receipt_000t, coal_stock_000t, gen_hydro_mu, gen_thermal_mu FROM monsoon_coal_daily")
        connection.execute("CHECKPOINT")
        connection.close()
        os.replace(staged, output)
        manifest = output.with_suffix(".manifest.json")
        manifest.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return summary
    except Exception:
        connection.close()
        staged.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="npp_data directory or its master subdirectory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-raw-dgr", action="store_true", help="Exclude the 8.1 million generic DGR source rows")
    args = parser.parse_args()
    result = build(args.source, args.output, include_raw_dgr=not args.skip_raw_dgr)
    print(json.dumps({"database": result["database"], "tables": result["tables"], "warnings": result["warnings"]}, indent=2))
