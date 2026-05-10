from pathlib import Path
import csv
import tempfile
import unittest

from datagovernedforbtc.candlestick import process_candlestick_file, run_candlestick_minimal


class CandlestickGovernanceTest(unittest.TestCase):
    def write_candles(self, path: Path, row_count: int = 1440, confirm: str = "0", duplicate_exact_count: int = 0, duplicate_conflict: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        start_ms = 1716134400000
        rows = []
        for i in range(row_count):
            px = 66800 + i * 0.1
            rows.append([
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
        for i in range(duplicate_exact_count):
            dup = list(rows[i])
            if duplicate_conflict:
                dup[4] = "99999.9"
            rows.append(dup)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["instrument_name", "open", "high", "low", "close", "vol", "vol_ccy", "vol_quote", "open_time", "confirm"])
            w.writerows(rows)

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
    def test_exact_duplicate_candles_are_deduplicated_with_quality_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Candlesticks" / "Spot" / "2024" / "BTC-USDT-candlesticks-2024-06-25.csv"
            self.write_candles(p, row_count=1440, confirm="0", duplicate_exact_count=45)

            _, quality, normalized = process_candlestick_file(p, root)

            self.assertEqual(quality["row_count"], 1485)
            self.assertEqual(quality["deduplicated_row_count"], 1440)
            self.assertEqual(quality["exact_duplicate_open_time_count"], 45)
            self.assertIn("exact_duplicate_open_time_deduplicated", quality["data_quality_flags"])
            self.assertTrue(quality["allow_into_training"])
            self.assertEqual(len(normalized), 1440)

    def test_conflicting_duplicate_candles_remain_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Candlesticks" / "Spot" / "2024" / "BTC-USDT-candlesticks-2024-06-25.csv"
            self.write_candles(p, row_count=1440, confirm="0", duplicate_exact_count=1, duplicate_conflict=True)

            _, quality, normalized = process_candlestick_file(p, root)

            self.assertIn("duplicate_open_time_detected", quality["data_quality_flags"])
            self.assertIn("conflicting_duplicate_open_time_detected", quality["data_quality_flags"])
            self.assertFalse(quality["allow_into_training"])
            self.assertEqual(normalized, [])
    def test_blocked_candlestick_run_removes_stale_normalized_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Candlesticks" / "Spot" / "2024" / "BTC-USDT-candlesticks-2024-07-18.csv"
            self.write_candles(p, row_count=1440, confirm="0")
            run_candlestick_minimal(root)
            out = root / "data_lake/normalized/exchange=okx/dataset_type=candlestick/market=spot/instrument=BTC-USDT/interval=1m/exchange_date_utc8=2024-07-18/candlestick_normalized.csv"
            self.assertTrue(out.exists())

            # Rerun with the same source date now blocked by conflicting duplicate rows.
            self.write_candles(p, row_count=1440, confirm="0", duplicate_exact_count=1, duplicate_conflict=True)
            summary = run_candlestick_minimal(root)

            self.assertEqual(summary["blocked_count"], 1)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
