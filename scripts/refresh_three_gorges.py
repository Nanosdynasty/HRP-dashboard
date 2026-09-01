"""Refresh Three Gorges daily observations from the linked monthly DOCX files.

Only normalized measurements and source URLs are persisted.  Source documents
are held in memory for extraction and are never stored in the repository.
"""
from __future__ import annotations

import argparse
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


def table_rows(content: bytes, source_month: str, source_url: str) -> list[dict[str, Any]]:
    """Extract the document's five-column daily source table."""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml"))
    rows = []
    current_day = None
    month = MONTHS[source_month.split()[0].casefold()]
    for cells in root.findall(".//w:tr", NS):
        values = ["".join(cell.itertext()).strip() for cell in cells.findall("w:tc", NS)]
        if len(values) < 5 or "water levels" in " ".join(values).casefold():
            continue
        date_text = values[0]
        day_match = re.search(r"\b(0?[1-9]|[12]\d|3[01])\b", date_text)
        if day_match:
            current_day = int(day_match.group(1))
        if current_day is None or current_day > monthrange(2026, month)[1]:
            continue
        measures = [number(value) for value in values[1:5]]
        if any(value is None for value in measures):
            continue
        rows.append({
            "date": f"2026-{month:02d}-{current_day:02d}",
            "upstream_level_m": measures[0], "downstream_level_m": measures[1],
            "inflow_m3s": measures[2], "outflow_m3s": measures[3],
            "source_month": source_month, "source_file": source_url.rsplit("/", 1)[-1],
            "source_url": source_url, "source_row_sequence": len(rows) + 1,
            "quality_flag": None,
        })
    expected = monthrange(2026, month)[1]
    if len(rows) != expected:
        raise ValueError(f"{source_month}: extracted {len(rows)} rows, expected {expected}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/three_gorges_reservoir_watch.json"))
    args = parser.parse_args()
    payload = json.loads(args.data.read_text(encoding="utf-8"))
    refreshed: list[dict[str, Any]] = []
    with httpx.Client(headers={"User-Agent": "HRP-dashboard/4.2 Three-Gorges refresh"}, follow_redirects=True, timeout=40) as client:
        for source_month, source_url in SOURCES.items():
            response = client.get(source_url)
            response.raise_for_status()
            refreshed.extend(table_rows(response.content, source_month, source_url))

    start = "2026-05-01"
    observations = [row for row in payload.get("observations", []) if str(row.get("date") or "") < start]
    observations.extend(refreshed)
    observations.sort(key=lambda row: (row["date"], row.get("source_row_sequence") or 0))
    coverage = [item for item in payload.get("monthly_coverage", []) if item.get("source_month") not in SOURCES]
    for source_month, source_url in SOURCES.items():
        month = MONTHS[source_month.split()[0].casefold()]
        count = sum(row["source_month"] == source_month for row in refreshed)
        coverage.append({
            "source_month": source_month, "rows_extracted": count,
            "calendar_days": monthrange(2026, month)[1], "missing_days": None,
            "duplicate_days": None, "status": "Downloaded and extracted",
            "source_note": "DOCX table fetched from the linked Probe International source and normalized without storing the source file.",
            "direct_file_url": source_url,
        })
    payload["observations"] = observations
    payload["monthly_coverage"] = coverage
    payload["coverage_end"] = observations[-1]["date"]
    payload["known_gaps"] = ["May 2023 has no download link on the source page."]
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["source_provenance"] = "Reviewed extraction of linked monthly Probe International DOC/DOCX source files"
    args.data.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Updated {args.data}: {len(refreshed)} new rows through {payload['coverage_end']}")


if __name__ == "__main__":
    main()
