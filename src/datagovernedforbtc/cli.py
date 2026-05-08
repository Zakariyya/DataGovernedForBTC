from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="datagovernedforbtc",
        description="OKX BTC market data governance system for AlphaTenant.",
    )
    parser.add_argument(
        "--root",
        default=str(Path.cwd()),
        help="DataGovernedForBTC project root. Default: current working directory.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("layout", help="Print the expected project data layout.")
    sub.add_parser("version", help="Print package version.")
    sub.add_parser("candlestick-minimal", help="Run Candlestick + File Manifest + Quality Report minimal loop.")
    sub.add_parser("simple-manifest-quality", help="Run Manifest + Quality Report loops for Funding/Borrowing/Trade.")
    sub.add_parser("low-frequency-minimal", help="Run Funding/Borrowing + File Manifest + Quality Report minimal loop.")
    trade_parser = sub.add_parser("trade-minimal", help="Run Trade + File Manifest + Quality Report + 1m feature minimal loop.")
    trade_parser.add_argument("--max-files", type=int, default=None, help="Optional safety limit for processing the first N trade files.")
    ob_parser = sub.add_parser("orderbook-audit", help="Run safe Orderbook JSONL audit without full L2 reconstruction.")
    ob_parser.add_argument("--max-lines", type=int, default=5000, help="Maximum JSONL rows per orderbook file to inspect.")
    ob_parser.add_argument("--max-files", type=int, default=None, help="Optional safety limit for processing the first N orderbook files.")
    cur_parser = sub.add_parser("curated-state-minimal", help="Build minimal curated_btc_market_state_1m sample with time-causal as-of joins.")
    cur_parser.add_argument("--max-candle-files", type=int, default=1, help="Number of normalized candle files to use.")
    cur_parser.add_argument("--max-trade-files", type=int, default=1, help="Number of trade feature files to use.")
    sub.add_parser("audit-okx", help="Audit current OKX historical data directory.")
    return parser


def print_layout(root: Path) -> None:
    print(f"DataGovernedForBTC root: {root}")
    print("raw source: okx/{Borrowrates,Candlesticks,Fundingrates,Orderbook,Trade}")
    print("manifests: manifests/exchange=okx/dataset_type=.../instrument=.../exchange_date_utc8=.../")
    print("normalized: data_lake/normalized/exchange=okx/dataset_type=.../")
    print("features: data_lake/features/exchange=okx/instrument=BTC-USDT/interval=1m/")
    print("regime: data_lake/regime/exchange=okx/instrument=BTC-USDT/interval=1m/")
    print("snapshots: snapshots/exchange=okx/instrument=BTC-USDT/interval=1m/snapshot_id=.../")
    print("reports: reports/{quality,coverage,gap,future_leak}/")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "layout":
        print_layout(root)
        return 0
    if args.command == "version":
        from datagovernedforbtc import __version__
        print(__version__)
        return 0
    if args.command == "candlestick-minimal":
        from datagovernedforbtc.candlestick import run_candlestick_minimal
        print(json.dumps(run_candlestick_minimal(root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "simple-manifest-quality":
        from datagovernedforbtc.simple_datasets import run_all_simple_manifest_quality
        print(json.dumps(run_all_simple_manifest_quality(root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "low-frequency-minimal":
        from datagovernedforbtc.low_frequency import run_low_frequency_minimal
        print(json.dumps(run_low_frequency_minimal(root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "trade-minimal":
        from datagovernedforbtc.trade import run_trade_minimal
        print(json.dumps(run_trade_minimal(root, max_files=args.max_files), ensure_ascii=False, indent=2))
        return 0
    if args.command == "orderbook-audit":
        from datagovernedforbtc.orderbook import run_orderbook_audit
        print(json.dumps(run_orderbook_audit(root, max_lines=args.max_lines, max_files=args.max_files), ensure_ascii=False, indent=2))
        return 0
    if args.command == "curated-state-minimal":
        from datagovernedforbtc.curated_state import run_curated_state_minimal
        print(json.dumps(run_curated_state_minimal(root, max_candle_files=args.max_candle_files, max_trade_files=args.max_trade_files), ensure_ascii=False, indent=2))
        return 0
    if args.command == "audit-okx":
        from datagovernedforbtc.audit import run_okx_audit
        print(json.dumps(run_okx_audit(root), ensure_ascii=False, indent=2))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
