import unittest

from datagovernedforbtc.curated_state import build_curated_market_state_1m


class CuratedStateOrderbookNoteTest(unittest.TestCase):
    def test_curated_rows_mark_orderbook_not_included_without_counting_as_time_source_failure(self):
        candles = [
            {
                "exchange": "okx",
                "instrument_name": "BTC-USDT",
                "source_market_type": "spot",
                "close_time_ms": 60000,
                "available_time_ms": 60000,
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "vol_base": "10",
                "vol_quote": "1000",
                "data_quality_score": "1.0",
            }
        ]
        funding = [{"instrument_name": "BTC-USDT-SWAP", "available_time_ms": 60000, "realized_funding_rate": "0.001", "funding_interval_ms": "28800000", "data_quality_score": "1.0"}]
        borrowing = [
            {"currency_name": "BTC", "available_time_ms": 60000, "borrow_rate_raw": "0.01", "data_quality_score": "1.0"},
            {"currency_name": "ETH", "available_time_ms": 60000, "borrow_rate_raw": "0.02", "data_quality_score": "1.0"},
            {"currency_name": "USDT", "available_time_ms": 60000, "borrow_rate_raw": "0.03", "data_quality_score": "1.0"},
        ]
        trade_features = [{"instrument_name": "BTC-USDT", "available_time_ms": 60000, "feature_time_ms": 60000, "trade_count_1m": 2, "volume_delta_1m": "1", "data_quality_score": "1.0"}]

        rows = build_curated_market_state_1m(candles, funding, borrowing, trade_features)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["orderbook_feature_missing_reason"], "not_included_in_current_window")
        self.assertNotIn("orderbook_feature_missing", rows[0]["data_quality_flags"])
        self.assertTrue(rows[0]["allow_into_feature_layer"])


if __name__ == "__main__":
    unittest.main()
