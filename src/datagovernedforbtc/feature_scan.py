from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .path_semantics import infer_source_market_type

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

RAW_DATASET_DIRS = {
    "borrowing_rate": "Borrowrates",
    "candlestick": "Candlesticks",
    "funding_rate": "Fundingrates",
    "orderbook": "Orderbook",
    "trade": "Trade",
}


def source_file_date_from_name(name: str) -> str | None:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def orderbook_extension(name: str) -> str:
    lower = name.lower()
    for compound in (".data.txt", ".tar.gz", ".tar.tar"):
        if lower.endswith(compound):
            return compound
    return Path(name).suffix.lower()


def is_orderbook_source_file(path: Path) -> bool:
    return orderbook_extension(path.name) in {".data", ".data.txt", ".tar.gz", ".tar.tar"}


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sample_csv_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            return next(reader, [])
    except Exception:
        return []


def sample_jsonl_keys(path: Path, max_lines: int = 20) -> list[str]:
    keys: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                if idx >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                keys.update(obj.keys())
    except Exception:
        return []
    return sorted(keys)


def scan_raw_feature_points(root: Path) -> dict[str, Any]:
    datasets: dict[str, Any] = {}
    for dataset_type, dirname in RAW_DATASET_DIRS.items():
        base = root / "okx" / dirname
        files = [p for p in base.rglob("*") if p.is_file()] if base.exists() else []
        if dataset_type == "orderbook":
            files = [p for p in files if is_orderbook_source_file(p)]
        else:
            files = [p for p in files if p.suffix.lower() in {".csv", ".zip"}]
        dates = sorted({d for p in files if (d := source_file_date_from_name(p.name))})
        markets: dict[str, int] = {}
        extensions: dict[str, int] = {}
        sample_fields: dict[str, list[str]] = {}
        sample_files: list[str] = []
        for p in files:
            market = infer_source_market_type(p)
            markets[market] = markets.get(market, 0) + 1
            suffix = orderbook_extension(p.name) if dataset_type == "orderbook" else p.suffix.lower()
            extensions[suffix] = extensions.get(suffix, 0) + 1
        for market in sorted(markets):
            candidates = [p for p in files if infer_source_market_type(p) == market]
            if not candidates:
                continue
            if dataset_type == "orderbook":
                readable = [p for p in candidates if p.name.endswith(".data") or p.name.endswith(".data.txt")]
                sample = sorted(readable or candidates)[0]
            else:
                sample = sorted(candidates)[0]
            sample_files.append(str(sample.relative_to(root)))
            if dataset_type == "orderbook" and orderbook_extension(sample.name) in {".tar.gz", ".tar.tar"}:
                sample_fields[market] = [f"{orderbook_extension(sample.name).lstrip('.')}_archive_not_expanded"]
            elif dataset_type == "orderbook":
                sample_fields[market] = sample_jsonl_keys(sample)
            elif sample.suffix.lower() == ".csv":
                sample_fields[market] = sample_csv_header(sample)
            else:
                sample_fields[market] = ["zip_sample_not_expanded"]
        datasets[dataset_type] = {
            "raw_dir": str(base.relative_to(root)) if base.exists() else str(base),
            "file_count": len(files),
            "market_type_counts": dict(sorted(markets.items())),
            "extension_counts": dict(sorted(extensions.items())),
            "min_source_file_date": dates[0] if dates else None,
            "max_source_file_date": dates[-1] if dates else None,
            "sample_files": sample_files,
            "sample_fields_by_market": sample_fields,
        }
    return {
        "scan_type": "raw_feature_point_scan",
        "raw_root": str(root / "okx"),
        "datasets": datasets,
    }


