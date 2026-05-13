from __future__ import annotations

import csv
import json
import math
import bisect
from pathlib import Path
from typing import Any

from .io_utils import write_csv_rows
from .curated_state import as_float, as_int, is_true, read_csv_dicts


CONTEXT_CONTRACT = "not_alpha_signal_not_level2_not_allow_paper"


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def _fmt(value: float | int | bool | str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if math.isnan(value) or math.isinf(value):
        return ""
    return f"{value:.10g}"


def _returns(closes: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        out.append(_safe_div(closes[i] - prev, prev))
    return out


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _causal_percentile_series(values: list[float], lookback: int = 1440) -> list[float]:
    ranked: list[float] = []
    out: list[float] = []
    for i, value in enumerate(values):
        bisect.insort(ranked, value)
        if i > lookback:
            old = values[i - lookback - 1]
            pos = bisect.bisect_left(ranked, old)
            if pos < len(ranked):
                ranked.pop(pos)
        out.append(bisect.bisect_right(ranked, value) / len(ranked) if ranked else 0.0)
    return out


def _rolling_std_series(values: list[float], window: int) -> list[float]:
    out: list[float] = []
    sum_v = 0.0
    sum_sq = 0.0
    q: list[float] = []
    for value in values:
        q.append(value)
        sum_v += value
        sum_sq += value * value
        if len(q) > window:
            old = q.pop(0)
            sum_v -= old
            sum_sq -= old * old
        n = len(q)
        if n < 2:
            out.append(0.0)
        else:
            variance = max(0.0, (sum_sq - (sum_v * sum_v / n)) / (n - 1))
            out.append(math.sqrt(variance))
    return out


def _percentile_rank_causal(history: list[float], value: float) -> float:
    if not history:
        return 0.0
    return sum(1 for v in history if v <= value) / len(history)


def _flag_list(value: Any) -> list[str]:
    return [v for v in str(value or "").split(";") if v]


def _join_flags(flags: list[str]) -> str:
    seen: list[str] = []
    for flag in flags:
        if flag and flag not in seen:
            seen.append(flag)
    return ";".join(seen)


def _slippage_bucket(spread_bps: float, unreliable: bool) -> str:
    if unreliable:
        return "unreliable"
    if spread_bps <= 2:
        return "low"
    if spread_bps <= 10:
        return "medium"
    return "high"


def _blocked_reason_codes(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for flag in _flag_list(row.get("data_quality_flags")):
        mapping = {
            "trade_feature_missing": "trade_feature_missing",
            "trade_feature_not_current_1m": "trade_feature_stale",
            "orderbook_feature_missing": "orderbook_feature_missing",
            "orderbook_feature_not_current_1m": "orderbook_stale",
            "orderbook_crossed_book": "crossed_book_flag",
            "funding_missing": "funding_missing",
            "funding_age_exceeds_max": "funding_stale",
            "source_1m_quality_blocked": "source_1m_quality_blocked",
            "source_1m_future_leak_violation": "future_leak_violation",
        }
        reasons.append(mapping.get(flag, flag))
    if as_int(row.get("future_leak_violation_count"), 0) > 0:
        reasons.append("future_leak_violation")
    if not is_true(row.get("allow_into_feature_layer")) and not reasons:
        reasons.append("unspecified_quality_block")
    return reasons


def enrich_stage46_contexts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add Stage46 market-state context columns using only current/past rows.

    The outputs are governance inputs for AlphaTenant opportunity/regime/cost/tail
    research. They are explicitly not trade signals, Level2 approval, or ALLOW_PAPER
    evidence.
    """
    ordered = sorted([dict(r) for r in rows], key=lambda r: as_int(r.get("feature_time_ms"), -1))
    closes = [as_float(r.get("close")) for r in ordered]
    highs = [as_float(r.get("high")) for r in ordered]
    lows = [as_float(r.get("low")) for r in ordered]
    opens = [as_float(r.get("open")) for r in ordered]
    rets = _returns(closes)
    ranges_pct = [_safe_div(highs[i] - lows[i], closes[i]) for i in range(len(ordered))]
    rv5_series = _rolling_std_series(rets, 5)
    rv15_series = _rolling_std_series(rets, 15)
    rv60_series = _rolling_std_series(rets, 60)
    range_percentiles = _causal_percentile_series(ranges_pct)
    abs_ret_percentiles = _causal_percentile_series([abs(v) for v in rets])
    rv15_percentiles = _causal_percentile_series(rv15_series)
    rv5_percentiles = _causal_percentile_series(rv5_series)
    spread_bps_series = [as_float(r.get("orderbook_spread_pct_last")) * 10000 if r.get("orderbook_spread_pct_last") not in (None, "") else 0.0 for r in ordered]
    spread_percentiles = _causal_percentile_series(spread_bps_series)

    enriched: list[dict[str, Any]] = []
    for i, row in enumerate(ordered):
        ft = as_int(row.get("feature_time_ms"), -1)
        close = closes[i]
        high = highs[i]
        low = lows[i]
        open_px = opens[i]
        candle_range = high - low
        body = abs(close - open_px)
        ret_abs = abs(rets[i])
        def rv(minutes: int) -> float:
            start = max(0, i - minutes + 1)
            return _std(rets[start:i + 1])

        def range_pct(minutes: int) -> float:
            start = max(0, i - minutes + 1)
            hh = max(highs[start:i + 1])
            ll = min(lows[start:i + 1])
            return _safe_div(hh - ll, close)

        def slope(minutes: int) -> float:
            start = max(0, i - minutes + 1)
            base = closes[start]
            elapsed = max(1, i - start)
            return _safe_div(close - base, base) / elapsed

        spread_pct = row.get("orderbook_spread_pct_last")
        spread_bps = as_float(spread_pct) * 10000 if spread_pct not in (None, "") else 0.0
        orderbook_feature_time = as_int(row.get("orderbook_feature_time_ms"), ft)
        orderbook_stale_ms = max(0, ft - orderbook_feature_time) if row.get("orderbook_feature_time_ms") not in (None, "") else 0
        trade_count = as_int(row.get("trade_count_1m"), 0)
        trade_volume = as_float(row.get("buy_volume_1m")) + as_float(row.get("sell_volume_1m"))
        orderbook_missing = bool(row.get("orderbook_feature_missing_reason"))
        orderbook_stale = orderbook_stale_ms > 0
        spread_unavailable = spread_pct in (None, "")
        depth_unavailable = row.get("orderbook_top20_depth_imbalance_last") in (None, "")
        low_information = trade_count <= 0 or as_int(row.get("orderbook_update_count_1m"), 0) <= 0
        liquidity_unreliable = orderbook_missing or orderbook_stale or spread_unavailable or depth_unavailable

        rv5 = rv5_series[i]
        rv15 = rv15_series[i]
        rv60 = rv60_series[i]
        spread_rank = spread_percentiles[i] if not spread_unavailable else 0.0
        vol_expansion = _safe_div(rv15, rv60) if rv60 else 0.0
        compression = 1.0 - min(1.0, range_percentiles[i])
        expansion = range_percentiles[i]
        trend_persistence = abs(slope(15)) / (rv15 + 1e-12) if rv15 else 0.0
        choppiness = _safe_div(sum(abs(v) for v in rets[max(0, i - 14):i + 1]), abs(closes[i] - closes[max(0, i - 14)]) / closes[max(0, i - 14)] if i else 0.0)
        choppiness = 1.0 / choppiness if choppiness else 0.0
        downside_values = [min(0.0, v) for v in rets[max(0, i - 14):i + 1]]
        downside_vol = _std(downside_values)
        abs_ret_pct = abs_ret_percentiles[i]
        spread_shock = spread_rank >= 0.95 and spread_bps > 0
        depth_collapse = depth_unavailable
        jump_candidate = abs_ret_pct >= 0.98 and ret_abs > 0
        extreme_move = abs_ret_pct >= 0.99 and ret_abs > 0
        transition_candidate = (vol_expansion >= 1.5 or expansion >= 0.9 or trend_persistence >= 2.0)

        missing_flags: list[str] = []
        stale_flags: list[str] = []
        if row.get("trade_feature_missing_reason"):
            missing_flags.append("trade")
        if orderbook_missing:
            missing_flags.append("orderbook")
        if orderbook_stale:
            stale_flags.append("orderbook")
        if row.get("funding_age_ms") in (None, ""):
            missing_flags.append("funding")
        if row.get("btc_borrow_rate_raw") in (None, ""):
            missing_flags.append("borrowing")

        blocked = _blocked_reason_codes(row)
        warnings: list[str] = []
        if low_information:
            warnings.append("no_activity_or_low_information")
        if liquidity_unreliable:
            warnings.append("liquidity_context_unreliable")
        if transition_candidate:
            warnings.append("market_state_transition_candidate")
        if jump_candidate:
            warnings.append("jump_candidate")

        row.update({
            "market": "spot",
            "instrument": row.get("instrument_name", "BTC-USDT"),
            "instrument_type": "spot",
            "source_exchange": "okx",
            "source_market_type": row.get("source_market_type", "spot"),
            "source_instrument": row.get("instrument_name", "BTC-USDT"),
            "source_dataset_family": "curated_btc_market_state",
            "feature_context_contract": CONTEXT_CONTRACT,
            "rolling_realized_volatility_5m": _fmt(rv5),
            "rolling_realized_volatility_15m": _fmt(rv15),
            "rolling_realized_volatility_1h": _fmt(rv60),
            "rolling_range_pct_5m": _fmt(range_pct(5)),
            "rolling_range_pct_15m": _fmt(range_pct(15)),
            "rolling_range_pct_1h": _fmt(range_pct(60)),
            "candle_body_to_range_ratio": _fmt(_safe_div(body, candle_range)),
            "close_location_in_range": _fmt(_safe_div(close - low, candle_range)),
            "intraday_range_percentile_causal": _fmt(range_percentiles[i]),
            "recent_gap_or_missing_bar_count": 0 if i == 0 or ft - as_int(ordered[i - 1].get("feature_time_ms"), ft - 60000) == 60000 else 1,
            "trade_volume_1m": _fmt(trade_volume),
            "orderbook_spread_bps": _fmt(spread_bps) if not spread_unavailable else "",
            "orderbook_depth_near_mid": row.get("orderbook_top20_depth_imbalance_last", ""),
            "orderbook_snapshot_age_ms": orderbook_stale_ms,
            "liquidity_data_stale_flag": str(orderbook_stale),
            "no_activity_or_low_information_flag": str(low_information),
            "causal_trend_slope_15m": _fmt(slope(15)),
            "causal_trend_slope_1h": _fmt(slope(60)),
            "causal_trend_slope_4h": _fmt(slope(240)),
            "rolling_high_low_breakout_distance": _fmt(min(abs(close - max(highs[max(0, i - 14):i + 1])), abs(close - min(lows[max(0, i - 14):i + 1])))),
            "volatility_expansion_ratio": _fmt(vol_expansion),
            "realized_volatility_regime_percentile": _fmt(rv15_percentiles[i]),
            "range_compression_score": _fmt(compression),
            "range_expansion_score": _fmt(expansion),
            "trend_persistence_score": _fmt(trend_persistence),
            "choppiness_or_range_bound_score": _fmt(choppiness),
            "market_state_transition_candidate_flag": str(transition_candidate),
            "spread_bps": _fmt(spread_bps) if not spread_unavailable else "",
            "spread_percentile_causal": _fmt(spread_rank),
            "top_of_book_depth_usd": "",
            "depth_10bps_usd": "",
            "depth_25bps_usd": "",
            "orderbook_imbalance_near_mid": row.get("orderbook_top20_depth_imbalance_last", ""),
            "trade_volume_usd_1m": row.get("vol_quote", ""),
            "trade_volume_usd_5m": _fmt(sum(as_float(r.get("vol_quote")) for r in ordered[max(0, i - 4):i + 1])),
            "volume_drought_flag": str(trade_volume <= 0 or trade_count <= 0),
            "orderbook_stale_ms": orderbook_stale_ms,
            "orderbook_reconstruction_quality": row.get("orderbook_book_reconstruction_quality", ""),
            "crossed_book_flag": str(str(row.get("orderbook_is_crossed_book_last", "")).lower() == "true"),
            "update_without_snapshot_count": 0,
            "liquidity_fragility_flag": str(liquidity_unreliable or spread_shock),
            "estimated_minimum_slippage_bucket": _slippage_bucket(spread_bps, liquidity_unreliable),
            "orderbook_missing": str(orderbook_missing),
            "orderbook_stale": str(orderbook_stale),
            "spread_unavailable": str(spread_unavailable),
            "depth_unavailable": str(depth_unavailable),
            "liquidity_context_unreliable": str(liquidity_unreliable),
            "rolling_return_abs_percentile": _fmt(abs_ret_pct),
            "rolling_downside_volatility": _fmt(downside_vol),
            "intraday_extreme_move_flag": str(extreme_move),
            "wick_ratio": _fmt(_safe_div((high - max(open_px, close)) + (min(open_px, close) - low), candle_range)),
            "tail_ratio": _fmt(_safe_div(min(open_px, close) - low, candle_range)),
            "jump_candidate_flag": str(jump_candidate),
            "liquidation_proxy_context": "unavailable_no_okx_liquidation_source",
            "funding_shock_context": "unavailable_without_threshold_contract" if row.get("last_realized_funding_rate") in (None, "") else "observed_okx_funding_context_only",
            "spread_shock_flag": str(spread_shock),
            "depth_collapse_flag": str(depth_collapse),
            "volatility_cluster_score": _fmt(rv5_percentiles[i]),
            "blocked_reason_codes": _join_flags(blocked),
            "warning_reason_codes": _join_flags(warnings),
            "source_family_missing_flags": _join_flags(missing_flags),
            "source_family_stale_flags": _join_flags(stale_flags),
        })
        row["missing_or_stale_source_count"] = max(as_int(row.get("missing_or_stale_source_count"), 0), len(set(missing_flags + stale_flags)))
        enriched.append(row)
    return enriched


def summarize_context_rows(rows: list[dict[str, Any]], *, dataset_type: str, interval: str, label: str) -> dict[str, Any]:
    row_count = len(rows)
    allowed = sum(1 for row in rows if is_true(row.get("allow_into_feature_layer")))
    reason_counts: dict[str, int] = {}
    opportunity_missing: dict[str, dict[str, Any]] = {}
    for row in rows:
        for code in _flag_list(row.get("blocked_reason_codes")):
            reason_counts[code] = reason_counts.get(code, 0) + 1
    for column in [
        "rolling_realized_volatility_5m", "rolling_realized_volatility_15m", "rolling_realized_volatility_1h",
        "rolling_range_pct_5m", "rolling_range_pct_15m", "rolling_range_pct_1h",
        "candle_body_to_range_ratio", "close_location_in_range", "intraday_range_percentile_causal",
        "trade_count_1m", "trade_volume_1m", "orderbook_spread_bps", "orderbook_update_count_1m",
        "liquidity_data_stale_flag", "no_activity_or_low_information_flag",
    ]:
        if not rows or column not in rows[0]:
            continue
        missing = sum(1 for row in rows if row.get(column) in (None, ""))
        stale = sum(1 for row in rows if str(row.get(column)).lower() == "true" and column.endswith("stale_flag"))
        opportunity_missing[column] = {
            "coverage": (row_count - missing) / row_count if row_count else 0,
            "missing_rate": missing / row_count if row_count else 0,
            "stale_rate": stale / row_count if row_count else 0,
        }
    return {
        "dataset_type": dataset_type,
        "interval": interval,
        "label": label,
        "row_count": row_count,
        "allow_into_feature_layer_rows": allowed,
        "allow_into_feature_layer_ratio": allowed / row_count if row_count else 0,
        "blocked_rows": row_count - allowed,
        "future_leak_violation_count": sum(as_int(row.get("future_leak_violation_count"), 0) for row in rows),
        "blocked_reason_code_counts": reason_counts,
        "opportunity_context_field_quality": opportunity_missing,
        "stage46_context_contract": CONTEXT_CONTRACT,
        "asof_rule": "all Stage46 context fields use only current and past governed rows; no future-window confirmation",
    }


def build_horizon_safe_curated_state(rows_1m: list[dict[str, Any]], *, interval_minutes: int) -> list[dict[str, Any]]:
    if interval_minutes <= 1:
        raise ValueError("interval_minutes must be > 1")
    ordered = sorted([dict(r) for r in rows_1m], key=lambda r: as_int(r.get("feature_time_ms"), -1))
    out: list[dict[str, Any]] = []
    for i in range(0, len(ordered), interval_minutes):
        chunk = ordered[i:i + interval_minutes]
        if len(chunk) < interval_minutes:
            continue
        first = chunk[0]
        last = chunk[-1]
        allowed_count = sum(1 for row in chunk if is_true(row.get("allow_into_feature_layer")))
        future_leaks = sum(as_int(row.get("future_leak_violation_count"), 0) for row in chunk)
        source_flags = _join_flags(sum([_flag_list(row.get("data_quality_flags")) for row in chunk], []))
        blocked_reasons = _join_flags(sum([_flag_list(row.get("blocked_reason_codes")) for row in chunk], []))
        flags: list[str] = []
        if allowed_count != len(chunk):
            flags.append("source_1m_quality_blocked")
        if future_leaks:
            flags.append("source_1m_future_leak_violation")
        row = dict(last)
        row.update({
            "interval": f"{interval_minutes}m" if interval_minutes < 60 else "1h" if interval_minutes == 60 else f"{interval_minutes}m",
            "window_start_feature_time_ms": as_int(first.get("feature_time_ms")),
            "window_end_feature_time_ms": as_int(last.get("feature_time_ms")),
            "source_1m_row_count": len(chunk),
            "source_1m_allowed_row_count": allowed_count,
            "source_allowed_row_count": allowed_count,
            "aggregation_source": "governed_curated_btc_market_state_1m_only",
            "open": first.get("open", ""),
            "high": _fmt(max(as_float(r.get("high")) for r in chunk)),
            "low": _fmt(min(as_float(r.get("low")) for r in chunk)),
            "close": last.get("close", ""),
            "vol_base": _fmt(sum(as_float(r.get("vol_base")) for r in chunk)),
            "vol_quote": _fmt(sum(as_float(r.get("vol_quote")) for r in chunk)),
            "source_1m_data_quality_flags": source_flags,
            "future_leak_violation_count": future_leaks,
            "data_quality_flags": _join_flags(flags),
            "blocked_reason_codes": _join_flags([blocked_reasons] + ["source_1m_quality_blocked"] if flags else [blocked_reasons]),
            "missing_or_stale_source_count": len(flags),
            "overall_data_quality_score": f"{max(0.0, 1.0 - 0.1 * len(flags) - 0.5 * future_leaks):.4f}",
            "allow_into_feature_layer": future_leaks == 0 and not flags,
            "aggregation_rule": "high-horizon rows are aggregated from governed 1m rows only; if any key source 1m row is blocked, the high-horizon row is blocked",
        })
        out.append(row)
    return out


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_stage46_enrich_sample(root: Path, *, source_label: str, label: str | None = None) -> dict[str, Any]:
    label = label or f"{source_label}_stage46"
    source_path = root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m" / f"sample={source_label}" / "curated_btc_market_state_1m.csv"
    if not source_path.exists():
        raise FileNotFoundError(f"curated 1m source not found: {source_path}")
    rows = read_csv_dicts(source_path)
    enriched = enrich_stage46_contexts(rows)
    rows_5m = build_horizon_safe_curated_state(enriched, interval_minutes=5)
    rows_15m = build_horizon_safe_curated_state(enriched, interval_minutes=15)
    rows_1h = build_horizon_safe_curated_state(enriched, interval_minutes=60)

    outputs: dict[str, str] = {}
    summaries: dict[str, str] = {}
    datasets = [
        ("1m", "curated_btc_market_state_1m", enriched, "curated_btc_market_state_1m.csv"),
        ("5m", "curated_btc_market_state_5m", rows_5m, "curated_btc_market_state_5m.csv"),
        ("15m", "curated_btc_market_state_15m", rows_15m, "curated_btc_market_state_15m.csv"),
        ("1h", "curated_btc_market_state_1h", rows_1h, "curated_btc_market_state_1h.csv"),
    ]
    for interval, dataset_type, dataset_rows, filename in datasets:
        out_dir = root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state" / f"interval={interval}" / f"sample={label}"
        out_path = out_dir / filename
        if dataset_rows:
            write_csv_rows(out_path, dataset_rows, list(dataset_rows[0].keys()))
        outputs[interval] = str(out_path)
        summary = summarize_context_rows(dataset_rows, dataset_type=dataset_type, interval=interval, label=label)
        # Preserve existing window fields for snapshot-admission compatibility.
        source_summary_path = root / "reports/quality" / f"curated_state_window_{source_label}_summary.json"
        if source_summary_path.exists():
            source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
            for key in ("window_start", "window_end", "expected_day_partitions", "day_partitions_used", "missing_day_partitions"):
                if key in source_summary:
                    summary[key] = source_summary[key]
        summary["output"] = str(out_path) if dataset_rows else None
        summary_path = root / "reports/quality" / (f"curated_state_window_{label}_summary.json" if interval == "1m" else f"curated_state_{interval}_{label}_summary.json")
        _write_json(summary_path, summary)
        summaries[interval] = str(summary_path)
    result = {
        "source_label": source_label,
        "label": label,
        "outputs": outputs,
        "quality_summaries": summaries,
        "contract": CONTEXT_CONTRACT,
        "forbidden_usage": ["trade_signal", "order_generation", "position_generation", "parameter_selection", "level2_approval", "allow_paper_decision"],
    }
    _write_json(root / "reports/readiness" / f"stage46_context_enrichment_{label}.json", result)
    return result
