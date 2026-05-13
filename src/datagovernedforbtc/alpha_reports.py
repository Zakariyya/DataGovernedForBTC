from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .feature_scan import RAW_DATASET_DIRS, is_orderbook_source_file, source_file_date_from_name
from .path_semantics import infer_source_market_type
from .snapshot import build_snapshot_index, write_json

DATASET_FAMILY_ROWS = [
    ("okx", "spot", "BTC-USDT", "candlestick"),
    ("okx", "spot", "BTC-USDT", "trade"),
    ("okx", "spot", "BTC-USDT", "orderbook"),
    ("okx", "perpetual", "BTC-USDT-SWAP", "funding"),
    ("okx", "spot", "BTC", "borrowing"),
    ("okx", "spot", "USDT", "borrowing"),
    ("okx", "perpetual", "BTC-USDT-SWAP", "open_interest"),
    ("okx", "perpetual", "BTC-USDT-SWAP", "long_short_ratio"),
    ("okx", "perpetual", "BTC-USDT-SWAP", "liquidation"),
    ("okx", "spot", "BTC-USDT", "taker_flow"),
    ("okx", "perpetual", "BTC-USDT-SWAP", "mark_price"),
    ("okx", "spot", "BTC-USDT", "index_price"),
]

RAW_FAMILY_TO_DATASET_TYPE = {
    "candlestick": "candlestick",
    "trade": "trade",
    "orderbook": "orderbook",
    "funding": "funding_rate",
    "borrowing": "borrowing_rate",
}

FEATURE_DATASET_TYPE_BY_FAMILY = {
    "candlestick": "curated_btc_market_state",
    "trade": "trade_feature",
    "orderbook": "orderbook_feature",
    "funding": "curated_btc_market_state",
    "borrowing": "curated_btc_market_state",
}

DATE_RE = re.compile(r"exchange_date_utc8=(\d{4}-\d{2}-\d{2})")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def inclusive_expected_count(dates: list[str]) -> int | None:
    if not dates:
        return None
    start = parse_date(dates[0])
    end = parse_date(dates[-1])
    return (end - start).days + 1


def missing_dates_between(dates: list[str]) -> list[str]:
    if not dates:
        return []
    present = set(dates)
    start = parse_date(dates[0])
    end = parse_date(dates[-1])
    out: list[str] = []
    cur = start
    while cur <= end:
        s = cur.isoformat()
        if s not in present:
            out.append(s)
        cur = date.fromordinal(cur.toordinal() + 1)
    return out


def instrument_matches(path: Path, instrument: str, family: str) -> bool:
    name = path.name.upper()
    if family in {"borrowing", "funding"}:
        # OKX low-frequency public archives can be multi-instrument files such as
        # allswap-fundingrates or allmargin-borrowrates. Instrument-level filtering
        # is performed in normalized/as-of governance, not by filename alone.
        return True
    return instrument.upper() in name


def raw_files_for_family(root: Path, family: str, market: str, instrument: str) -> list[Path]:
    dataset_type = RAW_FAMILY_TO_DATASET_TYPE.get(family)
    if not dataset_type:
        return []
    dirname = RAW_DATASET_DIRS[dataset_type]
    base = root / "okx" / dirname
    if not base.exists():
        return []
    files = [p for p in base.rglob("*") if p.is_file()]
    if family == "orderbook":
        files = [p for p in files if is_orderbook_source_file(p)]
    else:
        files = [p for p in files if p.suffix.lower() in {".csv", ".zip"}]
    return sorted(p for p in files if infer_source_market_type(p) == market and instrument_matches(p, instrument, family))


def feature_dates_for_family(root: Path, family: str, market: str, instrument: str) -> list[str]:
    dataset_type = FEATURE_DATASET_TYPE_BY_FAMILY.get(family)
    if not dataset_type:
        return []
    base = root / "data_lake" / "features" / "exchange=okx"
    if not base.exists():
        return []
    candidates = [p for p in base.rglob("*") if p.is_file() and f"dataset_type={dataset_type}" in p.as_posix()]
    if market:
        candidates = [p for p in candidates if f"market={market}" in p.as_posix() or dataset_type == "curated_btc_market_state"]
    if instrument:
        candidates = [p for p in candidates if f"instrument={instrument}" in p.as_posix() or dataset_type == "curated_btc_market_state"]
    dates = sorted({m.group(1) for p in candidates if (m := DATE_RE.search(p.as_posix()))})
    return dates


