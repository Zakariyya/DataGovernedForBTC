from pathlib import Path
import unittest

from datagovernedforbtc.path_semantics import infer_source_market_type, infer_instrument_type_from_path


class PathSemanticsTest(unittest.TestCase):
    def test_infers_spot_from_dataset_subdirectory(self):
        p = Path("okx/Candlesticks/Spot/2026/BTC-USDT-candlesticks-2026-05-01.csv")
        self.assertEqual(infer_source_market_type(p), "spot")
        self.assertEqual(infer_instrument_type_from_path("BTC-USDT", p), "spot")

    def test_infers_perpetual_from_dataset_subdirectory(self):
        p = Path("okx/Fundingrates/Perpetual/2026/allswap-fundingrates-2026-05-01.csv")
        self.assertEqual(infer_source_market_type(p), "perpetual")
        self.assertEqual(infer_instrument_type_from_path("BTC-USDT-SWAP", p), "perpetual_swap")

    def test_falls_back_to_instrument_suffix_when_path_unknown(self):
        p = Path("okx/Fundingrates/2026/allswap-fundingrates-2026-05-01.csv")
        self.assertEqual(infer_source_market_type(p), "unknown")
        self.assertEqual(infer_instrument_type_from_path("BTC-USDT-SWAP", p), "perpetual_swap")


if __name__ == "__main__":
    unittest.main()
