from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import read_csv_rows_from_path, sha256_file
from .path_semantics import infer_source_market_type
from .schemas import EXPECTED_COLUMNS

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

DATASET_DIRS = {
    "borrowing_rate": "Borrowrates",
    "candlestick": "Candlesticks",
    "funding_rate": "Fundingrates",
    "orderbook": "Orderbook",
    "trade": "Trade",
}

FILENAME_PATTERNS = {
    "borrowing_rate": re.compile(r"allmargin-borrowrates-(\d{4}-\d{2}-\d{2})\.csv$"),
    "candlestick": re.compile(r"BTC-USDT-candlesticks-(\d{4}-\d{2}-\d{2})\.(csv|zip)$"),
    "funding_rate": re.compile(r"allswap-fundingrates-(\d{4}-\d{2}-\d{2})\.csv$"),
    "orderbook": re.compile(r"BTC-USDT-L2orderbook-400lv-(\d{4}-\d{2}-\d{2})\.(data|data\.txt|zip)$"),
    "trade": re.compile(r"BTC-USDT-trades-(\d{4}-\d{2}-\d{2})\.csv$"),
}

TIME_COLUMNS = {
    "borrowing_rate": "time",
    "candlestick": "open_time",
    "funding_rate": "funding_time",
    "orderbook": "ts",
    "trade": "created_time",
}


def source_file_date_from_name(name: str) -> str | None:
    m = DATE_RE.search(name)
    return m.group(1) if m else None


def utc_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def read_header_and_sample(path: Path, max_rows: int = 5000, dataset_type: str | None = None) -> tuple[list[str], list[dict[str, str]], str | None]:
    if dataset_type == "orderbook" and path.suffix.lower() in {".data", ".txt"}:
        rows: list[dict[str, str]] = []
        header_keys: set[str] = set()
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_rows:
                    break
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                row = {k: obj.get(k) for k in ["instId", "action", "asks", "bids", "ts"]}
                rows.append(row)  # type: ignore[arg-type]
                header_keys.update(obj.keys())
        ordered = [k for k in ["instId", "action", "asks", "bids", "ts"] if k in header_keys]
        return ordered, rows, None
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            csv_names = [n for n in names if n.lower().endswith(".csv")]
            if not csv_names:
                return [], [], None
            inner = csv_names[0]
            text = zf.read(inner).decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row)
            return list(reader.fieldnames or []), rows, inner
    if path.suffix.lower() in {".csv", ".txt", ".data"}:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append(row)
            return list(reader.fieldnames or []), rows, None
    return [], [], None


def audit_file(dataset_type: str, path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_file_name": path.name,
        "source_file_path": str(path),
        "source_market_type": infer_source_market_type(path),
        "source_file_date": source_file_date_from_name(path.name),
        "file_size_bytes": path.stat().st_size,
        "source_file_hash": sha256_file(path),
        "schema_status": "unknown",
        "parse_status": "unknown",
        "parse_error_message": None,
        "row_sample_count": 0,
        "min_event_time_ms_sample": None,
        "max_event_time_ms_sample": None,
        "min_event_time_utc_sample": None,
        "max_event_time_utc_sample": None,
        "missing_columns": [],
        "extra_columns": [],
        "future_leak_risks": [],
    }
    try:
        header, rows, inner = read_header_and_sample(path, dataset_type=dataset_type)
        result["zip_inner_csv"] = inner
        expected = EXPECTED_COLUMNS.get(dataset_type, [])
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        result["missing_columns"] = missing
        result["extra_columns"] = extra
        result["schema_status"] = "match" if not missing else "missing_columns"
        result["parse_status"] = "success"
        result["row_sample_count"] = len(rows)
        tcol = TIME_COLUMNS.get(dataset_type)
        times = []
        if tcol and tcol in header:
            for r in rows:
                v = r.get(tcol)
                if v not in (None, ""):
                    try:
                        times.append(int(float(v)))
                    except ValueError:
                        pass
        if times:
            result["min_event_time_ms_sample"] = min(times)
            result["max_event_time_ms_sample"] = max(times)
            result["min_event_time_utc_sample"] = utc_iso(min(times))
            result["max_event_time_utc_sample"] = utc_iso(max(times))
            result["out_of_order_time_count_sample"] = sum(1 for a, b in zip(times, times[1:]) if b < a)
        # risk flags by dataset semantics
        if dataset_type == "candlestick":
            result["future_leak_risks"].append("open_time_is_bar_start; features must use close_time_ms=open_time+60000, not open_time")
            result["future_leak_risks"].append("confirm=0 rows must be excluded from historical training")
        elif dataset_type == "funding_rate":
            result["future_leak_risks"].append("funding_rate is realized settlement; do not rename/use as predicted_funding_rate")
            result["future_leak_risks"].append("available_time_ms must be funding_time + configured_latency_ms")
        elif dataset_type == "borrowing_rate":
            result["future_leak_risks"].append("borrow_rate unit is unknown_raw unless explicitly configured; do not annualize silently")
            result["future_leak_risks"].append("as-of joined borrow rates require age_ms and max-age cutoff")
        elif dataset_type == "trade":
            result["future_leak_risks"].append("side semantics are not assumed taker side; do not create aggressive volume without config")
            result["future_leak_risks"].append("tick data must be aggregated before AlphaTenant use")
        elif dataset_type == "orderbook":
            result["future_leak_risks"].append("update cannot be applied without same-instrument prior snapshot")
            result["future_leak_risks"].append("no sequence/checksum means reconstruction continuity is not provable")
        return result
    except Exception as e:
        result["parse_status"] = "error"
        result["parse_error_message"] = str(e)
        result["schema_status"] = "unknown_error"
        return result


