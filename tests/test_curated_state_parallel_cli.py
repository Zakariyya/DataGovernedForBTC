from __future__ import annotations

import unittest

from datagovernedforbtc.cli import build_parser


class CuratedStateParallelCliTest(unittest.TestCase):
    def test_cli_accepts_curated_state_day_command(self):
        args = build_parser().parse_args([
            "curated-state-day",
            "--date", "2024-05-20",
            "--label", "unit",
        ])

        self.assertEqual(args.command, "curated-state-day")
        self.assertEqual(args.date, "2024-05-20")
        self.assertEqual(args.label, "unit")

    def test_cli_accepts_window_finalize_command(self):
        args = build_parser().parse_args([
            "curated-state-window-finalize",
            "--start-date", "2024-05-20",
            "--end-date", "2024-05-21",
            "--label", "unit",
        ])

        self.assertEqual(args.command, "curated-state-window-finalize")
        self.assertEqual(args.start_date, "2024-05-20")
        self.assertEqual(args.end_date, "2024-05-21")
        self.assertEqual(args.label, "unit")

    def test_cli_accepts_curated_state_window_workers(self):
        args = build_parser().parse_args([
            "curated-state-window",
            "--start-date", "2024-05-20",
            "--end-date", "2024-05-21",
            "--label", "unit",
            "--workers", "4",
        ])

        self.assertEqual(args.command, "curated-state-window")
        self.assertEqual(args.workers, 4)


if __name__ == "__main__":
    unittest.main()
