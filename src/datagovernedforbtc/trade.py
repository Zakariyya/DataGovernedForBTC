from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import read_csv_rows_from_path, sha256_file, write_csv_rows
from .path_semantics import infer_instrument_type_from_path, infer_source_market_type
from .schemas import EXPECTED_COLUMNS
from .time_semantics import exchange_date_utc8_from_ms, ms_to_utc_iso

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def source_file_date_from_name(name: str) -> str | None:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as e:
        raise ValueError(f"invalid decimal value: {value!r}") from e


def dec_str(value: Decimal) -> str:
    # Keep deterministic compact decimal text without scientific notation for common market values.
    s = format(value.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


@dataclass
class TradeQuality:
    source_file_name: str
    parse_status: str
    parse_error_message: str | None
    row_count: int
    normalized_row_count: int
    missing_columns: list[str]
    extra_columns: list[str]
    instrument_count: int
    min_created_time_ms: int | None
    max_created_time_ms: int | None
    min_created_time_utc: str | None
    max_created_time_utc: str | None
    duplicate_trade_id_count: int
    out_of_order_time_count: int
    invalid_price_count: int
    invalid_size_count: int
    invalid_side_count: int
    side_semantics: str
    allow_into_feature_aggregation: bool
    data_quality_score: float


def process_trade_file(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    source_file_date = source_file_date_from_name(path.name)
    source_market_type = infer_source_market_type(path)
    manifest: dict[str, Any] = {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_file_hash": file_hash,
        "dataset_type": "trade",
        "source_market_type": source_market_type,
        "exchange": "okx",
        "instrument_name": None,
        "instrument_type": None,
        "source_file_date": source_file_date,
        "exchange_date_utc8": source_file_date,
        "row_count": 0,
        "min_event_time_ms": None,
        "max_event_time_ms": None,
        "schema_version": versions.schema_version,
        "governance_version": versions.governance_version,
        "parse_status": "unknown",
        "parse_error_message": None,
    }
    try:
        header, rows, inner = read_csv_rows_from_path(path)
        expected = EXPECTED_COLUMNS["trade"]
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        if missing:
            raise ValueError(f"missing columns: {missing}")

        seen: set[str] = set()
        duplicate_count = 0
        invalid_price = 0
        invalid_size = 0
        invalid_side = 0
        out_of_order = 0
        previous_time: int | None = None
        instruments: set[str] = set()
        normalized_by_trade_id: dict[str, dict[str, Any]] = {}

        for raw in rows:
            trade_id = str(raw["trade_id"])
            if trade_id in seen:
                duplicate_count += 1
                continue
            seen.add(trade_id)

            inst = raw["instrument_name"]
            instruments.add(inst)
            side_raw = str(raw["side"]).strip().lower()
            if side_raw not in {"buy", "sell"}:
                invalid_side += 1
            event_time = int(float(raw["created_time"]))
            if previous_time is not None and event_time < previous_time:
                out_of_order += 1
            previous_time = event_time
            price = dec(raw["price"])
            size = dec(raw["size"])
            if price <= 0:
                invalid_price += 1
            if size <= 0:
                invalid_size += 1
            quote = price * size
            normalized_by_trade_id[trade_id] = {
                "exchange": "okx",
                "dataset_type": "trade",
                "source_market_type": source_market_type,
                "instrument_name": inst,
                "instrument_type": infer_instrument_type_from_path(inst, path),
                "event_time_ms": event_time,
                "event_time_utc": ms_to_utc_iso(event_time),
                "available_time_ms": event_time,
                "available_time_utc": ms_to_utc_iso(event_time),
                "created_time_ms": event_time,
                "created_time_utc": ms_to_utc_iso(event_time),
                "exchange_date_utc8": exchange_date_utc8_from_ms(event_time),
                "source_file_date": source_file_date,
                "trade_id": trade_id,
                "side_raw": side_raw,
                "price": dec_str(price),
                "size": dec_str(size),
                "quote_volume": dec_str(quote),
                "side_semantics": "unknown_not_assumed_taker",
                "source_file_name": path.name,
                "source_file_hash": file_hash,
                "schema_version": versions.schema_version,
                "governance_version": versions.governance_version,
                "data_quality_score": "1.0",
            }

        normalized = sorted(normalized_by_trade_id.values(), key=lambda r: (int(r["event_time_ms"]), str(r["trade_id"])))
        times = [int(r["event_time_ms"]) for r in normalized]
        inst_name = sorted(instruments)[0] if len(instruments) == 1 else None
        penalties = min(25, duplicate_count) + min(25, invalid_side * 5) + min(25, invalid_price * 5 + invalid_size * 5) + min(25, out_of_order)
        score = max(0.0, 100.0 - penalties) / 100.0
        allow = bool(normalized and invalid_side == 0 and invalid_price == 0 and invalid_size == 0)
        manifest.update({
            "instrument_name": inst_name,
            "instrument_type": infer_instrument_type_from_path(inst_name or "", path) if inst_name else "multi_instrument",
            "row_count": len(rows),
            "normalized_row_count": len(normalized),
            "min_event_time_ms": min(times) if times else None,
            "max_event_time_ms": max(times) if times else None,
            "parse_status": "success",
            "zip_inner_csv": inner,
        })
        quality = TradeQuality(
            source_file_name=path.name,
            parse_status="success",
            parse_error_message=None,
            row_count=len(rows),
            normalized_row_count=len(normalized),
            missing_columns=missing,
            extra_columns=extra,
            instrument_count=len(instruments),
            min_created_time_ms=min(times) if times else None,
            max_created_time_ms=max(times) if times else None,
            min_created_time_utc=ms_to_utc_iso(min(times)) if times else None,
            max_created_time_utc=ms_to_utc_iso(max(times)) if times else None,
            duplicate_trade_id_count=duplicate_count,
            out_of_order_time_count=out_of_order,
            invalid_price_count=invalid_price,
            invalid_size_count=invalid_size,
            invalid_side_count=invalid_side,
            side_semantics="unknown_not_assumed_taker",
            allow_into_feature_aggregation=allow,
            data_quality_score=score,
        )
        return manifest, asdict(quality), normalized
    except Exception as e:
        manifest.update({"parse_status": "error", "parse_error_message": str(e)})
        quality = TradeQuality(
            source_file_name=path.name,
            parse_status="error",
            parse_error_message=str(e),
            row_count=0,
            normalized_row_count=0,
            missing_columns=[],
            extra_columns=[],
            instrument_count=0,
            min_created_time_ms=None,
            max_created_time_ms=None,
            min_created_time_utc=None,
            max_created_time_utc=None,
            duplicate_trade_id_count=0,
            out_of_order_time_count=0,
            invalid_price_count=0,
            invalid_size_count=0,
            invalid_side_count=0,
            side_semantics="unknown_not_assumed_taker",
            allow_into_feature_aggregation=False,
            data_quality_score=0.0,
        )
        return manifest, asdict(quality), []


def aggregate_trade_1m(normalized_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        event_time = int(row["event_time_ms"])
        window_start = (event_time // 60_000) * 60_000
        key = (str(row["instrument_name"]), window_start)
        buckets[key].append(row)

    features: list[dict[str, Any]] = []
    for (inst, window_start), rows in sorted(buckets.items(), key=lambda x: (x[0][1], x[0][0])):
        window_end = window_start + 60_000
        buy_rows = [r for r in rows if r["side_raw"] == "buy"]
        sell_rows = [r for r in rows if r["side_raw"] == "sell"]
        buy_volume = sum((dec(r["size"]) for r in buy_rows), Decimal("0"))
        sell_volume = sum((dec(r["size"]) for r in sell_rows), Decimal("0"))
        buy_quote = sum((dec(r["quote_volume"]) for r in buy_rows), Decimal("0"))
        sell_quote = sum((dec(r["quote_volume"]) for r in sell_rows), Decimal("0"))
        sizes = [dec(r["size"]) for r in rows]
        total_volume = buy_volume + sell_volume
        volume_delta = buy_volume - sell_volume
        volume_delta_ratio = (volume_delta / total_volume) if total_volume != 0 else None
        large_threshold = max(sizes) if sizes else Decimal("0")
        large_rows = [r for r in rows if dec(r["size"]) >= large_threshold]
        first = rows[0]
        features.append({
            "exchange": "okx",
            "dataset_type": "trade_feature",
            "source_market_type": first.get("source_market_type", "unknown"),
            "instrument_name": inst,
            "instrument_type": first.get("instrument_type", "unknown"),
            "window_interval": "1m",
            "window_start_ms": window_start,
            "window_start_utc": ms_to_utc_iso(window_start),
            "window_end_ms": window_end,
            "window_end_utc": ms_to_utc_iso(window_end),
            "feature_time_ms": window_end,
            "feature_time_utc": ms_to_utc_iso(window_end),
            "available_time_ms": window_end,
            "available_time_utc": ms_to_utc_iso(window_end),
            "trade_count_1m": len(rows),
            "buy_trade_count_1m": len(buy_rows),
            "sell_trade_count_1m": len(sell_rows),
            "buy_volume_1m": dec_str(buy_volume),
            "sell_volume_1m": dec_str(sell_volume),
            "buy_quote_volume_1m": dec_str(buy_quote),
            "sell_quote_volume_1m": dec_str(sell_quote),
            "volume_delta_1m": dec_str(volume_delta),
            "volume_delta_ratio_1m": "" if volume_delta_ratio is None else dec_str(volume_delta_ratio),
            "avg_trade_size_1m": dec_str(total_volume / Decimal(len(rows))) if rows else "0",
            "max_trade_size_1m": dec_str(max(sizes)) if sizes else "0",
            "large_trade_count_1m": len(large_rows),
            "large_trade_volume_1m": dec_str(sum((dec(r["size"]) for r in large_rows), Decimal("0"))),
            "trade_velocity_1m": dec_str(Decimal(len(rows)) / Decimal(60)),
            "side_semantics": "unknown_not_assumed_taker",
            "source_file_names": ",".join(sorted({str(r["source_file_name"]) for r in rows})),
            "schema_version": first.get("schema_version"),
            "governance_version": first.get("governance_version"),
            "feature_version": GovernanceVersions().feature_version,
            "data_quality_score": "1.0",
        })
    return features


def run_trade_minimal(root: Path, max_files: int | None = None) -> dict[str, Any]:
    source_dir = root / "okx" / "Trade"
    all_files = sorted([p for p in source_dir.rglob("*.csv") if p.is_file()])
    files = all_files[:max_files] if max_files is not None else all_files
    summary: dict[str, Any] = {"dataset_type": "trade", "source_file_count": len(files), "total_discovered_source_file_count": len(all_files), "max_files": max_files, "success_count": 0, "error_count": 0, "outputs": []}
    total_normalized = 0
    total_feature_rows = 0
    duplicate_count = 0
    for p in files:
        manifest, quality, normalized = process_trade_file(p, root)
        features = aggregate_trade_1m(normalized)
        source_date = manifest.get("source_file_date") or "unknown"
        market = manifest.get("source_market_type") or "unknown"
        inst = manifest.get("instrument_name") or "unknown"
        manifest_base = root / "manifests" / "exchange=okx" / "dataset_type=trade" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        quality_base = root / "reports" / "quality" / "exchange=okx" / "dataset_type=trade" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        normalized_base = root / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=trade" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        feature_base = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=trade_feature" / f"market={market}" / f"instrument={inst}" / "interval=1m" / f"exchange_date_utc8={source_date}"
        write_json(manifest_base / "file_manifest.json", manifest)
        write_json(quality_base / "quality_report.json", quality)
        if normalized:
            write_csv_rows(normalized_base / "trade_normalized.csv", normalized, list(normalized[0].keys()))
        if features:
            write_csv_rows(feature_base / "trade_features_1m.csv", features, list(features[0].keys()))
        summary["success_count"] += 1 if manifest["parse_status"] == "success" else 0
        summary["error_count"] += 1 if manifest["parse_status"] != "success" else 0
        total_normalized += len(normalized)
        total_feature_rows += len(features)
        duplicate_count += int(quality.get("duplicate_trade_id_count") or 0)
        summary["outputs"].append({
            "source": str(p),
            "manifest": str(manifest_base / "file_manifest.json"),
            "quality_report": str(quality_base / "quality_report.json"),
            "normalized_rows": len(normalized),
            "feature_rows_1m": len(features),
        })
    summary["total_normalized_rows"] = total_normalized
    summary["total_feature_rows_1m"] = total_feature_rows
    summary["duplicate_trade_id_count"] = duplicate_count
    summary_path = root / "reports" / "quality" / "trade_minimal_summary.json"
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary
