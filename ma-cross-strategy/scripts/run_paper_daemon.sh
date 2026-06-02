#!/usr/bin/env bash
# =============================================================================
# run_paper_daemon.sh — MA cross paper trade daemon
#
# 使用 cyqnt_trd 框架的 mvp_paper_daemon entrypoint。
#
# 用法：
#   chmod +x scripts/run_paper_daemon.sh
#   ./scripts/run_paper_daemon.sh
#
# 背景執行：
#   nohup ./scripts/run_paper_daemon.sh > /tmp/paper_daemon.out 2>&1 &
#
# 停止：
#   python -c "
#   import json, pathlib
#   p = pathlib.Path('./watcher/MA_CROSS_V1_BTCUSDT_1h/state.json')
#   d = json.loads(p.read_text()); d['status'] = 'stopped'; p.write_text(json.dumps(d))
#   "
# =============================================================================

set -euo pipefail

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$(dirname "$SCRIPT_DIR")"
STATE_DIR="${WORKSPACE}/watcher/MA_CROSS_V1_BTCUSDT_1h"

# ── 策略參數 ──────────────────────────────────────────────────────────────────
SYMBOL="BTCUSDT"
INTERVAL="1h"
STRATEGY="ma_cross_v1"
STRATEGY_MODULE="strategies.ma_cross_v1"
MARKET_TYPE="futures"

INITIAL_CAPITAL="10000"
FEE_BPS="4"
SLIPPAGE_BPS="2"
WARM_UP_BARS="80"
POLL_INTERVAL="3570"

# ── 環境 ──────────────────────────────────────────────────────────────────────
mkdir -p "${STATE_DIR}"
export PYTHONPATH="${WORKSPACE}:${PYTHONPATH:-}"

PYTHON="$(command -v python3.11 || command -v python3)"

echo "[paper_daemon] symbol=${SYMBOL} interval=${INTERVAL}"
echo "[paper_daemon] state_dir=${STATE_DIR}"
echo "[paper_daemon] python=${PYTHON}"

# ── 啟動 ──────────────────────────────────────────────────────────────────────
exec "${PYTHON}" -m cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon \
  --engine           python \
  --strategy         "${STRATEGY}" \
  --strategy-module  "${STRATEGY_MODULE}" \
  --symbol           "${SYMBOL}" \
  --interval         "${INTERVAL}" \
  --market-type      "${MARKET_TYPE}" \
  --state-dir        "${STATE_DIR}" \
  --poll-interval    "${POLL_INTERVAL}" \
  --warm-up-bars     "${WARM_UP_BARS}" \
  --initial-capital  "${INITIAL_CAPITAL}" \
  --fee-bps          "${FEE_BPS}" \
  --slippage-bps     "${SLIPPAGE_BPS}"
