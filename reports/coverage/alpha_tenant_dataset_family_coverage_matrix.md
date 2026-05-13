# AlphaTenant Dataset Family Coverage Matrix

Generated: `2026-05-13T04:30:02Z`

Universe: `okx_spot_btc_usdt_with_okx_derivative_context`
Exchange consistency: `single_exchange_okx_cross_market_context`; allowed exchanges: `okx`

| exchange | market | instrument | family | raw | governed_feature | snapshot | dates | missing | blocked | admission_status |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| okx | spot | BTC-USDT | candlestick | True | True | True | 568 / 1041 | 473 | 1 | snapshot_available |
| okx | spot | BTC-USDT | trade | True | True | True | 1215 / 1709 | 494 | 0 | snapshot_available |
| okx | spot | BTC-USDT | orderbook | True | True | True | 241 / 716 | 475 | 0 | snapshot_available |
| okx | perpetual | BTC-USDT-SWAP | funding | True | True | True | 1422 / 1528 | 106 | 0 | snapshot_available |
| okx | spot | BTC | borrowing | True | True | True | 412 / 1605 | 1193 | 0 | snapshot_available |
| okx | spot | USDT | borrowing | True | True | True | 412 / 1605 | 1193 | 0 | snapshot_available |
| okx | perpetual | BTC-USDT-SWAP | open_interest | False | False | False | 0 / None | 0 | 0 | unavailable |
| okx | perpetual | BTC-USDT-SWAP | long_short_ratio | False | False | False | 0 / None | 0 | 0 | unavailable |
| okx | perpetual | BTC-USDT-SWAP | liquidation | False | False | False | 0 / None | 0 | 0 | unavailable |
| okx | spot | BTC-USDT | taker_flow | False | False | False | 0 / None | 0 | 0 | unavailable |
| okx | perpetual | BTC-USDT-SWAP | mark_price | False | False | False | 0 / None | 0 | 0 | unavailable |
| okx | spot | BTC-USDT | index_price | False | False | False | 0 / None | 0 | 0 | unavailable |

## Notes

- Raw coverage is not feature readiness.
- Candlestick coverage is not evidence for funding/OI/orderbook/liquidation coverage.
- Binance or other exchanges are not used as OKX proxies; cross-exchange data remains fail-closed.
