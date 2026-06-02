# MA Cross Strategy

Moving Average golden/death cross strategy built on `cyqnt-trd` blocks engine.

## Structure

```
ma-cross-strategy/
├── strategies/
│   └── ma_cross_v1.py                # Strategy core (make_signals)
├── binance-cli-trading-reference.md   # binance-cli 指令速查
└── scripts/                           # (deprecated — 已整合進 cyqnt_trd 框架)
    └── ...
```

## Strategy Logic

- **Long**: fast SMA (20) crosses above slow SMA (60) — golden cross
- **Short**: fast SMA (20) crosses below slow SMA (60) — death cross
- **No-lookahead**: signals use `shift(1)`, confirmed at bar close, executed at next bar open
- **Position-flip model**: 金叉直接翻多、死叉直接翻空（不經過 flat）

## Requirements

```
cyqnt-trd>=0.1.9.dev5
pandas
```

## 使用方式（透過 cyqnt_trd 框架）

策略檔 `strategies/ma_cross_v1.py` 應複製到 `crypto_trading-main/strategies/` 內使用。
所有執行都透過框架的 entrypoints，不需要 standalone scripts。

### 1. Backtest（回測）

```bash
cd /path/to/crypto_trading-main

python -m cyqnt_trd.standard_bot.entrypoints.mvp_backtest \
  --engine python \
  --strategy ma_cross_v1 \
  --strategy-module strategies.ma_cross_v1 \
  --symbol BTCUSDT \
  --interval 1h \
  --market-type futures \
  --historical-dir data/mtf_90d \
  --storage-timeframe 1m \
  --limit 2000 \
  --initial-capital 10000 \
  --commission-bps 4 \
  --slippage-bps 2 \
  --execution-model next_bar_open \
  --tail-bars 120
```

### 2. Paper Trade（模擬交易）

```bash
python -m cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon \
  --engine python \
  --strategy ma_cross_v1 \
  --strategy-module strategies.ma_cross_v1 \
  --symbol BTCUSDT \
  --interval 1h \
  --market-type futures \
  --state-dir ./watcher/MA_CROSS_V1_BTCUSDT_1h \
  --poll-interval 3570 \
  --warm-up-bars 80 \
  --initial-capital 10000 \
  --fee-bps 4 \
  --slippage-bps 2
```

輸出：
- `state.json` — 即時狀態（equity、position、latest signal）
- `trades.jsonl` — 每筆 paper fill

### 3. Live Trade（真實交易）

Live trade 需要**兩個 process 配對運行**：

```bash
# Terminal 1: Paper daemon（訊號來源 — 和 paper mode 完全相同）
python -m cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon \
  --engine python \
  --strategy ma_cross_v1 \
  --strategy-module strategies.ma_cross_v1 \
  --symbol BTCUSDT \
  --interval 1h \
  --market-type futures \
  --state-dir ./watcher/MA_CROSS_V1_BTCUSDT_1h \
  --poll-interval 3570 \
  --warm-up-bars 80 \
  --initial-capital 10000 \
  --fee-bps 4 \
  --slippage-bps 2

# Terminal 2: Live executor（先 dry-run 驗證）
python -m cyqnt_trd.standard_bot.entrypoints.mvp_live_executor \
  --state-dir ./watcher/MA_CROSS_V1_BTCUSDT_1h \
  --symbol BTCUSDT \
  --max-notional 200 \
  --notional-fraction 0.95 \
  --dry-run

# 確認 dry-run 正確後，移除 --dry-run 正式下單
python -m cyqnt_trd.standard_bot.entrypoints.mvp_live_executor \
  --state-dir ./watcher/MA_CROSS_V1_BTCUSDT_1h \
  --symbol BTCUSDT \
  --max-notional 200 \
  --notional-fraction 0.95
```

### 緊急停止

