import tempfile
import unittest
from pathlib import Path

from datagovernedforbtc.feature_scan import build_alphatenant_dataset_shape, scan_raw_feature_points


class FeatureScanTest(unittest.TestCase):
    def test_dataset_shape_contains_required_layers_and_time_keys(self):
        shape = build_alphatenant_dataset_shape()
        names = {item["dataset_name"] for item in shape}
        self.assertIn("curated_btc_market_state_1m", names)
        self.assertIn("btc_regime_1m", names)
        market_state = next(item for item in shape if item["dataset_name"] == "curated_btc_market_state_1m")
        self.assertIn("feature_time_ms", market_state["primary_key"])
        self.assertIn("available_time_ms", market_state["required_time_fields"])
        self.assertIn("funding_age_ms", market_state["required_age_fields"])
        self.assertIn("trade_count_1m", market_state["feature_groups"]["trade"])
        self.assertIn("spread_pct_last", market_state["feature_groups"]["orderbook"])

    def test_orderbook_scan_counts_tar_tar_archives_without_expanding_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orderbook_dir = root / "okx" / "Orderbook" / "Spot" / "2024"
            orderbook_dir.mkdir(parents=True)
            (orderbook_dir / "BTC-USDT-L2orderbook-400lv-2024-05-20.data").write_text(
                '{"instId":"BTC-USDT","action":"snapshot","ts":"1","asks":[],"bids":[]}\n',
                encoding="utf-8",
            )
            (orderbook_dir / "BTC-USDT-L2orderbook-400lv-2024-05-21.tar.gz").write_bytes(b"not expanded")
            (orderbook_dir / "BTC-USDT-L2orderbook-400lv-2024-05-22.tar.tar").write_bytes(b"not expanded")

            scan = scan_raw_feature_points(root)

        orderbook = scan["datasets"]["orderbook"]
        self.assertEqual(orderbook["file_count"], 3)
        self.assertEqual(orderbook["extension_counts"][".data"], 1)
        self.assertEqual(orderbook["extension_counts"][".tar.gz"], 1)
        self.assertEqual(orderbook["extension_counts"][".tar.tar"], 1)
        self.assertEqual(orderbook["min_source_file_date"], "2024-05-20")
        self.assertEqual(orderbook["max_source_file_date"], "2024-05-22")
        self.assertEqual(orderbook["sample_fields_by_market"]["spot"], ["action", "asks", "bids", "instId", "ts"])


if __name__ == "__main__":
    unittest.main()
