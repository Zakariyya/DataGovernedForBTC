from __future__ import annotations

import json
import re
import tarfile
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

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



def iter_orderbook_jsonl_lines(path: Path) -> Iterator[str]:
    """Yield JSONL rows from a raw .data file or a single-member OKX tar archive.

    Raw archives are read streaming-only; members are not extracted to disk.
    """
    if path.name.endswith(".data") or path.name.endswith(".data.txt"):
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line
        return
    if path.name.endswith(".tar.gz") or path.name.endswith(".tar.tar"):
        # OKX historical archives seen locally use both .tar.gz and .tar.tar
        # names; .tar.tar may still contain a gzip-compressed tar payload.
        # Use auto-detection and stream members without extracting to disk.
        with tarfile.open(path, "r:*") as tar:
            members = [m for m in tar if m.isfile()]
            for member in members:
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                for raw in extracted:
                    yield raw.decode("utf-8", errors="replace")
        return
    raise ValueError(f"unsupported orderbook source file: {path}")


def apply_book_update(book: dict[str, Decimal], levels: list[list[Any]]) -> None:
    for lvl in levels:
        if len(lvl) < 2:
            continue
        price = dec(lvl[0])
        size = dec(lvl[1])
        key = dec_str(price)
        if size == 0:
            book.pop(key, None)
        else:
            book[key] = size


def book_levels_from_map(book: dict[str, Decimal], reverse: bool = False) -> list[list[Any]]:
    prices = sorted((dec(p) for p in book.keys()), reverse=reverse)
    return [[dec_str(price), dec_str(book[dec_str(price)]), ""] for price in prices]