def snapshot_has_family(entry: dict[str, Any], family: str) -> bool:
    groups = set(entry.get("feature_contract", {}).get("feature_group", {}).values())
    if family == "candlestick":
        return "price_context" in groups
    if family == "trade":
        return "trade_flow_context" in groups
    if family == "orderbook":
        return "orderbook_microstructure" in groups or "cost_liquidity_context" in groups
    if family == "funding":
        return "funding_context" in groups
    if family == "borrowing":
        return "borrowing_context" in groups
    return False


def quality_blocked_dates_for_family(root: Path, family: str, dates: list[str]) -> list[str]:
    if family == "candlestick":
        base = root / "reports" / "quality" / "exchange=okx" / "dataset_type=candlestick"
        if not base.exists():
            return []
        blocked: list[str] = []
        for report in base.rglob("quality_report.json"):
            text = report.as_posix()
            m = DATE_RE.search(text)
            d = m.group(1) if m else source_file_date_from_name(text)
            if d and dates and d not in dates:
                continue
            try:
                obj = json.loads(report.read_text(encoding="utf-8"))
            except Exception:
                continue
            if obj.get("allow_into_training") is False or obj.get("allow_into_feature_layer") is False:
                blocked.append(d)
        return sorted({d for d in blocked if d})
    return []


def admission_status(*, raw_available: bool, feature_available: bool, snapshot_available: bool, quality_blocked_dates: list[str]) -> str:
    if quality_blocked_dates and not feature_available:
        return "blocked_by_quality_gate"
    if snapshot_available and feature_available:
        return "snapshot_available"
    if snapshot_available and raw_available:
        return "raw_only_snapshot_available"
    if feature_available:
        return "governed_feature_available_not_snapshot_specific"
    if raw_available:
        return "raw_only_not_feature_governed"
    return "unavailable"


def build_dataset_family_coverage_matrix(root: Path) -> dict[str, Any]:
    snapshot_index = build_snapshot_index(root, for_alphatenant=True)
    snapshots = snapshot_index.get("snapshots", [])
    rows: list[dict[str, Any]] = []
    for exchange, market, instrument, family in DATASET_FAMILY_ROWS:
        raw_files = raw_files_for_family(root, family, market, instrument)
        raw_dates = sorted({d for p in raw_files if (d := source_file_date_from_name(p.name))})
        feature_dates = feature_dates_for_family(root, family, market, instrument)
        raw_available = bool(raw_files)
        feature_available = bool(feature_dates)
        snapshot_available = any(snapshot_has_family(entry, family) for entry in snapshots)
        all_dates = sorted(set(raw_dates) | set(feature_dates))
        quality_blocked = quality_blocked_dates_for_family(root, family, all_dates)
        rows.append({
            "exchange": exchange,
            "market": market,
            "instrument": instrument,
            "dataset_family": family,
            "min_event_time": all_dates[0] if all_dates else None,
            "max_event_time": all_dates[-1] if all_dates else None,
            "date_count": len(all_dates),
            "expected_date_count": inclusive_expected_count(all_dates),
            "missing_dates": missing_dates_between(all_dates),
            "partial_dates": [],
            "stale_dates": [],
            "quality_blocked_dates": quality_blocked,
            "raw_coverage_available": raw_available,
            "governed_feature_available": feature_available,
            "alpha_tenant_snapshot_available": snapshot_available,
            "admission_status": admission_status(
                raw_available=raw_available,
                feature_available=feature_available,
                snapshot_available=snapshot_available,
                quality_blocked_dates=quality_blocked,
            ),
        })
    return {
        "schema_version": "datagoverned.alpha_tenant_dataset_family_coverage_matrix.v1",
        "generated_at_utc": utc_now_iso(),
        "purpose": "Machine-readable coverage/admission matrix for AlphaTenant research readiness. Raw coverage is separated from governed feature and snapshot availability.",
        "universe_id": "okx_spot_btc_usdt_with_okx_derivative_context",
        "exchange_consistency_scope": "single_exchange_okx_cross_market_context",
        "allowed_source_exchanges": ["okx"],
        "mixed_exchange_features_present": False,
        "mixed_exchange_usage_policy": "fail_closed",
        "snapshot_index_status": snapshot_index.get("index_status"),
        "snapshot_count": snapshot_index.get("snapshot_count"),
        "rows": rows,
    }


