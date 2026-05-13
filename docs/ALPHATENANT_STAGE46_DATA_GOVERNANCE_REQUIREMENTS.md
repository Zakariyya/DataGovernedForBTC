# AlphaTenant Stage46 数据治理需求响应

完成时间：2026-05-13

## 1. 背景

AlphaTenant 当前策略失败复盘结论表明，主要问题不是参数，而是结构性数据与研究边界问题：机会集覆盖不足、regime / 策略职责错位、压力成本脆弱、cash / no-trade 与 alpha 混淆、收益集中度风险，以及 OKX 单交易所策略不得混入 Binance 因子的交易所一致性约束。

DataGovernedForBTC 的响应边界是：提供 time-causal、可审计、可 fail-closed 的市场状态、机会集、成本/流动性、尾部风险与数据可用性治理；不提供交易信号、不提供策略收益、不提供 Level2 readiness、不提供 ALLOW_PAPER 建议。

## 2. 总原则

- DataGovernedForBTC 是数据治理层，不是策略层。
- 所有字段必须能证明 `available_time_ms <= feature_time_ms`。
- rolling / percentile / score 只能使用当前及过去数据。
- 缺失、stale、重建失败必须显式 flag，禁止 forward-fill 成正常状态。
- OKX snapshot 默认只允许 OKX source exchange；跨交易所字段 fail-closed 或发布到隔离 universe。
- raw coverage 不等于 feature readiness；orderbook archive 不等于 reconstructed L2 readiness。
- AlphaTenant 消费前必须过滤：`allow_into_feature_layer == True`。

## 3. P0：Snapshot / Feature Contract 角色边界

### 要求

snapshot / snapshot_index / feature_contract 必须机器可读地提供：

- `allowed_feature_columns`
- `forbidden_as_features`
- `feature_group`
- `feature_role`
- `forbidden_usage`
- `required_filter = allow_into_feature_layer == True`

### feature_group 词表

- `price_context`
- `volatility_context`
- `liquidity_context`
- `trade_flow_context`
- `orderbook_microstructure`
- `funding_context`
- `borrowing_context`
- `data_quality_context`
- `regime_context`
- `activity_context`
- `opportunity_context`
- `regime_input_context`
- `cost_liquidity_context`
- `tail_risk_context`

### feature_role 词表

- `raw_observed_market_state`
- `derived_causal_feature`
- `quality_gate`
- `regime_input`
- `cost_liquidity_input`
- `opportunity_input`
- `tail_risk_context_input`
- `not_alpha_signal`

### forbidden_usage 词表

- `trade_signal`
- `order_generation`
- `position_generation`
- `parameter_selection`
- `level2_approval`
- `allow_paper_decision`

### 当前恢复动作

- `src/datagovernedforbtc/snapshot.py` 已扩展 `build_schema()` / `build_snapshot_entry()`。
- `schema.json`、`feature_contract.md` 与 `snapshots/snapshot_index.json` 的新生成结果将包含上述机器字段。
- `tests/test_snapshot_index.py` 已覆盖新增 contract 字段与交易所一致性字段。

## 4. P0：Opportunity Set / Activity Eligibility 输入层

目标是提供“机会集输入”，不是是否交易。

候选字段方向：

- `rolling_realized_volatility_5m / 15m / 1h`
- `rolling_range_pct_5m / 15m / 1h`
- `candle_body_to_range_ratio`
- `close_location_in_range`
- `intraday_range_percentile_causal`
- `recent_gap_or_missing_bar_count`
- `trade_count_1m / 5m`
- `trade_volume_1m / 5m`
- `orderbook_spread_bps`
- `orderbook_depth_near_mid`
- `orderbook_update_count_1m`
- `orderbook_snapshot_age_ms`
- `liquidity_data_stale_flag`
- `no_activity_or_low_information_flag`

治理要求：

- 命名使用 `context` / `input` / `flag`，禁止 `buy/sell/active_signal`。
- 每个字段输出 coverage、missing_rate、stale_rate。
- stale / missing 不得被填成正常市场状态。

## 5. P0：Regime Transition / Volatility Expansion 输入层

目标是提供事前 regime input，不提供 regime 下的买卖解释。

候选字段方向：

- `causal_trend_slope_15m / 1h / 4h`
- `rolling_high_low_breakout_distance`
- `volatility_expansion_ratio`
- `realized_volatility_regime_percentile`
- `range_compression_score`
- `range_expansion_score`
- `trend_persistence_score`
- `choppiness_or_range_bound_score`
- `market_state_transition_candidate_flag`

治理要求：

- 生成逻辑必须文档化。
- 不得使用未来窗口确认当前 regime。
- rolling percentile 必须记录 lookback window 与 min_periods。
- snapshot 附带 `regime_feature_contract`，声明这些是研究输入，不是策略标签。

## 6. P0：Cost / Liquidity Fragility 输入层

目标是让 AlphaTenant 能做 risk filter / reducer 研究，而不是让策略自行猜测成本状态。

候选字段方向：

- `spread_bps`
- `spread_percentile_causal`
- `top_of_book_depth_usd`
- `depth_10bps_usd / depth_25bps_usd`
- `orderbook_imbalance_near_mid`
- `trade_volume_usd_1m / 5m`
- `trade_count_1m / 5m`
- `volume_drought_flag`
- `orderbook_stale_ms`
- `orderbook_reconstruction_quality`
- `crossed_book_flag`
- `update_without_snapshot_count`
- `liquidity_fragility_flag`
- `estimated_minimum_slippage_bucket`

治理要求：

