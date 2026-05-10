#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="reports/runs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/v02_orderbook_contiguous_20240520_20241108_$(date -u +%Y%m%dT%H%M%SZ).log"

{
  echo "[START] $(date -u +%Y-%m-%dT%H:%M:%SZ) v0.2-orderbook-contiguous governance pipeline"
  echo "[WINDOW] 2024-05-20 ~ 2024-11-08"
  echo "[LABEL_1M] target_2024-05-20_to_2024-11-08_with_orderbook"
  echo "[LABEL_5M] target_2024-05-20_to_2024-11-08_with_orderbook_5m"
  echo "[SNAPSHOT] okx_btc_market_state_1m_v0_2_20240520_20241108_with_orderbook"

  echo "[STEP] candlestick-minimal"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli candlestick-minimal

  echo "[STEP] low-frequency-minimal"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli low-frequency-minimal

  echo "[STEP] trade-stream spot BTC-USDT 2024-05-20..2024-11-08"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli trade-stream \
    --start-date 2024-05-20 \
    --end-date 2024-11-08 \
    --market spot \
    --instrument BTC-USDT \
    --resume \
    --chunk-size 100000

  echo "[STEP] orderbook-stream-features spot BTC-USDT 2024-05-20..2024-11-08"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli orderbook-stream-features \
    --start-date 2024-05-20 \
    --end-date 2024-11-08 \
    --market spot \
    --instrument BTC-USDT \
    --resume

  echo "[STEP] curated-state-window 1m (date-partitioned workers=4)"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-window \
    --start-date 2024-05-20 \
    --end-date 2024-11-08 \
    --label target_2024-05-20_to_2024-11-08_with_orderbook \
    --workers 4

  echo "[STEP] curated-state-5m"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli curated-state-5m \
    --source-label target_2024-05-20_to_2024-11-08_with_orderbook \
    --label target_2024-05-20_to_2024-11-08_with_orderbook_5m

  echo "[STEP] snapshot-admission"
  PYTHONPATH=src /usr/bin/python3 -m datagovernedforbtc.cli snapshot-admission \
    --label target_2024-05-20_to_2024-11-08_with_orderbook \
    --snapshot-id okx_btc_market_state_1m_v0_2_20240520_20241108_with_orderbook

  echo "[DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ) v0.2-orderbook-contiguous governance pipeline completed"
} 2>&1 | tee "$LOG"
