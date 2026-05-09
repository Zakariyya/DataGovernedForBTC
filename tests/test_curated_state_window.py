from pathlib import Path
import csv
import tempfile
import unittest

from datagovernedforbtc.curated_state import run_curated_state_window


class CuratedStateWindowTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def test_run_curated_state_window_uses_inclusive_date_range_and_writes_labelled_output(self):
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
            self.write_csv(root / "data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8=2024-05-20/trade_features_1m.csv", [{"instrument_name": "BTC-USDT", "available_time_ms": 60000, "feature_time_ms": 60000, "trade_count_1m": 2, "volume_delta_1m": "1", "data_quality_score": "1.0"}])

            summary = run_curated_state_window(root, start_date="2024-05-20", end_date="2024-05-20", label="unit")

            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["allow_into_feature_layer_rows"], 1)
            self.assertTrue(Path(summary["output"]).exists())
            self.assertIn("sample=unit", summary["output"])


if __name__ == "__main__":
    unittest.main()
