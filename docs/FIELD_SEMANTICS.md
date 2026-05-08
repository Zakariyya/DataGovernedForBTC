# OKX 字段语义与时间可用性规范

## Candlestick

- `open_time` 是 K 线开始时间，不是完成时间。
- 1 分钟 K 线 `close_time_ms = open_time + 60000`。
- 只有 `confirm = 1` 的 K 线可进入历史训练层。
- OHLCV 只能在 `close_time_ms` 之后使用。
- `feature_time_ms` 优先使用 `close_time_ms`。

## Funding Rate

- `funding_rate` 是 realized funding rate。
- 标准字段必须命名为 `realized_funding_rate`。
- 不允许命名为 `predicted_funding_rate`。
- `available_time_ms = funding_time + configured_latency_ms`。
- Funding interval 必须根据相邻 `funding_time` 自动推断，不能硬编码所有品种都是 8 小时。

## Borrowing Rate

- `borrow_rate` 必须保留为 `borrow_rate_raw`。
- 默认单位为 `unknown_raw`。
- 未经配置确认，不允许生成 annualized/hourly/percentage 派生字段。
- as-of join 后必须输出 age 字段，例如 `btc_borrow_rate_age_ms`。

## Trade History

- `created_time` 是成交事件时间。
- `trade_id` 是去重主键。
- `side` 必须保留为 `side_raw`。
- 未确认 side 是 taker side 前，只能生成 buy/sell volume，不能生成 aggressive buy/sell。

## Order Book / L2

- `snapshot` 表示完整盘口快照，`update` 表示增量。
- 无同 instrument 前置 snapshot 时，不允许应用 update。
- 无 sequence/checksum 时，重建连续性不能被证明，必须标记质量等级。
- `event_time_ms = ts`，`available_time_ms = ts + configured_latency_ms`。
- bids 必须高到低排序，asks 必须低到高排序，且 best_bid < best_ask。