def minute_end_ms(ts_ms: int) -> int:
    return ((ts_ms // 60000) + 1) * 60000


def feature_from_book_state(
    *,
    path: Path,
    file_hash: str,
    versions: GovernanceVersions,
    inst: str,
    event_time_ms: int,
    feature_time_ms: int,
    bids_book: dict[str, Decimal],
    asks_book: dict[str, Decimal],
    update_count: int,
    snapshot_count: int,
    crossed_count: int,
    quality_label: str,
) -> dict[str, Any] | None:
    asks = book_levels_from_map(asks_book, reverse=False)
    bids = book_levels_from_map(bids_book, reverse=True)
    if not asks or not bids:
        return None
    best_ask = dec(asks[0][0])
    best_bid = dec(bids[0][0])
    mid = (best_bid + best_ask) / Decimal("2")
    spread = best_ask - best_bid
    top20_bid = depth_sum(bids, 20)
    top20_ask = depth_sum(asks, 20)
    denom = top20_bid + top20_ask
    imbalance = None if denom == 0 else (top20_bid - top20_ask) / denom
    is_crossed = best_bid >= best_ask
    score = "0.0" if is_crossed or crossed_count else "1.0"
    return {
        "exchange": "okx",
        "dataset_type": "orderbook_feature",
        "source_market_type": infer_source_market_type(path),
        "instrument_name": inst,
        "instrument_type": infer_instrument_type_from_path(inst, path),
        "event_time_ms": event_time_ms,
        "event_time_utc": ms_to_utc_iso(event_time_ms),
        "feature_time_ms": feature_time_ms,
        "feature_time_utc": ms_to_utc_iso(feature_time_ms),
        "available_time_ms": feature_time_ms,
        "available_time_utc": ms_to_utc_iso(feature_time_ms),
        "exchange_date_utc8": exchange_date_utc8_from_ms(event_time_ms),
        "best_bid_last": dec_str(best_bid),
        "best_ask_last": dec_str(best_ask),
        "mid_price_last": dec_str(mid),
        "spread_abs_last": dec_str(spread),
        "spread_pct_last": dec_str(spread / mid) if mid != 0 else "",
        "top5_bid_depth_last": dec_str(depth_sum(bids, 5)),
        "top5_ask_depth_last": dec_str(depth_sum(asks, 5)),
        "top20_bid_depth_last": dec_str(top20_bid),
        "top20_ask_depth_last": dec_str(top20_ask),
        "top20_depth_imbalance_last": "" if imbalance is None else dec_str(imbalance),
        "orderbook_update_count_1m": update_count,
        "orderbook_snapshot_count_1m": snapshot_count,
        "is_crossed_book_last": str(is_crossed).lower(),
        "crossed_book_count_1m": crossed_count,
        "book_reconstruction_quality": quality_label,
        "source_file_name": path.name,
        "source_file_hash": file_hash,
        "schema_version": versions.schema_version,
        "governance_version": versions.governance_version,
        "feature_version": versions.feature_version,
        "orderbook_quality_score": score,
    }


def fmt_num(value: float) -> str:
    s = (f"{value:.12f}").rstrip("0").rstrip(".")
    return s or "0"


def process_orderbook_minute_feature_file(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = GovernanceVersions()
    file_hash = sha256_file(path)
    source_file_date = source_file_date_from_name(path.name)
    source_market_type = infer_source_market_type(path)
    manifest: dict[str, Any] = {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_file_hash": file_hash,
        "dataset_type": "orderbook_feature",
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
        bids_book: dict[float, float] = {}
        asks_book: dict[float, float] = {}
        has_snapshot = False
        instruments: set[str] = set()
        min_ts: int | None = None
        max_ts: int | None = None
        features: list[dict[str, Any]] = []
        current_minute: int | None = None
        minute_update_count = 0
        minute_snapshot_count = 0
        last_event_time: int | None = None
        snapshot_count = 0
        update_count = 0
        update_without_snapshot = 0
        parse_errors = 0
        crossed_total = 0
        row_count = 0
        quality_label = "best_effort_reconstructed_without_sequence_checksum"

        def apply_float_update(book: dict[float, float], levels: list[list[Any]]) -> None:
            for lvl in levels:
                if len(lvl) < 2:
                    continue
                price = float(lvl[0])
                size = float(lvl[1])
                if size == 0.0:
                    book.pop(price, None)
                else:
                    book[price] = size

        def flush() -> None:
            nonlocal minute_update_count, minute_snapshot_count, current_minute, last_event_time, crossed_total
            if current_minute is None or last_event_time is None or not has_snapshot or not asks_book or not bids_book:
                return
            inst = sorted(instruments)[0] if instruments else "unknown"
            best_ask = min(asks_book)
            best_bid = max(bids_book)
            is_crossed = best_bid >= best_ask
            crossed_count = 1 if is_crossed else 0
            crossed_total += crossed_count
            mid = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            bid_prices = sorted(bids_book.keys(), reverse=True)
            ask_prices = sorted(asks_book.keys())
            top5_bid = sum(bids_book[p] for p in bid_prices[:5])
            top5_ask = sum(asks_book[p] for p in ask_prices[:5])
            top20_bid = sum(bids_book[p] for p in bid_prices[:20])
            top20_ask = sum(asks_book[p] for p in ask_prices[:20])
            denom = top20_bid + top20_ask
            imbalance = "" if denom == 0 else fmt_num((top20_bid - top20_ask) / denom)
            features.append({
                "exchange": "okx",
                "dataset_type": "orderbook_feature",
                "source_market_type": infer_source_market_type(path),
                "instrument_name": inst,
                "instrument_type": infer_instrument_type_from_path(inst, path),
                "event_time_ms": last_event_time,
                "event_time_utc": ms_to_utc_iso(last_event_time),
                "feature_time_ms": current_minute,
                "feature_time_utc": ms_to_utc_iso(current_minute),
                "available_time_ms": current_minute,
                "available_time_utc": ms_to_utc_iso(current_minute),
                "exchange_date_utc8": exchange_date_utc8_from_ms(last_event_time),
                "best_bid_last": fmt_num(best_bid),
                "best_ask_last": fmt_num(best_ask),
                "mid_price_last": fmt_num(mid),
                "spread_abs_last": fmt_num(spread),
                "spread_pct_last": fmt_num(spread / mid) if mid != 0 else "",
                "top5_bid_depth_last": fmt_num(top5_bid),
                "top5_ask_depth_last": fmt_num(top5_ask),
                "top20_bid_depth_last": fmt_num(top20_bid),
                "top20_ask_depth_last": fmt_num(top20_ask),
                "top20_depth_imbalance_last": imbalance,
                "orderbook_update_count_1m": minute_update_count,
                "orderbook_snapshot_count_1m": minute_snapshot_count,
                "is_crossed_book_last": str(is_crossed).lower(),
                "crossed_book_count_1m": crossed_count,
                "book_reconstruction_quality": quality_label,
                "source_file_name": path.name,
                "source_file_hash": file_hash,
                "schema_version": versions.schema_version,
                "governance_version": versions.governance_version,
                "feature_version": versions.feature_version,
                "orderbook_quality_score": "0.0" if is_crossed else "1.0",
            })
            minute_update_count = 0
            minute_snapshot_count = 0

        for line in iter_orderbook_jsonl_lines(path):
            row_count += 1
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                ts = int(float(row.get("ts")))
            except Exception:
                parse_errors += 1
                continue
            inst = row.get("instId") or "unknown"
            instruments.add(inst)
            min_ts = ts if min_ts is None else min(min_ts, ts)
            max_ts = ts if max_ts is None else max(max_ts, ts)
            m_end = minute_end_ms(ts)
            if current_minute is None:
                current_minute = m_end
            elif m_end != current_minute:
                flush()
                current_minute = m_end
            action = row.get("action")
            asks = row.get("asks") or []
            bids = row.get("bids") or []
            if action == "snapshot":
                asks_book = {float(lvl[0]): float(lvl[1]) for lvl in asks if len(lvl) >= 2 and float(lvl[1]) != 0.0}
                bids_book = {float(lvl[0]): float(lvl[1]) for lvl in bids if len(lvl) >= 2 and float(lvl[1]) != 0.0}
                has_snapshot = True
                snapshot_count += 1
                minute_snapshot_count += 1
            elif action == "update":
                update_count += 1
                minute_update_count += 1
                if not has_snapshot:
                    update_without_snapshot += 1
                    continue
                apply_float_update(asks_book, asks)
                apply_float_update(bids_book, bids)
            else:
                parse_errors += 1
                continue
            last_event_time = ts
        flush()
        inst_name = sorted(instruments)[0] if len(instruments) == 1 else None
        manifest.update({
            "instrument_name": inst_name,
            "instrument_type": infer_instrument_type_from_path(inst_name or "", path) if inst_name else "multi_instrument",
            "row_count": row_count,
            "min_event_time_ms": min_ts,
            "max_event_time_ms": max_ts,
            "parse_status": "success",
        })
        allow = bool(snapshot_count > 0 and features and parse_errors == 0 and crossed_total == 0)
        quality = {
            "source_file_name": path.name,
            "parse_status": "success",
            "parse_error_message": None,
            "row_count_observed": row_count,
            "instrument_count": len(instruments),
            "min_ts_ms": min_ts,
            "max_ts_ms": max_ts,
            "min_ts_utc": ms_to_utc_iso(min_ts) if min_ts is not None else None,
            "max_ts_utc": ms_to_utc_iso(max_ts) if max_ts is not None else None,
            "snapshot_count": snapshot_count,
            "update_count": update_count,
            "update_without_snapshot_count": update_without_snapshot,
            "minute_feature_rows": len(features),
            "crossed_book_count": crossed_total,
            "parse_json_error_count": parse_errors,
            "book_reconstruction_quality": quality_label if snapshot_count else "unusable_no_snapshot",
            "sequence_checksum_available": False,
            "allow_into_feature_layer": allow,
            "data_quality_score": 1.0 if allow else 0.0,
        }
        return manifest, quality, features
    except Exception as e:
        manifest.update({"parse_status": "error", "parse_error_message": str(e)})
        q = {"source_file_name": path.name, "parse_status": "error", "parse_error_message": str(e), "book_reconstruction_quality": "unusable_parse_error", "allow_into_feature_layer": False, "data_quality_score": 0.0}
        return manifest, q, []

def select_orderbook_source_files(root: Path, start_date: str | None = None, end_date: str | None = None, market: str | None = None, instrument: str | None = None, max_files: int | None = None) -> list[Path]:
    source_dir = root / "okx" / "Orderbook"
    suffixes = (".data", ".data.txt", ".tar.gz", ".tar.tar")
    files = sorted([p for p in source_dir.rglob("*") if p.is_file() and p.name.endswith(suffixes)])
    selected: list[Path] = []
    seen: set[tuple[str, str, str]] = set()
    for p in files:
        source_date = source_file_date_from_name(p.name)
        if start_date is not None and (source_date is None or source_date < start_date):
            continue
        if end_date is not None and (source_date is None or source_date > end_date):
            continue
        src_market = infer_source_market_type(p)
        if market is not None and src_market != market:
            continue
        if instrument is not None and not p.name.startswith(instrument):
            continue
        key = (src_market, instrument or p.name.split("-L2orderbook", 1)[0], source_date or "unknown")
        if key in seen:
            # Prefer the first lexicographic path to avoid duplicate .tar.gz/.tar.tar source copies.
            continue
        seen.add(key)
        selected.append(p)
    return selected[:max_files] if max_files is not None else selected


def run_orderbook_minute_features(root: Path, start_date: str | None = None, end_date: str | None = None, market: str | None = None, instrument: str | None = None, max_files: int | None = None) -> dict[str, Any]:
    files = select_orderbook_source_files(root, start_date=start_date, end_date=end_date, market=market, instrument=instrument, max_files=max_files)
    summary: dict[str, Any] = {
        "dataset_type": "orderbook_feature",
        "start_date": start_date,
        "end_date": end_date,
        "market": market,
        "instrument": instrument,
        "source_file_count": len(files),
        "success_count": 0,
        "error_count": 0,
        "minute_feature_rows": 0,
        "outputs": [],
    }
    for p in files:
        manifest, quality, features = process_orderbook_minute_feature_file(p, root)
        source_date = manifest.get("source_file_date") or "unknown"
        out_market = manifest.get("source_market_type") or "unknown"
        inst = manifest.get("instrument_name") or instrument or "unknown"
        manifest_base = root / "manifests" / "exchange=okx" / "dataset_type=orderbook_feature" / f"market={out_market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        quality_base = root / "reports" / "quality" / "exchange=okx" / "dataset_type=orderbook_feature" / f"market={out_market}" / f"instrument={inst}" / f"exchange_date_utc8={source_date}"
        feature_base = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=orderbook_feature" / f"market={out_market}" / f"instrument={inst}" / "interval=1m" / f"exchange_date_utc8={source_date}"
        write_json(manifest_base / "file_manifest.json", manifest)
        write_json(quality_base / "quality_report.json", quality)
        feature_path = feature_base / "orderbook_features_1m.csv"
        if features:
            write_csv_rows(feature_path, features, list(features[0].keys()))
        summary["success_count"] += 1 if manifest["parse_status"] == "success" else 0
        summary["error_count"] += 1 if manifest["parse_status"] != "success" else 0
        summary["minute_feature_rows"] += len(features)
        summary["outputs"].append({
            "source": str(p),
            "manifest": str(manifest_base / "file_manifest.json"),
            "quality_report": str(quality_base / "quality_report.json"),
            "features": str(feature_path) if features else None,
            "minute_feature_rows": len(features),
            "book_reconstruction_quality": quality.get("book_reconstruction_quality"),
            "allow_into_feature_layer": quality.get("allow_into_feature_layer"),
        })
    summary_path = root / "reports" / "quality" / "orderbook_minute_features_summary.json"
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary


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
