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

## 里程碑 5：Trade History 治理与 1m 聚合特征安全样本闭环

完成时间：2026-05-08

### ✅ 已完成

- 新增 `trade.py`，实现 Trade File Manifest + Quality Report + normalized tick + 1m trade feature 输出。
- 按 `trade_id` 去重，按 `created_time` 排序，不假设原文件有序。
- 保留 `side_raw`，显式标记 `side_semantics=unknown_not_assumed_taker`。
- 不生成 `aggressive_buy_volume`、`aggressive_sell_volume`、`aggressive_delta` 等 taker-side 依赖字段。
- 1m 聚合窗口使用 `window_start_ms <= created_time < window_end_ms`，并将 `feature_time_ms = available_time_ms = window_end_ms`。
- CLI 新增 `trade-minimal --max-files N`，避免在 21GB raw trade 数据上误触发一次性全量 normalized tick 输出。

### 📊 当前真实样本验证结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli trade-minimal --max-files 5
```

- Trade 总发现源文件：1215
- 本次安全样本源文件：5
- 成功解析：5
- 失败：0
- normalized rows：2,363,551
- 1m feature rows：7,200
- duplicate trade_id：0
- 生成 manifest：5
- 生成 quality report：5
- 生成 normalized CSV：5
- 生成 1m feature CSV：5

### 🔒 Future-Leak 防护

- 原始 tick 不直接给 AlphaTenant 使用。
- 1m Trade Feature 只在窗口结束后可用。
- `side` 不被解释为 taker side，避免错误生成 aggressive 类方向特征。
- 全量 1215 文件约 21GB raw，后续全量治理应先升级为流式处理与 Parquet/分批断点续跑。

## 里程碑 6：Orderbook L2 安全审计入口

完成时间：2026-05-08

### ✅ 已完成

- 新增 `orderbook.py`，实现 L2 JSON Lines 安全审计入口。
- CLI 新增 `orderbook-audit --max-lines N --max-files N`，默认每个文件只抽样前 5000 行，避免误触发 3GB+ L2 全量重建。
- 生成 Orderbook File Manifest、Quality Report 与 snapshot sample feature。
- 统计 snapshot/update 数量、无前置 snapshot 的 update、empty asks/bids、depth level、depth=400 完整度、snapshot crossed book。
- 明确不应用 update 重建完整盘口；无 sequence/checksum 时只标记 `book_reconstruction_quality`，不证明连续性。
- 修正一个重要语义坑：update 行的 asks/bids 是增量更新数组，不能直接用 update 数组判断 `best_bid < best_ask`；crossed book 只对 snapshot / sample feature 判断。

### 📊 当前真实样本验证结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli orderbook-audit --max-lines 5000
```

- Orderbook 源文件：5
- 成功解析：5
- 失败：0
- sample feature rows：5
- manifest：5
- quality report：5
- sample feature CSV：5
- snapshot crossed book：0
- update_without_snapshot：0
- book_reconstruction_quality：`snapshot_only_sample`

### 🔒 Future-Leak / L2 质量边界

- 当前只审计 snapshot 样本，不把 raw L2 或 update 重建盘口直接交给 AlphaTenant。
- update 没有 sequence/checksum，不能证明连续性。
- 后续如需 L2 feature，必须先实现有质量标签的重建器，且对无前置 snapshot、crossed book、depth 不足、stale book 做显式标记。

## 里程碑 7：curated_btc_market_state_1m 最小 as-of join 原型

完成时间：2026-05-08

### ✅ 已完成

- 新增 `curated_state.py`，实现朴素、清晰、可审计的 1m 主状态表原型。
- 主时间轴使用 Candlestick `close_time_ms` / `available_time_ms`。
- Funding / Borrowing 使用 as-of join：只允许 `available_time_ms <= feature_time_ms`。
- Funding 显式限定 BTC-USDT-SWAP，不从 allswap 多 instrument 数据中随意取其他 instrument。
- Borrowing 输出 BTC/ETH/USDT 的 raw rate 与 age 字段，不做单位换算。
- Trade Feature 只接受当前 1m `feature_time_ms` 精确匹配；缺失时输出 `trade_feature_missing_reason=no_current_trade_feature`，不做无标记 forward fill。
- CLI 新增 `curated-state-minimal --max-candle-files N --max-trade-files N`。
- 按用户要求避免过度优化：当前实现不做复杂索引、不做性能工程，只作为时间因果正确性原型。

