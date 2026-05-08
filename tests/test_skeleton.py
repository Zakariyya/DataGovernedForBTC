import unittest

from datagovernedforbtc.time_semantics import candle_close_time_ms, exchange_date_utc8_from_ms


class TimeSemanticsTest(unittest.TestCase):
    def test_candle_close_time_uses_next_minute(self):
        self.assertEqual(candle_close_time_ms(1_000), 61_000)

    def test_exchange_date_utc8_boundary(self):
        # 2026-04-30 16:00:00 UTC == 2026-05-01 00:00:00 UTC+8
        self.assertEqual(exchange_date_utc8_from_ms(1_777_564_800_000), "2026-05-01")


if __name__ == "__main__":
    unittest.main()
