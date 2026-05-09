from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from datagovernedforbtc.trade import run_trade_stream


class TradeStreamingCheckpointTest(unittest.TestCase):
    def write_trade_csv(self, path: Path, rows: list[list[object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["instrument_name", "trade_id", "side", "price", "size", "created_time"])
            w.writerows(rows)

    def test_trade_stream_writes_parquet_checkpoint_and_resume_skips_completed_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "okx" / "Trade" / "Spot" / "2024" / "BTC-USDT-trades-2024-05-20.csv"
            self.write_trade_csv(src, [
                ["BTC-USDT", "t2", "sell", "99", "0.20", "59999"],
                ["BTC-USDT", "t1", "buy", "100", "0.10", "0"],
                ["BTC-USDT", "t3", "buy", "101", "0.50", "60000"],
            ])

            first = run_trade_stream(
                root,
                start_date="2024-05-20",
                end_date="2024-05-20",
                market="spot",
                instrument="BTC-USDT",
                resume=True,
            )

            self.assertEqual(first["source_file_count"], 1)
            self.assertEqual(first["processed_count"], 1)
            self.assertEqual(first["skipped_count"], 0)
            self.assertEqual(first["total_normalized_rows"], 3)
            self.assertEqual(first["total_feature_rows_1m"], 2)
            output = first["outputs"][0]
            normalized_path = Path(output["normalized_parquet"])
            feature_path = Path(output["feature_parquet"])
            checkpoint_path = Path(output["checkpoint"])
            self.assertTrue(normalized_path.exists())
            self.assertTrue(feature_path.exists())
            self.assertTrue(checkpoint_path.exists())
            self.assertFalse(normalized_path.with_name("trade_normalized.csv").exists())
            self.assertEqual(pd.read_parquet(normalized_path).shape[0], 3)
            self.assertEqual(pd.read_parquet(feature_path).shape[0], 2)

            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["status"], "completed")
            self.assertEqual(checkpoint["source_file_hash"], output["source_file_hash"])
            self.assertEqual(checkpoint["normalized_rows"], 3)
            self.assertEqual(checkpoint["feature_rows_1m"], 2)
            self.assertIn("normalized_parquet_sha256", checkpoint)
            self.assertIn("feature_parquet_sha256", checkpoint)

            second = run_trade_stream(
                root,
                start_date="2024-05-20",
                end_date="2024-05-20",
                market="spot",
                instrument="BTC-USDT",
                resume=True,
            )
            self.assertEqual(second["processed_count"], 0)
            self.assertEqual(second["skipped_count"], 1)
            self.assertEqual(second["outputs"][0]["status"], "skipped_completed")

    def test_trade_stream_reprocesses_when_source_hash_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "okx" / "Trade" / "Spot" / "2024" / "BTC-USDT-trades-2024-05-20.csv"
            self.write_trade_csv(src, [["BTC-USDT", "t1", "buy", "100", "0.10", "0"]])
            first = run_trade_stream(root, start_date="2024-05-20", end_date="2024-05-20", market="spot", instrument="BTC-USDT", resume=True)
            first_hash = first["outputs"][0]["source_file_hash"]

            self.write_trade_csv(src, [
                ["BTC-USDT", "t1", "buy", "100", "0.10", "0"],
                ["BTC-USDT", "t2", "sell", "101", "0.20", "60000"],
            ])
            second = run_trade_stream(root, start_date="2024-05-20", end_date="2024-05-20", market="spot", instrument="BTC-USDT", resume=True)

            self.assertEqual(second["processed_count"], 1)
            self.assertEqual(second["skipped_count"], 0)
            self.assertNotEqual(second["outputs"][0]["source_file_hash"], first_hash)
            self.assertEqual(second["outputs"][0]["normalized_rows"], 2)


if __name__ == "__main__":
    unittest.main()