### 📊 当前真实样本验证结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-minimal --max-candle-files 1 --max-trade-files 1
```

- 选中 candle 文件：2026-05-06 1m
- 输出行数：1440
- Funding 文件：396
- Borrowing 文件：20
- Trade feature 文件：1
- 首行 funding_age_ms：60000
- 首行 usdt_borrow_rate_age_ms：60000
- Trade feature 因当前只生成了 2021 样本，与 2026 candle 不重叠，显式标记 missing。

### 🔒 时间因果边界

- 所有低频数据必须满足 `available_time_ms <= feature_time_ms`。
- Funding / Borrowing forward-as-of 必须带 age 字段。
- 当前不做无标记填充，不用未来 Trade feature 填当前 candle。

## 里程碑 8：OKX 最新数据特征点扫描与 AlphaTenant 数据集形状确认

完成时间：2026-05-08

### ✅ 已完成

- 新增 `feature_scan.py`，对 `okx/` 最新 Raw Source Zone 做轻量特征点扫描。
- CLI 新增 `feature-scan`，输出 JSON 与 Markdown 报告。
- 扫描只读取路径、日期、扩展名、表头/少量 JSONL key，不全量加载 46GB+ raw 数据。
- 明确给 AlphaTenant 的目标数据集形状：
  - `curated_btc_market_state_1m`
  - `curated_btc_market_state_5m`
  - `btc_regime_1m`
  - `data_quality_report`
- 修正 scanner：Orderbook 新增 `.tar.gz` 归档必须计入文件覆盖，但字段抽样优先读取 `.data/.data.txt`，不展开大归档。

### 📊 最新 Raw Feature Point 扫描结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli feature-scan
```

- Borrowing Rate：34 文件，spot，2021-12-14 → 2026-05-06，字段 `currency_name, borrow_rate, time`
- Candlestick：374 文件，perpetual 184 / spot 190，2023-07-01 → 2026-05-06，字段 `instrument_name, open, high, low, close, vol, vol_ccy, vol_quote, open_time, confirm`
- Funding Rate：396 文件，perpetual，2022-03-01 → 2026-05-06，字段 `instrument_name, funding_rate, funding_time`
- Orderbook：58 文件，perpetual 18 / spot 40，2024-05-20 → 2026-05-05，扩展名 `.data` 5 / `.tar.gz` 23 / `.tar.tar` 30，字段 `action, asks, bids, instId, ts`（可读 `.data` 样本；归档不展开）
- Trade：1672 文件，perpetual 457 / spot 1215，2021-09-01 → 2026-05-06，字段 `instrument_name, trade_id, side, price, size, created_time`

### 🎯 AlphaTenant 后续数据集形状判断

- 第一优先：`curated_btc_market_state_1m`
  - 主键：`exchange, instrument_name, feature_time_ms`
  - 粒度：BTC-USDT 1m candle close_time 一行
  - 必备字段：OHLCV、Funding、Borrowing、Trade 1m、Orderbook-derived、质量分
  - 必备 age 字段：`funding_age_ms`, `btc/eth/usdt_borrow_rate_age_ms`, `trade_feature_age_ms`, `orderbook_feature_age_ms`
- 第二优先：`data_quality_report`
  - 作为 AlphaTenant 数据准入门，不通过质量闸门的数据不能进入训练。
- 第三优先：`btc_regime_1m`
  - 基于 curated state 的可解释 rule-based regime，不使用未来 rolling / 全样本 quantile。
- `curated_btc_market_state_5m` 后续应从 1m governed state 聚合，不直接绕过 1m 质量层。

### 🔒 边界

- AlphaTenant 仍不能读取 raw CSV、raw tick、raw L2、未治理归档或无版本特征。
- 当前扫描用于确认形状，不代表数据已全部可进入 AlphaTenant。
- 不做过度优化：本轮只产出轻量 scanner 与形状报告，后续按质量闸门逐步补齐。

## 下一步建议

1. 为 `curated_btc_market_state_1m` 增加轻量质量闸门：future-leak 检查、age 超限检查、missing 占比、overall_data_quality_score。
2. 将 Trade 全量治理升级为流式 + Parquet + checkpoint，避免一次性写出超大 CSV。
3. 将 Orderbook `.tar.gz` 归档纳入安全解包/抽样审计入口，仍不直接重建或喂给 AlphaTenant。
4. 在质量闸门稳定后，再将 Candlestick / Funding / Borrowing / Trade Feature 统一升级为 Parquet 优先输出。

