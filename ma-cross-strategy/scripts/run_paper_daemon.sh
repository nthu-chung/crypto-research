#!/usr/bin/env bash
# =============================================================================
# run_paper_daemon.sh — MA cross paper trade daemon (python engine)
#
# 用途：
#   啟動 mvp_paper_daemon，使用 python engine（cyqnt_trd.blocks）跑 MA cross
#   策略，持續監聽 Binance REST，每根 bar close 後更新 state.json
#
# 執行方式：
#   chmod +x run_paper_daemon.sh
#   ./run_paper_daemon.sh
#
# 背景執行：
#   nohup ./run_paper_daemon.sh > /tmp/paper_daemon.out 2>&1 &
#   echo $! > /tmp/paper_daemon.pid
#
# 停止方式（寫入 stop_requested 到 state.json）：
#   python3.11 -c "
#   import json, pathlib
#   p = pathlib.Path('/root/.openclaw/workspace/watcher/MA_CROSS_BTCUSDT_1h/state.json')
#   d = json.loads(p.read_text()); d['status'] = 'stop_requested'; p.write_text(json.dumps(d))
#   "
# =============================================================================

set -euo pipefail

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
WORKSPACE="/root/.openclaw/workspace"
VENV_PIP="${WORKSPACE}/venv-pip"
STATE_DIR="${WORKSPACE}/watcher/MA_CROSS_BTCUSDT_1h"

# ── 策略參數 ──────────────────────────────────────────────────────────────────
SYMBOL="BTCUSDT"
INTERVAL="1h"
STRATEGY_ID="ma_cross_v1"
STRATEGY_MODULE="strategies.ma_cross_v1"   # 對應 workspace/strategies/ma_cross_v1.py
ENGINE="python"

INITIAL_CAPITAL="10000"
FEE_BPS="4"         # Binance USD-M futures taker ≈ 0.04% = 4 bps
SLIPPAGE_BPS="2"    # 保守估計
MARKET_TYPE="futures"

# warm_up_bars 需 ≥ SLOW_PERIOD + 2（MA cross SLOW=60 → 62）
# 設 80 有充裕的 warm-up 緩衝，且 Binance REST 單次最多回傳 1500 根
WARM_UP_BARS="80"

# poll_interval：1h bar = 3600 秒
# 設 3570（提早 30 秒輪詢）讓 REST fetch 有餘裕等 bar close
POLL_INTERVAL="3570"

# ── Jarvis 通知（成交時推播）──────────────────────────────────────────────────
JARVIS_USER_ID="147809639"
JARVIS_THREAD_ID="019e6e1c-5d38-7a19-9c13-2cd8c7b50163"

# ── 環境建立 ──────────────────────────────────────────────────────────────────
mkdir -p "${STATE_DIR}"

# PYTHONPATH 順序：
#   1. venv-pip → cyqnt_trd dev6
#   2. workspace → strategies.ma_cross_v1 模組
export PYTHONPATH="${VENV_PIP}:${WORKSPACE}"

echo "[paper_daemon] symbol=${SYMBOL} interval=${INTERVAL} engine=${ENGINE}"
echo "[paper_daemon] state_dir=${STATE_DIR}"
echo "[paper_daemon] warm_up_bars=${WARM_UP_BARS} poll=${POLL_INTERVAL}s"

# ── 啟動 ──────────────────────────────────────────────────────────────────────
exec python3.11 -m cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon \
  --symbol           "${SYMBOL}" \
  --interval         "${INTERVAL}" \
  --strategy         "${STRATEGY_ID}" \
  --strategy-module  "${STRATEGY_MODULE}" \
  --engine           "${ENGINE}" \
  --state-dir        "${STATE_DIR}" \
  --poll-interval    "${POLL_INTERVAL}" \
  --warm-up-bars     "${WARM_UP_BARS}" \
  --initial-capital  "${INITIAL_CAPITAL}" \
  --fee-bps          "${FEE_BPS}" \
  --slippage-bps     "${SLIPPAGE_BPS}" \
  --market-type      "${MARKET_TYPE}" \
  --jarvis-user-id   "${JARVIS_USER_ID}" \
  --jarvis-thread-id "${JARVIS_THREAD_ID}"
