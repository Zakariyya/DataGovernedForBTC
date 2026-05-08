from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import read_csv_rows_from_path, sha256_file, write_csv_rows
from .path_semantics import infer_instrument_type_from_path, infer_source_market_type
from .schemas import EXPECTED_COLUMNS
from .time_semantics import ms_to_utc_iso

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def source_file_date_from_name(name: str) -> str | None:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def numeric_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"", "none", "null", "nan"}:
        return None
    return float(s)


def instrument_type(instrument_name: str) -> str:
    return infer_instrument_type_from_path(instrument_name, Path("unknown"))


def base_manifest(path: Path, dataset_type: str, file_hash: str, versions: GovernanceVersions) -> dict[str, Any]:
    source_file_date = source_file_date_from_name(path.name)
    return {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_file_hash": file_hash,
        "dataset_type": dataset_type,
        "source_market_type": infer_source_market_type(path),
        "exchange": "okx",
        "instrument_name": None,
        "instrument_type": None,
        "source_file_date": source_file_date,
        "exchange_date_utc8": source_file_date,
        "row_count": 0,
        "min_event_time_ms": None,
        "max_event_time_ms": None,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": versions.schema_version,
        "governance_version": versions.governance_version,
        "parse_status": "unknown",
        "parse_error_message": None,
    }


def infer_intervals_by_key(events: dict[str, list[int]]) -> dict[str, int | None]:
    inferred: dict[str, int | None] = {}
    for key, times in events.items():
        uniq = sorted(set(times))
        diffs = [b - a for a, b in zip(uniq, uniq[1:]) if b > a]
        if not diffs:
            inferred[key] = None
        else:
            inferred[key] = Counter(diffs).most_common(1)[0][0]
    return inferred


@dataclass
class FundingQuality:
    source_file_name: str
    parse_status: str
    parse_error_message: str | None
    row_count: int
    missing_columns: list[str]
    extra_columns: list[str]
    instrument_count: int
    min_funding_time_ms: int | None
    max_funding_time_ms: int | None
    min_funding_time_utc: str | None
    max_funding_time_utc: str | None
    null_funding_rate_count: int
    inferred_funding_interval_ms_by_instrument: dict[str, int | None]
    quality_level: str
    data_quality_score: float


@dataclass
class BorrowingQuality:
    source_file_name: str
    parse_status: str
    parse_error_message: str | None
    row_count: int
    missing_columns: list[str]
    extra_columns: list[str]
    currency_count: int
    present_key_currencies: list[str]
    missing_key_currencies: list[str]
    min_time_ms: int | None
    max_time_ms: int | None
    min_time_utc: str | None
    max_time_utc: str | None
    null_borrow_rate_count: int
    borrow_rate_unit: str
    expected_rows_per_currency_per_day: int
    currency_row_counts: dict[str, int]
    data_quality_score: float