## 里程碑 9：curated_btc_market_state_1m 轻量质量闸门

完成时间：2026-05-09

### ✅ 已完成

- 为 `curated_btc_market_state_1m` 增加行级质量闸门字段：
  - `future_leak_violation_count`
  - `data_quality_flags`
  - `missing_or_stale_source_count`
  - `overall_data_quality_score`
  - `allow_into_feature_layer`
- 对 Funding / Borrowing age 设置保守上限，超限时打标而不是静默准入。
- 对 BTC/ETH/USDT Borrowing 缺失、Trade Feature 缺失做显式 flags。
- 保持 Trade Feature 只能精确匹配当前 1m `feature_time_ms`；不做无标记 forward fill。
- 新增 TDD 单测覆盖 missing / stale source 的质量闸门行为。

### 📊 当前真实样本验证结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-minimal --max-candle-files 1 --max-trade-files 1
```

- 输出行数：1440
- 质量闸门字段已写入 CSV。
- `future_leak_violation_count=0`。
- 当前样本中 2026 candle 与已生成 2021 trade feature 样本不重叠，因此 1440 行均标记 `trade_feature_missing`。
- `allow_into_feature_layer=False`：这是预期的保守准入结果，表示当前 minimal sample 还不能直接交给 AlphaTenant 训练/研究使用。

### 🔒 AlphaTenant 准入边界

- `feature-scan` 与 curated minimal 原型仍只是治理证据，不等于数据准入许可。
- AlphaTenant 后续只能消费 `allow_into_feature_layer=True` 且版本/质量报告匹配的 governed feature/regime/snapshot。
- 若 Trade / Orderbook 特征未覆盖当前 1m 时间戳，必须以缺失/过期 flag 表示，不允许静默补值或用未来数据回填。

## 里程碑 10：Orderbook `.tar.tar` 归档纳入轻量扫描覆盖

完成时间：2026-05-09

### ✅ 已完成

- 修正 `feature_scan.py` 的 Orderbook 原始文件识别规则。
- `.tar.tar` 与 `.tar.gz`、`.data`、`.data.txt` 一样纳入 coverage 统计。
- 归档文件只计入覆盖与日期范围，不在 lightweight scan 中展开。
- 新增 TDD 单测，验证 `.data` / `.tar.gz` / `.tar.tar` 同时存在时 file count、extension count、date range 与 JSONL sample fields 都正确。

### 📊 当前真实 Raw Source Zone 扫描结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli feature-scan
```

Orderbook 最新统计：

- 文件总数：58
- market_type_counts：perpetual 18 / spot 40
- extension_counts：`.data` 5 / `.tar.gz` 23 / `.tar.tar` 30
- 日期范围：2024-05-20 → 2026-05-05
- Perpetual 当前样本为归档：`tar.tar_archive_not_expanded`
- Spot 当前样本可读取 JSONL 字段：`action, asks, bids, instId, ts`

### 🔒 边界

- `.tar.tar` 被识别为 OKX Raw Orderbook coverage，不代表 L2 已完成重建。
- Lightweight scan 不展开归档、不验证归档内部连续性、不生成可训练 Orderbook feature。
- 后续若要利用归档，需另建“安全解包 / 抽样审计 / 质量标签”入口，仍不得直接向 AlphaTenant 暴露 raw L2。

## 里程碑 10：2024-05-20 ~ 2024-06-11 目标窗口治理跑通（不训练）

完成时间：2026-05-09

### ✅ 已完成

