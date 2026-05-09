from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import write_csv_rows
from .time_semantics import ms_to_utc_iso


MAX_FUNDING_AGE_MS = 24 * 60 * 60 * 1000
MAX_BORROW_AGE_MS = 24 * 60 * 60 * 1000


def read_csv_dicts(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def as_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return int(float(value))


def asof_row(rows: list[dict[str, Any]], t: int, time_field: str = "available_time_ms") -> dict[str, Any] | None:
    candidate = None
    for row in rows:
        if as_int(row.get(time_field), -1) <= t:
            candidate = row
        else:
            break
    return candidate


def finalize_quality_gate(row: dict[str, Any]) -> None:
    """Attach a conservative, auditable quality gate to a curated 1m row."""
    flags: list[str] = []
    future_leak_violation_count = 0
    feature_time = as_int(row.get("feature_time_ms"), -1)

    funding_age = row.get("funding_age_ms")
    if funding_age == "":
        flags.append("funding_missing")
    elif as_int(funding_age) > MAX_FUNDING_AGE_MS:
        flags.append("funding_age_exceeds_max")

    for ccy in ("btc", "eth", "usdt"):
        rate_key = f"{ccy}_borrow_rate_raw"
        age_key = f"{ccy}_borrow_rate_age_ms"
        age_value = row.get(age_key)
        if row.get(rate_key) == "":
            flags.append(f"{ccy}_borrow_rate_missing")
        elif age_value != "" and as_int(age_value) > MAX_BORROW_AGE_MS:
            flags.append(f"{ccy}_borrow_rate_age_exceeds_max")

    if row.get("trade_feature_missing_reason"):
        flags.append("trade_feature_missing")
    else:
        trade_feature_time = as_int(row.get("trade_feature_time_ms"), feature_time)
        trade_age = feature_time - trade_feature_time
        if trade_age != 0:
            flags.append("trade_feature_not_current_1m")

    row["future_leak_violation_count"] = future_leak_violation_count
    row["data_quality_flags"] = ";".join(flags)
    row["missing_or_stale_source_count"] = len(flags)
    row["overall_data_quality_score"] = f"{max(0.0, 1.0 - 0.1 * len(flags) - 0.5 * future_leak_violation_count):.4f}"
    row["allow_into_feature_layer"] = future_leak_violation_count == 0 and not flags


def build_curated_market_state_1m(
    candles: list[dict[str, Any]],
    funding_rows: list[dict[str, Any]] | None = None,
    borrowing_rows: list[dict[str, Any]] | None = None,
    trade_feature_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a minimal time-causal BTC 1m market state table.

    This is intentionally simple and audit-friendly. It is not a performance-optimized
    full data engine. Every join uses available_time_ms <= candle feature_time_ms.
    """
    versions = GovernanceVersions()
    funding_rows = [r for r in (funding_rows or []) if str(r.get("instrument_name", "BTC-USDT-SWAP")) in {"", "BTC-USDT-SWAP"}]
    funding_rows = sorted(funding_rows, key=lambda r: as_int(r.get("available_time_ms"), -1))
    borrowing_rows = sorted(borrowing_rows or [], key=lambda r: (str(r.get("currency_name", "")), as_int(r.get("available_time_ms"), -1)))
    trade_feature_rows = sorted(trade_feature_rows or [], key=lambda r: as_int(r.get("available_time_ms"), -1))
    candles_sorted = sorted(candles, key=lambda r: as_int(r.get("available_time_ms") or r.get("close_time_ms"), -1))

    borrow_by_currency: dict[str, list[dict[str, Any]]] = {}
    for row in borrowing_rows:
        borrow_by_currency.setdefault(str(row.get("currency_name", "")).upper(), []).append(row)

    output: list[dict[str, Any]] = []
    for candle in candles_sorted:
        feature_time = as_int(candle.get("close_time_ms") or candle.get("available_time_ms"))
        funding = asof_row(funding_rows, feature_time)
        trade = asof_row(trade_feature_rows, feature_time)
        row: dict[str, Any] = {
            "exchange": candle.get("exchange", "okx"),
            "instrument_name": candle.get("instrument_name", "BTC-USDT"),
            "source_market_type": candle.get("source_market_type", "unknown"),
            "feature_time_ms": feature_time,
            "feature_time_utc": ms_to_utc_iso(feature_time),
            "available_time_ms": feature_time,
            "available_time_utc": ms_to_utc_iso(feature_time),
            "open": candle.get("open", ""),
            "high": candle.get("high", ""),
            "low": candle.get("low", ""),
            "close": candle.get("close", ""),
            "vol_base": candle.get("vol_base", ""),
            "vol_quote": candle.get("vol_quote", ""),
            "candle_quality_score": candle.get("data_quality_score", ""),
            "last_realized_funding_rate": "",
            "funding_age_ms": "",
            "funding_interval_ms": "",
            "funding_quality_score": "",
            "btc_borrow_rate_raw": "",
            "btc_borrow_rate_age_ms": "",
            "eth_borrow_rate_raw": "",
            "eth_borrow_rate_age_ms": "",
            "usdt_borrow_rate_raw": "",
            "usdt_borrow_rate_age_ms": "",
            "borrow_quality_score": "",
            "trade_count_1m": "",
            "buy_volume_1m": "",
            "sell_volume_1m": "",
            "volume_delta_1m": "",
            "volume_delta_ratio_1m": "",
            "trade_feature_missing_reason": "",
            "trade_feature_time_ms": "",
            "trade_quality_score": "",
            "future_leak_violation_count": 0,
            "data_quality_flags": "",
            "missing_or_stale_source_count": 0,
            "overall_data_quality_score": "",
            "allow_into_feature_layer": False,
            "schema_version": candle.get("schema_version", versions.schema_version),
            "feature_version": versions.feature_version,
            "governance_version": candle.get("governance_version", versions.governance_version),
        }
        if funding is not None:
            funding_time = as_int(funding.get("available_time_ms"), feature_time)
            row.update({
                "last_realized_funding_rate": funding.get("realized_funding_rate", ""),
                "funding_age_ms": feature_time - funding_time,
                "funding_interval_ms": funding.get("funding_interval_ms", ""),
                "funding_quality_score": funding.get("data_quality_score", ""),
            })
        for ccy in ("BTC", "ETH", "USDT"):
            b = asof_row(borrow_by_currency.get(ccy, []), feature_time)
            if b is not None:
                b_time = as_int(b.get("available_time_ms"), feature_time)
                row[f"{ccy.lower()}_borrow_rate_raw"] = b.get("borrow_rate_raw", "")
                row[f"{ccy.lower()}_borrow_rate_age_ms"] = feature_time - b_time
                row["borrow_quality_score"] = b.get("data_quality_score", row.get("borrow_quality_score", ""))
        if trade is not None and as_int(trade.get("feature_time_ms") or trade.get("available_time_ms"), -1) == feature_time:
            row.update({
                "trade_count_1m": trade.get("trade_count_1m", ""),
                "buy_volume_1m": trade.get("buy_volume_1m", ""),
                "sell_volume_1m": trade.get("sell_volume_1m", ""),
                "volume_delta_1m": trade.get("volume_delta_1m", ""),
                "volume_delta_ratio_1m": trade.get("volume_delta_ratio_1m", ""),
                "trade_feature_time_ms": trade.get("feature_time_ms") or trade.get("available_time_ms", ""),
                "trade_quality_score": trade.get("data_quality_score", ""),
            })
        else:
            row["trade_feature_missing_reason"] = "no_current_trade_feature"
        finalize_quality_gate(row)
        output.append(row)
    return output


def load_csvs(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in paths:
        rows.extend(read_csv_dicts(p))
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_curated_state_minimal(root: Path, max_candle_files: int = 1, max_trade_files: int = 1) -> dict[str, Any]:
    candle_paths = sorted((root / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=candlestick").rglob("candlestick_normalized.csv"))
    funding_paths = sorted((root / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=funding_rate").rglob("funding_normalized.csv"))
    borrowing_paths = sorted((root / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=borrowing_rate").rglob("borrowing_normalized.csv"))
    trade_paths = sorted((root / "data_lake" / "features" / "exchange=okx" / "dataset_type=trade_feature").rglob("trade_features_1m.csv"))

    selected_candle_paths = candle_paths[-max_candle_files:] if max_candle_files is not None else candle_paths
    selected_trade_paths = trade_paths[:max_trade_files] if max_trade_files is not None else trade_paths
    candles = load_csvs(selected_candle_paths)
    funding = load_csvs(funding_paths)
    borrowing = load_csvs(borrowing_paths)
    trades = load_csvs(selected_trade_paths)
    rows = build_curated_market_state_1m(candles, funding, borrowing, trades)

    out_dir = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=curated_btc_market_state" / "interval=1m" / "sample=minimal"
    out_path = out_dir / "curated_btc_market_state_1m.csv"
    if rows:
        write_csv_rows(out_path, rows, list(rows[0].keys()))
    summary = {
        "dataset_type": "curated_btc_market_state_1m",
        "candle_files_used": len(selected_candle_paths),
        "candle_files_selected": [str(p) for p in selected_candle_paths],
        "funding_files_used": len(funding_paths),
        "borrowing_files_used": len(borrowing_paths),
        "trade_feature_files_used": len(selected_trade_paths),
        "row_count": len(rows),
        "output": str(out_path) if rows else None,
        "asof_rule": "join only rows with available_time_ms <= feature_time_ms; trade feature must match current 1m feature_time_ms",
    }
    summary_path = root / "reports" / "quality" / "curated_state_minimal_summary.json"
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary
