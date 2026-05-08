from pathlib import Path
import json
import tempfile
import unittest

from datagovernedforbtc.orderbook import process_orderbook_file


class OrderbookAuditTest(unittest.TestCase):
    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def test_flags_update_without_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Orderbook" / "Spot" / "2026" / "BTC-USDT-L2orderbook-400lv-2026-05-01.data"
            self.write_jsonl(p, [
                {"instId": "BTC-USDT", "action": "update", "ts": "1000", "asks": [["101", "1", "1"]], "bids": [["100", "1", "1"]]},
            ])

            manifest, quality, features = process_orderbook_file(p, root, max_lines=10)

            self.assertEqual(manifest["parse_status"], "success")
            self.assertEqual(manifest["source_market_type"], "spot")
            self.assertEqual(quality["update_without_snapshot_count"], 1)
            self.assertEqual(quality["snapshot_count"], 0)
            self.assertEqual(quality["book_reconstruction_quality"], "unusable_no_snapshot")
            self.assertEqual(features, [])

    def test_snapshot_feature_and_crossed_book_detection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "okx" / "Orderbook" / "Spot" / "2026" / "BTC-USDT-L2orderbook-400lv-2026-05-01.data"
            self.write_jsonl(p, [
                {"instId": "BTC-USDT", "action": "snapshot", "ts": "1000", "asks": [["101", "2", "3"], ["102", "1", "1"]], "bids": [["100", "1.5", "2"], ["99", "0.5", "1"]]},
                {"instId": "BTC-USDT", "action": "snapshot", "ts": "2000", "asks": [["100", "1", "1"]], "bids": [["101", "1", "1"]]},
            ])

            manifest, quality, features = process_orderbook_file(p, root, max_lines=10)

            self.assertEqual(quality["snapshot_count"], 2)
            self.assertEqual(quality["crossed_book_count"], 1)
            self.assertEqual(quality["min_ask_depth_levels"], 1)
            self.assertEqual(quality["min_bid_depth_levels"], 1)
            self.assertEqual(features[0]["best_bid"], "100")
            self.assertEqual(features[0]["best_ask"], "101")
            self.assertEqual(features[0]["spread_abs"], "1")
            self.assertEqual(features[0]["feature_time_ms"], 1000)
            self.assertEqual(features[0]["available_time_ms"], 1000)
            self.assertEqual(features[0]["book_reconstruction_quality"], "snapshot_only_sample")


if __name__ == "__main__":
    unittest.main()