```bash
# 方法 1: Kill switch（取消掛單 + 退出 executor）
touch ./watcher/MA_CROSS_V1_BTCUSDT_1h/EMERGENCY_STOP

# 方法 2: Ctrl+C 中斷 executor

# 方法 3: 停止 daemon
python -c "
import json, pathlib
p = pathlib.Path('./watcher/MA_CROSS_V1_BTCUSDT_1h/state.json')
d = json.loads(p.read_text()); d['status'] = 'stopped'; p.write_text(json.dumps(d))
"
```

## Signal Consistency（訊號一致性）

三種模式都呼叫**完全相同**的 `make_signals()` 函式：

| Mode | Signal path | Execution |
|------|------------|-----------|
| Backtest | `SnapshotBacktestRunner` → `BlockStrategyPlugin.run()` → `make_signals(df)` | 模擬 fill (next_bar_open) |
| Paper | `PythonLivePaperSession.tick()` → `_compute_latest_target()` → `make_signals(df)` | 模擬 fill (next_bar_open) |
| Live | 同 Paper → `trades.jsonl` → `BinanceCliExecutor` | `binance-cli` 真實下單 |

### Action types

MA cross 是 position-flip 策略，paper daemon 產生的 action 分佈：

| action | 說明 | 頻率 |
|--------|------|------|
| `open_long` | 首次開多（只在第一筆） | ~3% |
| `flip_to_short` | 死叉 → 直接翻空 | ~48% |
| `flip_to_long` | 金叉 → 直接翻多 | ~48% |

Live executor 將 flip 拆成：close → verify → open（兩步安全執行）。

## Safety Gates

| 機制 | 說明 |
|------|------|
| `--dry-run` | 只印 binance-cli 指令不執行 |
| `--max-notional` | 單筆最大 USDT（預設 200） |
| `--notional-fraction` | 佔可用餘額比例（預設 0.95） |
| Reconciliation | 下單前檢查真實倉位方向 |
| Retry | 失敗自動重試（exponential backoff, 最多 3 次） |
| Kill switch | `touch EMERGENCY_STOP` 取消掛單 + 退出 |
| Audit trail | 每筆 execution 記錄在 `executions.jsonl` |

## 框架程式碼位置

| 元件 | 位置（crypto_trading-main 內） |
|------|------|
| Live Executor | `cyqnt_trd/standard_bot/execution/cli_executor.py` |
| Live Executor CLI | `cyqnt_trd/standard_bot/entrypoints/mvp_live_executor.py` |
| Paper Daemon | `cyqnt_trd/standard_bot/entrypoints/mvp_paper_daemon.py` |
| Backtest | `cyqnt_trd/standard_bot/entrypoints/mvp_backtest.py` |
| Strategy registration | `cyqnt_trd/blocks/strategy.py` |

## Scripts

`scripts/` 提供可直接執行的入口，內部呼叫 `cyqnt_trd` 框架 entrypoints：

| 檔案 | 用途 | 等價框架指令 |
|------|------|-------------|
| `run_strategy.py` | 統一入口（backtest/paper/live） | `python -m cyqnt_trd.standard_bot.entrypoints.mvp_*` |
| `signal_executor.py` | Live executor（讀 trades.jsonl → binance-cli） | `python -m cyqnt_trd.standard_bot.entrypoints.mvp_live_executor` |
| `run_paper_daemon.sh` | Paper daemon shell launcher | `python -m cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon` |
| `setup_env.py` | TOOLS.md → .env 同步（OpenClaw workspace 用） | — |
| `curl_monitor.sh` | HTTP monitor trigger helpers | `mvp_monitor_http` |

### 快速使用

```bash
# 確保 cyqnt-trd 已安裝且 PYTHONPATH 包含 workspace
export PYTHONPATH=.:"${PYTHONPATH:-}"

# 回測
python scripts/run_strategy.py --mode backtest --limit 2000

# Paper trade
python scripts/run_strategy.py --mode paper

# Live trade（dry-run）
python scripts/run_strategy.py --mode live --dry-run --max-notional 200

# Live trade（真實下單）
python scripts/run_strategy.py --mode live --max-notional 200
```
