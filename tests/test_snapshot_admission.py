from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.snapshot import run_snapshot_admission


class SnapshotAdmissionTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def test_snapshot_admission_writes_versioned_alphatenant_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            label = "target_unit_with_orderbook"
            curated = root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m" / f"sample={label}" / "curated_btc_market_state_1m.csv"
            self.write_csv(curated, [
                {
                    "exchange": "okx",
                    "instrument_name": "BTC-USDT",
                    "feature_time_ms": 60000,
                    "feature_time_utc": "1970-01-01T00:01:00Z",
                    "open": "1",
                    "close": "1",
                    "orderbook_feature_required": True,
                    "orderbook_book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum",
                    "future_leak_violation_count": 0,
                    "data_quality_flags": "",
                    "missing_or_stale_source_count": 0,
                    "allow_into_feature_layer": True,
                },
                {
                    "exchange": "okx",
                    "instrument_name": "BTC-USDT",
                    "feature_time_ms": 120000,
                    "feature_time_utc": "1970-01-01T00:02:00Z",
                    "open": "1",
                    "close": "1",
                    "orderbook_feature_required": True,
                    "orderbook_book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum",
                    "future_leak_violation_count": 0,
                    "data_quality_flags": "orderbook_feature_missing",
                    "missing_or_stale_source_count": 1,
                    "allow_into_feature_layer": False,
                },
            ])
            summary_path = root / "reports/quality" / f"curated_state_window_{label}_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps({
                "dataset_type": "curated_btc_market_state_1m",
                "window_start": "2024-05-20",
                "window_end": "2024-05-20",
                "label": label,
                "row_count": 2,
                "allow_into_feature_layer_rows": 1,
                "allow_into_feature_layer_ratio": 0.5,
                "future_leak_violation_count": 0,
                "data_quality_flag_counts": {"orderbook_feature_missing": 1},
                "output": str(curated),
            }), encoding="utf-8")

            result = run_snapshot_admission(root, label=label, snapshot_id="unit_snapshot_v0_1")

            snapshot_dir = Path(result["snapshot_dir"])
            self.assertTrue((snapshot_dir / "curated_btc_market_state_1m.csv").exists())
            self.assertTrue((snapshot_dir / "data_admission_report.json").exists())
            self.assertTrue((snapshot_dir / "source_manifest.json").exists())
            self.assertTrue((snapshot_dir / "quality_summary.json").exists())
            self.assertTrue((snapshot_dir / "schema.json").exists())
            self.assertTrue((snapshot_dir / "feature_contract.md").exists())
            self.assertTrue((snapshot_dir / "forbidden_raw_access_policy.md").exists())

            report = json.loads((snapshot_dir / "data_admission_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["snapshot_id"], "unit_snapshot_v0_1")
            self.assertEqual(report["allow_into_feature_layer_rows"], 1)
            self.assertEqual(report["blocked_rows"], 1)
            self.assertEqual(report["future_leak_violation_count"], 0)
            self.assertEqual(report["orderbook_reconstruction_quality"], "best_effort_reconstructed_without_sequence_checksum")
            self.assertIn("orderbook_feature_missing", report["blocking_quality_flags"])
            self.assertFalse(report["raw_zone_access_allowed_for_alphatenant"])

            manifest = json.loads((snapshot_dir / "source_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["curated_source"]["label"], label)
            self.assertIn("sha256", manifest["curated_source"])
            self.assertIn("data_lake/features", manifest["curated_source"]["path"])

            schema = json.loads((snapshot_dir / "schema.json").read_text(encoding="utf-8"))
            self.assertIn("feature_time_ms", schema["columns"])
            self.assertIn("allow_into_feature_layer", schema["governance_columns"])
            self.assertIn("open", schema["allowed_feature_columns"])
            self.assertNotIn("allow_into_feature_layer", schema["allowed_feature_columns"])


if __name__ == "__main__":
    unittest.main()