def contiguous_date_gaps(dates: list[str]) -> list[dict[str, str | int]]:
    parsed = sorted(datetime.fromisoformat(d).date() for d in set(dates))
    gaps = []
    for a, b in zip(parsed, parsed[1:]):
        diff = (b - a).days
        if diff > 1:
            gaps.append({"previous_date": a.isoformat(), "next_date": b.isoformat(), "missing_days": diff - 1})
    return gaps


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown_report(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# OKX 历史数据目录审计报告",
        "",
        f"生成时间 UTC：{audit['generated_at_utc']}",
        f"项目根目录：`{audit['root']}`",
        "",
        "## 总览",
        "",
        "| dataset_type | file_count | market_type_counts | min_source_file_date | max_source_file_date | schema_match_files | parse_error_files | date_gap_count |",
        "|---|---:|---|---|---|---:|---:|---:|",
    ]
    for ds, s in audit["datasets"].items():
        lines.append(f"| {ds} | {s['file_count']} | {s.get('market_type_counts')} | {s.get('min_source_file_date')} | {s.get('max_source_file_date')} | {s['schema_match_files']} | {s['parse_error_files']} | {len(s['date_gaps'])} |")
    lines.extend(["", "## Future-Leak 风险提示", ""])
    for ds, s in audit["datasets"].items():
        lines.append(f"### {ds}")
        risks = sorted(set(r for f in s["sample_file_audits"] for r in f.get("future_leak_risks", [])))
        for r in risks:
            lines.append(f"- {r}")
        if not risks:
            lines.append("- 未在样本审计中发现额外语义风险提示。")
        lines.append("")
    lines.extend(["## 日期缺口", ""])
    for ds, s in audit["datasets"].items():
        lines.append(f"### {ds}")
        if s["date_gaps"]:
            for g in s["date_gaps"][:50]:
                lines.append(f"- {g['previous_date']} -> {g['next_date']} 缺 {g['missing_days']} 天")
        else:
            lines.append("- 样本文件名日期范围内未发现日期断点。")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_okx_audit(root: Path) -> dict[str, Any]:
    okx = root / "okx"
    audit: dict[str, Any] = {
        "root": str(root),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "datasets": {},
    }
    for ds, dirname in DATASET_DIRS.items():
        d = okx / dirname
        files = sorted([p for p in d.rglob("*") if p.is_file()]) if d.exists() else []
        dates = [source_file_date_from_name(p.name) for p in files]
        dates = [x for x in dates if x]
        sample_audits = [audit_file(ds, p) for p in files[:20]]
        # include newest 20 as well if many files
        if len(files) > 20:
            seen = {a["source_file_path"] for a in sample_audits}
            for p in files[-20:]:
                if str(p) not in seen:
                    sample_audits.append(audit_file(ds, p))
        audit["datasets"][ds] = {
            "source_dir": str(d),
            "exists": d.exists(),
            "file_count": len(files),
            "min_source_file_date": min(dates) if dates else None,
            "max_source_file_date": max(dates) if dates else None,
            "date_gaps": contiguous_date_gaps(dates),
            "schema_match_files": sum(1 for a in sample_audits if a.get("schema_status") == "match"),
            "parse_error_files": sum(1 for a in sample_audits if a.get("parse_status") == "error"),
            "extensions": dict(sorted({p.suffix.lower(): sum(1 for x in files if x.suffix.lower() == p.suffix.lower()) for p in files}.items())),
            "market_type_counts": dict(sorted({m: sum(1 for p in files if infer_source_market_type(p) == m) for m in {infer_source_market_type(p) for p in files}}.items())),
            "sample_file_audits": sample_audits,
        }
    json_path = root / "reports" / "coverage" / "okx_directory_audit.json"
    md_path = root / "reports" / "coverage" / "okx_directory_audit.md"
    write_json(json_path, audit)
    write_markdown_report(md_path, audit)
    audit["json_report_path"] = str(json_path)
    audit["markdown_report_path"] = str(md_path)
    return audit
