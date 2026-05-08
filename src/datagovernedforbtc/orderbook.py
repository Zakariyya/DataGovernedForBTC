from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import sha256_file, write_csv_rows
from .path_semantics import infer_instrument_type_from_path, infer_source_market_type
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
    s = format(value.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def depth_sum(levels: list[list[Any]], n: int) -> Decimal:
    total = Decimal("0")
    for lvl in levels[:n]:
        if len(lvl) >= 2:
            total += dec(lvl[1])
    return total


def order_count_sum(levels: list[list[Any]], n: int) -> int:
    total = 0
    for lvl in levels[:n]:
        if len(lvl) >= 3:
            total += int(dec(lvl[2]))
    return total


def sorted_book_sides(asks: list[list[Any]], bids: list[list[Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    asks_sorted = sorted(asks, key=lambda x: dec(x[0]))
    bids_sorted = sorted(bids, key=lambda x: dec(x[0]), reverse=True)
    return asks_sorted, bids_sorted


@dataclass
class OrderbookQuality:
    source_file_name: str
    parse_status: str
    parse_error_message: str | None
    sampled_line_count: int
    row_count_observed: int
    instrument_count: int
    min_ts_ms: int | None
    max_ts_ms: int | None
    min_ts_utc: str | None
    max_ts_utc: str | None
    snapshot_count: int
    update_count: int
    update_without_snapshot_count: int
    empty_asks_count: int
    empty_bids_count: int
    crossed_book_count: int
    min_ask_depth_levels: int | None
    min_bid_depth_levels: int | None
    max_ask_depth_levels: int | None
    max_bid_depth_levels: int | None
    depth_400_complete_count: int
    parse_json_error_count: int
    book_reconstruction_quality: str
    allow_into_feature_layer: bool
    data_quality_score: float


def feature_from_snapshot(row: dict[str, Any], path: Path, file_hash: str, versions: GovernanceVersions, quality_label: str) -> dict[str, Any] | None:
    asks_raw = row.get("asks") or []
    bids_raw = row.get("bids") or []
    if not asks_raw or not bids_raw:
        return None
    asks, bids = sorted_book_sides(asks_raw, bids_raw)
    best_ask = dec(asks[0][0])
    best_bid = dec(bids[0][0])
    mid = (best_bid + best_ask) / Decimal("2")
    spread = best_ask - best_bid
    ts = int(float(row["ts"]))
    inst = row.get("instId") or "unknown"
    top20_bid = depth_sum(bids, 20)
    top20_ask = depth_sum(asks, 20)
    denom = top20_bid + top20_ask
    imbalance = None if denom == 0 else (top20_bid - top20_ask) / denom
    return {
        "exchange": "okx",
        "dataset_type": "orderbook_sample_feature",
        "source_market_type": infer_source_market_type(path),
        "instrument_name": inst,
        "instrument_type": infer_instrument_type_from_path(inst, path),
        "event_time_ms": ts,
        "event_time_utc": ms_to_utc_iso(ts),
        "feature_time_ms": ts,
        "feature_time_utc": ms_to_utc_iso(ts),
        "available_time_ms": ts,
        "available_time_utc": ms_to_utc_iso(ts),
        "exchange_date_utc8": exchange_date_utc8_from_ms(ts),
        "best_bid": dec_str(best_bid),
        "best_ask": dec_str(best_ask),
        "mid_price": dec_str(mid),
        "spread_abs": dec_str(spread),
        "spread_pct": dec_str(spread / mid) if mid != 0 else "",
        "top5_bid_depth": dec_str(depth_sum(bids, 5)),
        "top5_ask_depth": dec_str(depth_sum(asks, 5)),
        "top20_bid_depth": dec_str(top20_bid),
        "top20_ask_depth": dec_str(top20_ask),
        "top20_depth_imbalance": "" if imbalance is None else dec_str(imbalance),
        "bid_order_count_top20": order_count_sum(bids, 20),
        "ask_order_count_top20": order_count_sum(asks, 20),
        "ask_depth_levels": len(asks),
        "bid_depth_levels": len(bids),
        "is_crossed_book": str(best_bid >= best_ask).lower(),
        "book_reconstruction_quality": quality_label,
        "source_file_name": path.name,
        "source_file_hash": file_hash,
        "schema_version": versions.schema_version,
        "governance_version": versions.governance_version,
        "feature_version": versions.feature_version,
        "data_quality_score": "1.0" if best_bid < best_ask else "0.0",
    }


def process_orderbook_file(path: Path, root: Path, max_lines: int | None = 5000) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    source_file_date = source_file_date_from_name(path.name)
    source_market_type = infer_source_market_type(path)
    manifest: dict[str, Any] = {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_file_hash": file_hash,
        "dataset_type": "orderbook",
        "source_market_type": source_market_type,
        "exchange": "okx",
        "instrument_name": None,
        "instrument_type": None,
        "source_file_date": source_file_date,
        "exchange_date_utc8": source_file_date,
        "row_count": 0,
        "sampled_line_count": 0,
        "min_event_time_ms": None,
        "max_event_time_ms": None,
        "schema_version": versions.schema_version,
        "governance_version": versions.governance_version,
        "parse_status": "unknown",
        "parse_error_message": None,
        "max_lines": max_lines,
    }
    try:
        snapshot_seen: set[str] = set()
        instruments: set[str] = set()
        times: list[int] = []
        snapshot_count = 0
        update_count = 0
        update_without_snapshot = 0
        empty_asks = 0
        empty_bids = 0
        crossed = 0
        depth_400 = 0
        ask_depths: list[int] = []
        bid_depths: list[int] = []
        parse_errors = 0
        sampled = 0
        features: list[dict[str, Any]] = []

        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if max_lines is not None and sampled >= max_lines:
                    break
                sampled += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                inst = row.get("instId") or "unknown"
                instruments.add(inst)
                action = row.get("action")
                ts = int(float(row.get("ts")))
                times.append(ts)
                asks = row.get("asks") or []
                bids = row.get("bids") or []
                ask_depths.append(len(asks))
                bid_depths.append(len(bids))
                if not asks:
                    empty_asks += 1
                if not bids:
                    empty_bids += 1
                if len(asks) >= 400 and len(bids) >= 400:
                    depth_400 += 1
                if action == "snapshot" and asks and bids:
                    asks_sorted, bids_sorted = sorted_book_sides(asks, bids)
                    if dec(bids_sorted[0][0]) >= dec(asks_sorted[0][0]):
                        crossed += 1
                if action == "snapshot":
                    snapshot_count += 1
                    snapshot_seen.add(inst)
                    feat = feature_from_snapshot(row, path, file_hash, versions, "snapshot_only_sample")
                    if feat is not None:
                        features.append(feat)
                elif action == "update":
                    update_count += 1
                    if inst not in snapshot_seen:
                        update_without_snapshot += 1
                else:
                    # Unknown actions are treated as parse-quality issues but not fatal.
                    parse_errors += 1

        if snapshot_count == 0:
            reconstruction_quality = "unusable_no_snapshot"
        elif update_without_snapshot > 0:
            reconstruction_quality = "partial_snapshot_with_orphan_updates"
        else:
            reconstruction_quality = "snapshot_only_sample"
        penalties = min(30, parse_errors * 5) + min(30, crossed * 5) + min(20, update_without_snapshot * 5) + min(20, empty_asks + empty_bids)
        score = max(0.0, 100.0 - penalties) / 100.0
        allow = bool(snapshot_count > 0 and crossed == 0 and parse_errors == 0)
        inst_name = sorted(instruments)[0] if len(instruments) == 1 else None
        manifest.update({
            "instrument_name": inst_name,
            "instrument_type": infer_instrument_type_from_path(inst_name or "", path) if inst_name else "multi_instrument",
            "row_count": sampled,
            "sampled_line_count": sampled,
            "min_event_time_ms": min(times) if times else None,
            "max_event_time_ms": max(times) if times else None,
            "parse_status": "success",
        })
        quality = OrderbookQuality(
            source_file_name=path.name,
            parse_status="success",
            parse_error_message=None,
            sampled_line_count=sampled,
            row_count_observed=sampled,
            instrument_count=len(instruments),
            min_ts_ms=min(times) if times else None,
            max_ts_ms=max(times) if times else None,
            min_ts_utc=ms_to_utc_iso(min(times)) if times else None,
            max_ts_utc=ms_to_utc_iso(max(times)) if times else None,
            snapshot_count=snapshot_count,
            update_count=update_count,
            update_without_snapshot_count=update_without_snapshot,
            empty_asks_count=empty_asks,
            empty_bids_count=empty_bids,
            crossed_book_count=crossed,
            min_ask_depth_levels=min(ask_depths) if ask_depths else None,
            min_bid_depth_levels=min(bid_depths) if bid_depths else None,
            max_ask_depth_levels=max(ask_depths) if ask_depths else None,
            max_bid_depth_levels=max(bid_depths) if bid_depths else None,
            depth_400_complete_count=depth_400,
            parse_json_error_count=parse_errors,
            book_reconstruction_quality=reconstruction_quality,
            allow_into_feature_layer=allow,
            data_quality_score=score,
        )
        return manifest, asdict(quality), features
    except Exception as e:
        manifest.update({"parse_status": "error", "parse_error_message": str(e)})
        q = OrderbookQuality(path.name, "error", str(e), 0, 0, 0, None, None, None, None, 0, 0, 0, 0, 0, 0, None, None, None, None, 0, 0, "unusable_parse_error", False, 0.0)
        return manifest, asdict(q), []


def run_orderbook_audit(root: Path, max_lines: int | None = 5000, max_files: int | None = None) -> dict[str, Any]:
    source_dir = root / "okx" / "Orderbook"
    all_files = sorted([p for p in source_dir.rglob("*") if p.is_file() and (p.name.endswith(".data") or p.name.endswith(".data.txt"))])
    files = all_files[:max_files] if max_files is not None else all_files
    summary: dict[str, Any] = {
        "dataset_type": "orderbook",
        "source_file_count": len(files),
        "total_discovered_source_file_count": len(all_files),
        "max_files": max_files,
        "max_lines": max_lines,
        "success_count": 0,
        "error_count": 0,
        "sample_feature_rows": 0,
        "outputs": [],
    }
    for p in files:
        manifest, quality, features = process_orderbook_file(p, root, max_lines=max_lines)
        source_date = manifest.get("source_file_date") or "unknown"
        market = manifest.get("source_market_type") or "unknown"
        inst = manifest.get("instrument_name") or "unknown"
        manifest_base = root / "manifests" / "exchange=okx" / "dataset_type=orderbook" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        quality_base = root / "reports" / "quality" / "exchange=okx" / "dataset_type=orderbook" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        feature_base = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=orderbook_sample_feature" / f"market={market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        write_json(manifest_base / "file_manifest.json", manifest)
        write_json(quality_base / "quality_report.json", quality)
        if features:
            write_csv_rows(feature_base / "orderbook_sample_features.csv", features, list(features[0].keys()))
        summary["success_count"] += 1 if manifest["parse_status"] == "success" else 0
        summary["error_count"] += 1 if manifest["parse_status"] != "success" else 0
        summary["sample_feature_rows"] += len(features)
        summary["outputs"].append({
            "source": str(p),
            "manifest": str(manifest_base / "file_manifest.json"),
            "quality_report": str(quality_base / "quality_report.json"),
            "sample_feature_rows": len(features),
            "book_reconstruction_quality": quality.get("book_reconstruction_quality"),
            "crossed_book_count": quality.get("crossed_book_count"),
            "update_without_snapshot_count": quality.get("update_without_snapshot_count"),
        })
    summary_path = root / "reports" / "quality" / "orderbook_audit_summary.json"
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary
