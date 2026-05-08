from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import sha256_file
from .schemas import EXPECTED_COLUMNS
from .time_semantics import ms_to_utc_iso, exchange_date_utc8_from_ms

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

DATASET_CONFIG = {
    "funding_rate": {
        "source_dir": "Fundingrates",
        "time_col": "funding_time",
        "instrument_col": "instrument_name",
        "quality_level": "official_realized",
        "glob_suffixes": [".csv"],
        "future_leak_notes": [
            "funding_rate is realized funding; never use as predicted_funding_rate",
            "available_time_ms = funding_time + configured_latency_ms",
            "infer funding_interval_ms from adjacent funding_time values, do not hard-code all instruments to 8h",
        ],
    },
    "borrowing_rate": {
        "source_dir": "Borrowrates",
        "time_col": "time",
        "instrument_col": "currency_name",
        "quality_level": "official_raw_unit_unknown",
        "glob_suffixes": [".csv"],
        "future_leak_notes": [
            "borrow_rate unit defaults to unknown_raw; do not annualize/hourly-convert without config",
            "available_time_ms = time + configured_latency_ms",
            "as-of joined borrowing features require borrow_rate_age_ms and max-age cutoff",
        ],
    },
    "trade": {
        "source_dir": "Trade",
        "time_col": "created_time",
        "instrument_col": "instrument_name",
        "quality_level": "official_trade_history",
        "glob_suffixes": [".csv"],
        "future_leak_notes": [
            "side is preserved as side_raw; do not assume taker side without config",
            "dedupe by trade_id before feature aggregation",
            "raw tick trade data must not be read directly by AlphaTenant",
        ],
    },
}


@dataclass
class SimpleQuality:
    source_file_name: str
    dataset_type: str
    parse_status: str
    parse_error_message: str | None
    row_count: int
    min_event_time_ms: int | None
    max_event_time_ms: int | None
    min_event_time_utc: str | None
    max_event_time_utc: str | None
    source_file_date: str | None
    exchange_date_utc8_min: str | None
    exchange_date_utc8_max: str | None
    missing_columns: list[str]
    extra_columns: list[str]
    duplicate_time_count: int
    out_of_order_time_count: int
    null_time_count: int
    null_value_count: int
    quality_level: str
    future_leak_notes: list[str]
    allow_into_normalized: bool
    data_quality_score: float