- 按 TDD 增加 Candlestick 历史归档 `confirm=0` 语义测试，先观察 RED，再实现 GREEN。
- 保留 OKX API 官方语义：`confirm=0` 表示 API 当前 K 线未完成，`confirm=1` 表示完成。
- 针对本地 OKX 历史归档的特殊形态新增显式治理策略：当日文件完整 1440 行、无 gap、无重复 open_time、无 OHLC/负成交量异常、且全量 `confirm=0` 时，标记为 `source_archive_confirm_policy=historical_archive_confirm_0_closed_bar_by_complete_daily_file`。
- 不把 `confirm=0` 静默改成 `confirm=1`；normalized 中仍保留原始 `confirm=0`，并增加 `data_quality_flags=source_archive_confirm_0_closed_bar_inferred`。
- `allow_into_training` 由“时间完整 + 历史归档语义确认 + 无 gap + 无 OHLC/成交量异常”共同决定；本次仍不启动训练，仅用于跑通治理链路。
- `trade-minimal` 新增 `--start-date/--end-date/--market/--instrument`，按日期窗口、市场与品种过滤，避免误处理不相关年份/市场。
- 新增 `curated-state-window`，按目标窗口生成 `curated_btc_market_state_1m`，主时间轴为 Spot BTC-USDT 1m candle，Funding/Borrowing as-of join，Trade 1m feature 精确匹配。
- 当前窗口暂不纳入 Orderbook，行级字段显式记录 `orderbook_feature_missing_reason=not_included_in_current_window`。

### 📊 目标窗口真实验证结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli candlestick-minimal
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli trade-minimal --start-date 2024-05-20 --end-date 2024-06-11 --market spot --instrument BTC-USDT
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-window --start-date 2024-05-20 --end-date 2024-06-11 --label target_2024-05-20_to_2024-06-11
```

- Candlestick Spot BTC-USDT 目标窗口：23 天全部存在 quality report。
- Candlestick normalized：33,120 行。
- Candlestick policy：23 天均为 `historical_archive_confirm_0_closed_bar_by_complete_daily_file`。
- Candlestick quality flag：23 天均为 `source_archive_confirm_0_closed_bar_inferred`。
- Trade Spot BTC-USDT：23 天全部处理完成。
- Trade normalized tick：7,137,407 行。
- Trade 1m feature：33,120 行。
- Trade duplicate_trade_id：0。
- Funding normalized 文件：23。
- Borrowing normalized 文件：23。
- Curated output：`data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m/sample=target_2024-05-20_to_2024-06-11/curated_btc_market_state_1m.csv`。
- Curated rows：33,120。
- `future_leak_violation_count` 总和：0。
- `allow_into_feature_layer=True`：33,120 / 33,120，比例 1.0。
- `missing_or_stale_source_count` 分布：`0: 33120`。
- `data_quality_flags`：空分布（无异常 flag）。
- `orderbook_feature_missing_rows`：33,120，原因均为当前窗口显式未纳入 Orderbook。

### 🔒 边界说明

- 本里程碑是治理链路跑通，不是训练准入、不是策略研究、不是回测结论。
- `confirm=0` 历史归档语义通过显式 policy/flag 记录，不覆盖原始字段，不伪装成官方 `confirm=1`。
- Orderbook 原始归档存在不等于 L2 特征可用；当前 curated 明确不包含 Orderbook 特征。
- AlphaTenant 后续只能消费治理后的 feature/snapshot，不得直接读取 raw tick/L2/CSV。
## 里程碑 11：目标窗口 Orderbook 1m 特征与 curated 对齐

完成时间：2026-05-09

### ✅ 已完成

- 按 TDD 新增 Orderbook 归档解析与 1m 特征测试：
  - 支持 `.data`、`.tar.gz`、`.tar.tar`；`.tar.tar` 可能实际是 gzip tar，读取时使用自动探测。
  - 从同文件内 snapshot 起，best-effort 应用 update，按 1m 窗口输出最后盘口状态。
  - 不把 raw L2 直接交给 AlphaTenant；输出为治理后的 `orderbook_feature`。
- 新增 CLI：

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli orderbook-minute-features --start-date 2024-05-20 --end-date 2024-06-11 --market spot --instrument BTC-USDT
```

- `curated-state-window` 已自动读取同窗口 Spot BTC-USDT `orderbook_feature/interval=1m`，并要求 Orderbook feature 与当前 1m `feature_time_ms` 精确匹配。
- 对 Orderbook 缺失、非当前分钟、crossed book 做显式 quality flags。
- 保留质量边界：当前无 sequence/checksum 字段，盘口重建质量标记为 `best_effort_reconstructed_without_sequence_checksum`，不是可证明连续的 L2 reconstruction。

