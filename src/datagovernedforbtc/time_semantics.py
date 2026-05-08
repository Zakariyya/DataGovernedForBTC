from __future__ import annotations

from datetime import datetime, timezone, timedelta

UTC8 = timezone(timedelta(hours=8))


def ms_to_utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def exchange_date_utc8_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC8).date().isoformat()


def candle_close_time_ms(open_time_ms: int, interval_ms: int = 60_000) -> int:
    return open_time_ms + interval_ms
