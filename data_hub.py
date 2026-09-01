"""Provider-neutral upload, lineage, comparison and relationship workspace."""
from __future__ import annotations

import io
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - requirements include pypdf
    PdfReader = None


PROVIDERS = {
    "gtt": {"label": "GTT", "accent": "#0b5b9c"},
    "kpler": {"label": "Kpler", "accent": "#ef3d48"},
    "oceanbolt": {"label": "Oceanbolt", "accent": "#0e7182"},
    "axs_marine": {"label": "AXS Marine", "accent": "#dc8b1d"},
    "custom": {"label": "Custom data", "accent": "#596579"},
    "hrp_app": {"label": "HRP app data", "accent": "#0b3f75", "internal": True},
}
FREQUENCIES = {"daily", "weekly", "monthly", "quarterly", "yearly", "ad_hoc"}
SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".json", ".pdf"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
_api_secrets: Dict[str, str] = {}


class ApiConnectionRequest(BaseModel):
    provider: str
    endpoint_url: str = ""
    api_key: str
    connection_label: str = "Default connection"


class RelationshipRequest(BaseModel):
    dataset_ids: List[str]
    question: str = ""


class RelationshipApproval(BaseModel):
    approved: bool = True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return str(value) if not isinstance(value, (str, int, float, bool)) else value


