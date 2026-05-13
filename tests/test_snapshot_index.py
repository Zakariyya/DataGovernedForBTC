from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from datagovernedforbtc.cli import main
from datagovernedforbtc.snapshot import build_snapshot_index, run_snapshot_admission, write_snapshot_index


class SnapshotIndexTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def make_snapshot(self, root: Path) -> dict[str, object]:
        label = "target_unit_with_orderbook"
        curated = root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m" / f"sample={label}" / "curated_btc_market_state_1m.csv"
        self.write_csv(curated, [
            {
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "feature_time_ms": 1716163260000,
                "feature_time_utc": "2024-05-20T00:01:00Z",
                "open": "1",
                "close": "2",
                "orderbook_book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum",
                "future_leak_violation_count": 0,
                "data_quality_flags": "",
                "missing_or_stale_source_count": 0,
                "overall_data_quality_score": "1.0",
                "allow_into_feature_layer": True,
            },
            {
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "feature_time_ms": 1716163320000,
                "feature_time_utc": "2024-05-20T00:02:00Z",
                "open": "2",
                "close": "3",
                "orderbook_book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum",
                "future_leak_violation_count": 0,
                "data_quality_flags": "orderbook_feature_missing",
                "missing_or_stale_source_count": 1,
                "overall_data_quality_score": "0.8",
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
            "future_leak_violation_count": 0,
            "data_quality_flag_counts": {"orderbook_feature_missing": 1},
            "output": str(curated),
        }), encoding="utf-8")
        return run_snapshot_admission(root, label=label, snapshot_id="okx_btc_market_state_1m_v0_2_20240520_20240520_with_orderbook")

    def test_build_snapshot_index_for_alphatenant_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_snapshot(root)

            index = build_snapshot_index(root, for_alphatenant=True)

            self.assertEqual(index["schema_version"], "datagoverned.snapshot_index.v0")
            self.assertEqual(index["publisher"], "DataGovernedForBTC")
            self.assertEqual(index["consumer_contract"], "alphatenant.governed_snapshot.v0")
            self.assertEqual(index["index_status"], "ready")
            self.assertEqual(index["snapshot_count"], 1)
            entry = index["snapshots"][0]
            self.assertEqual(entry["dataset_key"], "governed-snapshot-okx_btc_market_state_1m_v0_2_20240520_20240520_with_orderbook")
            self.assertEqual(entry["status"], "admitted")
            self.assertEqual(entry["readiness"], "admitted_with_row_level_quality_filter")
            self.assertTrue(entry["path"].startswith("snapshots/"))
            self.assertNotIn("data_lake", entry["path"])
            self.assertNotIn("raw", entry["path"])
            self.assertEqual(entry["row_count"], 2)
            self.assertEqual(entry["allowed_rows"], 1)
            self.assertEqual(entry["blocked_rows"], 1)
            self.assertEqual(entry["required_row_filter"], "allow_into_feature_layer == True")
            self.assertFalse(entry["admission"]["is_trade_signal"])
            self.assertFalse(entry["admission"]["is_strategy_ready"])
            self.assertFalse(entry["admission"]["level2_auto_upgrade"])
            self.assertTrue(entry["admission"]["allow_into_feature_layer_required"])
            self.assertIn("curated_btc_market_state_1m.csv", entry["files"].values())
            allowed = set(entry["feature_contract"]["allowed_feature_columns"])
            forbidden = set(entry["feature_contract"]["forbidden_as_features"])
            self.assertFalse(allowed & forbidden)
            contract = entry["feature_contract"]
            self.assertEqual(contract["required_filter"], "allow_into_feature_layer == True")
            self.assertIn("feature_group", contract)
            self.assertIn("feature_role", contract)
            self.assertIn("forbidden_usage", contract)
            self.assertEqual(contract["feature_group"]["open"], "price_context")
            self.assertEqual(contract["feature_role"]["open"], "raw_observed_market_state")
            self.assertEqual(contract["feature_role"]["allow_into_feature_layer"], "quality_gate")
            self.assertIn("trade_signal", contract["forbidden_usage"])
            self.assertIn("level2_approval", contract["forbidden_usage"])
            self.assertEqual(entry["universe_id"], "okx_spot_btc_usdt_with_okx_derivative_context")
            self.assertEqual(entry["exchange_consistency_scope"], "single_exchange_okx_cross_market_context")
            self.assertEqual(entry["allowed_source_exchanges"], ["okx"])
            self.assertFalse(entry["mixed_exchange_features_present"])
            self.assertEqual(entry["mixed_exchange_usage_policy"], "fail_closed")

    def test_write_snapshot_index_and_cli_json_are_parseable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_snapshot(root)

            result = write_snapshot_index(root, for_alphatenant=True)
            index_path = root / "snapshots" / "snapshot_index.json"
            self.assertEqual(Path(result["index_path"]), index_path)
            self.assertTrue(index_path.exists())
            parsed = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["snapshot_count"], 1)

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = main(["--root", str(root), "snapshot-list", "--for-alphatenant", "--format", "json"])
            self.assertEqual(exit_code, 0)
            cli_obj = json.loads(out.getvalue())
            self.assertEqual(cli_obj["schema_version"], "datagoverned.snapshot_index.v0")
            self.assertEqual(cli_obj["snapshot_count"], 1)

            table_out = io.StringIO()
            with redirect_stdout(table_out):
                exit_code = main(["--root", str(root), "snapshot-list", "--for-alphatenant", "--format", "table"])
            self.assertEqual(exit_code, 0)
            table = table_out.getvalue()
            self.assertIn("dataset_key", table)
            self.assertIn("allowed_rows", table)
            self.assertIn("governed-snapshot-okx_btc_market_state_1m_v0_2_20240520_20240520_with_orderbook", table)


if __name__ == "__main__":
    unittest.main()
