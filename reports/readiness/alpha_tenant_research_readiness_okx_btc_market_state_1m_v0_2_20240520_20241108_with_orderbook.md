# AlphaTenant Research Readiness Report: okx_btc_market_state_1m_v0_2_20240520_20241108_with_orderbook

Generated: `2026-05-13T04:32:18Z`

Readiness status: `research_ready_with_row_level_quality_filter`
Required filter: `allow_into_feature_layer == True`

## Exchange Consistency

- Universe: `okx_spot_btc_usdt_with_okx_derivative_context`
- Scope: `single_exchange_okx_cross_market_context`
- Allowed source exchanges: `okx`
- Mixed exchange features present: `False`
- Mixed exchange policy: `fail_closed`

## Row Counts

- row_count: 249120
- allowed_row_count: 165673
- blocked_row_count: 83447
- allowed_ratio: 0.665033

## Feature Group Coverage

- `borrowing_context`: 6
- `data_quality_context`: 24
- `funding_context`: 3
- `orderbook_microstructure`: 10
- `price_context`: 6
- `trade_flow_context`: 6

## No-lookahead Checks

- `all_features_available_time_lte_feature_time`: True
- `rolling_features_use_current_and_past_only`: True
- `future_window_regime_confirmation_used`: False
- `strategy_pnl_used_in_features`: False

## Allowed AlphaTenant Use

- coverage_audit
- structural_hypothesis_preregistration
- research_only_feature_matrix
- regime_input_research
- no_lookahead_alignment
- forward_observation_input

## Forbidden AlphaTenant Use

- live_trading
- paper_trading_permission
- level2_auto_upgrade
- parameter_selection
- direct_trade_signal
- cross_exchange_proxy

## Boundary

This report does not authorize live trading, paper trading, Level2 upgrade, parameter selection, or direct trade-signal use.
