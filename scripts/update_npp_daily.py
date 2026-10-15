"""Append newly published NPP daily fuel and DGR1 reports to reviewed Coal CSVs.

Only dates advertised by the NPP report selectors are requested. Original files
are read in memory; a failed validation leaves the previous snapshot untouched.
"""
from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "india_coal_master" / "canonical"
FUEL = DATA / "npp_daily_coal_national.csv"
DGR = DATA / "npp_daily_generation_dgr1.csv"
COVER = DATA / "npp_station_stock_cover_latest.csv"
REPORTS = ROOT / "data" / "india_coal_master" / "ui" / "npp_daily_refresh.json"
HOST = "https://npp.gov.in"


def numeric(value):
    try:
        parsed = float(str(value).replace(",", ""))
        return parsed if pd.notna(parsed) else None
    except (TypeError, ValueError):
        return None


def advertised(client: httpx.Client, page: str) -> list[str]:
    response = client.get(HOST + "/" + page)
    response.raise_for_status()
    return sorted(set(re.findall(r"20\d{2}-\d{2}-\d{2}", response.text)))


def fuel_row(content: bytes, iso: str) -> dict:
    sheet = pd.read_excel(io.BytesIO(content), header=None)
    if sheet.shape[1] < 33 or "Consumption of the day" not in str(sheet.iloc[3, 32]):
        raise ValueError(f"Fuel schema changed on {iso}")
    serial = pd.to_numeric(sheet[0], errors="coerce")
    rows = sheet.loc[serial.between(1, 500)].copy()
    # Numeric station labels are summary blocks, including one misleading row
    # with 17 thousand tonnes of consumption in the 2026-09-27 report.
    station = rows[6].astype(str).str.strip()
    rows = rows.loc[station.ne("") & station.ne("nan") & ~station.str.fullmatch(r"\d+(?:\.\d+)?") & ~station.str.contains("total", case=False)]
    values = rows[[8, 24, 31, 32]].apply(pd.to_numeric, errors="coerce")
    values = values.loc[values[32].between(0, 150) & values[8].gt(0)]
    result = {"date": iso, "n_plants": len(values),
              "coal_cons_000t": round(values[32].sum(), 3),
              "coal_receipt_000t": round(values[31].sum(), 3),
              "coal_stock_000t": round(values[24].sum(), 3),
              "capacity_mw": round(values[8].sum(), 3)}
    if not (100 <= result["n_plants"] <= 300 and 500 <= result["coal_cons_000t"] <= 4500
            and 100000 <= result["capacity_mw"] <= 300000 and result["coal_stock_000t"] >= 0):
        raise ValueError(f"Implausible fuel totals on {iso}: {result}")
    return result


def fuel_cover(content: bytes, iso: str) -> list[dict]:
    """Derive days of cover from each station's reported stock and 85% PLF need."""
    sheet = pd.read_excel(io.BytesIO(content), header=None)
    serial = pd.to_numeric(sheet[0], errors="coerce")
    rows = sheet.loc[serial.between(1, 500)].copy()
    station = rows[6].astype(str).str.strip()
    rows = rows.loc[station.ne("") & station.ne("nan") & ~station.str.fullmatch(r"\d+(?:\.\d+)?") & ~station.str.contains("total", case=False)]
    stock = pd.to_numeric(rows[24], errors="coerce")
    requirement = pd.to_numeric(rows[14], errors="coerce")
    days = stock / requirement.where(requirement.gt(0))
    bands = [("Under 3 days", days.lt(3)), ("3–7 days", days.ge(3) & days.lt(7)),
             ("7–14 days", days.ge(7) & days.lt(14)), ("14+ days", days.ge(14)),
             ("Unavailable", days.isna())]
    counts = [{"date": iso, "band": label, "station_count": int(mask.sum()),
               "method": "Reported stock divided by daily requirement at 85% PLF"} for label, mask in bands]
    if sum(item["station_count"] for item in counts) != len(rows) or len(rows) < 100:
        raise ValueError("Station stock-cover distribution did not reconcile")
    return counts


