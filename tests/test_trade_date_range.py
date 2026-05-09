from pathlib import Path
import tempfile
import unittest

from datagovernedforbtc.trade import select_trade_source_files


class TradeDateRangeTest(unittest.TestCase):
    def touch_trade(self, root: Path, date_text: str) -> Path:
        path = root / "okx" / "Trade" / "Spot" / date_text[:4] / f"BTC-USDT-trades-{date_text}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("instrument_name,trade_id,side,price,size,created_time\n", encoding="utf-8")
        return path

    def test_select_trade_source_files_filters_inclusive_date_range_before_max_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.touch_trade(root, "2024-05-19")
            expected_20 = self.touch_trade(root, "2024-05-20")
            expected_21 = self.touch_trade(root, "2024-05-21")
            self.touch_trade(root, "2024-06-12")
            perp = root / "okx" / "Trade" / "Perpetual" / "2024" / "BTC-USDT-SWAP-trades-2024-05-20.csv"
            perp.parent.mkdir(parents=True, exist_ok=True)
            perp.write_text("instrument_name,trade_id,side,price,size,created_time\n", encoding="utf-8")

            selected = select_trade_source_files(
                root,
                start_date="2024-05-20",
                end_date="2024-06-11",
                max_files=2,
                market="spot",
                instrument="BTC-USDT",
            )

            self.assertEqual(selected, [expected_20, expected_21])


if __name__ == "__main__":
    unittest.main()
