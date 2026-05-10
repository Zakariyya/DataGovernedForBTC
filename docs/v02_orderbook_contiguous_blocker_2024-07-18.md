# v0.2-orderbook-contiguous 阻断报告：2024-07-18 K 线 mixed confirm

## 结论

当前 `target_2024-05-20_to_2024-11-08_with_orderbook` 不能合规发布完整 173 天 snapshot。

原因不是 Trade / Orderbook 缺失，而是 Spot BTC-USDT Candlestick 的 `2024-07-18` 被质量门禁阻断：原始文件虽然有 1440 个唯一 1m open_time 且无 gap/重复/OHLC 异常，但 `confirm` 字段混合，当前治理规则将其标记为 `mixed_confirm_values_unresolved`，`allow_into_training=false`。

在清理陈旧产物后：

- `2024-06-25`：已通过“完全相同 open_time 重复行去重”治理，normalized 1440 行。
- `2024-07-18`：normalized 已被删除；curated 日分区已被删除；窗口 finalize fail-closed。
- 窗口 summary：`admission_status=rejected_missing_day_partitions`，`missing_day_partitions=["2024-07-18"]`。

## 2024-07-18 原始 K 线审计

原始文件：

`okx/Candlesticks/Spot/2024/BTC-USDT-candlesticks-2024-07-18.csv`

审计结果：

- raw rows: 1440
- unique open_time: 1440
- gap_count: 0
- duplicate_open_time_count: 0
- ohlc_invalid_count: 0
- negative_volume_count: 0
- confirm=0: 609 行
  - UTC: 2024-07-17T16:00:00 ~ 2024-07-18T02:08:00
- confirm=1: 831 行
  - UTC: 2024-07-18T02:09:00 ~ 2024-07-18T15:59:00

当前质量报告字段：

- `source_archive_confirm_policy = mixed_confirm_values_unresolved`
- `data_quality_flags = mixed_confirm_values`
- `allow_into_training = false`

## 已完成的治理修复

1. `curated-state-window-finalize` 缺日 fail-closed：缺任意日分区时不再生成窗口 CSV。
2. Candlestick 完全相同重复 open_time 行可审计去重：只接受完全相同重复行；冲突重复仍阻断。
3. Candlestick 被阻断时删除对应旧 normalized CSV/Parquet，防止旧策略产物残留。
4. Curated day rows 为空时删除对应旧日分区 CSV。
5. Curated window finalize 缺日时删除旧窗口 CSV。

## 当前状态

目标窗口：`2024-05-20 ~ 2024-11-08`

目标 label：`target_2024-05-20_to_2024-11-08_with_orderbook`

当前窗口状态：

- expected_day_partitions: 173
- day_partitions_used: 172
- missing_day_partitions: `["2024-07-18"]`
- output: null
- admission_status: `rejected_missing_day_partitions`

## 后续可选方案

### 方案 A：保持严格治理，等待/补充真实更干净 K 线源

优点：最稳妥，不扩大 confirm 语义假设。

缺点：当前完整 173 天 v0.2 snapshot 无法发布。

### 方案 B：缩短 v0.2 clean window，避开 2024-07-18

例如拆成：

- `2024-05-20 ~ 2024-07-17`
- 或 `2024-07-19 ~ 2024-11-08`

优点：无需扩大质量规则。

缺点：训练窗口变短或断裂。

### 方案 C：新增明确的 mixed-confirm 历史归档政策

只有在用户明确认可后，才可 TDD 增加类似：

`historical_archive_mixed_confirm_closed_bar_by_complete_daily_file`

候选前提必须至少包括：

- 1440 唯一 open_time
- 无 gap
- 无重复
- 无 OHLC/volume 异常
- 保留 raw `confirm` 不改写
- 标记 `mixed_confirm_values_inferred_closed_bar`
- 降低质量分或保留显式风险 flag

注意：这是扩大治理假设，不应默认执行。