def process_funding_file(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    manifest = base_manifest(path, "funding_rate", file_hash, versions)
    try:
        header, rows, inner = read_csv_rows_from_path(path)
        expected = EXPECTED_COLUMNS["funding_rate"]
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        if missing:
            raise ValueError(f"missing columns: {missing}")
        events: dict[str, list[int]] = defaultdict(list)
        null_rates = 0
        normalized: list[dict[str, Any]] = []
        instruments = set()
        for r in rows:
            inst = r["instrument_name"]
            instruments.add(inst)
            t = int(float(r["funding_time"]))
            events[inst].append(t)
            rate = numeric_or_none(r.get("funding_rate"))
            if rate is None:
                null_rates += 1
            normalized.append({
                "exchange": "okx",
                "dataset_type": "funding_rate",
                "instrument_name": inst,
                "instrument_type": infer_instrument_type_from_path(inst, path),
                "source_market_type": infer_source_market_type(path),
                "event_time_ms": t,
                "event_time_utc": ms_to_utc_iso(t),
                "funding_time_ms": t,
                "funding_time_utc": ms_to_utc_iso(t),
                "available_time_ms": t,
                "available_time_utc": ms_to_utc_iso(t),
                "realized_funding_rate": r.get("funding_rate"),
                "funding_interval_ms": "",
                "funding_age_ms": "0",
                "source_file_name": path.name,
                "source_file_hash": file_hash,
                "quality_level": "official_realized",
                "schema_version": versions.schema_version,
                "governance_version": versions.governance_version,
                "data_quality_score": "1.0",
            })
        intervals = infer_intervals_by_key(events)
        for row in normalized:
            interval = intervals.get(row["instrument_name"])
            row["funding_interval_ms"] = "" if interval is None else str(interval)
        times = [t for vals in events.values() for t in vals]
        inst_name = sorted(instruments)[0] if len(instruments) == 1 else None
        manifest.update({
            "instrument_name": inst_name,
            "instrument_type": infer_instrument_type_from_path(inst_name or "", path) if inst_name else "multi_instrument",
            "source_market_type": infer_source_market_type(path),
            "row_count": len(rows),
            "min_event_time_ms": min(times) if times else None,
            "max_event_time_ms": max(times) if times else None,
            "parse_status": "success",
            "zip_inner_csv": inner,
        })
        penalties = min(50, null_rates * 5) + (20 if missing else 0)
        quality = FundingQuality(
            source_file_name=path.name,
            parse_status="success",
            parse_error_message=None,
            row_count=len(rows),
            missing_columns=missing,
            extra_columns=extra,
            instrument_count=len(instruments),
            min_funding_time_ms=min(times) if times else None,
            max_funding_time_ms=max(times) if times else None,
            min_funding_time_utc=ms_to_utc_iso(min(times)) if times else None,
            max_funding_time_utc=ms_to_utc_iso(max(times)) if times else None,
            null_funding_rate_count=null_rates,
            inferred_funding_interval_ms_by_instrument=intervals,
            quality_level="official_realized",
            data_quality_score=max(0.0, 100.0 - penalties) / 100.0,
        )
        return manifest, asdict(quality), normalized
    except Exception as e:
        manifest.update({"parse_status": "error", "parse_error_message": str(e)})
        q = FundingQuality(path.name, "error", str(e), 0, [], [], 0, None, None, None, None, 0, {}, "official_realized", 0.0)
        return manifest, asdict(q), []


def process_borrowing_file(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    manifest = base_manifest(path, "borrowing_rate", file_hash, versions)
    try:
        header, rows, inner = read_csv_rows_from_path(path)
        expected = EXPECTED_COLUMNS["borrowing_rate"]
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        if missing:
            raise ValueError(f"missing columns: {missing}")
        currency_counts: Counter[str] = Counter()
        null_rates = 0
        times: list[int] = []
        normalized: list[dict[str, Any]] = []
        for r in rows:
            ccy = r["currency_name"]
            currency_counts[ccy] += 1
            t = int(float(r["time"]))
            times.append(t)
            rate = numeric_or_none(r.get("borrow_rate"))
            if rate is None:
                null_rates += 1
            normalized.append({
                "exchange": "okx",
                "dataset_type": "borrowing_rate",
                "source_market_type": infer_source_market_type(path),
                "currency_name": ccy,
                "event_time_ms": t,
                "event_time_utc": ms_to_utc_iso(t),
                "available_time_ms": t,
                "available_time_utc": ms_to_utc_iso(t),
                "borrow_rate_raw": r.get("borrow_rate"),
                "borrow_rate_unit": "unknown_raw",
                "borrow_rate_interval": "hourly_observed_expected",
                "borrow_rate_age_ms": "0",
                "source_file_name": path.name,
                "source_file_hash": file_hash,
                "quality_level": "official_raw_unit_unknown",
                "schema_version": versions.schema_version,
                "governance_version": versions.governance_version,
                "data_quality_score": "1.0",
            })
        present_keys = [c for c in ["BTC", "ETH", "USDT"] if c in currency_counts]
        missing_keys = [c for c in ["BTC", "ETH", "USDT"] if c not in currency_counts]
        manifest.update({
            "instrument_name": None,
            "instrument_type": "margin_borrow_rate",
            "source_market_type": infer_source_market_type(path),
            "row_count": len(rows),
            "min_event_time_ms": min(times) if times else None,
            "max_event_time_ms": max(times) if times else None,
            "parse_status": "success",
            "zip_inner_csv": inner,
        })
        penalties = min(30, len(missing_keys) * 10) + min(50, null_rates * 5)
        q = BorrowingQuality(
            source_file_name=path.name,
            parse_status="success",
            parse_error_message=None,
            row_count=len(rows),
            missing_columns=missing,
            extra_columns=extra,
            currency_count=len(currency_counts),
            present_key_currencies=present_keys,
            missing_key_currencies=missing_keys,
            min_time_ms=min(times) if times else None,
            max_time_ms=max(times) if times else None,
            min_time_utc=ms_to_utc_iso(min(times)) if times else None,
            max_time_utc=ms_to_utc_iso(max(times)) if times else None,
            null_borrow_rate_count=null_rates,
            borrow_rate_unit="unknown_raw",
            expected_rows_per_currency_per_day=24,
            currency_row_counts=dict(sorted(currency_counts.items())),
            data_quality_score=max(0.0, 100.0 - penalties) / 100.0,
        )
        return manifest, asdict(q), normalized
    except Exception as e:
        manifest.update({"parse_status": "error", "parse_error_message": str(e)})
        q = BorrowingQuality(path.name, "error", str(e), 0, [], [], 0, [], ["BTC", "ETH", "USDT"], None, None, None, None, 0, "unknown_raw", 24, {}, 0.0)
        return manifest, asdict(q), []


def run_low_frequency_minimal(root: Path) -> dict[str, Any]:
    jobs = [
        ("funding_rate", root / "okx" / "Fundingrates", process_funding_file, "funding_normalized.csv"),
        ("borrowing_rate", root / "okx" / "Borrowrates", process_borrowing_file, "borrowing_normalized.csv"),
    ]
    summary: dict[str, Any] = {"datasets": {}}
    for dataset_type, source_dir, processor, normalized_name in jobs:
        files = sorted([p for p in source_dir.rglob("*.csv") if p.is_file()])
        ds = {"source_file_count": len(files), "success_count": 0, "error_count": 0, "outputs": []}
        for p in files:
            manifest, quality, normalized = processor(p, root)
            source_date = manifest.get("source_file_date") or "unknown"
            market = manifest.get("source_market_type") or "unknown"
            manifest_base = root / "manifests" / "exchange=okx" / f"dataset_type={dataset_type}" / f"market={market}" / f"exchange_date_utc8={source_date}"
            quality_base = root / "reports" / "quality" / "exchange=okx" / f"dataset_type={dataset_type}" / f"market={market}" / f"exchange_date_utc8={source_date}"
            normalized_base = root / "data_lake" / "normalized" / "exchange=okx" / f"dataset_type={dataset_type}" / f"market={market}" / f"exchange_date_utc8={source_date}"
            write_json(manifest_base / "file_manifest.json", manifest)
            write_json(quality_base / "quality_report.json", quality)
            if normalized:
                write_csv_rows(normalized_base / normalized_name, normalized, list(normalized[0].keys()))
            ds["success_count"] += 1 if manifest["parse_status"] == "success" else 0
            ds["error_count"] += 1 if manifest["parse_status"] != "success" else 0
            ds["outputs"].append({
                "source": str(p),
                "manifest": str(manifest_base / "file_manifest.json"),
                "quality_report": str(quality_base / "quality_report.json"),
                "normalized_rows": len(normalized),
            })
        summary["datasets"][dataset_type] = ds
    summary_path = root / "reports" / "quality" / "low_frequency_minimal_summary.json"
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary
