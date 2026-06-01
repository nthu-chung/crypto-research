#!/usr/bin/env bash
# =============================================================================
# curl_monitor.sh — 呼叫 run_live_monitor 的各種 HTTP 指令範例
#
# 使用方式：
#   source curl_monitor.sh          # 載入函式
#   monitor_signal_only             # 只看訊號，不下單
#   monitor_dry_run                 # dry_run=true，有訊號也不送到 broker
#   monitor_live_confirm            # 真實下單（confirm_mainnet=true）
# =============================================================================

MONITOR_URL="http://127.0.0.1:8787"

# ────────────────────────────────────────────────────────────────────
# 基本健康檢查
# ────────────────────────────────────────────────────────────────────
monitor_health() {
  curl -s "${MONITOR_URL}/health" | python3.11 -m json.tool
}

# ────────────────────────────────────────────────────────────────────
# 只取訊號，不下單（signal_only=true）
# 用於確認 blocks 策略是否正確被 registry 載入、訊號是否如預期
# ────────────────────────────────────────────────────────────────────
monitor_signal_only() {
  curl -s -X POST "${MONITOR_URL}/run" \
    -H 'Content-Type: application/json' \
    -d '{
      "symbol":      "BTCUSDT",
      "interval":    "1h",
      "strategy":    "ma_cross_v1",
      "limit":       200,
      "signal_only": true
    }' | python3.11 -m json.tool
}

# ────────────────────────────────────────────────────────────────────
# dry_run=true：訊號產生，但 broker.place_order 不會被呼叫
# 用於 paper broker 或 mainnet 最後確認前的沙盒測試
# ────────────────────────────────────────────────────────────────────
monitor_dry_run() {
  curl -s -X POST "${MONITOR_URL}/run" \
    -H 'Content-Type: application/json' \
    -d '{
      "symbol":   "BTCUSDT",
      "interval": "1h",
      "strategy": "ma_cross_v1",
      "limit":    200,
      "dry_run":  true
    }' | python3.11 -m json.tool
}

# ────────────────────────────────────────────────────────────────────
# 真實下單（mainnet live）
# 前提：monitor 以 --broker binance_futures_mainnet --allow-mainnet-live 啟動
# confirm_mainnet=true 是雙重安全閘門，缺少則 403
# ────────────────────────────────────────────────────────────────────
monitor_live_confirm() {
  curl -s -X POST "${MONITOR_URL}/run" \
    -H 'Content-Type: application/json' \
    -d '{
      "symbol":          "BTCUSDT",
      "interval":        "1h",
      "strategy":        "ma_cross_v1",
      "limit":           200,
      "dry_run":         false,
      "signal_only":     false,
      "confirm_mainnet": true
    }' | python3.11 -m json.tool
}
