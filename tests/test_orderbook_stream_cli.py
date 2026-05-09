from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path

from datagovernedforbtc.cli import main


class OrderbookStreamCliTest(unittest.TestCase):
    def write_tar_jsonl(self, path: Path, member_name: str, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(r) + "\n" for r in rows).encode("utf-8")
        with tarfile.open(path, "w") as tar:
            info = tarfile.TarInfo(member_name)
            info.size = len(payload)
            tar.addfile(info, BytesIO(payload))

    def test_orderbook_stream_features_cli_runs_date_bounded_parquet_checkpoint_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "okx" / "Orderbook" / "Spot" / "2024" / "BTC-USDT-L2orderbook-400lv-2024-05-20.tar.tar"
            self.write_tar_jsonl(src, "BTC-USDT-L2orderbook-400lv-2024-05-20.data", [
                {"instId": "BTC-USDT", "action": "snapshot", "ts": "1716163200000", "asks": [["101", "2", "1"]], "bids": [["100", "3", "1"]]},
            ])
            out = StringIO()
            with redirect_stdout(out):
                code = main([
                    "--root", str(root),
                    "orderbook-stream-features",
                    "--start-date", "2024-05-20",
                    "--end-date", "2024-05-20",
                    "--market", "spot",
                    "--instrument", "BTC-USDT",
                    "--no-resume",
                ])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["mode"], "stream_parquet_checkpoint")
            self.assertEqual(payload["processing_engine"], "streaming_orderbook_feature_parquet_v1")
            self.assertEqual(payload["processed_count"], 1)
            self.assertTrue(Path(payload["outputs"][0]["feature_parquet"]).exists())


if __name__ == "__main__":
    unittest.main()
