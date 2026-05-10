from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.curated_state import (
    run_curated_state_day,
    run_curated_state_window_finalize,
)


class CuratedStateDayFinalizeTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def seed_day(self, root: Path, date: str, feature_time_ms: int, close: str = "100.5") -> None:
        candle = {
            "exchange": "okx",
            "instrument_name": "BTC-USDT",
            "source_market_type": "spot",
            "close_time_ms": feature_time_ms,
            "available_time_ms": feature_time_ms,
            "open": "100",
            "high": "101",
            "low": "99",
            "close": close,
            "vol_base": "10",
            "vol_quote": "1000",
            "data_quality_score": "1.0",
        }
        self.write_csv(root / f"data_lake/normalized/exchange=okx/dataset_type=candlestick/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8={date}/candlestick_normalized.csv", [candle])
        self.write_csv(root / f"data_lake/normalized/exchange=okx/dataset_type=funding_rate/market=perpetual/exchange_date_utc8={date}/funding_normalized.csv", [
            {"instrument_name": "BTC-USDT-SWAP", "available_time_ms": feature_time_ms, "realized_funding_rate": "0.001", "funding_interval_ms": "28800000", "data_quality_score": "1.0"}
        ])
        self.write_csv(root / f"data_lake/normalized/exchange=okx/dataset_type=borrowing_rate/market=spot/exchange_date_utc8={date}/borrowing_normalized.csv", [
            {"currency_name": "BTC", "available_time_ms": feature_time_ms, "borrow_rate_raw": "0.01", "data_quality_score": "1.0"},
            {"currency_name": "ETH", "available_time_ms": feature_time_ms, "borrow_rate_raw": "0.02", "data_quality_score": "1.0"},
            {"currency_name": "USDT", "available_time_ms": feature_time_ms, "borrow_rate_raw": "0.03", "data_quality_score": "1.0"},
        ])
        self.write_csv(root / f"data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8={date}/trade_features_1m.csv", [
            {"instrument_name": "BTC-USDT", "available_time_ms": feature_time_ms, "feature_time_ms": feature_time_ms, "trade_count_1m": 2, "buy_volume_1m": "0.1", "sell_volume_1m": "0.2", "volume_delta_1m": "-0.1", "data_quality_score": "1.0"}
        ])
        self.write_csv(root / f"data_lake/features/exchange=okx/dataset_type=orderbook_feature/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8={date}/orderbook_features_1m.csv", [
            {"instrument_name": "BTC-USDT", "available_time_ms": feature_time_ms, "feature_time_ms": feature_time_ms, "best_bid_last": "100", "best_ask_last": "101", "mid_price_last": "100.5", "spread_abs_last": "1", "spread_pct_last": "0.01", "top20_depth_imbalance_last": "0", "orderbook_update_count_1m": 10, "orderbook_snapshot_count_1m": 1, "orderbook_quality_score": "1.0", "book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum", "is_crossed_book_last": False}
        ])

    def test_curated_state_day_writes_date_partition_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.seed_day(root, "2024-05-20", 60000)

            summary = run_curated_state_day(root, date="2024-05-20", label="unit_day")

            out = Path(summary["output"])
            self.assertTrue(out.exists())
            self.assertIn("sample=unit_day", str(out))
            self.assertIn("exchange_date_utc8=2024-05-20", str(out))
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["allow_into_feature_layer_rows"], 1)
            with out.open(newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["orderbook_feature_missing_reason"], "")
            self.assertEqual(row["allow_into_feature_layer"], "True")

    def test_curated_state_window_finalize_combines_existing_day_partitions_without_raw_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.seed_day(root, "2024-05-20", 60000, close="100.5")
            self.seed_day(root, "2024-05-21", 120000, close="101.5")
            run_curated_state_day(root, date="2024-05-20", label="unit_window")
            run_curated_state_day(root, date="2024-05-21", label="unit_window")

            summary = run_curated_state_window_finalize(root, start_date="2024-05-20", end_date="2024-05-21", label="unit_window")

            out = Path(summary["output"])
            self.assertTrue(out.exists())
            self.assertEqual(summary["day_partitions_used"], 2)
            self.assertEqual(summary["row_count"], 2)
            self.assertEqual(summary["allow_into_feature_layer_rows"], 2)
            with out.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual([row["close"] for row in rows], ["100.5", "101.5"])

    def test_curated_state_window_finalize_fails_closed_when_any_day_partition_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.seed_day(root, "2024-05-20", 60000, close="100.5")
            self.seed_day(root, "2024-05-21", 120000, close="101.5")
            run_curated_state_day(root, date="2024-05-20", label="missing_window")
            run_curated_state_day(root, date="2024-05-21", label="missing_window")
            existing = run_curated_state_window_finalize(root, start_date="2024-05-20", end_date="2024-05-21", label="missing_window")
            out = Path(existing["output"])
            self.assertTrue(out.exists())
            missing_day_out = root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m/sample=missing_window/exchange_date_utc8=2024-05-21/curated_btc_market_state_1m.csv"
            missing_day_out.unlink()

            with self.assertRaisesRegex(ValueError, "missing curated day partitions"):
                run_curated_state_window_finalize(root, start_date="2024-05-20", end_date="2024-05-21", label="missing_window")

            self.assertFalse(out.exists())

    def test_curated_state_day_can_asof_join_previous_day_low_frequency_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Seed current day candle/trade/orderbook only, then provide funding/borrow from previous day.
            self.seed_day(root, "2024-05-20", 60000)
            current_funding = root / "data_lake/normalized/exchange=okx/dataset_type=funding_rate/market=perpetual/exchange_date_utc8=2024-05-20/funding_normalized.csv"
            current_borrow = root / "data_lake/normalized/exchange=okx/dataset_type=borrowing_rate/market=spot/exchange_date_utc8=2024-05-20/borrowing_normalized.csv"
            current_funding.unlink()
            current_borrow.unlink()
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=funding_rate/market=perpetual/exchange_date_utc8=2024-05-19/funding_normalized.csv", [
                {"instrument_name": "BTC-USDT-SWAP", "available_time_ms": 0, "realized_funding_rate": "0.009", "funding_interval_ms": "28800000", "data_quality_score": "1.0"}
            ])
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=borrowing_rate/market=spot/exchange_date_utc8=2024-05-19/borrowing_normalized.csv", [
                {"currency_name": "BTC", "available_time_ms": 0, "borrow_rate_raw": "0.09", "data_quality_score": "1.0"},
                {"currency_name": "ETH", "available_time_ms": 0, "borrow_rate_raw": "0.08", "data_quality_score": "1.0"},
                {"currency_name": "USDT", "available_time_ms": 0, "borrow_rate_raw": "0.07", "data_quality_score": "1.0"},
            ])

            summary = run_curated_state_day(root, date="2024-05-20", label="prev_lowfreq")

            with Path(summary["output"]).open(newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["last_realized_funding_rate"], "0.009")
            self.assertEqual(row["btc_borrow_rate_raw"], "0.09")
            self.assertEqual(row["allow_into_feature_layer"], "True")
    def test_curated_state_day_removes_stale_output_when_source_becomes_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.seed_day(root, "2024-05-20", 60000)
            first = run_curated_state_day(root, date="2024-05-20", label="stale_day")
            out = Path(first["output"])
            self.assertTrue(out.exists())

            candle = root / "data_lake/normalized/exchange=okx/dataset_type=candlestick/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8=2024-05-20/candlestick_normalized.csv"
            candle.unlink()
            second = run_curated_state_day(root, date="2024-05-20", label="stale_day")

            self.assertIsNone(second["output"])
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
