from __future__ import annotations

import csv
import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import GovernanceVersions
from .io_utils import sha256_file


GOVERNANCE_COLUMNS = {
    "future_leak_violation_count",
    "data_quality_flags",
    "missing_or_stale_source_count",
    "overall_data_quality_score",
    "allow_into_feature_layer",
    "schema_version",
    "feature_version",
    "governance_version",
    "orderbook_feature_required",
    "orderbook_feature_missing_reason",
    "trade_feature_missing_reason",
}

META_COLUMNS = {
    "exchange",
    "instrument_name",
    "source_market_type",
    "feature_time_ms",
    "feature_time_utc",
    "available_time_ms",
    "available_time_utc",
}

QUALITY_SCORE_COLUMNS = {
    "candle_quality_score",
    "funding_quality_score",
    "borrow_quality_score",
    "trade_quality_score",
    "orderbook_quality_score",
}


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_curated_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def truthy(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def compute_admission_report(*, snapshot_id: str, label: str, summary: dict[str, Any], columns: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    versions = GovernanceVersions()
    allow_rows = sum(1 for r in rows if truthy(r.get("allow_into_feature_layer")))
    future_leaks = sum(int(float(r.get("future_leak_violation_count") or 0)) for r in rows)
    flag_counts: Counter[str] = Counter()
    orderbook_qualities: set[str] = set()
    min_feature_time = None
    max_feature_time = None
    for row in rows:
        ft_raw = row.get("feature_time_ms")
        if ft_raw not in (None, ""):
            ft = int(float(ft_raw))
            min_feature_time = ft if min_feature_time is None else min(min_feature_time, ft)
            max_feature_time = ft if max_feature_time is None else max(max_feature_time, ft)
        for flag in str(row.get("data_quality_flags", "")).split(";"):
            if flag:
                flag_counts[flag] += 1
        q = row.get("orderbook_book_reconstruction_quality")
        if q:
            orderbook_qualities.add(q)
    orderbook_quality = "mixed" if len(orderbook_qualities) > 1 else (next(iter(orderbook_qualities)) if orderbook_qualities else "not_included")
    row_count = len(rows)
    blocked = row_count - allow_rows
    return {
        "snapshot_id": snapshot_id,
        "dataset_type": "curated_btc_market_state_1m",
        "label": label,
        "instrument_name": "BTC-USDT",
        "exchange": "okx",
        "interval": "1m",
        "window_start": summary.get("window_start"),
        "window_end": summary.get("window_end"),
        "min_feature_time_ms": min_feature_time,
        "max_feature_time_ms": max_feature_time,
        "row_count": row_count,
        "allow_into_feature_layer_rows": allow_rows,
        "allow_into_feature_layer_ratio": (allow_rows / row_count) if row_count else 0,
        "blocked_rows": blocked,
        "future_leak_violation_count": future_leaks,
        "blocking_quality_flags": dict(sorted(flag_counts.items())),
        "orderbook_reconstruction_quality": orderbook_quality,
        "alpha_tenant_readiness": "admitted_with_row_level_quality_filter" if future_leaks == 0 and allow_rows > 0 else "blocked",
        "required_alpha_tenant_filter": "allow_into_feature_layer == True",
        "raw_zone_access_allowed_for_alphatenant": False,
        "raw_zone_policy": "AlphaTenant must read this snapshot or other governed Feature/Regime/Snapshot assets only; raw okx/ access is forbidden.",
        "training_warning": "This snapshot is a governed data-admission artifact, not a strategy/backtest result. Use only according to AlphaTenant train/validation cutoff policy.",
        "schema_version": versions.schema_version,
        "feature_version": versions.feature_version,
        "governance_version": versions.governance_version,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_summary": summary,
        "column_count": len(columns),
    }


def build_schema(columns: list[str]) -> dict[str, Any]:
    governance_columns = [c for c in columns if c in GOVERNANCE_COLUMNS or c.endswith("_missing_reason") or c.endswith("_quality_score")]
    meta_columns = [c for c in columns if c in META_COLUMNS]
    allowed_feature_columns = [
        c for c in columns
        if c not in set(governance_columns)
        and c not in set(meta_columns)
        and c not in QUALITY_SCORE_COLUMNS
        and not c.endswith("_time_ms")
        and not c.endswith("_time_utc")
        and c not in {"data_quality_flags"}
    ]
    return {
        "dataset_type": "curated_btc_market_state_1m",
        "columns": columns,
        "meta_columns": meta_columns,
        "governance_columns": governance_columns,
        "allowed_feature_columns": allowed_feature_columns,
        "forbidden_as_features": sorted(set(governance_columns + meta_columns + list(QUALITY_SCORE_COLUMNS))),
        "row_filter_required_before_alpha_tenant_feature_use": "allow_into_feature_layer == True",
    }


def write_feature_contract(path: Path, report: dict[str, Any], schema: dict[str, Any]) -> None:
    lines = [
        f"# AlphaTenant Feature Contract: {report['snapshot_id']}",
        "",
        "## 用途",
        "本 snapshot 是 DataGovernedForBTC 生成的 OKX BTC-USDT 1m market-state 治理产物。AlphaTenant 只能读取本 snapshot 或其他治理后的 Feature/Regime/Snapshot Layer，禁止读取 raw okx/。",
        "",
        "## 必须过滤",
        "- 使用前必须过滤：`allow_into_feature_layer == True`。",
        "- `data_quality_flags` 非空的行不得静默进入特征层。",
        "- `future_leak_violation_count` 必须为 0。",
        "",
        "## Orderbook 边界",
        f"- Orderbook reconstruction quality: `{report['orderbook_reconstruction_quality']}`。",
        "- 当前 Orderbook 没有 sequence/checksum，因此属于 best-effort update-applied 1m feature，不是可严格证明连续的完整 L2 重建。",
        "",
        "## 允许作为候选特征的列",
        "```text",
        *schema["allowed_feature_columns"],
        "```",
        "",
        "## 治理列不能作为模型特征",
        "```text",
        *schema["governance_columns"],
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_forbidden_policy(path: Path) -> None:
    path.write_text(
        "# Forbidden Raw Access Policy\n\n"
        "AlphaTenant 禁止直接读取 DataGovernedForBTC 的 `okx/` Raw Source Zone、raw tick、raw L2、临时解压 `.data`、未版本化 CSV 或无质量闸门特征。\n\n"
        "允许入口只有治理后的 Feature Layer、Regime Layer 与 Snapshot Layer。\n\n"
        "如需新增数据，必须先在 DataGovernedForBTC 侧完成 manifest、quality report、time-causal feature、admission report，再暴露给 AlphaTenant。\n",
        encoding="utf-8",
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_commit(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        return proc.stdout.strip() or None
    except Exception:
        return None


def rel_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def snapshot_dirs(root: Path) -> list[Path]:
    base = root / "snapshots"
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("snapshot_id=*") if p.is_dir())


def require_snapshot_files(snapshot_dir: Path) -> dict[str, str]:
    files = {
        "data": "curated_btc_market_state_1m.csv",
        "data_admission_report": "data_admission_report.json",
        "source_manifest": "source_manifest.json",
        "quality_summary": "quality_summary.json",
        "schema": "schema.json",
        "feature_contract": "feature_contract.md",
        "forbidden_raw_access_policy": "forbidden_raw_access_policy.md",
        "snapshot_summary": "snapshot_summary.json",
    }
    return {key: name for key, name in files.items() if (snapshot_dir / name).exists()}


def millis_to_utc_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ms = int(float(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_snapshot_entry(root: Path, snapshot_dir: Path) -> dict[str, Any]:
    summary_path = snapshot_dir / "snapshot_summary.json"
    admission_path = snapshot_dir / "data_admission_report.json"
    schema_path = snapshot_dir / "schema.json"
    manifest_path = snapshot_dir / "source_manifest.json"
    quality_path = snapshot_dir / "quality_summary.json"
    if not summary_path.exists() or not admission_path.exists() or not schema_path.exists():
        raise FileNotFoundError(f"snapshot contract files missing under {snapshot_dir}")

    summary = read_json(summary_path)
    admission_report = read_json(admission_path)
    schema = read_json(schema_path)
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    quality_summary = read_json(quality_path) if quality_path.exists() else {}

    snapshot_id = str(admission_report.get("snapshot_id") or summary.get("snapshot_id") or snapshot_dir.name.removeprefix("snapshot_id="))
    dataset_key = f"governed-snapshot-{snapshot_id}"
    readiness = str(admission_report.get("alpha_tenant_readiness") or summary.get("alpha_tenant_readiness") or "blocked")
    allowed_rows = int(admission_report.get("allow_into_feature_layer_rows") or summary.get("allow_into_feature_layer_rows") or 0)
    row_count = int(admission_report.get("row_count") or summary.get("curated_rows") or 0)
    blocked_rows = int(admission_report.get("blocked_rows") or max(row_count - allowed_rows, 0))
    future_leaks = int(admission_report.get("future_leak_violation_count") or summary.get("future_leak_violation_count") or 0)
    core_files = require_snapshot_files(snapshot_dir)
    missing_core_files = sorted({
        "data",
        "data_admission_report",
        "source_manifest",
        "quality_summary",
        "schema",
        "feature_contract",
        "forbidden_raw_access_policy",
        "snapshot_summary",
    } - set(core_files))

    if missing_core_files:
        status = "blocked"
        readiness = "blocked_missing_required_files"
    elif future_leaks > 0:
        status = "blocked"
        readiness = "blocked_future_leak_risk"
    elif allowed_rows > 0 and readiness == "admitted_with_row_level_quality_filter":
        status = "admitted"
    elif allowed_rows > 0:
        status = "partial"
    else:
        status = "blocked"

    data_path = snapshot_dir / core_files.get("data", "curated_btc_market_state_1m.csv")
    source_hash_summary = None
    curated_source = manifest.get("curated_source") if isinstance(manifest.get("curated_source"), dict) else {}
    if curated_source.get("sha256"):
        source_hash_summary = f"sha256:{curated_source['sha256']}"

    return {
        "dataset_key": dataset_key,
        "snapshot_id": snapshot_id,
        "status": status,
        "readiness": readiness,
        "path": rel_to_root(root, snapshot_dir),
        "exchange": admission_report.get("exchange", "okx"),
        "symbol": admission_report.get("instrument_name", "BTC-USDT"),
        "instrument": admission_report.get("instrument_name", "BTC-USDT"),
        "instrument_type": "spot",
        "market_scope": "okx_spot_btc_usdt_with_perpetual_context",
        "dataset_type": admission_report.get("dataset_type", "curated_btc_market_state_1m"),
        "interval": admission_report.get("interval", "1m"),
        "start_time_utc": millis_to_utc_iso(admission_report.get("min_feature_time_ms")) or quality_summary.get("window_start"),
        "end_time_utc": millis_to_utc_iso(admission_report.get("max_feature_time_ms")) or quality_summary.get("window_end"),
        "row_count": row_count,
        "allowed_rows": allowed_rows,
        "blocked_rows": blocked_rows,
        "required_row_filter": "allow_into_feature_layer == True",
        "files": core_files,
        "feature_contract": {
            "allowed_feature_columns": schema.get("allowed_feature_columns", []),
            "forbidden_as_features": schema.get("forbidden_as_features", []),
            "required_quality_columns": [
                "allow_into_feature_layer",
                "data_quality_flags",
                "overall_data_quality_score",
            ],
            "timestamp_columns": {
                "feature_time": "feature_time_ms",
                "available_time": "available_time_ms",
            },
            "join_semantics": {
                "required": "all joined source features must satisfy available_time_ms <= feature_time_ms",
                "row_filter": "allow_into_feature_layer == True",
            },
        },
        "admission": {
            "allow_into_alphatenant": status in {"admitted", "partial"},
            "allow_into_feature_layer_required": True,
            "is_trade_signal": False,
            "is_strategy_ready": False,
            "level2_auto_upgrade": False,
            "allowed_consumption_modes": [
                "loader_smoke",
                "feature_matrix",
                "regime_input",
                "research_only",
            ],
            "forbidden_consumption_modes": [
                "live_trading",
                "order_generation",
                "strategy_return_claim",
                "parameter_selection",
                "level2_auto_upgrade",
            ],
        },
        "provenance": {
            "governance_version": admission_report.get("governance_version"),
            "schema_version": admission_report.get("schema_version") or schema.get("schema_version"),
            "source_hash_summary": source_hash_summary,
            "snapshot_hash": f"sha256:{sha256_file(data_path)}" if data_path.exists() else None,
        },
        "missing_core_files": missing_core_files,
    }


def build_snapshot_index(root: Path, for_alphatenant: bool = False) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for snap_dir in snapshot_dirs(root):
        try:
            entry = build_snapshot_entry(root, snap_dir)
        except FileNotFoundError:
            continue
        if for_alphatenant and not entry["admission"]["allow_into_alphatenant"]:
            # Keep blocked entries visible to AlphaTenant only when they have a stable dataset key.
            entries.append(entry)
        else:
            entries.append(entry)

    if not entries:
        index_status = "blocked"
    elif any(e["status"] == "admitted" for e in entries) and all(not e.get("missing_core_files") for e in entries):
        index_status = "ready"
    elif any(e["status"] in {"admitted", "partial"} for e in entries):
        index_status = "partial"
    else:
        index_status = "blocked"

    return {
        "schema_version": "datagoverned.snapshot_index.v0",
        "publisher": "DataGovernedForBTC",
        "generated_at_utc": utc_now_iso(),
        "project_root": str(root),
        "consumer_contract": "alphatenant.governed_snapshot.v0" if for_alphatenant else "datagoverned.snapshot_index.v0",
        "index_status": index_status,
        "snapshot_count": len(entries),
        "snapshots": entries,
        "git_commit": git_commit(root),
        "generator": {
            "name": "datagovernedforbtc.snapshot.build_snapshot_index",
            "command": "snapshot-list --for-alphatenant --format json" if for_alphatenant else "snapshot-list --format json",
        },
    }


def write_snapshot_index(root: Path, for_alphatenant: bool = True) -> dict[str, Any]:
    index = build_snapshot_index(root, for_alphatenant=for_alphatenant)
    index_path = root / "snapshots" / "snapshot_index.json"
    write_json(index_path, index)
    return {
        "index_path": str(index_path),
        "schema_version": index["schema_version"],
        "snapshot_count": index["snapshot_count"],
        "index_status": index["index_status"],
    }


def format_snapshot_index_table(index: dict[str, Any]) -> str:
    columns = ["dataset_key", "status", "readiness", "interval", "start_time_utc", "end_time_utc", "row_count", "allowed_rows", "blocked_rows"]
    rows = [[str(entry.get(col, "")) for col in columns] for entry in index.get("snapshots", [])]
    widths = [len(col) for col in columns]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))
    header = " | ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    sep = "-+-".join("-" * w for w in widths)
    body = [" | ".join(value.ljust(widths[i]) for i, value in enumerate(row)) for row in rows]
    return "\n".join([header, sep, *body]) + "\n"


def run_snapshot_list(root: Path, for_alphatenant: bool = False, output_format: str = "json") -> str:
    index = build_snapshot_index(root, for_alphatenant=for_alphatenant)
    if for_alphatenant:
        write_json(root / "snapshots" / "snapshot_index.json", index)
    if output_format == "json":
        return json.dumps(index, ensure_ascii=False, indent=2)
    if output_format == "table":
        return format_snapshot_index_table(index)
    raise ValueError(f"unsupported snapshot-list format: {output_format}")


def run_snapshot_admission(root: Path, label: str, snapshot_id: str | None = None) -> dict[str, Any]:
    snapshot_id = snapshot_id or f"okx_btc_market_state_1m_v0_1_{label}"
    curated_path = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=curated_btc_market_state" / "interval=1m" / f"sample={label}" / "curated_btc_market_state_1m.csv"
    summary_path = root / "reports" / "quality" / f"curated_state_window_{label}_summary.json"
    if not curated_path.exists():
        raise FileNotFoundError(f"curated state not found: {curated_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"curated quality summary not found: {summary_path}")
    columns, rows = read_curated_rows(curated_path)
    summary = read_json(summary_path)
    snapshot_dir = root / "snapshots" / "exchange=okx" / "instrument=BTC-USDT" / "interval=1m" / f"snapshot_id={snapshot_id}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    snapshot_curated = snapshot_dir / "curated_btc_market_state_1m.csv"
    shutil.copy2(curated_path, snapshot_curated)
    quality_summary_path = snapshot_dir / "quality_summary.json"
    write_json(quality_summary_path, summary)

    report = compute_admission_report(snapshot_id=snapshot_id, label=label, summary=summary, columns=columns, rows=rows)
    write_json(snapshot_dir / "data_admission_report.json", report)

    schema = build_schema(columns)
    write_json(snapshot_dir / "schema.json", schema)

    source_manifest = {
        "snapshot_id": snapshot_id,
        "curated_source": {
            "label": label,
            "path": str(curated_path),
            "sha256": sha256_file(curated_path),
            "copied_to": str(snapshot_curated),
            "copied_sha256": sha256_file(snapshot_curated),
        },
        "quality_summary_source": {
            "path": str(summary_path),
            "sha256": sha256_file(summary_path),
            "copied_to": str(quality_summary_path),
            "copied_sha256": sha256_file(quality_summary_path),
        },
        "raw_sources_included_directly": False,
        "raw_zone_path": str(root / "okx"),
        "raw_zone_access_allowed_for_alphatenant": False,
    }
    write_json(snapshot_dir / "source_manifest.json", source_manifest)
    write_feature_contract(snapshot_dir / "feature_contract.md", report, schema)
    write_forbidden_policy(snapshot_dir / "forbidden_raw_access_policy.md")

    result = {
        "snapshot_id": snapshot_id,
        "snapshot_dir": str(snapshot_dir),
        "curated_rows": len(rows),
        "allow_into_feature_layer_rows": report["allow_into_feature_layer_rows"],
        "blocked_rows": report["blocked_rows"],
        "future_leak_violation_count": report["future_leak_violation_count"],
        "alpha_tenant_readiness": report["alpha_tenant_readiness"],
        "required_alpha_tenant_filter": report["required_alpha_tenant_filter"],
    }
    write_json(snapshot_dir / "snapshot_summary.json", result)
    return result