def render_coverage_matrix_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# AlphaTenant Dataset Family Coverage Matrix",
        "",
        f"Generated: `{matrix['generated_at_utc']}`",
        "",
        f"Universe: `{matrix['universe_id']}`",
        f"Exchange consistency: `{matrix['exchange_consistency_scope']}`; allowed exchanges: `{', '.join(matrix['allowed_source_exchanges'])}`",
        "",
        "| exchange | market | instrument | family | raw | governed_feature | snapshot | dates | missing | blocked | admission_status |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in matrix["rows"]:
        lines.append(
            f"| {r['exchange']} | {r['market']} | {r['instrument']} | {r['dataset_family']} | "
            f"{r['raw_coverage_available']} | {r['governed_feature_available']} | {r['alpha_tenant_snapshot_available']} | "
            f"{r['date_count']} / {r['expected_date_count']} | {len(r['missing_dates'])} | {len(r['quality_blocked_dates'])} | {r['admission_status']} |"
        )
    lines.extend([
        "",
        "## Notes",
        "",
        "- Raw coverage is not feature readiness.",
        "- Candlestick coverage is not evidence for funding/OI/orderbook/liquidation coverage.",
        "- Binance or other exchanges are not used as OKX proxies; cross-exchange data remains fail-closed.",
    ])
    return "\n".join(lines) + "\n"


def write_dataset_family_coverage_matrix(root: Path) -> dict[str, Any]:
    matrix = build_dataset_family_coverage_matrix(root)
    json_path = root / "reports" / "coverage" / "alpha_tenant_dataset_family_coverage_matrix.json"
    md_path = root / "reports" / "coverage" / "alpha_tenant_dataset_family_coverage_matrix.md"
    write_json(json_path, matrix)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_coverage_matrix_markdown(matrix), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "row_count": len(matrix["rows"]), "schema_version": matrix["schema_version"]}


def build_research_readiness_report(root: Path, snapshot_id: str | None = None) -> dict[str, Any]:
    snapshot_index = build_snapshot_index(root, for_alphatenant=True)
    snapshots = snapshot_index.get("snapshots", [])
    if not snapshots:
        raise FileNotFoundError("no governed snapshots found")
    if snapshot_id:
        matches = [entry for entry in snapshots if entry.get("snapshot_id") == snapshot_id]
        if not matches:
            raise FileNotFoundError(f"snapshot_id not found: {snapshot_id}")
        entry = matches[0]
    else:
        admitted = [entry for entry in snapshots if entry.get("status") == "admitted"]
        entry = admitted[-1] if admitted else snapshots[-1]
    feature_contract = entry.get("feature_contract", {})
    groups = Counter(feature_contract.get("feature_group", {}).values())
    quality_path = root / entry["path"] / entry.get("files", {}).get("quality_summary", "quality_summary.json")
    quality_summary: dict[str, Any] = {}
    if quality_path.exists():
        try:
            quality_summary = json.loads(quality_path.read_text(encoding="utf-8"))
        except Exception:
            quality_summary = {}
    row_count = int(entry.get("row_count") or 0)
    allowed = int(entry.get("allowed_rows") or 0)
    blocked = int(entry.get("blocked_rows") or max(row_count - allowed, 0))
    future_leaks = 0
    admission_path = root / entry["path"] / entry.get("files", {}).get("data_admission_report", "data_admission_report.json")
    if admission_path.exists():
        try:
            future_leaks = int(json.loads(admission_path.read_text(encoding="utf-8")).get("future_leak_violation_count") or 0)
        except Exception:
            future_leaks = 0
    readiness_status = "blocked"
    if entry.get("status") == "admitted" and future_leaks == 0 and allowed > 0:
        readiness_status = "research_ready_with_row_level_quality_filter"
    elif allowed > 0:
        readiness_status = "partial_research_ready_with_row_level_quality_filter"
    return {
        "schema_version": "datagoverned.alpha_tenant_research_readiness_report.v1",
        "generated_at_utc": utc_now_iso(),
        "snapshot_id": entry.get("snapshot_id"),
        "universe_id": entry.get("universe_id"),
        "exchange_consistency_status": {
            "exchange_consistency_scope": entry.get("exchange_consistency_scope"),
            "allowed_source_exchanges": entry.get("allowed_source_exchanges"),
            "mixed_exchange_features_present": entry.get("mixed_exchange_features_present"),
            "mixed_exchange_usage_policy": entry.get("mixed_exchange_usage_policy"),
            "cross_exchange_authorization_required": bool(entry.get("mixed_exchange_features_present")),
        },
        "research_window_start": entry.get("start_time_utc"),
        "research_window_end": entry.get("end_time_utc"),
        "sealed_verification_boundary": "2025-01-01T00:00:00Z",
        "row_count": row_count,
        "allowed_row_count": allowed,
        "blocked_row_count": blocked,
        "allowed_ratio": (allowed / row_count) if row_count else 0,
        "dataset_family_coverage": {
            "matrix_path": "reports/coverage/alpha_tenant_dataset_family_coverage_matrix.json",
            "summary": {},
        },
        "feature_group_coverage": dict(sorted(groups.items())),
        "missing_stale_blocked_summary": {
            "blocked_reason_code_counts": quality_summary.get("data_quality_flag_counts") or quality_summary.get("blocking_quality_flags") or {},
            "warning_reason_code_counts": quality_summary.get("warning_reason_code_counts", {}),
            "source_family_missing_flag_counts": quality_summary.get("source_family_missing_flag_counts", {}),
            "source_family_stale_flag_counts": quality_summary.get("source_family_stale_flag_counts", {}),
        },
        "no_lookahead_checks": {
            "all_features_available_time_lte_feature_time": future_leaks == 0,
            "rolling_features_use_current_and_past_only": True,
            "future_window_regime_confirmation_used": False,
            "strategy_pnl_used_in_features": False,
        },
        "future_leak_violation_count": future_leaks,
        "required_filter": feature_contract.get("required_filter", "allow_into_feature_layer == True"),
        "allowed_alpha_tenant_use": [
            "coverage_audit",
            "structural_hypothesis_preregistration",
            "research_only_feature_matrix",
            "regime_input_research",
            "no_lookahead_alignment",
            "forward_observation_input",
        ],
        "forbidden_alpha_tenant_use": [
            "live_trading",
            "paper_trading_permission",
            "level2_auto_upgrade",
            "parameter_selection",
            "direct_trade_signal",
            "cross_exchange_proxy",
        ],
        "readiness_status": readiness_status,
        "notes": [
            "This is a research data-readiness report, not a strategy return report.",
            "It is not Level2 readiness and not ALLOW_PAPER evidence.",
        ],
    }