- `estimated_minimum_slippage_bucket` 只能是粗分桶，不得由策略收益反推。
- row-level flags 必须包括：`orderbook_missing`、`orderbook_stale`、`spread_unavailable`、`depth_unavailable`、`liquidity_context_unreliable`。
- 严重 orderbook 缺失或重建失败应影响 `allow_into_feature_layer`。

## 7. P0：交易所一致性治理

snapshot / feature_contract / snapshot_index 必须显式提供：

- `universe_id`
- `exchange`
- `market`
- `instrument`
- `instrument_type`
- `source_exchange`
- `source_market_type`
- `source_instrument`
- `source_dataset_family`
- `exchange_consistency_scope`
- `allowed_source_exchanges`
- `mixed_exchange_features_present`
- `mixed_exchange_usage_policy`

默认规则：

- OKX BTC-USDT spot 策略只能默认消费 OKX BTC-USDT spot 及明确标注的 OKX derivative context。
- Binance 数据不得混入 OKX 单交易所 snapshot。
- Binance universe 必须发布独立 snapshot universe。

## 8. P1：Tail / Payoff Shape 市场上下文

DataGovernedForBTC 不计算策略收益集中度，但可以提供市场厚尾上下文：

- `rolling_return_abs_percentile`
- `rolling_downside_volatility`
- `intraday_extreme_move_flag`
- `wick_ratio / tail_ratio`
- `jump_candidate_flag`
- `funding_shock_context`（仅 OKX funding 可用时）
- `spread_shock_flag`
- `depth_collapse_flag`
- `volatility_cluster_score`

禁止用策略 PnL 或未来极值确认当前 tail flag。

## 9. P1：Dataset Family Coverage Matrix

按以下维度发布：

- `exchange`
- `market`
- `instrument`
- `dataset_family`
- `min_event_time`
- `max_event_time`
- `date_count`
- `expected_date_count`
- `missing_dates`
- `partial_dates`
- `stale_dates`
- `quality_blocked_dates`
- `governed_feature_available`
- `alpha_tenant_snapshot_available`
- `admission_status`

dataset family 至少覆盖：`candlestick`、`funding`、`borrowing`、`trade`、`orderbook`、`open_interest`、`long_short_ratio`、`liquidation`、`taker_flow`、`mark_price`、`index_price`。

## 10. P1：Row-level Quality Reason Codes

新增或规范：

- `allow_into_feature_layer`
- `blocked_reason_codes`
- `warning_reason_codes`
- `missing_or_stale_source_count`
- `future_leak_violation_count`
- `source_family_missing_flags`
- `source_family_stale_flags`
- `overall_data_quality_score`

典型 blocked reason codes：

- `candle_missing`
- `candle_duplicate_conflict`
- `candle_confirm_unresolved`
- `trade_feature_missing`
- `orderbook_feature_missing`
- `orderbook_stale`
- `orderbook_reconstruction_unreliable`
- `funding_missing`
- `borrowing_missing`
- `future_leak_violation`
- `mixed_exchange_source`
- `insufficient_source_coverage`

## 11. P1：Multiple Resolution / Horizon-safe 聚合

逐步支持：

- `curated_btc_market_state_15m`
- `curated_btc_market_state_1h`
- `btc_regime_5m`
- `btc_regime_15m`
- `btc_regime_1h`

要求：

- 高周期必须从已治理低周期聚合。
- 输出 `window_start`、`window_end`、`feature_time_ms`。
- low-frequency / orderbook state 使用窗口结束时可得 as-of 状态。
- 高周期也必须有 feature_contract、schema、quality_summary、source_manifest。

## 12. P1：AlphaTenant Research Readiness Report

每个 snapshot 发布专用 readiness report：

- snapshot_id / universe_id
- exchange consistency status
- research window / sealed verification boundary
- row counts / allowed ratio
- dataset_family_coverage
- feature_group_coverage
- missing / stale / blocked summary
- no-lookahead checks
- allowed_alpha_tenant_use
- forbidden_alpha_tenant_use

## 13. P2：明确禁止事项

DataGovernedForBTC 禁止：

1. 生成 buy/sell/long/short 信号。
2. 计算策略收益。
3. 给 Level2 readiness。
4. 给 ALLOW_PAPER 建议。
5. 基于 AlphaTenant 策略结果反推特征阈值。
6. 把 Binance 数据混入 OKX snapshot。
7. 对缺失数据插值伪造。
8. 把 raw coverage 说成 feature readiness。
9. 把 orderbook raw archive 说成 reconstructed L2 readiness。
10. 发布无版本、无 schema、无 quality summary 的中间层给 AlphaTenant。

## 14. 本轮交付物

- `docs/ALPHATENANT_STAGE46_DATA_GOVERNANCE_REQUIREMENTS.md`
- `schemas/alphatenant_snapshot_feature_contract_v_next.json`
- `reports/coverage/alpha_tenant_dataset_family_coverage_matrix.json`
- `reports/coverage/alpha_tenant_dataset_family_coverage_matrix.md`
- `reports/readiness/alpha_tenant_research_readiness_template.json`
- `reports/readiness/alpha_tenant_research_readiness_template.md`
- `src/datagovernedforbtc/snapshot.py` contract/index 扩展
- `tests/test_snapshot_index.py` contract/index TDD 覆盖

## 15. 一句话总结

DataGovernedForBTC 下一步不是给 AlphaTenant 更多可交易信号，而是给 AlphaTenant 更可审计的机会集输入、regime transition 输入、成本/流动性脆弱输入、尾部风险上下文、数据家族覆盖矩阵、交易所一致性证明和 row-level quality reason codes。