def build_alphatenant_dataset_shape() -> list[dict[str, Any]]:
    return [
        {
            "dataset_name": "curated_btc_market_state_1m",
            "layer": "feature",
            "consumer": "AlphaTenant",
            "primary_key": ["exchange", "instrument_name", "feature_time_ms"],
            "grain": "1 row per BTC-USDT 1m candle close_time_ms",
            "required_time_fields": ["feature_time_ms", "feature_time_utc", "available_time_ms", "available_time_utc"],
            "required_age_fields": [
                "funding_age_ms",
                "btc_borrow_rate_age_ms",
                "eth_borrow_rate_age_ms",
                "usdt_borrow_rate_age_ms",
                "trade_feature_age_ms",
                "orderbook_feature_age_ms",
            ],
            "feature_groups": {
                "ohlcv": ["open", "high", "low", "close", "vol_base", "vol_quote", "return_1m", "return_5m", "return_15m", "realized_vol_15m", "realized_vol_1h"],
                "funding": ["last_realized_funding_rate", "funding_age_ms", "funding_interval_ms", "funding_quality_score"],
                "borrowing": ["btc_borrow_rate_raw", "eth_borrow_rate_raw", "usdt_borrow_rate_raw", "*_borrow_rate_age_ms", "borrow_quality_score"],
                "trade": ["trade_count_1m", "buy_volume_1m", "sell_volume_1m", "volume_delta_1m", "volume_delta_ratio_1m", "large_trade_count_1m", "avg_trade_size_1m"],
                "orderbook": ["spread_pct_last", "spread_pct_median", "top20_depth_imbalance_last", "top20_depth_imbalance_mean", "top100_depth_imbalance_last", "slippage_buy_5k_last", "slippage_sell_5k_last", "book_reconstruction_quality"],
                "quality": ["candle_quality_score", "funding_quality_score", "borrow_quality_score", "trade_quality_score", "orderbook_quality_score", "overall_data_quality_score"],
            },
            "future_leak_rule": "Every source row joined into this table must satisfy source.available_time_ms <= feature_time_ms.",
            "current_status": "minimal prototype exists; needs full overlap coverage and quality gate before AlphaTenant consumption",
        },
        {
            "dataset_name": "curated_btc_market_state_5m",
            "layer": "feature",
            "consumer": "AlphaTenant",
            "primary_key": ["exchange", "instrument_name", "feature_time_ms"],
            "grain": "5m resample from governed 1m state; no future aggregation",
            "required_time_fields": ["feature_time_ms", "available_time_ms"],
            "required_age_fields": ["funding_age_ms", "*_borrow_rate_age_ms", "trade_feature_age_ms", "orderbook_feature_age_ms"],
            "feature_groups": {
                "ohlcv": ["open_5m", "high_5m", "low_5m", "close_5m", "vol_base_5m", "return_5m"],
                "flow": ["volume_delta_5m", "trade_count_5m"],
                "liquidity": ["spread_pct_median_5m", "top20_depth_imbalance_mean_5m"],
                "quality": ["overall_data_quality_score"],
            },
            "future_leak_rule": "Aggregate only closed 1m rows with row.feature_time_ms <= 5m feature_time_ms.",
            "current_status": "planned after 1m table quality gate",
        },
        {
            "dataset_name": "btc_regime_1m",
            "layer": "regime",
            "consumer": "AlphaTenant",
            "primary_key": ["exchange", "instrument_name", "feature_time_ms"],
            "grain": "1 row per governed market-state timestamp",
            "required_time_fields": ["feature_time_ms", "available_time_ms"],
            "required_age_fields": [],
            "feature_groups": {
                "regime_labels": ["trend_regime", "volatility_regime", "leverage_regime", "borrow_regime", "liquidity_regime", "panic_regime"],
                "explainability": ["regime_reason", "trigger_fields", "rule_version"],
                "quality": ["regime_quality_score", "source_market_state_quality_score"],
            },
            "future_leak_rule": "Regime rules may use only past rolling windows; no full-sample normalization or future quantiles.",
            "current_status": "planned; should be rule-based and explainable first",
        },
        {
            "dataset_name": "data_quality_report",
            "layer": "quality",
            "consumer": "AlphaTenant / human review",
            "primary_key": ["exchange", "dataset_type", "source_market_type", "source_file_date"],
            "grain": "file-level and dataset-level quality summaries",
            "required_time_fields": ["min_event_time_ms", "max_event_time_ms", "ingested_at"],
            "required_age_fields": [],
            "feature_groups": {
                "coverage": ["file_count", "row_count", "date_gap_count", "market_type_counts"],
                "schema": ["schema_match", "missing_columns", "parse_status"],
                "safety": ["allow_into_feature_layer", "future_leak_risk_flags", "manual_review_required"],
            },
            "future_leak_rule": "Quality metadata must not alter historical features retroactively without version bump.",
            "current_status": "partially implemented per dataset",
        },
    ]