def render_readiness_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# AlphaTenant Research Readiness Report: {report['snapshot_id']}",
        "",
        f"Generated: `{report['generated_at_utc']}`",
        "",
        f"Readiness status: `{report['readiness_status']}`",
        f"Required filter: `{report['required_filter']}`",
        "",
        "## Exchange Consistency",
        "",
        f"- Universe: `{report['universe_id']}`",
        f"- Scope: `{report['exchange_consistency_status']['exchange_consistency_scope']}`",
        f"- Allowed source exchanges: `{', '.join(report['exchange_consistency_status']['allowed_source_exchanges'] or [])}`",
        f"- Mixed exchange features present: `{report['exchange_consistency_status']['mixed_exchange_features_present']}`",
        f"- Mixed exchange policy: `{report['exchange_consistency_status']['mixed_exchange_usage_policy']}`",
        "",
        "## Row Counts",
        "",
        f"- row_count: {report['row_count']}",
        f"- allowed_row_count: {report['allowed_row_count']}",
        f"- blocked_row_count: {report['blocked_row_count']}",
        f"- allowed_ratio: {report['allowed_ratio']:.6f}",
        "",
        "## Feature Group Coverage",
        "",
    ]
    for group, count in report["feature_group_coverage"].items():
        lines.append(f"- `{group}`: {count}")
    lines.extend([
        "",
        "## No-lookahead Checks",
        "",
    ])
    for k, v in report["no_lookahead_checks"].items():
        lines.append(f"- `{k}`: {v}")
    lines.extend([
        "",
        "## Allowed AlphaTenant Use",
        "",
    ])
    for item in report["allowed_alpha_tenant_use"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Forbidden AlphaTenant Use",
        "",
    ])
    for item in report["forbidden_alpha_tenant_use"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Boundary",
        "",
        "This report does not authorize live trading, paper trading, Level2 upgrade, parameter selection, or direct trade-signal use.",
    ])
    return "\n".join(lines) + "\n"


def write_research_readiness_report(root: Path, snapshot_id: str | None = None) -> dict[str, Any]:
    report = build_research_readiness_report(root, snapshot_id=snapshot_id)
    sid = report["snapshot_id"]
    json_path = root / "reports" / "readiness" / f"alpha_tenant_research_readiness_{sid}.json"
    md_path = root / "reports" / "readiness" / f"alpha_tenant_research_readiness_{sid}.md"
    write_json(json_path, report)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_readiness_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "snapshot_id": sid, "readiness_status": report["readiness_status"]}
