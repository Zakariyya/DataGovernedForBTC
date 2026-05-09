from pathlib import Path
import csv
import tempfile
import unittest

from datagovernedforbtc.candlestick import process_candlestick_file


class CandlestickGovernanceTest(unittest.TestCase):
    def write_candles(self, path: Path, row_count: int = 1440, confirm: str = "0") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        start_ms = 1716134400000
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["instrument_name", "open", "high", "low", "close", "vol", "vol_ccy", "vol_quote", "open_time", "confirm"])
            for i in range(row_count):
                px = 66800 + i * 0.1
                w.writerow([
                    "BTC-USDT",
                    f"{px:.1f}",
                    f"{px + 2:.1f}",
                    f"{px - 2:.1f}",
                    f"{px + 0.5:.1f}",
                    "1.0",
                    "66800.0",
                    "66800.0",
                    str(start_ms + i * 60000),
                    confirm,
                ])

    def test_complete_historical_archive_confirm_0_is_policy_accepted_without_rewriting_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Candlesticks" / "Spot" / "2024" / "BTC-USDT-candlesticks-2024-05-20.csv"
            self.write_candles(p, row_count=1440, confirm="0")

            manifest, quality, normalized = process_candlestick_file(p, root)

            self.assertEqual(manifest["parse_status"], "success")
            self.assertEqual(quality["confirm_0_count"], 1440)
            self.assertEqual(quality["confirm_1_count"], 0)
            self.assertEqual(quality["source_archive_confirm_policy"], "historical_archive_confirm_0_closed_bar_by_complete_daily_file")
            self.assertIn("source_archive_confirm_0_closed_bar_inferred", quality["data_quality_flags"])
            self.assertTrue(quality["allow_into_training"])
            self.assertEqual(len(normalized), 1440)
            self.assertEqual(normalized[0]["confirm"], 0)
            self.assertEqual(normalized[0]["source_archive_confirm_policy"], "historical_archive_confirm_0_closed_bar_by_complete_daily_file")
            self.assertIn("source_archive_confirm_0_closed_bar_inferred", normalized[0]["data_quality_flags"])

    def test_incomplete_historical_archive_confirm_0_stays_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Candlesticks" / "Spot" / "2024" / "BTC-USDT-candlesticks-2024-05-20.csv"
            self.write_candles(p, row_count=1439, confirm="0")

            _, quality, normalized = process_candlestick_file(p, root)

            self.assertEqual(quality["source_archive_confirm_policy"], "unresolved_confirm_0")
            self.assertIn("confirm_0_unresolved", quality["data_quality_flags"])
            self.assertFalse(quality["allow_into_training"])
            self.assertEqual(normalized, [])


if __name__ == "__main__":
    unittest.main()
