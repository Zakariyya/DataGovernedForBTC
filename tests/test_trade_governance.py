from pathlib import Path
import csv
import tempfile
import unittest

from datagovernedforbtc.trade import process_trade_file, aggregate_trade_1m


class TradeGovernanceTest(unittest.TestCase):
    def write_trade_csv(self, path: Path) -> None:
        rows = [
            # intentionally unsorted
            ["BTC-USDT", "t3", "buy", "101", "0.50", "60000"],
            ["BTC-USDT", "t1", "buy", "100", "0.10", "0"],
            ["BTC-USDT", "t2", "sell", "99", "0.20", "59999"],
            ["BTC-USDT", "t2", "sell", "99", "0.20", "59999"],  # duplicate trade_id
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["instrument_name", "trade_id", "side", "price", "size", "created_time"])
            w.writerows(rows)

    def test_trade_normalization_sorts_deduplicates_and_preserves_side_raw(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Trade" / "Spot" / "2026" / "BTC-USDT-trades-2026-05-01.csv"
            p.parent.mkdir(parents=True)
            self.write_trade_csv(p)

            manifest, quality, normalized = process_trade_file(p, root)

            self.assertEqual(manifest["parse_status"], "success")
            self.assertEqual(manifest["source_market_type"], "spot")
            self.assertEqual(manifest["instrument_type"], "spot")
            self.assertEqual(quality["duplicate_trade_id_count"], 1)
            self.assertEqual([r["trade_id"] for r in normalized], ["t1", "t2", "t3"])
            self.assertEqual([r["event_time_ms"] for r in normalized], [0, 59999, 60000])
            self.assertIn("side_raw", normalized[0])
            self.assertNotIn("aggressive_buy_volume", normalized[0])
            self.assertEqual(normalized[0]["available_time_ms"], normalized[0]["event_time_ms"])

    def test_trade_1m_aggregation_uses_window_end_feature_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Trade" / "Spot" / "2026" / "BTC-USDT-trades-2026-05-01.csv"
            p.parent.mkdir(parents=True)
            self.write_trade_csv(p)
            _, _, normalized = process_trade_file(p, root)

            features = aggregate_trade_1m(normalized)

            self.assertEqual(len(features), 2)
            first = features[0]
            self.assertEqual(first["window_start_ms"], 0)
            self.assertEqual(first["window_end_ms"], 60000)
            self.assertEqual(first["feature_time_ms"], 60000)
            self.assertEqual(first["available_time_ms"], 60000)
            self.assertEqual(first["trade_count_1m"], 2)
            self.assertEqual(first["buy_trade_count_1m"], 1)
            self.assertEqual(first["sell_trade_count_1m"], 1)
            self.assertEqual(first["buy_volume_1m"], "0.1")
            self.assertEqual(first["sell_volume_1m"], "0.2")
            self.assertNotIn("aggressive_delta", first)


if __name__ == "__main__":
    unittest.main()