def dgr_xls_rows(content: bytes, iso: str) -> list[dict]:
    sheet = pd.read_excel(io.BytesIO(content), header=None)
    region = None
    result = []
    categories = {"THERMAL", "HYDRO", "NUCLEAR", "Total", "Bhutan IMP.", "R.E.S", "R.E.S."}
    for _, row in sheet.iterrows():
        label = str(row.iloc[1]).strip()
        if label.upper() == "ALL INDIA":
            region = "ALL INDIA"
            continue
        if region != "ALL INDIA" or label not in categories:
            continue
        numbers = [numeric(item) for item in row.iloc[2:]]
        first = next((i for i, item in enumerate(numbers) if item is not None), None)
        if first is None:
            continue
        numbers = numbers[first:]
        # Capacity-less Bhutan imports start with annual target; RES has no
        # actual generation. Only categories with an actual are included.
        if label in {"Bhutan IMP.", "R.E.S", "R.E.S."} or len(numbers) < 7:
            continue
        result.append({"date": iso, "region": region, "category": label,
                       "installed_mw": numbers[0], "monitored_mw": numbers[1],
                       "annual_target_mu": numbers[2], "today_prog_mu": numbers[3],
                       "today_actual_mu": numbers[4], "fy_prog_mu": numbers[5],
                       "fy_actual_mu": numbers[6], "source_file": f"dgr1-{iso}.xls"})
    thermal = next((row for row in result if row["category"] == "THERMAL"), None)
    if not thermal or not 1500 <= thermal["today_actual_mu"] <= 6000:
        raise ValueError(f"DGR thermal total missing or implausible on {iso}")
    return result


def dgr_pdf_rows(content: bytes, iso: str) -> list[dict]:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    # The PDF's ALL INDIA row is laid out in columns that extract in a
    # different order. The five region rows stay on one line and reconcile.
    section = text.split("Northern", 1)[-1].split("ALL INDIA", 1)[0]
    thermal = []
    for line in section.splitlines():
        if not line.startswith("THERMAL "):
            continue
        numbers = [float(item.replace(",", "")) for item in re.findall(r"-?\d[\d,]*\.\d+", line)]
        if len(numbers) >= 5:
            thermal.append(numbers[4])
    if len(thermal) != 5 or not 1500 <= sum(thermal) <= 6000:
        raise ValueError(f"Could not reconcile five DGR regions on {iso}")
    return [{"date": iso, "region": "ALL INDIA", "category": "THERMAL",
             "installed_mw": None, "monitored_mw": None, "annual_target_mu": None,
             "today_prog_mu": None, "today_actual_mu": round(sum(thermal), 2),
             "fy_prog_mu": None, "fy_actual_mu": None, "source_file": f"dgr1-{iso}.pdf"}]