### 📊 目标窗口真实验证结果

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli orderbook-minute-features --start-date 2024-05-20 --end-date 2024-06-11 --market spot --instrument BTC-USDT
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-window --start-date 2024-05-20 --end-date 2024-06-11 --label target_2024-05-20_to_2024-06-11_with_orderbook
```

Orderbook 结果：

- Spot BTC-USDT Orderbook 原始归档：23 天。
- 成功解析：23。
- 失败：0。
- 1m Orderbook feature rows：32,955。
- 输出路径：`data_lake/features/exchange=okx/dataset_type=orderbook_feature/market=spot/instrument=BTC-USDT/interval=1m/.../orderbook_features_1m.csv`。

Curated with Orderbook 结果：

- 输出：`data_lake/features/exchange=okx/dataset_type=curated_btc_market_state/interval=1m/sample=target_2024-05-20_to_2024-06-11_with_orderbook/curated_btc_market_state_1m.csv`。
- rows：33,120。
- candle/funding/borrowing/trade/orderbook 文件数：23 / 23 / 23 / 23 / 23。
- `future_leak_violation_count`：0。
- `allow_into_feature_layer=True`：32,404 / 33,120，比例 0.9783816425。
- `missing_or_stale_source_count` 分布：`0: 32404`, `1: 716`。
- `data_quality_flags`：`orderbook_feature_missing: 649`, `orderbook_crossed_book: 67`。

### 🔍 异常解释

- `orderbook_feature_missing` 主要集中在窗口开头：Candlestick 的 `2024-05-20` UTC+8 日从 UTC `2024-05-19 16:01` 开始，而本地没有 `2024-05-19` Spot BTC-USDT Orderbook 原始文件可补。该缺口不能伪造，只能显式标记。
- `orderbook_crossed_book` 只出现在少数分钟，来自 best-effort update 重建后出现的 crossed book 状态；由于原始数据没有 sequence/checksum，不能证明连续性，因此这些分钟被质量闸门阻断。

### 🔒 边界

- 当前已满足 AlphaTenant 需要“治理后的 Orderbook 1m 特征”的最低闭环：解析、质量报告、分钟聚合、时间对齐、curated quality gate。
- 但这仍不是严格可证明的全深度 L2 重建。后续若要提升等级，需要独立补充 sequence/checksum 或交易所官方可验证连续性机制，否则必须保留 `best_effort_reconstructed_without_sequence_checksum` 标签。
## 里程碑 12：AlphaTenant Snapshot v0.1 准入封装

完成时间：2026-05-09

### ✅ 已完成

- 新增 `snapshot-admission` CLI，将已经治理完成的 `curated_btc_market_state_1m` sample 封装为 AlphaTenant 可读取的版本化 Snapshot Layer。
- 新增 TDD 测试 `tests/test_snapshot_admission.py`，验证 snapshot 必须包含：
  - `curated_btc_market_state_1m.csv`
  - `data_admission_report.json`
  - `source_manifest.json`
  - `quality_summary.json`
  - `schema.json`
  - `feature_contract.md`
  - `forbidden_raw_access_policy.md`
  - `snapshot_summary.json`
- Snapshot 不包含 raw OKX 数据，不包含临时解压 `.data`，只复制治理后的 curated feature CSV 与质量摘要。
- `source_manifest.json` 记录 curated source 与 copied snapshot 文件的 sha256，确保可追溯、可复验。
- `feature_contract.md` 明确 AlphaTenant 必须过滤 `allow_into_feature_layer == True`，治理列不能作为模型特征。
- `forbidden_raw_access_policy.md` 明确 AlphaTenant 禁止读取 `okx/` Raw Source Zone、raw tick、raw L2、临时解压 `.data`、无版本化 CSV 或无质量闸门特征。

### 📦 当前 Snapshot

生成命令：

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli snapshot-admission \
  --label target_2024-05-20_to_2024-06-11_with_orderbook \
  --snapshot-id okx_btc_market_state_1m_v0_1_20240520_20240611_with_orderbook
```

Snapshot 路径：

```text
snapshots/exchange=okx/instrument=BTC-USDT/interval=1m/snapshot_id=okx_btc_market_state_1m_v0_1_20240520_20240611_with_orderbook/
```

准入摘要：

- rows：33,120
- `allow_into_feature_layer=True`：32,404
- blocked rows：716
- `future_leak_violation_count`：0
- blocking flags：
  - `orderbook_feature_missing`: 649
  - `orderbook_crossed_book`: 67
- AlphaTenant readiness：`admitted_with_row_level_quality_filter`
- 必须过滤：`allow_into_feature_layer == True`
- Orderbook 边界：`best_effort_reconstructed_without_sequence_checksum`

### 🔒 使用边界

