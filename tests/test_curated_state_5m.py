from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.curated_state import run_curated_state_5m


class CuratedState5mTest(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def test_5m_aggregates_only_from_curated_1m_and_preserves_quality_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows: list[dict[str, object]] = []
            for i in range(5):
                t = (i + 1) * 60_000
                rows.append({
                    "exchange": "okx",
                    "instrument_name": "BTC-USDT",
                    "source_market_type": "spot",
                    "feature_time_ms": t,
                    "feature_time_utc": f"t{i}",
                    "available_time_ms": t,
                    "available_time_utc": f"t{i}",
                    "open": str(100 + i),
                    "high": str(101 + i),
                    "low": str(99 + i),
                    "close": str(100.5 + i),
                    "vol_base": str(10 + i),
                    "vol_quote": str(1000 + i),
                    "last_realized_funding_rate": "0.001",
                    "funding_age_ms": str(i * 60_000),
                    "btc_borrow_rate_raw": "0.01",
                    "btc_borrow_rate_age_ms": str(i * 60_000),
                    "eth_borrow_rate_raw": "0.02",
                    "eth_borrow_rate_age_ms": str(i * 60_000),
                    "usdt_borrow_rate_raw": "0.03",
                    "usdt_borrow_rate_age_ms": str(i * 60_000),
                    "trade_count_1m": i + 1,
                    "buy_volume_1m": str(1 + i),
                    "sell_volume_1m": str(0.5 + i),
                    "volume_delta_1m": str(0.5),
                    "volume_delta_ratio_1m": "0.1",
                    "trade_feature_missing_reason": "",
                    "trade_feature_time_ms": t,
                    "orderbook_feature_required": True,
                    "orderbook_mid_price_last": str(100.2 + i),
                    "orderbook_spread_abs_last": "0.1",
                    "orderbook_top20_depth_imbalance_last": "0.2",
                    "orderbook_feature_time_ms": t,
                    "orderbook_feature_missing_reason": "",
                    "future_leak_violation_count": 0,
                    "data_quality_flags": "" if i != 2 else "orderbook_crossed_book",
                    "missing_or_stale_source_count": 0 if i != 2 else 1,
                    "overall_data_quality_score": "1.0000" if i != 2 else "0.9000",
                    "allow_into_feature_layer": "True" if i != 2 else "False",
                    "schema_version": "v1",
                    "feature_version": "v1",
                    "governance_version": "v1",
                })
            self.write_csv(
                root / "data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m/sample=unit/curated_btc_market_state_1m.csv",
                rows,
            )

            summary = run_curated_state_5m(root, source_label="unit", label="unit_5m")

            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["source_1m_rows"], 5)
            self.assertEqual(summary["allow_into_feature_layer_rows"], 0)
            self.assertEqual(summary["blocked_by_source_1m_quality_rows"], 1)
            with Path(summary["output"]).open(newline="", encoding="utf-8") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["interval"], "5m")
            self.assertEqual(row["source_1m_row_count"], "5")
            self.assertEqual(row["source_1m_allowed_row_count"], "4")
            self.assertEqual(row["open"], "100")
            self.assertEqual(row["high"], "105")
            self.assertEqual(row["low"], "99")
            self.assertEqual(row["close"], "104.5")
            self.assertEqual(row["trade_count_5m"], "15")
            self.assertIn("source_1m_quality_blocked", row["data_quality_flags"])
            self.assertIn("orderbook_crossed_book", row["source_1m_data_quality_flags"])
            self.assertEqual(row["allow_into_feature_layer"], "False")


if __name__ == "__main__":
    unittest.main()
