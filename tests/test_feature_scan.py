import unittest

from datagovernedforbtc.feature_scan import build_alphatenant_dataset_shape


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


if __name__ == "__main__":
    unittest.main()
