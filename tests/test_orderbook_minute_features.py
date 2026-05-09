from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from datagovernedforbtc.curated_state import build_curated_market_state_1m
from datagovernedforbtc.orderbook import process_orderbook_minute_feature_file


class OrderbookMinuteFeatureTest(unittest.TestCase):
    def write_tar_jsonl(self, path: Path, member_name: str, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(r) + "\n" for r in rows).encode("utf-8")
        mode = "w:gz" if path.name.endswith(".gz") else "w"
        with tarfile.open(path, mode) as tar:
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            tar.addfile(info, BytesIO(payload))

    def test_archived_orderbook_updates_reconstruct_last_book_per_minute_with_quality_label(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "okx" / "Orderbook" / "Spot" / "2024" / "BTC-USDT-L2orderbook-400lv-2024-05-20.tar.tar"
            self.write_tar_jsonl(archive, "BTC-USDT-L2orderbook-400lv-2024-05-20.data", [
                {"instId": "BTC-USDT", "action": "snapshot", "ts": "1716163200000", "asks": [["101", "2", "1"]], "bids": [["100", "3", "1"]]},
                {"instId": "BTC-USDT", "action": "update", "ts": "1716163205000", "asks": [["101", "0", "0"], ["102", "5", "1"]], "bids": [["100", "4", "1"]]},
                {"instId": "BTC-USDT", "action": "update", "ts": "1716163261000", "asks": [["102", "6", "1"]], "bids": [["99", "1", "1"]]},
            ])

            manifest, quality, features = process_orderbook_minute_feature_file(archive, root)

        self.assertEqual(manifest["parse_status"], "success")
        self.assertEqual(quality["book_reconstruction_quality"], "best_effort_reconstructed_without_sequence_checksum")
        self.assertEqual(len(features), 2)
        self.assertEqual(features[0]["feature_time_ms"], 1716163260000)
        self.assertEqual(features[0]["best_bid_last"], "100")
        self.assertEqual(features[0]["best_ask_last"], "102")
        self.assertEqual(features[0]["spread_abs_last"], "2")
        self.assertEqual(features[0]["top20_bid_depth_last"], "4")
        self.assertEqual(features[0]["top20_ask_depth_last"], "5")
        self.assertEqual(features[0]["orderbook_update_count_1m"], 1)
        self.assertEqual(features[0]["orderbook_snapshot_count_1m"], 1)
        self.assertEqual(features[0]["orderbook_quality_score"], "1.0")
        self.assertEqual(features[1]["feature_time_ms"], 1716163320000)
        self.assertEqual(features[1]["best_bid_last"], "100")
        self.assertEqual(features[1]["best_ask_last"], "102")
        self.assertEqual(features[1]["orderbook_update_count_1m"], 1)

    def test_tar_tar_extension_may_contain_gzip_tar_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "okx" / "Orderbook" / "Spot" / "2024" / "BTC-USDT-L2orderbook-400lv-2024-05-20.tar.tar"
            archive.parent.mkdir(parents=True, exist_ok=True)
            payload = (json.dumps({"instId": "BTC-USDT", "action": "snapshot", "ts": "1716163200000", "asks": [["101", "2", "1"]], "bids": [["100", "3", "1"]]}) + "\n").encode("utf-8")
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("BTC-USDT-L2orderbook-400lv-2024-05-20.data")
                info.size = len(payload)
                tar.addfile(info, BytesIO(payload))

            manifest, quality, features = process_orderbook_minute_feature_file(archive, root)

        self.assertEqual(manifest["parse_status"], "success")
        self.assertEqual(len(features), 1)

    def test_curated_state_requires_current_orderbook_feature_when_orderbook_rows_are_supplied(self):
        candles = [
            {"instrument_name": "BTC-USDT", "close_time_ms": 1716163260000, "open": "1", "high": "1", "low": "1", "close": "1"},
            {"instrument_name": "BTC-USDT", "close_time_ms": 1716163320000, "open": "1", "high": "1", "low": "1", "close": "1"},
        ]
        orderbook = [
            {"feature_time_ms": 1716163260000, "available_time_ms": 1716163260000, "best_bid_last": "100", "best_ask_last": "102", "spread_pct_last": "0.0198", "orderbook_quality_score": "1.0", "book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum"},
        ]

        rows = build_curated_market_state_1m(candles, orderbook_feature_rows=orderbook)

        self.assertEqual(rows[0]["orderbook_feature_missing_reason"], "")
        self.assertEqual(rows[0]["orderbook_best_bid_last"], "100")
        self.assertNotIn("orderbook_feature_missing", rows[0]["data_quality_flags"])
        self.assertEqual(rows[1]["orderbook_feature_missing_reason"], "no_current_orderbook_feature")
        self.assertIn("orderbook_feature_missing", rows[1]["data_quality_flags"])
        self.assertFalse(rows[1]["allow_into_feature_layer"])


if __name__ == "__main__":
    unittest.main()
