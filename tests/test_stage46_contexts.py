from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.stage46_contexts import (
    enrich_stage46_contexts,
    build_horizon_safe_curated_state,
    run_stage46_enrich_sample,
)
from datagovernedforbtc.snapshot import run_snapshot_admission


class Stage46ContextsTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def read_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def base_rows(self, n: int = 20) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for i in range(n):
            t = (i + 1) * 60_000
            open_px = 100 + i * 0.1
            close_px = open_px + (0.2 if i % 3 else -0.05)
            high = max(open_px, close_px) + 0.1
            low = min(open_px, close_px) - 0.1
            rows.append({
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "source_market_type": "spot",
                "feature_time_ms": t,
                "feature_time_utc": f"t{i}",
                "available_time_ms": t,
                "available_time_utc": f"t{i}",
                "open": f"{open_px:.4f}",
                "high": f"{high:.4f}",
                "low": f"{low:.4f}",
                "close": f"{close_px:.4f}",
                "vol_base": f"{10 + i:.4f}",
                "vol_quote": f"{1000 + i * 10:.4f}",
                "trade_count_1m": 0 if i == 3 else 10 + i,
                "buy_volume_1m": f"{2 + i:.4f}",
                "sell_volume_1m": f"{1 + i:.4f}",
                "volume_delta_1m": "1.0",
                "volume_delta_ratio_1m": "0.2",
                "trade_feature_missing_reason": "" if i != 4 else "no_current_trade_feature",
                "trade_feature_time_ms": t,
                "orderbook_feature_required": True,
                "orderbook_best_bid_last": f"{close_px - 0.01:.4f}",
                "orderbook_best_ask_last": f"{close_px + 0.01:.4f}",
                "orderbook_mid_price_last": f"{close_px:.4f}",
                "orderbook_spread_abs_last": "0.02",
                "orderbook_spread_pct_last": "0.0002" if i != 5 else "",
                "orderbook_top20_depth_imbalance_last": "0.1",
                "orderbook_update_count_1m": 0 if i == 6 else 5,
                "orderbook_snapshot_count_1m": 1,
                "orderbook_feature_time_ms": t if i != 7 else t - 60_000,
                "orderbook_book_reconstruction_quality": "best_effort_reconstructed_without_sequence_checksum",
                "orderbook_is_crossed_book_last": "false",
                "orderbook_feature_missing_reason": "" if i != 8 else "no_current_orderbook_feature",
                "future_leak_violation_count": 0,
                "data_quality_flags": "" if i not in {4, 7, 8} else "trade_feature_missing" if i == 4 else "orderbook_feature_not_current_1m" if i == 7 else "orderbook_feature_missing",
                "missing_or_stale_source_count": 0 if i not in {4, 7, 8} else 1,
                "overall_data_quality_score": "1.0000",
                "allow_into_feature_layer": "True" if i not in {4, 7, 8} else "False",
                "schema_version": "v1",
                "feature_version": "v1",
                "governance_version": "v1",
            })
        return rows

    def test_enrich_stage46_contexts_adds_causal_contexts_and_reason_codes(self):
        enriched = enrich_stage46_contexts(self.base_rows())

        row = enriched[-1]
        expected_columns = {
            "rolling_realized_volatility_5m",
            "rolling_range_pct_5m",
            "candle_body_to_range_ratio",
            "close_location_in_range",
            "intraday_range_percentile_causal",
            "no_activity_or_low_information_flag",
            "causal_trend_slope_15m",
            "volatility_expansion_ratio",
            "range_compression_score",
            "trend_persistence_score",
            "spread_bps",
            "spread_percentile_causal",
            "orderbook_stale_ms",
            "liquidity_fragility_flag",
            "estimated_minimum_slippage_bucket",
            "rolling_return_abs_percentile",
            "rolling_downside_volatility",
            "jump_candidate_flag",
            "spread_shock_flag",
            "blocked_reason_codes",
            "warning_reason_codes",
            "source_family_missing_flags",
            "source_family_stale_flags",
            "liquidity_context_unreliable",
        }
        self.assertTrue(expected_columns.issubset(set(row)))
        self.assertEqual(row["available_time_ms"], row["feature_time_ms"])
        self.assertEqual(row["source_dataset_family"], "curated_btc_market_state")
        self.assertEqual(row["source_exchange"], "okx")
        self.assertEqual(row["feature_context_contract"], "not_alpha_signal_not_level2_not_allow_paper")
        self.assertNotIn("buy_signal", row)
        self.assertNotIn("sell_signal", row)

        blocked = enriched[8]
        self.assertIn("orderbook_feature_missing", blocked["blocked_reason_codes"])
        self.assertEqual(blocked["orderbook_missing"], "True")
        self.assertEqual(blocked["liquidity_context_unreliable"], "True")

    def test_build_horizon_safe_15m_and_1h_rows_from_governed_1m_only(self):
        enriched = enrich_stage46_contexts(self.base_rows(70))
        rows_15m = build_horizon_safe_curated_state(enriched, interval_minutes=15)
        rows_1h = build_horizon_safe_curated_state(enriched, interval_minutes=60)

        self.assertEqual(len(rows_15m), 4)
        self.assertEqual(len(rows_1h), 1)
        first = rows_15m[0]
        self.assertEqual(first["interval"], "15m")
        self.assertEqual(first["source_1m_row_count"], 15)
        self.assertEqual(first["window_start_feature_time_ms"], 60000)
        self.assertEqual(first["window_end_feature_time_ms"], 900000)
        self.assertIn("source_1m_quality_blocked", first["data_quality_flags"])
        self.assertEqual(first["allow_into_feature_layer"], False)
        self.assertEqual(first["aggregation_source"], "governed_curated_btc_market_state_1m_only")

    def test_run_stage46_enrich_sample_writes_reports_and_snapshot_contract_lists_new_groups(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            label = "unit"
            source = root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m/sample=unit/curated_btc_market_state_1m.csv"
            self.write_csv(source, self.base_rows(70))
            summary_path = root / "reports/quality/curated_state_window_unit_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps({
                "dataset_type": "curated_btc_market_state_1m",
                "window_start": "2024-05-20",
                "window_end": "2024-05-20",
                "label": label,
                "row_count": 20,
                "allow_into_feature_layer_rows": 17,
                "allow_into_feature_layer_ratio": 0.85,
                "future_leak_violation_count": 0,
                "data_quality_flag_counts": {},
                "output": str(source),
            }), encoding="utf-8")

            result = run_stage46_enrich_sample(root, source_label=label, label="unit_stage46")
            enriched_path = Path(result["outputs"]["1m"])
            rows = self.read_rows(enriched_path)
            self.assertIn("rolling_realized_volatility_15m", rows[0])
            self.assertTrue(Path(result["outputs"]["5m"]).exists())
            self.assertTrue(Path(result["outputs"]["15m"]).exists())
            self.assertTrue(Path(result["outputs"]["1h"]).exists())
            self.assertTrue(Path(result["quality_summaries"]["1m"]).exists())
            self.assertTrue(Path(result["quality_summaries"]["5m"]).exists())
            self.assertTrue(Path(result["quality_summaries"]["15m"]).exists())
            self.assertTrue(Path(result["quality_summaries"]["1h"]).exists())

            snap = run_snapshot_admission(root, label="unit_stage46", snapshot_id="unit_stage46_snapshot")
            schema = json.loads((Path(snap["snapshot_dir"]) / "schema.json").read_text(encoding="utf-8"))
            self.assertEqual(schema["feature_group"]["rolling_realized_volatility_15m"], "volatility_context")
            self.assertEqual(schema["feature_role"]["causal_trend_slope_15m"], "regime_input")
            self.assertEqual(schema["feature_role"]["spread_bps"], "cost_liquidity_input")
            self.assertEqual(schema["feature_role"]["no_activity_or_low_information_flag"], "opportunity_input")
            self.assertEqual(schema["feature_role"]["jump_candidate_flag"], "tail_risk_context_input")
            self.assertIn("blocked_reason_codes", schema["forbidden_as_features"])

            snap_15m = run_snapshot_admission(root, label="unit_stage46", snapshot_id="unit_stage46_snapshot_15m", interval="15m")
            snap_1h = run_snapshot_admission(root, label="unit_stage46", snapshot_id="unit_stage46_snapshot_1h", interval="1h")
            self.assertTrue((Path(snap_15m["snapshot_dir"]) / "curated_btc_market_state_15m.csv").exists())
            self.assertTrue((Path(snap_1h["snapshot_dir"]) / "curated_btc_market_state_1h.csv").exists())
            schema_15m = json.loads((Path(snap_15m["snapshot_dir"]) / "schema.json").read_text(encoding="utf-8"))
            self.assertEqual(schema_15m["dataset_type"], "curated_btc_market_state_15m")
            self.assertEqual(schema_15m["required_filter"], "allow_into_feature_layer == True")


if __name__ == "__main__":
    unittest.main()
