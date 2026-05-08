# DataGovernedForBTC 数据目录规范

## 1. 原始数据输入区：`okx/`

`okx/` 是当前已存在的 OKX 原始数据落地点，视为 Raw Source Zone。治理程序只能读取它，不得修改、覆盖、重命名或删除其中任何原始文件。

```text
okx/
  Borrowrates/Spot/YYYY/allmargin-borrowrates-YYYY-MM-DD.csv
  Candlesticks/Spot/YYYY/BTC-USDT-candlesticks-YYYY-MM-DD.csv 或 .zip
  Candlesticks/Perpetual/YYYY/<instrument>-candlesticks-YYYY-MM-DD.csv 或 .zip
  Fundingrates/Perpetual/YYYY/allswap-fundingrates-YYYY-MM-DD.csv
  Orderbook/Spot/YYYY/BTC-USDT-L2orderbook-400lv-YYYY-MM-DD.data 或 .data.txt
  Orderbook/Perpetual/YYYY/<instrument>-L2orderbook-400lv-YYYY-MM-DD.data 或 .data.txt
  Trade/Spot/YYYY/BTC-USDT-trades-YYYY-MM-DD.csv
  Trade/Perpetual/YYYY/<instrument>-trades-YYYY-MM-DD.csv
```

`Spot` / `Perpetual` 是治理程序必须识别的 source market type，不能只依赖文件名或 instrument 后缀判断。所有 Manifest、Quality、Normalized 输出必须保留 `source_market_type`，并在分区路径中使用 `market=spot|perpetual|unknown` 防止现货与永续同名日期产物互相覆盖。

注意：文件名中的 `YYYY-MM-DD` 默认按交易所 UTC+8 日期解释，不能直接当作 UTC 日期。

## 2. Manifest 输出区：`manifests/`

每个原始文件必须生成 File Manifest。

```text
manifests/
  exchange=okx/
    dataset_type=candlestick/
      instrument=BTC-USDT/
        exchange_date_utc8=YYYY-MM-DD/
          file_manifest.json
```

Manifest 至少包含：source_file_name、source_file_path、source_file_hash、dataset_type、exchange、instrument_name、instrument_type、source_file_date、exchange_date_utc8、row_count、min_event_time_ms、max_event_time_ms、ingested_at、schema_version、governance_version、parse_status、parse_error_message。

## 3. 治理数据湖：`data_lake/`

```text
data_lake/
  raw/
  normalized/
  features/
  regime/
```

### `data_lake/raw/`

Raw Layer 不复制或改写原始大文件时，也必须通过 manifest/hash 保持可追溯。若未来需要归档副本，必须保证字节级不变。

### `data_lake/normalized/`

统一字段：exchange、dataset_type、instrument_name、instrument_type、event_time_ms、event_time_utc、available_time_ms、available_time_utc、source_file_name、source_file_hash、schema_version、governance_version、data_quality_score。

### `data_lake/features/`

推荐分区：

```text
data_lake/features/
  exchange=okx/
    instrument=BTC-USDT/
      interval=1m/
        exchange_date_utc8=YYYY-MM-DD/
```

Feature 只能使用 `available_time_ms <= feature_time_ms` 的数据。

### `data_lake/regime/`

Regime 是市场状态描述，不是交易信号。每个标签必须保存触发依据与版本号。

## 4. Walk-Forward 快照：`snapshots/`

```text
snapshots/
  exchange=okx/
    instrument=BTC-USDT/
      interval=1m/
        snapshot_id=YYYYMMDDTHHMMSSZ/
```

Snapshot 必须记录输入 manifest 集合、schema_version、feature_version、regime_version、governance_version、生成时间、时间范围和 hash。

## 5. 报告区：`reports/`

```text
reports/
  quality/
  coverage/
  gap/
  future_leak/
```

每次治理必须输出 Data Quality Report；覆盖率、缺口和 future-leak 风险审计单独归档。
