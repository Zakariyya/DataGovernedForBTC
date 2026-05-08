import unittest

from datagovernedforbtc.curated_state import build_curated_market_state_1m


class CuratedStateTest(unittest.TestCase):
    def test_asof_join_uses_only_available_past_data_and_outputs_age(self):
        candles = [
            {
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "source_market_type": "spot",
                "open_time_ms": 0,
                "close_time_ms": 60000,
                "available_time_ms": 60000,
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "vol_base": "10",
                "vol_quote": "1000",
                "data_quality_score": "1.0",
                "schema_version": "1",
                "governance_version": "1",
            },
            {
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "source_market_type": "spot",
                "open_time_ms": 60000,
                "close_time_ms": 120000,
                "available_time_ms": 120000,
                "open": "100.5",
                "high": "102",
                "low": "100",
                "close": "101",
                "vol_base": "12",
                "vol_quote": "1200",
                "data_quality_score": "1.0",
                "schema_version": "1",
                "governance_version": "1",
            },
        ]
        funding = [
            {"available_time_ms": 60000, "realized_funding_rate": "0.001", "funding_interval_ms": "28800000", "data_quality_score": "1.0"},
            {"available_time_ms": 180000, "realized_funding_rate": "0.999", "funding_interval_ms": "28800000", "data_quality_score": "1.0"},
        ]
        borrowing = [
            {"currency_name": "USDT", "available_time_ms": 30000, "borrow_rate_raw": "0.01", "data_quality_score": "1.0"},
            {"currency_name": "USDT", "available_time_ms": 180000, "borrow_rate_raw": "9.99", "data_quality_score": "1.0"},
            {"currency_name": "BTC", "available_time_ms": 60000, "borrow_rate_raw": "0.02", "data_quality_score": "1.0"},
        ]
        trade_features = [
            {"instrument_name": "BTC-USDT", "available_time_ms": 60000, "feature_time_ms": 60000, "trade_count_1m": 2, "volume_delta_1m": "1", "data_quality_score": "1.0"},
            {"instrument_name": "BTC-USDT", "available_time_ms": 180000, "feature_time_ms": 180000, "trade_count_1m": 999, "volume_delta_1m": "999", "data_quality_score": "1.0"},
        ]

        rows = build_curated_market_state_1m(candles, funding, borrowing, trade_features)

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["feature_time_ms"], 60000)
        self.assertEqual(first["last_realized_funding_rate"], "0.001")
        self.assertEqual(first["funding_age_ms"], 0)
        self.assertEqual(first["usdt_borrow_rate_raw"], "0.01")
        self.assertEqual(first["usdt_borrow_rate_age_ms"], 30000)
        self.assertEqual(first["btc_borrow_rate_raw"], "0.02")
        self.assertEqual(first["trade_count_1m"], 2)
        self.assertNotEqual(first["last_realized_funding_rate"], "0.999")
        self.assertNotEqual(first["usdt_borrow_rate_raw"], "9.99")

        second = rows[1]
        self.assertEqual(second["feature_time_ms"], 120000)
        self.assertEqual(second["last_realized_funding_rate"], "0.001")
        self.assertEqual(second["funding_age_ms"], 60000)
        self.assertEqual(second["trade_count_1m"], "")
        self.assertEqual(second["trade_feature_missing_reason"], "no_current_trade_feature")


if __name__ == "__main__":
    unittest.main()
