from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.curated_state import run_curated_state_window
from datagovernedforbtc.io_utils import write_parquet_rows


class CuratedStateParquetTradeFeatureTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def test_curated_state_window_reads_trade_feature_parquet_when_csv_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candle = {
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "source_market_type": "spot",
                "close_time_ms": 60000,
                "available_time_ms": 60000,
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "vol_base": "10",
                "vol_quote": "1000",
                "data_quality_score": "1.0",
            }
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=candlestick/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8=2024-05-20/candlestick_normalized.csv", [candle])
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=funding_rate/market=perpetual/exchange_date_utc8=2024-05-20/funding_normalized.csv", [{"instrument_name": "BTC-USDT-SWAP", "available_time_ms": 60000, "realized_funding_rate": "0.001", "funding_interval_ms": "28800000", "data_quality_score": "1.0"}])
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=borrowing_rate/market=spot/exchange_date_utc8=2024-05-20/borrowing_normalized.csv", [
                {"currency_name": "BTC", "available_time_ms": 60000, "borrow_rate_raw": "0.01", "data_quality_score": "1.0"},
                {"currency_name": "ETH", "available_time_ms": 60000, "borrow_rate_raw": "0.02", "data_quality_score": "1.0"},
                {"currency_name": "USDT", "available_time_ms": 60000, "borrow_rate_raw": "0.03", "data_quality_score": "1.0"},
            ])
            write_parquet_rows(root / "data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/format=parquet/exchange_date_utc8=2024-05-20/trade_features_1m.parquet", [
                {"instrument_name": "BTC-USDT", "available_time_ms": 60000, "feature_time_ms": 60000, "trade_count_1m": 2, "buy_volume_1m": "0.1", "sell_volume_1m": "0.2", "volume_delta_1m": "-0.1", "data_quality_score": "1.0"}
            ])

            summary = run_curated_state_window(root, start_date="2024-05-20", end_date="2024-05-20", label="parquet_trade")

            self.assertEqual(summary["trade_feature_files_used"], 1)
            self.assertEqual(summary["allow_into_feature_layer_rows"], 1)
            out = Path(summary["output"])
            with out.open(newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["trade_count_1m"], "2")
            self.assertEqual(row["trade_feature_missing_reason"], "")


    def test_curated_state_prefers_parquet_over_legacy_csv_for_same_trade_partition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candle = {
                "exchange": "okx", "instrument_name": "BTC-USDT", "source_market_type": "spot",
                "close_time_ms": 60000, "available_time_ms": 60000,
                "open": "100", "high": "101", "low": "99", "close": "100.5",
                "vol_base": "10", "vol_quote": "1000", "data_quality_score": "1.0",
            }
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=candlestick/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8=2024-05-20/candlestick_normalized.csv", [candle])
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=funding_rate/market=perpetual/exchange_date_utc8=2024-05-20/funding_normalized.csv", [{"instrument_name": "BTC-USDT-SWAP", "available_time_ms": 60000, "realized_funding_rate": "0.001", "funding_interval_ms": "28800000", "data_quality_score": "1.0"}])
            self.write_csv(root / "data_lake/normalized/exchange=okx/dataset_type=borrowing_rate/market=spot/exchange_date_utc8=2024-05-20/borrowing_normalized.csv", [
                {"currency_name": "BTC", "available_time_ms": 60000, "borrow_rate_raw": "0.01", "data_quality_score": "1.0"},
                {"currency_name": "ETH", "available_time_ms": 60000, "borrow_rate_raw": "0.02", "data_quality_score": "1.0"},
                {"currency_name": "USDT", "available_time_ms": 60000, "borrow_rate_raw": "0.03", "data_quality_score": "1.0"},
            ])
            legacy_csv = root / "data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8=2024-05-20/trade_features_1m.csv"
            self.write_csv(legacy_csv, [{"instrument_name": "BTC-USDT", "available_time_ms": 60000, "feature_time_ms": 60000, "trade_count_1m": 999, "volume_delta_1m": "999", "data_quality_score": "0.1"}])
            write_parquet_rows(root / "data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/format=parquet/exchange_date_utc8=2024-05-20/trade_features_1m.parquet", [
                {"instrument_name": "BTC-USDT", "available_time_ms": 60000, "feature_time_ms": 60000, "trade_count_1m": 2, "volume_delta_1m": "-0.1", "data_quality_score": "1.0"}
            ])

            summary = run_curated_state_window(root, start_date="2024-05-20", end_date="2024-05-20", label="prefer_parquet_trade")

            self.assertEqual(summary["trade_feature_files_used"], 1)
            with Path(summary["output"]).open(newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["trade_count_1m"], "2")


if __name__ == "__main__":
    unittest.main()
