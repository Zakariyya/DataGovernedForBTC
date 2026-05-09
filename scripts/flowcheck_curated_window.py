from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from datagovernedforbtc.config import GovernanceVersions
from datagovernedforbtc.curated_state import build_curated_market_state_1m, load_csvs
from datagovernedforbtc.io_utils import write_csv_rows
from datagovernedforbtc.time_semantics import candle_close_time_ms, exchange_date_utc8_from_ms, ms_to_utc_iso

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = GovernanceVersions()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


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


def read_raw_candles_for_flowcheck(dates: list[date]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    quality: list[dict[str, Any]] = []
    for d in dates:
        ds = d.isoformat()
        raw = ROOT / "okx" / "Candlesticks" / "Spot" / "2024" / f"BTC-USDT-candlesticks-{ds}.csv"
        qpath = ROOT / "reports" / "quality" / "exchange=okx" / "dataset_type=candlestick" / "market=spot" / "instrument=BTC-USDT" / f"exchange_date_utc8={ds}" / "quality_report.json"
        q = json.loads(qpath.read_text(encoding="utf-8")) if qpath.exists() else {}
        quality.append({
            "date": ds,
            "raw_exists": raw.exists(),
            "quality_exists": qpath.exists(),
            "allow_into_training": q.get("allow_into_training"),
            "confirm_1_count": q.get("confirm_1_count"),
            "confirm_0_count": q.get("confirm_0_count"),
        })
        if not raw.exists():
            continue
        with raw.open("r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                ot = int(r["open_time"])
                close_ms = candle_close_time_ms(ot)
                rows.append({
                    "exchange": "okx",
                    "dataset_type": "candlestick_flowcheck",
                    "instrument_name": r["instrument_name"],
                    "instrument_type": "spot",
                    "source_market_type": "spot",
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
                    "source_file_date": ds,
                    "open": r["open"],
                    "high": r["high"],
                    "low": r["low"],
                    "close": r["close"],
                    "vol_base": r["vol"],
                    "vol_ccy": r["vol_ccy"],
                    "vol_quote": r["vol_quote"],
                    "confirm": r["confirm"],
                    "source_file_name": raw.name,
                    "schema_version": VERSIONS.schema_version,
                    "governance_version": VERSIONS.governance_version,
                    "data_quality_score": "0.8",
                    "is_filled": "false",
                    "fill_method": "none",
                    "missing_reason": "none",
                    "flowcheck_quality_flag": "raw_candle_confirm_0_not_training_admissible" if str(r["confirm"]) == "0" else "",
                })
    return rows, quality


@dataclass
class TradeDaySummary:
    date: str
    raw_exists: bool
    row_count: int = 0
    duplicate_trade_id_count: int = 0
    invalid_price_count: int = 0
    invalid_size_count: int = 0
    invalid_side_count: int = 0
    feature_rows_1m: int = 0
    min_created_time_utc: str | None = None
    max_created_time_utc: str | None = None
    output: str | None = None


def aggregate_trade_day_flowcheck(d: date) -> TradeDaySummary:
    ds = d.isoformat()
    path = ROOT / "okx" / "Trade" / "Spot" / "2024" / f"BTC-USDT-trades-{ds}.csv"
    if not path.exists():
        return TradeDaySummary(date=ds, raw_exists=False)

    seen: set[str] = set()
    duplicate_count = 0
    invalid_price = 0
    invalid_size = 0
    invalid_side = 0
    row_count = 0
    min_time: int | None = None
    max_time: int | None = None
    buckets: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "trade_count_1m": 0,
        "buy_trade_count_1m": 0,
        "sell_trade_count_1m": 0,
        "buy_volume_1m": Decimal("0"),
        "sell_volume_1m": Decimal("0"),
        "buy_quote_volume_1m": Decimal("0"),
        "sell_quote_volume_1m": Decimal("0"),
        "sizes": [],
    })

    with path.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            row_count += 1
            trade_id = str(r["trade_id"])
            if trade_id in seen:
                duplicate_count += 1
                continue
            seen.add(trade_id)
            side = str(r["side"]).strip().lower()
            if side not in {"buy", "sell"}:
                invalid_side += 1
            price = dec(r["price"])
            size = dec(r["size"])
            if price <= 0:
                invalid_price += 1
            if size <= 0:
                invalid_size += 1
            event_time = int(float(r["created_time"]))
            min_time = event_time if min_time is None else min(min_time, event_time)
            max_time = event_time if max_time is None else max(max_time, event_time)
            window_start = (event_time // 60_000) * 60_000
            bucket = buckets[window_start]
            bucket["trade_count_1m"] += 1
            bucket["sizes"].append(size)
            quote = price * size
            if side == "buy":
                bucket["buy_trade_count_1m"] += 1
                bucket["buy_volume_1m"] += size
                bucket["buy_quote_volume_1m"] += quote
            elif side == "sell":
                bucket["sell_trade_count_1m"] += 1
                bucket["sell_volume_1m"] += size
                bucket["sell_quote_volume_1m"] += quote

    features: list[dict[str, Any]] = []
    for window_start, b in sorted(buckets.items()):
        window_end = window_start + 60_000
        buy_volume = b["buy_volume_1m"]
        sell_volume = b["sell_volume_1m"]
        total_volume = buy_volume + sell_volume
        volume_delta = buy_volume - sell_volume
        volume_delta_ratio = (volume_delta / total_volume) if total_volume != 0 else None
        sizes = b["sizes"]
        max_size = max(sizes) if sizes else Decimal("0")
        large_sizes = [x for x in sizes if x >= max_size]
        features.append({
            "exchange": "okx",
            "dataset_type": "trade_feature",
            "source_market_type": "spot",
            "instrument_name": "BTC-USDT",
            "instrument_type": "spot",
            "window_interval": "1m",
            "window_start_ms": window_start,
            "window_start_utc": ms_to_utc_iso(window_start),
            "window_end_ms": window_end,
            "window_end_utc": ms_to_utc_iso(window_end),
            "feature_time_ms": window_end,
            "feature_time_utc": ms_to_utc_iso(window_end),
            "available_time_ms": window_end,
            "available_time_utc": ms_to_utc_iso(window_end),
            "trade_count_1m": b["trade_count_1m"],
            "buy_trade_count_1m": b["buy_trade_count_1m"],
            "sell_trade_count_1m": b["sell_trade_count_1m"],
            "buy_volume_1m": dec_str(buy_volume),
            "sell_volume_1m": dec_str(sell_volume),
            "buy_quote_volume_1m": dec_str(b["buy_quote_volume_1m"]),
            "sell_quote_volume_1m": dec_str(b["sell_quote_volume_1m"]),
            "volume_delta_1m": dec_str(volume_delta),
            "volume_delta_ratio_1m": "" if volume_delta_ratio is None else dec_str(volume_delta_ratio),
            "avg_trade_size_1m": dec_str(total_volume / Decimal(b["trade_count_1m"])) if b["trade_count_1m"] else "0",
            "max_trade_size_1m": dec_str(max_size),
            "large_trade_count_1m": len(large_sizes),
            "large_trade_volume_1m": dec_str(sum(large_sizes, Decimal("0"))),
            "trade_velocity_1m": dec_str(Decimal(b["trade_count_1m"]) / Decimal(60)),
            "side_semantics": "unknown_not_assumed_taker",
            "source_file_names": path.name,
            "schema_version": VERSIONS.schema_version,
            "governance_version": VERSIONS.governance_version,
            "feature_version": VERSIONS.feature_version,
            "data_quality_score": "1.0" if not (invalid_price or invalid_size or invalid_side) else "0.8",
        })

    feature_base = ROOT / "data_lake" / "features" / "exchange=okx" / "dataset_type=trade_feature" / "market=spot" / "instrument=BTC-USDT" / "interval=1m" / f"exchange_date_utc8={ds}"
    out = feature_base / "trade_features_1m.csv"
    if features:
        write_csv_rows(out, features, list(features[0].keys()))
    q = {
        "source_file_name": path.name,
        "parse_status": "success",
        "row_count": row_count,
        "feature_rows_1m": len(features),
        "duplicate_trade_id_count": duplicate_count,
        "invalid_price_count": invalid_price,
        "invalid_size_count": invalid_size,
        "invalid_side_count": invalid_side,
        "side_semantics": "unknown_not_assumed_taker",
        "allow_into_feature_aggregation": bool(features and not invalid_price and not invalid_size and not invalid_side),
        "min_created_time_utc": ms_to_utc_iso(min_time) if min_time is not None else None,
        "max_created_time_utc": ms_to_utc_iso(max_time) if max_time is not None else None,
        "flowcheck_note": "aggregated directly from raw trade without writing tick-level normalized output",
    }
    qpath = ROOT / "reports" / "quality" / "flowcheck_trade_feature" / "market=spot" / "instrument=BTC-USDT" / f"exchange_date_utc8={ds}" / "quality_report.json"
    write_json(qpath, q)
    return TradeDaySummary(
        date=ds,
        raw_exists=True,
        row_count=row_count,
        duplicate_trade_id_count=duplicate_count,
        invalid_price_count=invalid_price,
        invalid_size_count=invalid_size,
        invalid_side_count=invalid_side,
        feature_rows_1m=len(features),
        min_created_time_utc=q["min_created_time_utc"],
        max_created_time_utc=q["max_created_time_utc"],
        output=str(out),
    )


def load_window_sources(dates: list[date]):
    funding_paths = []
    borrowing_paths = []
    trade_paths = []
    for d in dates:
        ds = d.isoformat()
        fp = ROOT / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=funding_rate" / "market=perpetual" / f"exchange_date_utc8={ds}" / "funding_normalized.csv"
        bp = ROOT / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=borrowing_rate" / "market=spot" / f"exchange_date_utc8={ds}" / "borrowing_normalized.csv"
        tp = ROOT / "data_lake" / "features" / "exchange=okx" / "dataset_type=trade_feature" / "market=spot" / "instrument=BTC-USDT" / "interval=1m" / f"exchange_date_utc8={ds}" / "trade_features_1m.csv"
        if fp.exists():
            funding_paths.append(fp)
        if bp.exists():
            borrowing_paths.append(bp)
        if tp.exists():
            trade_paths.append(tp)
    return funding_paths, borrowing_paths, trade_paths


def run_flowcheck(label: str, start: date, end: date) -> dict[str, Any]:
    dates = list(daterange(start, end))
    print(f"[flowcheck] {label}: {start} -> {end}, days={len(dates)}", flush=True)
    candles, candle_quality = read_raw_candles_for_flowcheck(dates)
    print(f"[flowcheck] {label}: candle flowcheck rows={len(candles)}", flush=True)
    trade_days = []
    for d in dates:
        td = aggregate_trade_day_flowcheck(d)
        trade_days.append(td)
        print(f"[flowcheck] {label}: trade {d} rows={td.row_count} feature_1m={td.feature_rows_1m}", flush=True)

    funding_paths, borrowing_paths, trade_paths = load_window_sources(dates)
    funding = load_csvs(funding_paths)
    borrowing = load_csvs(borrowing_paths)
    trades = load_csvs(trade_paths)
    rows = build_curated_market_state_1m(candles, funding, borrowing, trades)
    out_dir = ROOT / "data_lake" / "features" / "exchange=okx" / "dataset_type=curated_btc_market_state" / "interval=1m" / f"sample=flowcheck_{label}"
    out_csv = out_dir / "curated_btc_market_state_1m.csv"
    if rows:
        write_csv_rows(out_csv, rows, list(rows[0].keys()))

    flags = Counter()
    allow = 0
    for r in rows:
        if r.get("allow_into_feature_layer") is True or str(r.get("allow_into_feature_layer")) == "True":
            allow += 1
        for flag in str(r.get("data_quality_flags", "")).split(";"):
            if flag:
                flags[flag] += 1

    trade_summary = {
        "days_processed": sum(1 for x in trade_days if x.raw_exists),
        "days_missing": [x.date for x in trade_days if not x.raw_exists],
        "total_raw_rows": sum(x.row_count for x in trade_days),
        "total_feature_rows_1m": sum(x.feature_rows_1m for x in trade_days),
        "duplicate_trade_id_count": sum(x.duplicate_trade_id_count for x in trade_days),
        "invalid_price_count": sum(x.invalid_price_count for x in trade_days),
        "invalid_size_count": sum(x.invalid_size_count for x in trade_days),
        "invalid_side_count": sum(x.invalid_side_count for x in trade_days),
        "min_feature_rows_1m_per_day": min((x.feature_rows_1m for x in trade_days if x.raw_exists), default=0),
        "max_feature_rows_1m_per_day": max((x.feature_rows_1m for x in trade_days if x.raw_exists), default=0),
        "examples": [x.__dict__ for x in (trade_days[:2] + trade_days[-2:])],
    }
    summary = {
        "flowcheck_label": label,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "days": len(dates),
        "purpose": "pipeline flowcheck only; not training admission",
        "candle_rows_used_from_raw_flowcheck": len(candles),
        "candle_confirm_0_rows": sum(int(x.get("confirm_0_count") or 0) for x in candle_quality),
        "candle_training_admission": "blocked_by_existing_candlestick_quality_confirm_0",
        "candle_quality_days_allow_into_training": sum(1 for x in candle_quality if x.get("allow_into_training") is True),
        "funding_files_used": len(funding_paths),
        "borrowing_files_used": len(borrowing_paths),
        "trade_feature_files_used": len(trade_paths),
        "trade_summary": trade_summary,
        "curated_rows": len(rows),
        "curated_allow_into_feature_layer_rows": allow,
        "curated_blocked_rows": len(rows) - allow,
        "curated_quality_flag_counts": dict(flags),
        "output_csv": str(out_csv),
        "asof_rule": "Funding/Borrowing available_time_ms <= feature_time_ms; Trade feature must match current 1m feature_time_ms",
        "not_training_reasons": [
            "candlestick confirm=0 kept as blocking quality issue",
            "curated output under sample=flowcheck_*",
            "orderbook not included; archives not reconstructed",
        ],
    }
    report = ROOT / "reports" / "quality" / f"curated_state_flowcheck_{label}_summary.json"
    write_json(report, summary)
    summary["summary_path"] = str(report)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    run_flowcheck(args.label, parse_date(args.start), parse_date(args.end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
