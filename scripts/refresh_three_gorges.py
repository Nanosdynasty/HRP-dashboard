"""Refresh Three Gorges daily observations from the linked monthly DOCX files.

Only normalized measurements and source URLs are persisted.  Source documents
are held in memory for extraction and are never stored in the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx


MONTHS = {
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
}
SOURCES = {
    "May 2026": "https://journal.probeinternational.org/wp-content/uploads/2026/07/may-2026.docx",
    "June 2026": "https://journal.probeinternational.org/wp-content/uploads/2026/07/june-2026.docx",
    "July 2026": "https://journal.probeinternational.org/wp-content/uploads/2026/08/july-2026.docx",
}
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    return float(match.group()) if match else None


def table_rows(content: bytes, source_month: str, source_url: str | None, source_file: str | None = None) -> list[dict[str, Any]]:
    """Extract the document's five-column daily source table."""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml"))
    rows = []
    current_day = None
    month = MONTHS[source_month.split()[0].casefold()]
    year = int(source_month.split()[1])
    for cells in root.findall(".//w:tr", NS):
        values = ["".join(cell.itertext()).strip() for cell in cells.findall("w:tc", NS)]
        if len(values) < 5 or "water levels" in " ".join(values).casefold():
            continue
        date_text = values[0]
        day_match = re.search(r"\b(0?[1-9]|[12]\d|3[01])\b", date_text)
        if day_match:
            current_day = int(day_match.group(1))
        if current_day is None or current_day > monthrange(year, month)[1]:
            continue
        measures = [number(value) for value in values[1:5]]
        if any(value is None for value in measures):
            continue
        rows.append({
            "date": f"{year}-{month:02d}-{current_day:02d}",
            "upstream_level_m": measures[0], "downstream_level_m": measures[1],
            "inflow_m3s": measures[2], "outflow_m3s": measures[3],
            "source_month": source_month, "source_file": source_file or (source_url or "").rsplit("/", 1)[-1],
            "source_url": source_url, "source_row_sequence": len(rows) + 1,
            "quality_flag": None,
        })
    expected = monthrange(year, month)[1]
    expected_dates = {f"{year}-{month:02d}-{day:02d}" for day in range(1, expected + 1)}
    if len(rows) != expected or {row["date"] for row in rows} != expected_dates:
        raise ValueError(f"{source_month}: expected {expected} distinct daily observations; extracted {len(rows)} rows")
    if any(row[key] < 0 for row in rows for key in ("inflow_m3s", "outflow_m3s")):
        raise ValueError(f"{source_month}: flow cannot be negative")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/three_gorges_reservoir_watch.json"))
    parser.add_argument("--source-docx", type=Path, help="Import a user-supplied monthly DOCX without fetching remote sources")
    parser.add_argument("--source-month", help="Month and year of the local document, e.g. August 2026")
    args = parser.parse_args()
    if bool(args.source_docx) != bool(args.source_month):
        parser.error("--source-docx and --source-month must be supplied together")
    payload = json.loads(args.data.read_text(encoding="utf-8"))
    refreshed: list[dict[str, Any]] = []
    sources = SOURCES
    if args.source_docx:
        sources = {args.source_month: None}
        content = args.source_docx.read_bytes()
        refreshed = table_rows(content, args.source_month, None, args.source_docx.name)
        source_hash = hashlib.sha256(content).hexdigest()
        for row in refreshed:
            row["source_origin"] = "user_supplied_document"
            row["source_document_sha256"] = source_hash
    else:
        with httpx.Client(headers={"User-Agent": "HRP-dashboard/4.2 Three-Gorges refresh"}, follow_redirects=True, timeout=40) as client:
            for source_month, source_url in sources.items():
                response = client.get(source_url)
                response.raise_for_status()
                refreshed.extend(table_rows(response.content, source_month, source_url))

    replaced_periods = {row["date"][:7] for row in refreshed}
    observations = [row for row in payload.get("observations", []) if str(row.get("date") or "")[:7] not in replaced_periods]
    observations.extend(refreshed)
    observations.sort(key=lambda row: (row["date"], row.get("source_row_sequence") or 0))
    coverage = [item for item in payload.get("monthly_coverage", []) if item.get("source_month") not in sources]
    for source_month, source_url in sources.items():
        month = MONTHS[source_month.split()[0].casefold()]
        year = int(source_month.split()[1])
        count = sum(row["source_month"] == source_month for row in refreshed)
        item = {
            "source_month": source_month, "rows_extracted": count,
            "calendar_days": monthrange(year, month)[1], "missing_days": 0,
            "duplicate_days": 0, "status": "Imported and validated" if args.source_docx else "Downloaded and extracted",
            "source_note": "DOCX table fetched from the linked Probe International source and normalized without storing the source file.",
            "direct_file_url": source_url,
        }
        if args.source_docx:
            item.update({
                "source_file": args.source_docx.name,
                "source_document_sha256": source_hash,
                "source_origin": "user_supplied_document",
                "source_note": "User-supplied monthly DOCX; document attributes figures to Changjiang Hydrology (http://www.cjh.com.cn/). Downstream levels are at Yichang City, about 40 km below the dam, not at the dam site. Measurements transcribed without interpolation.",
            })
        coverage.append(item)
    coverage.sort(key=lambda item: datetime.strptime(item["source_month"], "%B %Y"))
    payload["observations"] = observations
    payload["monthly_coverage"] = coverage
    payload["coverage_end"] = observations[-1]["date"]
    payload["known_gaps"] = ["May 2023 has no download link on the source page."]
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    if any(item.get("source_origin") == "user_supplied_document" for item in coverage):
        payload["source_provenance"] = "Reviewed extraction of linked monthly Probe International DOC/DOCX source files and user-supplied monthly DOCX reports; see monthly coverage for provenance"
    temporary = args.data.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(args.data)
    print(f"Updated {args.data}: {len(refreshed)} new rows through {payload['coverage_end']}")


if __name__ == "__main__":
    main()