def render_markdown(scan: dict[str, Any], shapes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# AlphaTenant 数据集形状与 OKX 特征点扫描")
    lines.append("")
    lines.append("## 1. 最新 OKX Raw Feature Point 扫描")
    lines.append("")
    lines.append("| dataset | files | market_type_counts | date_range | extensions | sample_fields |")
    lines.append("|---|---:|---|---|---|---|")
    for dataset, info in scan["datasets"].items():
        fields_summary = []
        for market, fields in info["sample_fields_by_market"].items():
            fields_summary.append(f"{market}: {', '.join(fields[:10])}")
        lines.append(
            f"| {dataset} | {info['file_count']} | {info['market_type_counts']} | "
            f"{info['min_source_file_date']} → {info['max_source_file_date']} | {info['extension_counts']} | "
            f"{'<br>'.join(fields_summary)} |"
        )
    lines.append("")
    lines.append("## 2. 给 AlphaTenant 的目标数据集形状")
    lines.append("")
    for shape in shapes:
        lines.append(f"### {shape['dataset_name']}")
        lines.append("")
        lines.append(f"- Layer: `{shape['layer']}`")
        lines.append(f"- Grain: {shape['grain']}")
        lines.append(f"- Primary key: `{', '.join(shape['primary_key'])}`")
        lines.append(f"- Time fields: `{', '.join(shape['required_time_fields'])}`")
        if shape["required_age_fields"]:
            lines.append(f"- Age fields: `{', '.join(shape['required_age_fields'])}`")
        lines.append(f"- Future leak rule: {shape['future_leak_rule']}")
        lines.append(f"- Current status: {shape['current_status']}")
        lines.append("- Feature groups:")
        for group, fields in shape["feature_groups"].items():
            lines.append(f"  - `{group}`: {', '.join(fields)}")
        lines.append("")
    lines.append("## 3. 当前形状判断")
    lines.append("")
    lines.append("- AlphaTenant 后续应优先消费 `curated_btc_market_state_1m`、`btc_regime_1m` 与 `data_quality_report`，而不是 raw CSV / raw tick / raw L2。")
    lines.append("- 现阶段需要先补齐 1m curated 表的质量闸门与时间覆盖重叠，再考虑 5m/1h 派生。")
    lines.append("- Trade 与 Orderbook 原始数据体量较大，应继续保持样本验证 + 清晰治理规则，暂不做局部复杂优化。")
    return "\n".join(lines) + "\n"


def run_feature_scan(root: Path) -> dict[str, Any]:
    scan = scan_raw_feature_points(root)
    shapes = build_alphatenant_dataset_shape()
    out_dir = root / "reports" / "feature_scan"
    json_path = out_dir / "alphatenant_dataset_shape_scan.json"
    md_path = out_dir / "alphatenant_dataset_shape_scan.md"
    result = {
        "scan": scan,
        "alphatenant_dataset_shapes": shapes,
        "outputs": {"json": str(json_path), "markdown": str(md_path)},
    }
    write_json(json_path, result)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(scan, shapes), encoding="utf-8")
    return result
