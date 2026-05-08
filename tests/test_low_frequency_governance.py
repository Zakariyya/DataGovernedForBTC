from pathlib import Path
import tempfile
import unittest

from datagovernedforbtc.low_frequency import process_borrowing_file, process_funding_file


class LowFrequencyGovernanceTest(unittest.TestCase):
    def test_funding_manifest_uses_realized_name_and_infers_interval(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "allswap-fundingrates-2026-05-01.csv"
            path.write_text(
                "instrument_name,funding_rate,funding_time\n"
                "BTC-USDT-SWAP,0.0001,1000\n"
                "BTC-USDT-SWAP,0.0002,28801000\n",
                encoding="utf-8",
            )
            manifest, quality, normalized = process_funding_file(path, Path(d))
        self.assertEqual(manifest["parse_status"], "success")
        self.assertEqual(manifest["dataset_type"], "funding_rate")
        self.assertEqual(quality["quality_level"], "official_realized")
        self.assertEqual(quality["inferred_funding_interval_ms_by_instrument"]["BTC-USDT-SWAP"], 28_800_000)
        self.assertIn("realized_funding_rate", normalized[0])
        self.assertNotIn("predicted_funding_rate", normalized[0])
        self.assertEqual(normalized[0]["available_time_ms"], 1000)

    def test_borrowing_preserves_raw_unit_unknown_and_counts_key_currencies(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "allmargin-borrowrates-2026-05-01.csv"
            path.write_text(
                "currency_name,borrow_rate,time\n"
                "BTC,0.01,1000\n"
                "ETH,0.02,1000\n"
                "USDT,0.03,1000\n",
                encoding="utf-8",
            )
            manifest, quality, normalized = process_borrowing_file(path, Path(d))
        self.assertEqual(manifest["parse_status"], "success")
        self.assertEqual(manifest["dataset_type"], "borrowing_rate")
        self.assertEqual(quality["present_key_currencies"], ["BTC", "ETH", "USDT"])
        self.assertEqual(normalized[0]["borrow_rate_unit"], "unknown_raw")
        self.assertIn("borrow_rate_raw", normalized[0])
        self.assertNotIn("annualized_borrow_rate", normalized[0])
        self.assertEqual(normalized[0]["available_time_ms"], 1000)


if __name__ == "__main__":
    unittest.main()
