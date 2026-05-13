# AlphaTenant Dataset Family Coverage Matrix

状态：Stage46 恢复模板，等待下一次本地 coverage audit / feature-scan 生成真实数值。

## 用途

这个矩阵用于回答 AlphaTenant：当前 snapshot 中哪些数据家族可用、哪些只是 raw coverage、哪些已经 feature governed、哪些进入 snapshot、哪些被 quality gate 阻断、哪些完全 unavailable。

## 机器可读文件

- `reports/coverage/alpha_tenant_dataset_family_coverage_matrix.json`

## 字段

| 字段 | 含义 |
|---|---|
| exchange | source exchange，默认 OKX |
| market | spot / perpetual / margin 等市场类型 |
| instrument | 源品种 |
| dataset_family | candlestick / funding / borrowing / trade / orderbook / OI 等 |
| min_event_time / max_event_time | 该数据家族真实事件时间范围 |
| date_count / expected_date_count | 实际覆盖日期数 / 期望日期数 |
| missing_dates | 缺失日期 |
| partial_dates | 部分覆盖日期 |
| stale_dates | stale 日期 |
| quality_blocked_dates | 被质量闸门阻断日期 |
| raw_coverage_available | 是否存在 raw coverage |
| governed_feature_available | 是否已进入治理 feature 层 |
| alpha_tenant_snapshot_available | 是否进入 AlphaTenant 可消费 snapshot |
| admission_status | admitted / blocked / unavailable / pending 等 |

## 禁止推断

- 不得从 candles 覆盖推断 funding、OI、orderbook 覆盖。
- 不得把 raw orderbook archive 当成 reconstructed L2 readiness。
- 不得用 Binance 数据代理 OKX 缺失数据。
- 不得把 raw coverage 说成 feature readiness。
