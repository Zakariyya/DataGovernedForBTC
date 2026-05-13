from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.alpha_reports import build_dataset_family_coverage_matrix, build_research_readiness_report
from datagovernedforbtc.snapshot import write_json


class AlphaTenantReportsTest(unittest.TestCase):
    def test_build_dataset_family_coverage_matrix_separates_raw_feature_and_snapshot_availability(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw_candle = root / "okx/Candlesticks/Spot/BTC-USDT-1m-2024-05-20.csv"
            raw_candle.parent.mkdir(parents=True, exist_ok=True)
            raw_candle.write_text("ts,o,h,l,c,vol\n", encoding="utf-8")
            feature_trade = root / "data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/format=parquet/exchange_date_utc8=2024-05-20/trade_features_1m.parquet"
            feature_trade.parent.mkdir(parents=True, exist_ok=True)
            feature_trade.write_text("placeholder", encoding="utf-8")
            snap_dir = root / "snapshots/exchange=okx/instrument=BTC-USDT/interval=1m/snapshot_id=unit"
            snap_dir.mkdir(parents=True, exist_ok=True)
            write_json(snap_dir / "snapshot_summary.json", {"snapshot_id": "unit", "curated_rows": 2, "allow_into_feature_layer_rows": 1})
            write_json(snap_dir / "data_admission_report.json", {"snapshot_id": "unit", "dataset_type": "curated_btc_market_state_1m", "exchange": "okx", "instrument_name": "BTC-USDT", "interval": "1m", "row_count": 2, "allow_into_feature_layer_rows": 1, "blocked_rows": 1, "alpha_tenant_readiness": "admitted_with_row_level_quality_filter", "future_leak_violation_count": 0})
            write_json(snap_dir / "schema.json", {"columns": ["open", "trade_count_1m", "allow_into_feature_layer"], "allowed_feature_columns": ["open", "trade_count_1m"], "forbidden_as_features": ["allow_into_feature_layer"]})
            for name in ["curated_btc_market_state_1m.csv", "source_manifest.json", "quality_summary.json", "feature_contract.md", "forbidden_raw_access_policy.md"]:
                (snap_dir / name).write_text("{}" if name.endswith(".json") else "x", encoding="utf-8")

            matrix = build_dataset_family_coverage_matrix(root)
            rows = {(r["market"], r["instrument"], r["dataset_family"]): r for r in matrix["rows"]}

            candle = rows[("spot", "BTC-USDT", "candlestick")]
            self.assertTrue(candle["raw_coverage_available"])
            self.assertFalse(candle["governed_feature_available"])
            self.assertTrue(candle["alpha_tenant_snapshot_available"])
            self.assertEqual(candle["admission_status"], "raw_only_snapshot_available")

            trade = rows[("spot", "BTC-USDT", "trade")]
            self.assertTrue(trade["governed_feature_available"])
            self.assertTrue(trade["alpha_tenant_snapshot_available"])

            oi = rows[("perpetual", "BTC-USDT-SWAP", "open_interest")]
            self.assertFalse(oi["raw_coverage_available"])
            self.assertEqual(oi["admission_status"], "unavailable")

    def test_build_research_readiness_report_uses_snapshot_index_and_contract_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap_dir = root / "snapshots/exchange=okx/instrument=BTC-USDT/interval=1m/snapshot_id=unit"
            snap_dir.mkdir(parents=True, exist_ok=True)
            write_json(snap_dir / "snapshot_summary.json", {"snapshot_id": "unit", "curated_rows": 2, "allow_into_feature_layer_rows": 1})
            write_json(snap_dir / "data_admission_report.json", {"snapshot_id": "unit", "dataset_type": "curated_btc_market_state_1m", "exchange": "okx", "instrument_name": "BTC-USDT", "interval": "1m", "row_count": 2, "allow_into_feature_layer_rows": 1, "blocked_rows": 1, "alpha_tenant_readiness": "admitted_with_row_level_quality_filter", "future_leak_violation_count": 0})
            write_json(snap_dir / "schema.json", {"columns": ["open", "orderbook_spread_pct_last", "allow_into_feature_layer"], "allowed_feature_columns": ["open", "orderbook_spread_pct_last"], "forbidden_as_features": ["allow_into_feature_layer"]})
            write_json(snap_dir / "quality_summary.json", {"data_quality_flag_counts": {"orderbook_feature_missing": 1}})
            for name in ["curated_btc_market_state_1m.csv", "source_manifest.json", "feature_contract.md", "forbidden_raw_access_policy.md"]:
                (snap_dir / name).write_text("{}" if name.endswith(".json") else "x", encoding="utf-8")

            report = build_research_readiness_report(root, snapshot_id="unit")

            self.assertEqual(report["snapshot_id"], "unit")
            self.assertEqual(report["required_filter"], "allow_into_feature_layer == True")
            self.assertEqual(report["row_count"], 2)
            self.assertEqual(report["allowed_row_count"], 1)
            self.assertEqual(report["blocked_row_count"], 1)
            self.assertIn("price_context", report["feature_group_coverage"])
            self.assertIn("orderbook_microstructure", report["feature_group_coverage"])
            self.assertFalse(report["no_lookahead_checks"]["future_window_regime_confirmation_used"])
            self.assertIn("direct_trade_signal", report["forbidden_alpha_tenant_use"])
            self.assertEqual(report["readiness_status"], "research_ready_with_row_level_quality_filter")


if __name__ == "__main__":
    unittest.main()