def _json_rows(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _canonical_field(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    aliases = {
        "nation": "country", "country_name": "country", "origin_country": "origin",
        "destination_country": "destination", "discharge_port": "destination_port",
        "load_port": "origin_port", "loading_port": "origin_port",
        "month_year": "period", "reporting_period": "period", "date_time": "date",
        "vessel_imo": "imo", "imo_number": "imo", "vessel_mmsi": "mmsi",
        "commodity_name": "commodity", "product": "commodity",
    }
    return aliases.get(text, text)


class DataHubStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database_path)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def session(self):
        db = self.connect()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def _init_db(self) -> None:
        with self.session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    dataset_name TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    expected_frequency TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    column_count INTEGER NOT NULL,
                    columns_json TEXT NOT NULL,
                    numeric_columns_json TEXT NOT NULL,
                    date_columns_json TEXT NOT NULL,
                    data_start TEXT,
                    data_end TEXT,
                    latest_period TEXT,
                    next_due_at TEXT,
                    quality_status TEXT NOT NULL,
                    quality_issues_json TEXT NOT NULL,
                    duplicate_rows INTEGER NOT NULL DEFAULT 0,
                    null_rate REAL NOT NULL DEFAULT 0,
                    file_blob BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dataset_rows (
                    dataset_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    row_json TEXT NOT NULL,
                    PRIMARY KEY (dataset_id, row_index),
                    FOREIGN KEY (dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_dataset_rows_dataset
                    ON dataset_rows(dataset_id, row_index);
                CREATE TABLE IF NOT EXISTS api_connections (
                    provider TEXT PRIMARY KEY,
                    connection_label TEXT NOT NULL,
                    endpoint_url TEXT,
                    key_mask TEXT NOT NULL,
                    connected_at TEXT NOT NULL,
                    secret_storage TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    dataset_ids_json TEXT NOT NULL,
                    question TEXT,
                    proposal_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approved_at TEXT
                );
                """
            )

    @staticmethod
    def parse_file(filename: str, content: bytes) -> pd.DataFrame:
        extension = Path(filename).suffix.lower()
        source = io.BytesIO(content)
        if extension in {".xlsx", ".xls"}:
            sheets = pd.read_excel(source, sheet_name=None)
            frames = []
            for sheet_name, frame in sheets.items():
                if frame.empty:
                    continue
                copy = frame.copy()
                copy.insert(0, "_sheet", str(sheet_name))
                frames.append(copy)
            return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        if extension == ".csv":
            return pd.read_csv(source, sep=None, engine="python")
        if extension == ".json":
            payload = json.loads(content.decode("utf-8-sig"))
            if isinstance(payload, dict):
                for key in ("data", "records", "rows", "results"):
                    if isinstance(payload.get(key), list):
                        payload = payload[key]
                        break
            return pd.json_normalize(payload)
        if extension == ".pdf":
            if PdfReader is None:
                raise ValueError("PDF extraction is unavailable")
            reader = PdfReader(source)
            return pd.DataFrame([
                {"page_number": index + 1, "text": page.extract_text() or ""}
                for index, page in enumerate(reader.pages)
            ])
        raise ValueError("Unsupported file type")

    @staticmethod
    def _profile(frame: pd.DataFrame, frequency: str) -> Dict[str, Any]:
        frame = frame.copy()
        frame.columns = [str(column).strip() or f"column_{index + 1}" for index, column in enumerate(frame.columns)]
        numeric = [
            column for column in frame.columns
            if pd.to_numeric(frame[column], errors="coerce").notna().mean() >= 0.6
        ]
        date_columns: List[str] = []
        parsed_dates: Dict[str, pd.Series] = {}
        for column in frame.columns:
            hint = any(token in column.lower() for token in ("date", "month", "year", "period", "week", "time"))
            if not hint:
                continue
            parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
            if parsed.notna().mean() >= 0.4:
                date_columns.append(column)
                parsed_dates[column] = parsed
        selected_dates = parsed_dates.get(date_columns[0]) if date_columns else None
        data_start = selected_dates.min().isoformat() if selected_dates is not None and selected_dates.notna().any() else None
        data_end = selected_dates.max().isoformat() if selected_dates is not None and selected_dates.notna().any() else None
        duplicate_rows = int(frame.astype(str).duplicated().sum())
        null_rate = float(frame.isna().mean().mean()) if len(frame.columns) else 0.0
        issues = []
        if not date_columns:
            issues.append("No reliable date or reporting-period field was detected.")
        if not numeric:
            issues.append("No mostly numeric measure field was detected.")
        if duplicate_rows:
            issues.append(f"{duplicate_rows:,} exact duplicate rows need review.")
        if null_rate > 0.35:
            issues.append(f"Average field missingness is {null_rate:.0%}.")
        latest_dt = (
            datetime.fromisoformat(data_end.replace("Z", "+00:00"))
            if data_end else None
        )
        increments = {
            "daily": timedelta(days=2), "weekly": timedelta(days=9),
            "monthly": timedelta(days=40), "quarterly": timedelta(days=110),
            "yearly": timedelta(days=400), "ad_hoc": timedelta(days=3650),
        }
        next_due = latest_dt + increments[frequency] if latest_dt else None
        quality_status = "review_needed" if issues else "profiled"
        return {
            "frame": frame, "columns": list(frame.columns), "numeric_columns": numeric,
            "date_columns": date_columns, "data_start": data_start, "data_end": data_end,
            "latest_period": data_end,
            "next_due_at": next_due.isoformat() if next_due else None,
            "duplicate_rows": duplicate_rows, "null_rate": null_rate,
            "quality_status": quality_status, "quality_issues": issues,
        }

    def _store_dataset(
        self, provider: str, dataset_name: str, frequency: str,
        filename: str, content: bytes, dataset_id: str | None = None,
        uploaded_at: str | None = None,
    ) -> Dict[str, Any]:
        frame = self.parse_file(filename, content)
        if frame.empty:
            raise ValueError("The uploaded file has no readable rows")
        profile = self._profile(frame, frequency)
        frame = profile.pop("frame")
        dataset_id = dataset_id or uuid.uuid4().hex[:16]
        uploaded_at = uploaded_at or _utcnow().isoformat()
        rows = _json_rows(frame)
        with self.session() as db:
            db.execute("DELETE FROM dataset_rows WHERE dataset_id=?", (dataset_id,))
            db.execute(
                """INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    dataset_id, provider, dataset_name.strip() or Path(filename).stem,
                    filename, Path(filename).suffix.lower().lstrip("."), uploaded_at,
                    frequency, len(frame), len(frame.columns),
                    json.dumps(profile["columns"]), json.dumps(profile["numeric_columns"]),
                    json.dumps(profile["date_columns"]), profile["data_start"],
                    profile["data_end"], profile["latest_period"], profile["next_due_at"],
                    profile["quality_status"], json.dumps(profile["quality_issues"]),
                    profile["duplicate_rows"], profile["null_rate"], sqlite3.Binary(content),
                ),
            )
            db.executemany(
                "INSERT INTO dataset_rows(dataset_id,row_index,row_json) VALUES (?,?,?)",
                ((dataset_id, index, json.dumps(row, ensure_ascii=False)) for index, row in enumerate(rows)),
            )
        return self.dataset(dataset_id)

    def add_dataset(
        self, provider: str, dataset_name: str, frequency: str,
        filename: str, content: bytes,
    ) -> Dict[str, Any]:
        return self._store_dataset(provider, dataset_name, frequency, filename, content)

    def sync_app_datasets(self, base_dir: Path) -> List[Dict[str, Any]]:
        canonical_dir = base_dir / "data" / "india_coal_master" / "canonical"
        files = [
            canonical_dir / "coal_imports_by_origin.csv",
            canonical_dir / "coal_imports_by_port.csv",
            canonical_dir / "coal_imports_monthly.csv",
            canonical_dir / "coal_india_annual.csv",
            canonical_dir / "coal_monthly_official.csv",
            canonical_dir / "coal_offtake_by_sector.csv",
            canonical_dir / "coal_production_monthly.csv",
            canonical_dir / "india_power_generation_monthly.csv",
            canonical_dir / "india_power_mix_june.csv",
            canonical_dir / "india_power_mix_monthly.csv",
            canonical_dir / "steel_plant_coking_coal.csv",
        ]
        synced = []
        for path in files:
            if not path.exists():
                continue
            relative = path.relative_to(base_dir).as_posix()
            dataset_id = "hrp_" + hashlib.sha1(relative.encode("utf-8")).hexdigest()[:12]
            frequency = "yearly" if "annual" in path.stem else "monthly"
            dataset_name = path.stem.replace("_", " ").title()
            try:
                synced.append(self._store_dataset(
                    "hrp_app", dataset_name, frequency, path.name,
                    path.read_bytes(), dataset_id=dataset_id,
                    uploaded_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                ))
            except (ValueError, json.JSONDecodeError, pd.errors.ParserError):
                continue
        return synced

    @staticmethod
    def _freshness(row: Dict[str, Any]) -> Dict[str, str]:
        next_due = row.get("next_due_at")
        if not next_due:
            return {"status": "unknown", "label": "Freshness unknown"}
        due = datetime.fromisoformat(str(next_due).replace("Z", "+00:00"))
        delta = due - _utcnow()
        if delta.total_seconds() < 0:
            return {"status": "overdue", "label": f"Update overdue by {abs(delta.days):,} days"}
        if delta <= timedelta(days=7):
            return {"status": "due_soon", "label": f"Update due in {max(delta.days, 0)} days"}
        return {"status": "current", "label": f"Current · next update {due:%d %b %Y}"}

    def _row_to_dataset(self, row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item.pop("file_blob", None)
        for key in ("columns_json", "numeric_columns_json", "date_columns_json", "quality_issues_json"):
            item[key.removesuffix("_json")] = json.loads(item.pop(key) or "[]")
        item["freshness"] = self._freshness(item)
        return item

    def dataset(self, dataset_id: str) -> Dict[str, Any]:
        with self.session() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        if not row:
            raise KeyError(dataset_id)
        return self._row_to_dataset(row)

    def datasets(self) -> List[Dict[str, Any]]:
        with self.session() as db:
            rows = db.execute("SELECT * FROM datasets ORDER BY uploaded_at DESC").fetchall()
        return [self._row_to_dataset(row) for row in rows]

    def rows(self, dataset_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        self.dataset(dataset_id)
        with self.session() as db:
            rows = db.execute(
                "SELECT row_json FROM dataset_rows WHERE dataset_id=? ORDER BY row_index LIMIT ?",
                (dataset_id, limit),
            ).fetchall()
        return [json.loads(row["row_json"]) for row in rows]

    def all_rows(self, dataset_id: str) -> List[Dict[str, Any]]:
        self.dataset(dataset_id)
        with self.session() as db:
            rows = db.execute(
                "SELECT row_json FROM dataset_rows WHERE dataset_id=? ORDER BY row_index",
                (dataset_id,),
            ).fetchall()
        return [json.loads(row["row_json"]) for row in rows]

    def analytics(self, dataset_id: str, reporter: str | None = None, partner: str | None = None,
                  hs_code: str | None = None, year_from: int | None = None,
                  year_to: int | None = None) -> Dict[str, Any]:
        """Return compact, source-backed aggregates for canonical trade datasets."""
        dataset = self.dataset(dataset_id)
        frame = pd.DataFrame(self.all_rows(dataset_id))
        if frame.empty:
            raise ValueError("Dataset has no analytical rows")

        def first_field(*names: str) -> str | None:
            canonical = {_canonical_field(column): column for column in frame.columns}
            for name in names:
                if name in frame.columns:
                    return name
                if _canonical_field(name) in canonical:
                    return canonical[_canonical_field(name)]
            return None

        period_field = first_field("reporting_period", "period", "date", "month")
        quantity_field = first_field("quantity_mt", "volume_mt", "net_weight_mt", "metric_tonnes")
        reporter_field = first_field("reporter_country", "reporter", "origin", "country")
        partner_field = first_field("partner_country", "partner", "destination")
        commodity_field = first_field("commodity", "commodity_name", "hs_description")
        currency_field = first_field("currency")
        value_field = first_field("trade_value_original", "value_usd", "trade_value", "value")
        reporter_iso_field = first_field("reporter_iso2", "reporter_iso")
        partner_iso_field = first_field("partner_iso2", "partner_iso")
        hs_field = first_field("hs_code", "hs", "commodity_code")

        # Apply explicit explorer filters before calculating any KPI or chart aggregate.
        if reporter and reporter_field:
            frame = frame[frame[reporter_field].astype(str).str.casefold() == str(reporter).casefold()]
        if partner and partner_field:
            frame = frame[frame[partner_field].astype(str).str.casefold() == str(partner).casefold()]
        if hs_code and hs_field:
            frame = frame[frame[hs_field].astype(str).str.replace(".0", "", regex=False).str.casefold() == str(hs_code).casefold()]
        if year_from is not None and period_field:
            parsed = pd.to_datetime(frame[period_field], errors="coerce")
            frame = frame[parsed.dt.year >= int(year_from)]
        if year_to is not None and period_field:
            parsed = pd.to_datetime(frame[period_field], errors="coerce")
            frame = frame[parsed.dt.year <= int(year_to)]
        if frame.empty:
            raise ValueError("No records match the selected country, HS code and period filters")

        if period_field:
            frame["_period"] = pd.to_datetime(frame[period_field], errors="coerce")
        if quantity_field:
            frame["_quantity"] = pd.to_numeric(frame[quantity_field], errors="coerce")
        if value_field:
            frame["_value"] = pd.to_numeric(frame[value_field], errors="coerce")

        def ranked(field: str | None, measure: str, limit: int = 8) -> List[Dict[str, Any]]:
            if not field or measure not in frame:
                return []
            work = frame[[field, measure]].dropna()
            work = work[work[field].astype(str).str.strip().ne("")]
            if work.empty:
                return []
            result = work.groupby(field, dropna=False)[measure].sum().sort_values(ascending=False).head(limit)
            return [{"label": str(label), "value": float(value)} for label, value in result.items()]

        trend: List[Dict[str, Any]] = []
        if "_period" in frame and "_quantity" in frame:
            aggregations = {"quantity_mt": ("_quantity", "sum"), "records": ("_quantity", "size")}
            if "_value" in frame:
                aggregations["trade_value"] = ("_value", "sum")
            grouped = frame.dropna(subset=["_period"]).groupby("_period", as_index=False).agg(**aggregations).sort_values("_period")
            trend = [
                {"period": row["_period"].strftime("%Y-%m-%d"), "quantity_mt": float(row["quantity_mt"]), "trade_value": (float(row["trade_value"]) if "trade_value" in grouped.columns and pd.notna(row["trade_value"]) else None), "records": int(row["records"])}
                for _, row in grouped.iterrows()
            ]

        currencies = []
        if currency_field and "_value" in frame:
            for currency, value in frame.groupby(currency_field)["_value"].sum().sort_values(ascending=False).items():
                currencies.append({"currency": str(currency), "value": float(value)})

        map_flows: List[Dict[str, Any]] = []
        if reporter_field and partner_field and "_quantity" in frame:
            flow_fields = [reporter_field, partner_field, "_quantity"]
            for optional in (reporter_iso_field, partner_iso_field):
                if optional and optional not in flow_fields:
                    flow_fields.append(optional)
            flow_frame = frame[flow_fields].dropna(subset=[reporter_field, partner_field])
            if not flow_frame.empty:
                group_cols = [reporter_field, partner_field]
                grouped = flow_frame.groupby(group_cols, as_index=False)['_quantity'].sum().sort_values('_quantity', ascending=False).head(120)
                iso_lookup = {}
                if reporter_iso_field or partner_iso_field:
                    for _, source_row in flow_frame.iterrows():
                        key = (str(source_row[reporter_field]), str(source_row[partner_field]))
                        iso_lookup.setdefault(key, (str(source_row.get(reporter_iso_field, "")) if reporter_iso_field else "", str(source_row.get(partner_iso_field, "")) if partner_iso_field else ""))
                for _, flow in grouped.iterrows():
                    reporter_name = str(flow[reporter_field]); partner_name = str(flow[partner_field])
                    reporter_iso, partner_iso = iso_lookup.get((reporter_name, partner_name), ("", ""))
                    map_flows.append({"exporter": reporter_name, "importer": partner_name,
                                      "exporter_iso2": reporter_iso, "importer_iso2": partner_iso,
                                      "quantity_mt": float(flow["_quantity"])})

        quantity_total = float(frame["_quantity"].sum()) if "_quantity" in frame else None
        currency_count = int(frame[currency_field].nunique(dropna=True)) if currency_field else 0
        single_currency_value = None
        single_currency = None
        if currency_count == 1 and "_value" in frame:
            single_currency = str(frame[currency_field].dropna().iloc[0])
            single_currency_value = float(frame["_value"].sum())

        return {
            "dataset": dataset,
            "metrics": {
                "records": int(len(frame)),
                "quantity_mt": quantity_total,
                "trade_value": single_currency_value,
                "trade_value_currency": single_currency,
                "currency_count": currency_count,
                "reporter_count": int(frame[reporter_field].nunique(dropna=True)) if reporter_field else None,
                "partner_count": int(frame[partner_field].nunique(dropna=True)) if partner_field else None,
                "commodity_count": int(frame[commodity_field].nunique(dropna=True)) if commodity_field else None,
            },
            "trend": trend,
            "top_reporters": ranked(reporter_field, "_quantity"),
            "top_partners": ranked(partner_field, "_quantity"),
            "top_commodities": ranked(commodity_field, "_quantity"),
            "currency_totals": currencies[:12],
            "map_flows": map_flows,
            "dimensions": {
                "reporters": sorted(frame[reporter_field].dropna().astype(str).unique().tolist()) if reporter_field else [],
                "partners": sorted(frame[partner_field].dropna().astype(str).unique().tolist()) if partner_field else [],
                "hs_codes": sorted(frame[hs_field].dropna().astype(str).str.replace(".0", "", regex=False).unique().tolist()) if hs_field else [],
                "commodities": sorted(frame[commodity_field].dropna().astype(str).unique().tolist()) if commodity_field else [],
            },
            "filters": {"reporter": reporter, "partner": partner, "hs_code": hs_code, "year_from": year_from, "year_to": year_to},
            "fields": {
                "period": period_field, "quantity": quantity_field,
                "reporter": reporter_field, "partner": partner_field,
                "commodity": commodity_field, "currency": currency_field,
                "value": value_field,
            },
            "caveats": [
                "Trade values are not summed across currencies." if currency_count > 1 else "Trade value uses the source currency.",
                "Quantity totals use the uploaded metric-tonne field and do not infer missing quantities.",
            ],
        }

    def summary(self) -> Dict[str, Any]:
        datasets = self.datasets()
        with self.session() as db:
            connections = [dict(row) for row in db.execute("SELECT * FROM api_connections").fetchall()]
            relationships = [dict(row) for row in db.execute("SELECT * FROM relationships ORDER BY created_at DESC").fetchall()]
        connection_map = {item["provider"]: item for item in connections}
        cards = []
        for provider, definition in PROVIDERS.items():
            if definition.get("internal"):
                continue
            matches = [item for item in datasets if item["provider"] == provider]
            latest = matches[0] if matches else None
            cards.append({
                "id": provider, **definition, "dataset_count": len(matches),
                "latest": latest, "connection": connection_map.get(provider),
                "freshness": latest["freshness"] if latest else {
                    "status": "missing", "label": "No data uploaded"
                },
            })
        return {
            "providers": cards,
            "datasets": datasets,
            "totals": {
                "datasets": len(datasets),
                "rows": sum(item["row_count"] for item in datasets),
                "overdue": sum(item["freshness"]["status"] == "overdue" for item in datasets),
                "approved_relationships": sum(item["status"] == "approved" for item in relationships),
            },
            "relationships": relationships,
            "master_file": self.database_path.name,
        }

    def save_connection(self, request: ApiConnectionRequest) -> Dict[str, Any]:
        connection_id = f"{request.provider}:{request.connection_label}"
        _api_secrets[connection_id] = request.api_key
        key_mask = f"••••{request.api_key[-4:]}" if len(request.api_key) >= 4 else "••••"
        connected_at = _utcnow().isoformat()
        with self.session() as db:
            db.execute(
                """INSERT INTO api_connections(provider,connection_label,endpoint_url,key_mask,connected_at,secret_storage)
                   VALUES (?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET
                   connection_label=excluded.connection_label, endpoint_url=excluded.endpoint_url,
                   key_mask=excluded.key_mask, connected_at=excluded.connected_at,
                   secret_storage=excluded.secret_storage""",
                (request.provider, request.connection_label, request.endpoint_url, key_mask,
                 connected_at, "process_memory"),
            )
        return {
            "provider": request.provider, "connection_label": request.connection_label,
            "endpoint_url": request.endpoint_url, "key_mask": key_mask,
            "connected_at": connected_at, "secret_storage": "process_memory",
            "operational_status": "credentials_saved_mapping_required",
            "message": "Credentials saved for this running process. No provider data is being ingested until a reviewed connector mapping is configured.",
        }

    def compare(self, dataset_ids: List[str]) -> Dict[str, Any]:
        selected = [self.dataset(dataset_id) for dataset_id in dataset_ids]
        if len(selected) < 2:
            raise ValueError("Select at least two datasets")
        canonical_sets = [{_canonical_field(column) for column in item["columns"]} for item in selected]
        shared = sorted(set.intersection(*canonical_sets)) if canonical_sets else []
        comparison = []
        for item in selected:
            comparison.append({
                "id": item["id"], "provider": item["provider"], "dataset_name": item["dataset_name"],
                "rows": item["row_count"], "columns": item["column_count"],
                "data_start": item["data_start"], "data_end": item["data_end"],
                "null_rate": item["null_rate"], "duplicate_rows": item["duplicate_rows"],
                "quality_status": item["quality_status"], "freshness": item["freshness"],
            })
        return {
            "datasets": comparison, "shared_fields": shared,
            "join_ready": bool(shared),
            "warning": "Matching field names do not prove matching definitions, units, grain or coverage. Review before approval.",
        }

    def propose_relationship(self, request: RelationshipRequest) -> Dict[str, Any]:
        datasets = [self.dataset(dataset_id) for dataset_id in request.dataset_ids]
        if len(datasets) < 2:
            raise ValueError("Select at least two datasets")
        links = []
        for left_index, left in enumerate(datasets[:-1]):
            left_map = {_canonical_field(column): column for column in left["columns"]}
            for right in datasets[left_index + 1:]:
                right_map = {_canonical_field(column): column for column in right["columns"]}
                candidates = sorted(set(left_map).intersection(right_map))
                preferred = [
                    key for key in candidates
                    if any(token in key for token in ("date", "period", "country", "port", "commodity", "plant", "imo", "mmsi", "id"))
                ] or candidates[:5]
                links.append({
                    "left_dataset_id": left["id"], "left_dataset": left["dataset_name"],
                    "right_dataset_id": right["id"], "right_dataset": right["dataset_name"],
                    "candidate_keys": [
                        {"canonical": key, "left_field": left_map[key], "right_field": right_map[key]}
                        for key in preferred[:8]
                    ],
                    "status": "review_required" if preferred else "no_common_key",
                })
        relationship_id = uuid.uuid4().hex[:16]
        proposal = {
            "id": relationship_id, "dataset_ids": request.dataset_ids,
            "question": request.question, "links": links,
            "guardrails": [
                "Confirm units, time grain and entity definitions before joining.",
                "Many-to-many joins can inflate volumes; approve only reviewed keys.",
                "Correlation will be labelled association, not causation.",
            ],
            "status": "proposed", "created_at": _utcnow().isoformat(),
        }
        with self.session() as db:
            db.execute(
                "INSERT INTO relationships VALUES (?,?,?,?,?,?,?)",
                (relationship_id, json.dumps(request.dataset_ids), request.question,
                 json.dumps(proposal), "proposed", proposal["created_at"], None),
            )
        return proposal

    def approve_relationship(self, relationship_id: str, approved: bool) -> Dict[str, Any]:
        status = "approved" if approved else "rejected"
        approved_at = _utcnow().isoformat() if approved else None
        with self.session() as db:
            result = db.execute(
                "UPDATE relationships SET status=?, approved_at=? WHERE id=?",
                (status, approved_at, relationship_id),
            )
            if result.rowcount == 0:
                raise KeyError(relationship_id)
            row = db.execute("SELECT * FROM relationships WHERE id=?", (relationship_id,)).fetchone()
        payload = json.loads(row["proposal_json"])
        payload.update({
            "status": status,
            "approved_at": approved_at,
            "execution_status": "proposal_only_not_materialized",
        })
        return payload


def create_data_hub_router(base_dir: Path, storage_dir: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/data-hub", tags=["data-hub"])
    runtime_dir = storage_dir or Path(
        os.getenv("HRP_STORAGE_DIR", str(base_dir / "uploads"))
    )
    store = DataHubStore(runtime_dir / "provider_data" / "provider_master.sqlite3")
    store.sync_app_datasets(base_dir)

    @router.get("/summary")
    async def summary():
        return store.summary()

    @router.post("/upload")
    async def upload(
        provider: str = Query(...),
        dataset_name: str = Query(..., min_length=1, max_length=160),
        frequency: str = Query("monthly"),
        file: UploadFile = File(...),
    ):
        if provider not in PROVIDERS:
            raise HTTPException(400, "Unknown provider")
        if frequency not in FREQUENCIES:
            raise HTTPException(400, "Unknown update frequency")
        filename = Path(file.filename or "dataset").name
        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, "Supported: Excel, CSV, JSON and PDF")
        content = await file.read()
        if not content:
            raise HTTPException(400, "The uploaded file is empty")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "File too large (maximum 50 MB)")
        try:
            return store.add_dataset(provider, dataset_name, frequency, filename, content)
        except (ValueError, json.JSONDecodeError, pd.errors.ParserError) as exc:
            raise HTTPException(400, f"Could not ingest file: {exc}") from exc

    @router.post("/api-connections")
    async def connect_api(request: ApiConnectionRequest):
        if request.provider not in PROVIDERS:
            raise HTTPException(400, "Unknown provider")
        if not request.api_key.strip():
            raise HTTPException(400, "API key is required")
        return store.save_connection(request)

    @router.get("/datasets/{dataset_id}/preview")
    async def preview(dataset_id: str, limit: int = Query(100, ge=1, le=500)):
        try:
            return {"dataset": store.dataset(dataset_id), "rows": store.rows(dataset_id, limit)}
        except KeyError as exc:
            raise HTTPException(404, "Dataset not found") from exc

    @router.get("/datasets/{dataset_id}/analytics")
    async def analytics(dataset_id: str, reporter: str | None = Query(None), partner: str | None = Query(None),
                        hs_code: str | None = Query(None), year_from: int | None = Query(None),
                        year_to: int | None = Query(None)):
        try:
            return store.analytics(dataset_id, reporter, partner, hs_code, year_from, year_to)
        except KeyError as exc:
            raise HTTPException(404, "Dataset not found") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/compare")
    async def compare(dataset_ids: str = Query(...)):
        ids = [item.strip() for item in dataset_ids.split(",") if item.strip()]
        try:
            return store.compare(ids)
        except KeyError as exc:
            raise HTTPException(404, f"Dataset not found: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/relationships/propose")
    async def propose_relationship(request: RelationshipRequest):
        try:
            return store.propose_relationship(request)
        except KeyError as exc:
            raise HTTPException(404, f"Dataset not found: {exc.args[0]}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/relationships/{relationship_id}/approve")
    async def approve_relationship(relationship_id: str, request: RelationshipApproval):
        try:
            return store.approve_relationship(relationship_id, request.approved)
        except KeyError as exc:
            raise HTTPException(404, "Relationship proposal not found") from exc

    @router.get("/datasets/{dataset_id}/export")
    async def export_dataset(dataset_id: str, format: str = Query("xlsx", pattern="^(xlsx|csv|json)$")):
        try:
            dataset = store.dataset(dataset_id)
            rows = store.all_rows(dataset_id)
        except KeyError as exc:
            raise HTTPException(404, "Dataset not found") from exc
        frame = pd.DataFrame(rows)
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", dataset["dataset_name"]).strip("_") or "dataset"
        if format == "json":
            content = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
            media_type = "application/json"
        elif format == "csv":
            content = frame.to_csv(index=False).encode("utf-8-sig")
            media_type = "text/csv"
        else:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                frame.to_excel(writer, index=False, sheet_name="Data")
                pd.DataFrame([{
                    "Provider": PROVIDERS[dataset["provider"]]["label"],
                    "Dataset": dataset["dataset_name"], "Uploaded": dataset["uploaded_at"],
                    "Coverage start": dataset["data_start"], "Coverage end": dataset["data_end"],
                    "Quality": dataset["quality_status"],
                }]).to_excel(writer, index=False, sheet_name="Lineage")
            content = output.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return StreamingResponse(
            io.BytesIO(content), media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.{format}"'},
        )

    return router