def refresh() -> dict:
    fuel_old = pd.read_csv(FUEL)
    dgr_old = pd.read_csv(DGR)
    fuel_dates = set(fuel_old.date.astype(str))
    dgr_dates = set(dgr_old.loc[(dgr_old.region == "ALL INDIA") & (dgr_old.category == "THERMAL"), "date"].astype(str))
    new_fuel, new_dgr, failures, evidence = [], [], [], []
    latest_cover = None
    with httpx.Client(timeout=35, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
        try:
            fuel_releases = advertised(client, "dailyCoalReports")
        except Exception as exc:
            fuel_releases = []
            failures.append({"dataset": "fuel", "reason": f"Report index unavailable: {str(exc)[:120]}"})
        for iso in fuel_releases:
            if iso <= max(fuel_dates) or iso in fuel_dates or iso > date.today().isoformat():
                continue
            folder = datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
            stem = f"/public-reports/cea/daily/fuel/{folder}/dailyCoal1-{iso}"
            try:
                for extension in ("xls", "xlsx"):
                    response = client.get(HOST + stem + "." + extension)
                    if response.status_code == 200 and len(response.content) > 2000:
                        new_fuel.append(fuel_row(response.content, iso))
                        latest_cover = fuel_cover(response.content, iso)
                        evidence.append({"date": iso, "dataset": "fuel", "url": str(response.url)})
                        break
                else:
                    raise ValueError("No spreadsheet published")
            except Exception as exc:
                failures.append({"date": iso, "dataset": "fuel", "reason": str(exc)[:160]})
        try:
            dgr_releases = advertised(client, "dgrReports")
        except Exception as exc:
            dgr_releases = []
            failures.append({"dataset": "generation", "reason": f"Report index unavailable: {str(exc)[:120]}"})
        for iso in dgr_releases:
            if iso <= max(dgr_dates) or iso in dgr_dates or iso > date.today().isoformat():
                continue
            folder = datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
            stem = f"/public-reports/cea/daily/dgr/{folder}/dgr1-{iso}"
            try:
                response = client.get(HOST + stem + ".xls")
                if response.status_code == 200 and len(response.content) > 2000:
                    new_dgr.extend(dgr_xls_rows(response.content, iso))
                    evidence.append({"date": iso, "dataset": "generation", "url": str(response.url)})
                else:
                    response = client.get(HOST + stem + ".pdf")
                    if response.status_code != 200 or len(response.content) < 2000:
                        raise ValueError("No parseable XLS or PDF published")
                    new_dgr.extend(dgr_pdf_rows(response.content, iso))
                    evidence.append({"date": iso, "dataset": "generation", "url": str(response.url)})
            except Exception as exc:
                failures.append({"date": iso, "dataset": "generation", "reason": str(exc)[:160]})
        if latest_cover is None and not COVER.exists():
            iso = max(fuel_dates)
            folder = datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
            response = client.get(HOST + f"/public-reports/cea/daily/fuel/{folder}/dailyCoal1-{iso}.xls")
            response.raise_for_status()
            latest_cover = fuel_cover(response.content, iso)
    report = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "fuel_added": len(new_fuel),
              "generation_rows_added": len(new_dgr), "failures": failures, "sources": evidence}
    # Only publish each complete series after checking unique keys and ordering.
    if new_fuel:
        frame = pd.concat([fuel_old, pd.DataFrame(new_fuel)], ignore_index=True).sort_values("date")
        if frame.date.duplicated().any():
            raise ValueError("Duplicate fuel dates")
        target = FUEL.with_suffix(".csv.building")
        frame.to_csv(target, index=False)
        target.replace(FUEL)
    if new_dgr:
        frame = pd.concat([dgr_old, pd.DataFrame(new_dgr)], ignore_index=True).sort_values(["date", "region", "category"])
        if frame.duplicated(["date", "region", "category"]).any():
            raise ValueError("Duplicate DGR keys")
        target = DGR.with_suffix(".csv.building")
        frame.to_csv(target, index=False)
        target.replace(DGR)
    if latest_cover:
        target = COVER.with_suffix(".csv.building")
        pd.DataFrame(latest_cover).to_csv(target, index=False)
        target.replace(COVER)
    # Preserve lineage for prior incremental runs, including a no-op refresh.
    provenance = {}
    for row in pd.read_csv(FUEL).itertuples():
        if str(row.date) >= "2026-09-28":
            folder = datetime.strptime(row.date, "%Y-%m-%d").strftime("%d-%m-%Y")
            provenance[("fuel", row.date)] = {"date": row.date, "dataset": "fuel",
                "url": HOST + f"/public-reports/cea/daily/fuel/{folder}/dailyCoal1-{row.date}.xls"}
    for row in pd.read_csv(DGR).itertuples():
        if str(row.date) >= "2026-09-27" and row.region == "ALL INDIA" and row.category == "THERMAL":
            folder = datetime.strptime(row.date, "%Y-%m-%d").strftime("%d-%m-%Y")
            provenance[("generation", row.date)] = {"date": row.date, "dataset": "generation",
                "url": HOST + f"/public-reports/cea/daily/dgr/{folder}/{row.source_file}"}
    report["sources"] = list(provenance.values())
    REPORTS.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(refresh(), indent=2))
