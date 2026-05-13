# AlphaTenant Research Readiness Report: okx_btc_market_state_5m_v0_3_20240520_20241108_stage46

Generated: `2026-05-13T06:42:08Z`

Readiness status: `research_ready_with_row_level_quality_filter`
Required filter: `allow_into_feature_layer == True`

## Exchange Consistency

- Universe: `okx_spot_btc_usdt_with_okx_derivative_context`
- Scope: `single_exchange_okx_cross_market_context`
- Allowed source exchanges: `okx`
- Mixed exchange features present: `False`
- Mixed exchange policy: `fail_closed`

## Row Counts

- row_count: 49824
- allowed_row_count: 33116
- blocked_row_count: 16708
- allowed_ratio: 0.664660

## Feature Group Coverage

- `borrowing_context`: 6
- `cost_liquidity_context`: 16
- `data_quality_context`: 41
- `funding_context`: 4
- `opportunity_context`: 1
- `orderbook_microstructure`: 15
- `price_context`: 19
- `regime_input_context`: 5
- `tail_risk_context`: 3
- `trade_flow_context`: 7
- `volatility_context`: 16

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