- 这是数据准入产物，不是策略、训练或回测结论。
- AlphaTenant 只应读取 snapshot 目录内的治理产物，并按 `feature_contract.md` 过滤。
- 2025-2026 验证集隔离规则仍然有效；当前 snapshot 不改变任何训练/验证 cutoff 约束。

### 🧭 下一步数据补齐清单

已生成本地 gap/quality review 报告：

```text
reports/gap/orderbook_gap_and_quality_review_2024-05-20_to_2024-06-11.json
reports/gap/orderbook_gap_and_quality_review_2024-05-20_to_2024-06-11.md
```

优先级：

1. 高优先级补齐真实 OKX Spot BTC-USDT Orderbook `2024-05-19`：当前本地不存在该文件，导致目标窗口开头 UTC `2024-05-19 16:01` 至 `2024-05-20 00:00` 之间的 Orderbook feature 缺失。
2. 质量复核日期：`2024-05-22`、`2024-05-23`、`2024-06-04`、`2024-06-05`，原因分别为 crossed book 或分钟特征不足 1440。
3. 若补不到真实 OKX 原始文件，必须保留缺失与阻断；禁止合成、插值、未来 forward-fill 或使用其他交易所替代。
## 里程碑 13：Trade Parquet + Checkpoint 治理基础设施

完成时间：2026-05-09

### ✅ 已完成

- 新增 `trade-stream` CLI，作为 `trade-minimal` 的长期窗口替代入口：

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli trade-stream \
  --start-date 2024-05-20 \
  --end-date 2024-05-20 \
  --market spot \
  --instrument BTC-USDT \
  --resume
```

- 输出 normalized tick Parquet，而不是继续写出 normalized tick CSV：

```text
data_lake/normalized/exchange=okx/dataset_type=trade/market=spot/instrument=BTC-USDT/format=parquet/exchange_date_utc8=*/trade_normalized.parquet
```

- 输出 Trade 1m Feature Parquet：

```text
data_lake/features/exchange=okx/dataset_type=trade_feature/market=spot/instrument=BTC-USDT/interval=1m/format=parquet/exchange_date_utc8=*/trade_features_1m.parquet
```

- 新增文件级 checkpoint：

```text
checkpoints/exchange=okx/dataset_type=trade/market=spot/instrument=BTC-USDT/exchange_date_utc8=*/checkpoint.json
```

- checkpoint 记录 `source_file_hash`、行数、输出路径、输出 Parquet hash、schema/feature/governance version。
- `--resume` 时，如果 checkpoint 为 completed 且 source hash 未变化，并且输出文件存在，则跳过重复处理。
- 如果 raw source hash 变化，则自动重新处理该文件。
- `curated-state-window` 已支持读取 Trade Feature Parquet；当同一日期同时存在 legacy CSV 与 Parquet 时，优先使用 Parquet，避免重复读取。
- 新增 TDD 测试：
  - `tests/test_trade_streaming_checkpoint.py`
  - `tests/test_trade_stream_cli.py`
  - `tests/test_curated_state_parquet_trade.py`

### 📊 真实单日 smoke 验证

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli trade-stream --start-date 2024-05-20 --end-date 2024-05-20 --market spot --instrument BTC-USDT --resume
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli trade-stream --start-date 2024-05-20 --end-date 2024-05-20 --market spot --instrument BTC-USDT --resume
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-window --start-date 2024-05-20 --end-date 2024-05-20 --label stream_parquet_smoke_2024-05-20
```

结果：

- 首次 `trade-stream` 处理 1 个真实 Spot BTC-USDT Trade 文件。
- normalized Parquet rows：251,498。
- Trade 1m Feature Parquet rows：1,440。
- duplicate trade_id：0。
- 第二次 `trade-stream --resume` 成功跳过：processed=0, skipped=1。
- Curated smoke：`trade_feature_files_used=1`，确认 Parquet feature 可被 curated 读取。

### 🔒 当前边界

- 当前 checkpoint 粒度为“单个 raw source file”，已经能支持日期窗口级断点续跑。
- 当前实现避免了 normalized tick CSV 继续膨胀，但单文件内部仍会构建 normalized rows 后写 Parquet；这已经适合推进数月窗口 smoke，但还不是最终的 chunked ParquetWriter。
- 后续若扩到全年或多年 Trade 历史，应继续升级为 chunked writer / row-group writer，并把 1m 聚合改成在线 bucket 聚合。

