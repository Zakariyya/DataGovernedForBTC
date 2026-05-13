# AlphaTenant Research Readiness Report Template

状态：Stage46 恢复模板。

## 用途

每个 DataGovernedForBTC snapshot 后续应发布一份 AlphaTenant 专用 research readiness report。该报告只说明数据研究可用性、质量边界与禁止用途，不声明策略收益、不触发 Level2、不构成 ALLOW_PAPER。

## 机器可读文件

- `reports/readiness/alpha_tenant_research_readiness_template.json`

## 必填内容

- `snapshot_id`
- `universe_id`
- `exchange_consistency_status`
- `research_window_start / research_window_end`
- `sealed_verification_boundary`
- `row_count / allowed_row_count / blocked_row_count / allowed_ratio`
- `dataset_family_coverage`
- `feature_group_coverage`
- `missing_stale_blocked_summary`
- `no_lookahead_checks`
- `future_leak_violation_count`
- `allowed_alpha_tenant_use`
- `forbidden_alpha_tenant_use`

## allowed_alpha_tenant_use

- coverage_audit
- structural_hypothesis_preregistration
- research_only_feature_matrix
- regime_input_research
- no_lookahead_alignment
- forward_observation_input

## forbidden_alpha_tenant_use

- live_trading
- paper_trading_permission
- level2_auto_upgrade
- parameter_selection
- direct_trade_signal
- cross_exchange_proxy

## 审计边界

- 该报告不是策略报告。
- 该报告不得使用策略 PnL、收益排序或参数扫描结果。
- 该报告必须显式说明 `required_filter = allow_into_feature_layer == True`。
- 若 coverage matrix 显示某数据家族 unavailable，不得用其他交易所或其他数据家族代理。