def source_file_date_from_name(name: str) -> str | None:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def infer_instrument_type(dataset_type: str, value: str | None) -> str:
    if dataset_type == "borrowing_rate":
        return "currency"
    if value and value.endswith("-SWAP"):
        return "swap"
    return "spot_or_margin_unknown"


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def process_simple_file(dataset_type: str, path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = DATASET_CONFIG[dataset_type]
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    now = datetime.now(timezone.utc).isoformat()
    source_date = source_file_date_from_name(path.name)
    manifest: dict[str, Any] = {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_file_hash": file_hash,
        "dataset_type": dataset_type,
        "exchange": "okx",
        "instrument_name": None,
        "instrument_type": None,
        "source_file_date": source_date,
        "exchange_date_utc8": source_date,
        "row_count": 0,
        "min_event_time_ms": None,
        "max_event_time_ms": None,
        "ingested_at": now,
        "schema_version": versions.schema_version,
        "governance_version": versions.governance_version,
        "parse_status": "unknown",
        "parse_error_message": None,
    }
    try:
        header, rows = read_csv_rows(path)
        expected = EXPECTED_COLUMNS[dataset_type]
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        if missing:
            raise ValueError(f"missing columns: {missing}")
        tcol = cfg["time_col"]
        icol = cfg["instrument_col"]
        times: list[int] = []
        null_time = 0
        null_values = 0
        instruments: set[str] = set()
        for row in rows:
            if row.get(icol):
                instruments.add(str(row.get(icol)))
            tv = row.get(tcol)
            if tv in (None, "", "None", "null"):
                null_time += 1
            else:
                times.append(int(float(tv)))
            null_values += sum(1 for v in row.values() if v in (None, "", "None", "null"))
        duplicates = len(times) - len(set(times))
        out_of_order = sum(1 for a, b in zip(times, times[1:]) if b < a)
        min_ms = min(times) if times else None
        max_ms = max(times) if times else None
        inst = sorted(instruments)[0] if instruments else None
        penalties = 0
        penalties += 30 if missing else 0
        penalties += min(20, null_time * 2)
        penalties += min(20, out_of_order)
        if dataset_type == "trade":
            ids = [r.get("trade_id") for r in rows if r.get("trade_id")]
            duplicate_ids = len(ids) - len(set(ids))
            penalties += min(20, duplicate_ids * 2)
        else:
            duplicate_ids = 0
        score = max(0.0, 100.0 - penalties) / 100.0
        allow = not missing and null_time == 0
        manifest.update({
            "instrument_name": inst,
            "instrument_type": infer_instrument_type(dataset_type, inst),
            "row_count": len(rows),
            "min_event_time_ms": min_ms,
            "max_event_time_ms": max_ms,
            "parse_status": "success",
        })
        quality = SimpleQuality(
            source_file_name=path.name,
            dataset_type=dataset_type,
            parse_status="success",
            parse_error_message=None,
            row_count=len(rows),
            min_event_time_ms=min_ms,
            max_event_time_ms=max_ms,
            min_event_time_utc=ms_to_utc_iso(min_ms) if min_ms is not None else None,
            max_event_time_utc=ms_to_utc_iso(max_ms) if max_ms is not None else None,
            source_file_date=source_date,
            exchange_date_utc8_min=exchange_date_utc8_from_ms(min_ms) if min_ms is not None else None,
            exchange_date_utc8_max=exchange_date_utc8_from_ms(max_ms) if max_ms is not None else None,
            missing_columns=missing,
            extra_columns=extra,
            duplicate_time_count=duplicates,
            out_of_order_time_count=out_of_order,
            null_time_count=null_time,
            null_value_count=null_values,
            quality_level=cfg["quality_level"],
            future_leak_notes=cfg["future_leak_notes"],
            allow_into_normalized=allow,
            data_quality_score=score,
        )
        q = asdict(quality)
        if dataset_type == "trade":
            q["duplicate_trade_id_count"] = duplicate_ids
        return manifest, q
    except Exception as exc:
        manifest["parse_status"] = "error"
        manifest["parse_error_message"] = str(exc)
        quality = SimpleQuality(
            source_file_name=path.name,
            dataset_type=dataset_type,
            parse_status="error",
            parse_error_message=str(exc),
            row_count=0,
            min_event_time_ms=None,
            max_event_time_ms=None,
            min_event_time_utc=None,
            max_event_time_utc=None,
            source_file_date=source_date,
            exchange_date_utc8_min=None,
            exchange_date_utc8_max=None,
            missing_columns=[],
            extra_columns=[],
            duplicate_time_count=0,
            out_of_order_time_count=0,
            null_time_count=0,
            null_value_count=0,
            quality_level=cfg["quality_level"],
            future_leak_notes=cfg["future_leak_notes"],
            allow_into_normalized=False,
            data_quality_score=0.0,
        )
        return manifest, asdict(quality)


def run_simple_manifest_quality(root: Path, dataset_type: str) -> dict[str, Any]:
    cfg = DATASET_CONFIG[dataset_type]
    source_dir = root / "okx" / cfg["source_dir"]
    suffixes = set(cfg["glob_suffixes"])
    files = sorted([p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in suffixes])
    summary = {"dataset_type": dataset_type, "source_file_count": len(files), "success_count": 0, "error_count": 0, "outputs": []}
    for p in files:
        manifest, quality = process_simple_file(dataset_type, p)
        source_date = manifest.get("source_file_date") or "unknown"
        inst = manifest.get("instrument_name") or "unknown"
        base = root / "manifests" / "exchange=okx" / f"dataset_type={dataset_type}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        qpath = root / "reports" / "quality" / "exchange=okx" / f"dataset_type={dataset_type}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}" / "quality_report.json"
        write_json(base / "file_manifest.json", manifest)
        write_json(qpath, quality)
        summary["success_count"] += 1 if manifest["parse_status"] == "success" else 0
        summary["error_count"] += 1 if manifest["parse_status"] != "success" else 0
        summary["outputs"].append({"source": str(p), "manifest": str(base / "file_manifest.json"), "quality_report": str(qpath)})
    summary["allow_into_normalized_count"] = sum(1 for item in summary["outputs"] if json.loads(Path(item["quality_report"]).read_text(encoding="utf-8")).get("allow_into_normalized"))
    spath = root / "reports" / "quality" / f"{dataset_type}_manifest_quality_summary.json"
    write_json(spath, summary)
    summary["summary_path"] = str(spath)
    return summary


def run_all_simple_manifest_quality(root: Path) -> dict[str, Any]:
    result = {"datasets": {}}
    for ds in ["funding_rate", "borrowing_rate", "trade"]:
        result["datasets"][ds] = run_simple_manifest_quality(root, ds)
    path = root / "reports" / "quality" / "simple_datasets_manifest_quality_summary.json"
    write_json(path, result)
    result["summary_path"] = str(path)
    return result
