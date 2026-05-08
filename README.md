# DataGovernedForBTC

DataGovernedForBTC 是服务于 AlphaTenant 的 BTC 市场数据治理系统。它不交易、不预测价格、不生成策略；唯一职责是把 OKX 历史市场原始数据治理为时间一致、可复现、可 Walk-Forward 验证的结构化数据资产。

## 🎯 核心原则

- 数据可信度 > 数据数量
- 时间因果性 > 特征复杂度
- 可复现性 > 短期收益
- 数据治理质量 > AI 模型复杂度

AlphaTenant 不允许直接读取未经治理的 Raw Data，只能读取 Feature Layer、Regime Layer 与 Walk-Forward Snapshot Layer。

## 📁 当前目录形态

```text
DataGovernedForBTC/
  okx/                         # 已存在：OKX 原始历史数据落地点，Raw Source Zone，不修改不覆盖
    Borrowrates/Spot/
    Candlesticks/Spot|Perpetual/
    Fundingrates/Perpetual/
    Orderbook/Spot|Perpetual/
    Trade/Spot|Perpetual/

  config/                      # 治理配置：版本、延迟、字段语义、质量阈值
  docs/                        # 数据目录规范、字段语义、治理契约
  src/datagovernedforbtc/      # 治理代码包
  tests/                       # 单元测试与治理不变量测试
  scripts/                     # CLI 包装脚本
  manifests/                   # File Manifest 输出
  data_lake/                   # 治理后的分层数据资产
  reports/                     # Data Quality / Coverage / Gap / Future-Leak 风险报告
  snapshots/                   # Walk-Forward Snapshot Layer
```

## 🧱 数据层级

```text
Layer 1 Raw Data Layer
  okx/ 与 data_lake/raw/manifest 引用。原始数据永不修改、永不覆盖、永不丢弃原字段。

Layer 2 Normalized Data Layer
  data_lake/normalized/。统一 event_time、available_time、source_file_hash、schema/governance version。

Layer 3 Feature Layer
  data_lake/features/。只允许使用 available_time_ms <= feature_time_ms 的数据。

Layer 4 Regime Layer
  data_lake/regime/。可解释市场状态，不是交易信号。

Layer 5 Walk-Forward Snapshot Layer
  snapshots/。固定版本、固定时间范围、固定输入 manifest 的可复现快照。
```

## ✅ 首批执行顺序

1. 建立项目骨架与数据目录规范（当前步骤）。
2. 实现 Candlestick + File Manifest + Quality Report 的最小闭环。
3. 审计现有 OKX 历史数据目录，输出 coverage / schema / gap / future-leak 风险报告。

## 🔒 硬性红线

- 不把文件名日期当作 UTC 日期。
- 不在 open_time 使用该分钟 K 线的 high/low/close/volume。
- 不把 realized funding 伪装成 predicted funding。
- 不擅自换算 borrow_rate 单位。
- 不默认 side 是 taker side。
- 不应用缺少前置 snapshot 的 L2 update。
- 不 silently fill missing values。
- 不做全样本标准化或未来窗口统计。
- 不混用不同交易所数据。

## 🧪 当前验证命令

当前项目采用 `src/` 布局，未安装包时使用 `PYTHONPATH=src` 执行：

```bash
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli --help
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli layout
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli candlestick-minimal
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli low-frequency-minimal
PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli audit-okx
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
```

## 📦 当前已生成的治理产物

- Candlestick 最小闭环汇总：`reports/quality/candlestick_minimal_summary.json`
- Candlestick File Manifest：`manifests/exchange=okx/dataset_type=candlestick/instrument=BTC-USDT/exchange_date_utc8=*/file_manifest.json`
- Candlestick Quality Report：`reports/quality/exchange=okx/dataset_type=candlestick/instrument=BTC-USDT/exchange_date_utc8=*/quality_report.json`
- Candlestick Normalized CSV：`data_lake/normalized/exchange=okx/dataset_type=candlestick/instrument=BTC-USDT/interval=1m/exchange_date_utc8=*/candlestick_normalized.csv`
- Funding/Borrowing 最小闭环汇总：`reports/quality/low_frequency_minimal_summary.json`
- Funding File Manifest / Quality / Normalized：`manifests|reports|data_lake/.../dataset_type=funding_rate/...`
- Borrowing File Manifest / Quality / Normalized：`manifests|reports|data_lake/.../dataset_type=borrowing_rate/...`
- OKX 目录审计 JSON：`reports/coverage/okx_directory_audit.json`
- OKX 目录审计 Markdown：`reports/coverage/okx_directory_audit.md`
