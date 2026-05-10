from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import read_csv_rows_from_path, sha256_file, write_csv_rows, write_parquet_rows
from .path_semantics import infer_instrument_type_from_path, infer_source_market_type
from .schemas import EXPECTED_COLUMNS
from .time_semantics import candle_close_time_ms, exchange_date_utc8_from_ms, ms_to_utc_iso

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class CandlestickQuality:
    source_file_name: str
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
    expected_rows_1m: int
    has_expected_1440_rows: bool
    confirm_1_count: int
    confirm_0_count: int
    confirm_1_ratio: float | None
    source_archive_confirm_policy: str
    data_quality_flags: str
    missing_columns: list[str]
    extra_columns: list[str]
    duplicate_open_time_count: int
    exact_duplicate_open_time_count: int
    conflicting_duplicate_open_time_count: int
    deduplicated_row_count: int
    out_of_order_time_count: int
    gap_count: int
    first_gaps: list[dict[str, Any]]
    ohlc_invalid_count: int
    negative_volume_count: int
    allow_into_training: bool
    data_quality_score: float


def source_file_date_from_name(name: str) -> str | None:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def process_candlestick_file(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    now = datetime.now(timezone.utc).isoformat()
    source_file_date = source_file_date_from_name(path.name)
    source_market_type = infer_source_market_type(path)
    manifest: dict[str, Any] = {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_file_hash": file_hash,
        "dataset_type": "candlestick",
        "source_market_type": source_market_type,
        "exchange": "okx",
        "instrument_name": None,
        "instrument_type": None,
        "source_file_date": source_file_date,
        "exchange_date_utc8": source_file_date,
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
        header, rows, inner = read_csv_rows_from_path(path)
        expected = EXPECTED_COLUMNS["candlestick"]
        missing_columns = [c for c in expected if c not in header]
        extra_columns = [c for c in header if c not in expected]
        if missing_columns:
            raise ValueError(f"missing columns: {missing_columns}")
        raw_row_count = len(rows)
        rows_by_open_time: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_open_time.setdefault(str(row["open_time"]), []).append(row)
        deduped_rows: list[dict[str, Any]] = []
        exact_duplicate_open_time_count = 0
        conflicting_duplicate_open_time_count = 0
        for open_time in sorted(rows_by_open_time, key=lambda x: int(x)):
            grouped = rows_by_open_time[open_time]
            first = grouped[0]
            if len(grouped) > 1:
                if all(row == first for row in grouped[1:]):
                    exact_duplicate_open_time_count += len(grouped) - 1
                else:
                    conflicting_duplicate_open_time_count += len(grouped) - 1
            deduped_rows.append(first)
        rows_for_quality = deduped_rows if exact_duplicate_open_time_count and not conflicting_duplicate_open_time_count else rows
        normalized: list[dict[str, Any]] = []
        normalized_candidates: list[dict[str, Any]] = []
        open_times: list[int] = []
        confirm_1 = 0
        confirm_0 = 0
        ohlc_invalid = 0
        neg_vol = 0
        instruments = set()
        for r in rows_for_quality:
            inst = r["instrument_name"]
            instruments.add(inst)
            ot = int(r["open_time"])
            open_times.append(ot)
            close_ms = candle_close_time_ms(ot)
            confirm = int(r["confirm"])
            confirm_1 += 1 if confirm == 1 else 0
            confirm_0 += 1 if confirm == 0 else 0
            def optional_float(value: str | None) -> float | None:
                if value is None:
                    return None
                if str(value).strip().lower() in {"", "none", "null", "nan"}:
                    return None
                return float(value)

            o = float(r["open"]); h = float(r["high"]); l = float(r["low"]); c = float(r["close"])
            vol = optional_float(r["vol"]); vol_ccy = optional_float(r["vol_ccy"]); vol_quote = optional_float(r["vol_quote"])
            if h < max(o, c) or l > min(o, c) or h < l:
                ohlc_invalid += 1
            for volume_value in (vol, vol_ccy, vol_quote):
                if volume_value is not None and volume_value < 0:
                    neg_vol += 1
            normalized_candidates.append({
                "exchange": "okx",
                "dataset_type": "candlestick",
                "instrument_name": inst,
                "instrument_type": infer_instrument_type_from_path(inst, path),
                "source_market_type": source_market_type,
                "bar_interval": "1m",
                "event_time_ms": close_ms,
                "event_time_utc": ms_to_utc_iso(close_ms),
                "open_time_ms": ot,
                "open_time_utc": ms_to_utc_iso(ot),
                "close_time_ms": close_ms,
                "close_time_utc": ms_to_utc_iso(close_ms),
                "available_time_ms": close_ms,
                "available_time_utc": ms_to_utc_iso(close_ms),
                "exchange_date_utc8": exchange_date_utc8_from_ms(ot),
                "source_file_date": source_file_date,
                "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
                "vol_base": r["vol"],
                "vol_ccy": r["vol_ccy"],
                "vol_quote": r["vol_quote"],
                "confirm": confirm,
                "source_file_name": path.name,
                "source_file_hash": file_hash,
                "schema_version": versions.schema_version,
                "governance_version": versions.governance_version,
                "data_quality_score": "1.0",
                "is_filled": "false",
                "fill_method": "none",
                "missing_reason": "none",
            })
        sorted_times = sorted(open_times)
        duplicates = len(open_times) - len(set(open_times))
        out_of_order = sum(1 for a, b in zip(open_times, open_times[1:]) if b < a)
        gaps = []
        for prev, cur in zip(sorted_times, sorted_times[1:]):
            diff = cur - prev
            if diff != 60_000:
                gaps.append({"previous_open_time_ms": prev, "current_open_time_ms": cur, "gap_ms": diff})
        row_count = raw_row_count
        deduplicated_row_count = len(rows_for_quality)
        min_ms = min(open_times) if open_times else None
        max_ms = max(open_times) if open_times else None
        inst_name = sorted(instruments)[0] if instruments else None
        base_integrity_ok = bool(deduplicated_row_count == 1440 and not gaps and duplicates == 0 and conflicting_duplicate_open_time_count == 0 and ohlc_invalid == 0 and neg_vol == 0)
        quality_flags: list[str] = []
        if confirm_0 == 0:
            source_archive_confirm_policy = "strict_confirm_1"
        elif confirm_1 == 0 and base_integrity_ok:
            source_archive_confirm_policy = "historical_archive_confirm_0_closed_bar_by_complete_daily_file"
            quality_flags.append("source_archive_confirm_0_closed_bar_inferred")
        elif confirm_1 == 0:
            source_archive_confirm_policy = "unresolved_confirm_0"
            quality_flags.append("confirm_0_unresolved")
        else:
            source_archive_confirm_policy = "mixed_confirm_values_unresolved"
            quality_flags.append("mixed_confirm_values")
        if deduplicated_row_count != 1440:
            quality_flags.append("row_count_not_1440")
        if exact_duplicate_open_time_count:
            quality_flags.append("exact_duplicate_open_time_deduplicated")
        if conflicting_duplicate_open_time_count:
            quality_flags.append("conflicting_duplicate_open_time_detected")
        if gaps:
            quality_flags.append("time_gap_detected")
        if duplicates:
            quality_flags.append("duplicate_open_time_detected")
        if ohlc_invalid:
            quality_flags.append("ohlc_invalid_detected")
        if neg_vol:
            quality_flags.append("negative_volume_detected")
        confirm_semantics_ok = source_archive_confirm_policy in {
            "strict_confirm_1",
            "historical_archive_confirm_0_closed_bar_by_complete_daily_file",
        }
        allow = bool(base_integrity_ok and confirm_semantics_ok)
        if allow:
            for candidate in normalized_candidates:
                candidate["source_archive_confirm_policy"] = source_archive_confirm_policy
                candidate["data_quality_flags"] = ";".join(quality_flags)
                if source_archive_confirm_policy != "strict_confirm_1":
                    candidate["data_quality_score"] = "0.98"
            normalized = normalized_candidates
        penalties = 0
        penalties += 20 if row_count != 1440 else 0
        penalties += min(20, confirm_0)
        penalties += min(20, len(gaps) * 2)
        penalties += min(20, duplicates * 2 + out_of_order)
        penalties += min(20, ohlc_invalid + neg_vol)
        score = max(0.0, 100.0 - penalties) / 100.0
        quality = CandlestickQuality(
            source_file_name=path.name,
            parse_status="success",
            parse_error_message=None,
            row_count=row_count,
            min_event_time_ms=min_ms,
            max_event_time_ms=max_ms,
            min_event_time_utc=ms_to_utc_iso(min_ms) if min_ms is not None else None,
            max_event_time_utc=ms_to_utc_iso(max_ms) if max_ms is not None else None,
            source_file_date=source_file_date,
            exchange_date_utc8_min=exchange_date_utc8_from_ms(min_ms) if min_ms is not None else None,
            exchange_date_utc8_max=exchange_date_utc8_from_ms(max_ms) if max_ms is not None else None,
            expected_rows_1m=1440,
            has_expected_1440_rows=(deduplicated_row_count == 1440),
            confirm_1_count=confirm_1,
            confirm_0_count=confirm_0,
            confirm_1_ratio=(confirm_1 / row_count) if row_count else None,
            source_archive_confirm_policy=source_archive_confirm_policy,
            data_quality_flags=";".join(quality_flags),
            missing_columns=missing_columns,
            extra_columns=extra_columns,
            duplicate_open_time_count=duplicates,
            exact_duplicate_open_time_count=exact_duplicate_open_time_count,
            conflicting_duplicate_open_time_count=conflicting_duplicate_open_time_count,
            deduplicated_row_count=deduplicated_row_count,
            out_of_order_time_count=out_of_order,
            gap_count=len(gaps),
            first_gaps=gaps[:20],
            ohlc_invalid_count=ohlc_invalid,
            negative_volume_count=neg_vol,
            allow_into_training=allow,
            data_quality_score=score,
        )
        manifest.update({
            "instrument_name": inst_name,
            "instrument_type": infer_instrument_type_from_path(inst_name or "", path),
            "source_market_type": source_market_type,
            "row_count": row_count,
            "min_event_time_ms": min_ms,
            "max_event_time_ms": max_ms,
            "parse_status": "success",
            "zip_inner_csv": inner,
        })
        return manifest, asdict(quality), normalized
    except Exception as e:
        manifest["parse_status"] = "error"
        manifest["parse_error_message"] = str(e)
        quality = CandlestickQuality(
            source_file_name=path.name, parse_status="error", parse_error_message=str(e), row_count=0,
            min_event_time_ms=None, max_event_time_ms=None, min_event_time_utc=None, max_event_time_utc=None,
            source_file_date=source_file_date, exchange_date_utc8_min=None, exchange_date_utc8_max=None,
            expected_rows_1m=1440, has_expected_1440_rows=False, confirm_1_count=0, confirm_0_count=0,
            confirm_1_ratio=None, source_archive_confirm_policy="parse_error", data_quality_flags="parse_error", missing_columns=[], extra_columns=[], duplicate_open_time_count=0,
            exact_duplicate_open_time_count=0, conflicting_duplicate_open_time_count=0, deduplicated_row_count=0,
            out_of_order_time_count=0, gap_count=0, first_gaps=[], ohlc_invalid_count=0, negative_volume_count=0,
            allow_into_training=False, data_quality_score=0.0)
        return manifest, asdict(quality), []


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_candlestick_minimal(root: Path) -> dict[str, Any]:
    source_dir = root / "okx" / "Candlesticks"
    files = sorted([p for p in source_dir.rglob("*") if p.is_file() and (p.suffix.lower() in {".csv", ".zip"})])
    summary = {"dataset_type": "candlestick", "source_file_count": len(files), "success_count": 0, "error_count": 0, "outputs": []}
    all_quality = []
    for p in files:
        manifest, quality, normalized = process_candlestick_file(p, root)
        source_date = manifest.get("source_file_date") or "unknown"
        market = manifest.get("source_market_type") or "unknown"
        inst = manifest.get("instrument_name") or "unknown"
        base = root / "manifests" / "exchange=okx" / "dataset_type=candlestick" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        write_json(base / "file_manifest.json", manifest)
        qpath = root / "reports" / "quality" / "exchange=okx" / "dataset_type=candlestick" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}" / "quality_report.json"
        write_json(qpath, quality)
        if normalized:
            nbase = root / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=candlestick" / f"market={market}" / f"instrument={inst}" / "interval=1m" / f"exchange_date_utc8={source_date}"
            parquet_path = nbase / "candlestick_normalized.parquet"
            csv_path = nbase / "candlestick_normalized.csv"
            write_parquet_rows(parquet_path, normalized)
            write_csv_rows(csv_path, normalized, list(normalized[0].keys()))
        else:
            parquet_path = None
            csv_path = None
        all_quality.append(quality)
        summary["success_count"] += 1 if manifest["parse_status"] == "success" else 0
        summary["error_count"] += 1 if manifest["parse_status"] != "success" else 0
        summary["outputs"].append({"source": str(p), "manifest": str(base / "file_manifest.json"), "quality_report": str(qpath), "normalized_parquet": str(parquet_path) if parquet_path else None, "normalized_csv": str(csv_path) if csv_path else None, "normalized_rows": len(normalized)})
    summary["allow_into_training_count"] = sum(1 for q in all_quality if q.get("allow_into_training"))
    summary["blocked_count"] = len(all_quality) - summary["allow_into_training_count"]
    summary_path = root / "reports" / "quality" / "candlestick_minimal_summary.json"
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary
