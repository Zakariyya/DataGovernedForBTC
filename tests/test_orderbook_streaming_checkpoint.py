from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import pandas as pd

from datagovernedforbtc.curated_state import run_curated_state_window
from datagovernedforbtc.orderbook import run_orderbook_stream_features


class OrderbookStreamingCheckpointTest(unittest.TestCase):
    def write_tar_jsonl(self, path: Path, member_name: str, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(r) + "\n" for r in rows).encode("utf-8")
        mode = "w:gz" if path.name.endswith(".gz") else "w"
        with tarfile.open(path, mode) as tar:
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            tar.addfile(info, BytesIO(payload))

    def write_csv_rows(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            return
        import csv
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def test_orderbook_stream_writes_parquet_checkpoint_and_resume_skips_completed_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "okx" / "Orderbook" / "Spot" / "2024" / "BTC-USDT-L2orderbook-400lv-2024-05-20.tar.tar"
            self.write_tar_jsonl(src, "BTC-USDT-L2orderbook-400lv-2024-05-20.data", [
                {"instId": "BTC-USDT", "action": "snapshot", "ts": "1716163200000", "asks": [["101", "2", "1"]], "bids": [["100", "3", "1"]]},
                {"instId": "BTC-USDT", "action": "update", "ts": "1716163205000", "asks": [["101", "0", "0"], ["102", "5", "1"]], "bids": [["100", "4", "1"]]},
                {"instId": "BTC-USDT", "action": "update", "ts": "1716163261000", "asks": [["102", "6", "1"]], "bids": [["99", "1", "1"]]},
            ])

            first = run_orderbook_stream_features(
                root,
                start_date="2024-05-20",
                end_date="2024-05-20",
                market="spot",
                instrument="BTC-USDT",
                resume=True,
            )

            self.assertEqual(first["mode"], "stream_parquet_checkpoint")
            self.assertEqual(first["source_file_count"], 1)
            self.assertEqual(first["processed_count"], 1)
            self.assertEqual(first["skipped_count"], 0)
            self.assertEqual(first["total_feature_rows_1m"], 2)
            output = first["outputs"][0]
            feature_path = Path(output["feature_parquet"])
            checkpoint_path = Path(output["checkpoint"])
            self.assertTrue(feature_path.exists())
            self.assertFalse(feature_path.with_name("orderbook_features_1m.csv").exists())
            self.assertTrue(checkpoint_path.exists())
            feature_df = pd.read_parquet(feature_path)
            self.assertEqual(feature_df.shape[0], 2)
            self.assertEqual(list(feature_df["best_bid_last"]), ["100", "100"])
            self.assertEqual(list(feature_df["best_ask_last"]), ["102", "102"])

            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["status"], "completed")
            self.assertEqual(checkpoint["processing_engine"], "streaming_orderbook_feature_parquet_v1")
            self.assertEqual(checkpoint["source_file_hash"], output["source_file_hash"])
            self.assertEqual(checkpoint["feature_rows_1m"], 2)
            self.assertEqual(checkpoint["book_reconstruction_quality"], "best_effort_reconstructed_without_sequence_checksum")
            self.assertFalse(checkpoint["sequence_checksum_available"])
            self.assertIn("feature_parquet_sha256", checkpoint)

            second = run_orderbook_stream_features(
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

    def test_curated_state_window_prefers_orderbook_parquet_over_legacy_csv_for_same_partition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candle_dir = root / "data_lake" / "normalized" / "exchange=okx" / "dataset_type=candlestick" / "market=spot" / "instrument=BTC-USDT" / "interval=1m" / "exchange_date_utc8=2024-05-20"
            self.write_csv_rows(candle_dir / "candlestick_normalized.csv", [
                {"exchange": "okx", "instrument_name": "BTC-USDT", "source_market_type": "spot", "close_time_ms": 1716163260000, "available_time_ms": 1716163260000, "open": "1", "high": "1", "low": "1", "close": "1"},
            ])
            trade_dir = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=trade_feature" / "market=spot" / "instrument=BTC-USDT" / "interval=1m" / "exchange_date_utc8=2024-05-20"
            self.write_csv_rows(trade_dir / "trade_features_1m.csv", [
                {"feature_time_ms": 1716163260000, "available_time_ms": 1716163260000, "trade_count_1m": "1", "buy_volume_1m": "1", "sell_volume_1m": "0", "volume_delta_1m": "1", "volume_delta_ratio_1m": "1", "data_quality_score": "1.0"},
            ])
            ob_dir = root / "data_lake" / "features" / "exchange=okx" / "dataset_type=orderbook_feature" / "market=spot" / "instrument=BTC-USDT" / "interval=1m" / "exchange_date_utc8=2024-05-20"
            legacy = [{"feature_time_ms": 1716163260000, "available_time_ms": 1716163260000, "best_bid_last": "99", "best_ask_last": "101", "mid_price_last": "100", "spread_abs_last": "2", "spread_pct_last": "0.02", "top20_depth_imbalance_last": "0", "orderbook_update_count_1m": "1", "orderbook_snapshot_count_1m": "1", "orderbook_quality_score": "1.0", "book_reconstruction_quality": "legacy_csv", "is_crossed_book_last": "false"}]
            parquet = [{**legacy[0], "best_bid_last": "100", "best_ask_last": "102", "mid_price_last": "101", "book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum"}]
            self.write_csv_rows(ob_dir / "orderbook_features_1m.csv", legacy)
            ob_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(parquet).to_parquet(ob_dir / "orderbook_features_1m.parquet", index=False, engine="pyarrow")

            result = run_curated_state_window(root, "2024-05-20", "2024-05-20", label="orderbook_parquet_preference")
            with Path(result["output"]).open("r", encoding="utf-8", newline="") as f:
                rows = list(__import__("csv").DictReader(f))

        self.assertEqual(result["orderbook_feature_files_used"], 1)
        self.assertEqual(rows[0]["orderbook_best_bid_last"], "100")
        self.assertEqual(rows[0]["orderbook_book_reconstruction_quality"], "best_effort_reconstructed_without_sequence_checksum")


if __name__ == "__main__":
    unittest.main()
