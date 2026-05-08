from __future__ import annotations

EXPECTED_COLUMNS = {
    "candlestick": [
        "instrument_name", "open", "high", "low", "close", "vol", "vol_ccy", "vol_quote", "open_time", "confirm"
    ],
    "funding_rate": ["instrument_name", "funding_rate", "funding_time"],
    "borrowing_rate": ["currency_name", "borrow_rate", "time"],
    "trade": ["instrument_name", "trade_id", "side", "price", "size", "created_time"],
    "orderbook": ["instId", "action", "asks", "bids", "ts"],
}
