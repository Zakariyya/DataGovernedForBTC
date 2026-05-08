# DataGovernedForBTC 里程碑总结

## 里程碑 0：项目骨架与目录规范

完成时间：2026-05-08

### ✅ 已完成

- 建立 `src/datagovernedforbtc` Python 包结构。
- 建立 `config/`、`docs/`、`manifests/`、`data_lake/`、`reports/`、`snapshots/` 分层目录。
- 明确 `okx/` 为 Raw Source Zone：只读、不覆盖、不重命名、不删除。
- 编写数据目录规范、字段语义规范和治理契约。
- 建立 CLI 入口与基础单元测试。

### 🔒 治理边界

- AlphaTenant 不直接读取 `okx/` Raw Data。
- 文件名日期按交易所 UTC+8 日期处理，不直接当 UTC 日期。
- `Borrowrates/Candlesticks/Fundingrates/Orderbook/Trade` 下的 `Spot` / `Perpetual` 是 source market type 入口，治理程序必须写入 `source_market_type`，并在输出分区中使用 `market=...`。
- 所有训练、Walk-Forward、Feature 时间轴以 UTC 为准。

## 里程碑 1：Candlestick + File Manifest + Quality Report 最小闭环

完成时间：2026-05-08

### ✅ 已完成

- 支持读取 OKX Candlestick `.csv` 与 `.zip`。
- 生成每个原始文件的 File Manifest。
- 生成每个文件的 Candlestick Quality Report。
- 输出 normalized candlestick CSV。
- 正确处理 `open_time`、`close_time_ms`、`available_time_ms`。
- 仅 `confirm=1` 进入 normalized 输出。
- 处理历史文件中 `vol_ccy` / `vol_quote` 为字符串 `None` 的情况。

### 📊 当前结果

- Candlestick 源文件：20
- 成功解析：20
- 失败：0
- 生成 manifest：20
- 生成 quality report：20
- 生成 normalized CSV：20

## 里程碑 2：OKX 历史数据目录审计

完成时间：2026-05-08

### ✅ 已完成

- 输出 coverage / schema / gap / future-leak 风险报告。
- 识别 Orderbook `.data` 为 JSON Lines，不是 CSV。
- 对 Borrowing、Candlestick、Funding、Orderbook、Trade 进行目录级审计。

### 📊 最新审计入口

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli audit-okx
```

报告路径：

- `reports/coverage/okx_directory_audit.json`
- `reports/coverage/okx_directory_audit.md`

## 里程碑 3：Funding/Borrowing 最小闭环

完成时间：2026-05-08

### ✅ 已完成

- 新增 Funding Rate File Manifest + Quality Report + normalized 输出。
- 新增 Borrowing Rate File Manifest + Quality Report + normalized 输出。
- Funding 语义固定为 `official_realized`，normalized 字段使用 `realized_funding_rate`，不生成 `predicted_funding_rate`。
- Funding interval 根据同 instrument 相邻 `funding_time` 推断，不硬编码所有品种 8 小时。
- Borrowing 保留 `borrow_rate_raw`，默认 `borrow_rate_unit=unknown_raw`，不生成 annualized/hourly/percentage 派生字段。
- Borrowing 报告显式统计 BTC/ETH/USDT 是否存在。
- 低频数据 `available_time_ms = event_time_ms + configured_latency_ms`，当前配置 latency 为 0。

### 📊 当前结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli low-frequency-minimal
```

- Funding Rate 源文件：368
- Funding Rate 成功解析：368
- Funding Rate 失败：0
- Borrowing Rate 源文件：20
- Borrowing Rate 成功解析：20
- Borrowing Rate 失败：0

### 🔒 Future-Leak 防护

- Funding 只能在 `funding_time` 之后可用。
- Borrowing 只能在 `time` 之后可用。
- 后续 as-of join 必须输出 `funding_age_ms` / `borrow_rate_age_ms`，并设置 max-age cutoff。

## 里程碑 4：Spot / Perpetual 双层目录适配

完成时间：2026-05-08

### ✅ 已完成

- 新增 `path_semantics.py`，从原始文件路径识别 `source_market_type=spot|perpetual|unknown`。
- Candlestick / Funding / Borrowing 的 Manifest、Normalized 输出都写入 `source_market_type`。
- 输出路径增加 `market=spot|perpetual|unknown` 分区，避免现货与永续同日期文件互相覆盖。
- OKX 目录审计报告新增 `market_type_counts`。
- 清理旧版未带 market 分区的 Candlestick / Funding / Borrowing 产物，并重新生成。

### 📊 当前验证结果

- Candlestick manifest：20，market=spot
- Funding manifest：368，market=perpetual
- Borrowing manifest：20，market=spot
- 所有 manifest 数量均与对应源文件数一致。

## 下一步建议

1. 将 Candlestick / Funding / Borrowing normalized CSV 升级为 Parquet。
2. 实现 Trade History Manifest + Quality + 聚合特征入口。
3. 实现 Orderbook 安全审计入口：snapshot/update、crossed book、best_bid/best_ask、无前置 snapshot update。
4. 构建 `curated_btc_market_state_1m` 的 as-of join 原型。
