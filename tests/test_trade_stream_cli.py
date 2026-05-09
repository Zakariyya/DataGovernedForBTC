from __future__ import annotations

import csv
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from datagovernedforbtc.cli import main


class TradeStreamCliTest(unittest.TestCase):
    def test_trade_stream_cli_runs_date_bounded_parquet_checkpoint_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "okx" / "Trade" / "Spot" / "2024" / "BTC-USDT-trades-2024-05-20.csv"
            src.parent.mkdir(parents=True, exist_ok=True)
            with src.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["instrument_name", "trade_id", "side", "price", "size", "created_time"])
                w.writerow(["BTC-USDT", "t1", "buy", "100", "0.1", "0"])
            out = StringIO()
            with redirect_stdout(out):
                code = main([
                    "--root", str(root),
                    "trade-stream",
                    "--start-date", "2024-05-20",
                    "--end-date", "2024-05-20",
                    "--market", "spot",
                    "--instrument", "BTC-USDT",
                    "--resume",
                ])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["mode"], "stream_parquet_checkpoint")
            self.assertEqual(payload["processed_count"], 1)
            self.assertTrue(Path(payload["outputs"][0]["normalized_parquet"]).exists())


if __name__ == "__main__":
    unittest.main()
