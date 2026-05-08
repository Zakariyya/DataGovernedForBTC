# DataGovernedForBTC 治理契约

## 使命

DataGovernedForBTC 的使命是为 AlphaTenant 建立长期稳定、时间因果安全、可复现、可扩展、支持 Walk-Forward 与 Regime Analysis 的 BTC 市场数据资产体系。

## AlphaTenant 读取边界

禁止读取：Raw Tick、Raw L2 OrderBook、未治理 CSV、未确认时间语义的数据、无版本号 Feature。

允许读取：curated_btc_market_state_1m/5m/1h、btc_regime_1m/5m/1h、Walk-Forward Snapshot、data_quality_report。

## Future Leak 防护

任何特征必须满足：

```text
available_time_ms <= feature_time_ms
```

禁止全样本标准化、未来窗口统计、未来数据填补过去缺失、随机 shuffle 破坏时间顺序。

## 缺失值治理

禁止 silently fill missing values。任何缺失或 forward fill 必须输出：is_missing、missing_reason、is_forward_filled、fill_method、fill_source_time_ms、age_ms、source_available、data_quality_score。

## 版本规则

- schema 变化：schema_version += 1
- feature 逻辑变化：feature_version += 1
- regime 规则变化：regime_version += 1
- 治理规则变化：governance_version += 1
