# MA Cross Strategy → Full Pipeline 架構審查報告

> 審查日期：2026-06-02  
> 涵蓋：`crypto-research/ma-cross-strategy/` + `crypto_trading-main/` (cyqnt_trd 0.1.9.dev6)

---

## 目錄

1. [整體架構概覽](#1-整體架構概覽)
2. [Backtest 路徑 — ✅ 正確](#2-backtest-路徑--正確)
3. [Paper Trade 路徑 — ✅ 正確](#3-paper-trade-路徑--正確)
4. [Live Trade 路徑 — ⚠️ 需要修正](#4-live-trade-路徑--需要修正)
5. [問題清單](#5-問題清單)
6. [Live Trade 架構建議](#6-live-trade-架構建議)
7. [Paper → Live 模式切換方案](#7-paper--live-模式切換方案)
8. [建議的目錄結構](#8-建議的目錄結構)
9. [創意探索：可考慮的增強](#9-創意探索可考慮的增強)

---

## 1. 整體架構概覽

你的目標路徑：

```
┌─────────────────────────────────────────────────────────────────────────┐
│  策略定義 (blocks)                                                       │
│  strategies/ma_cross_v1.py                                              │
│  ├── make_signals(df) → (long_signal, short_signal)                     │
│  └── strategy.register("ma_cross_v1", make_signals)                     │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ 同一份 make_signals()
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌───────────┐  ┌───────────────┐
        │ Backtest │  │   Paper   │  │   Live Trade  │
        │Snapshot │  │  Daemon   │  │               │
        │ Runner   │  │ (Python)  │  │  ?????        │
        └──────────┘  └───────────┘  └───────────────┘
```

**核心設計原則**：三條路都呼叫同一個 `make_signals()`，差別只在 broker 層。

---

## 2. Backtest 路徑 — ✅ 正確

```
mvp_backtest --engine python --strategy ma_cross_v1 --strategy-module strategies.ma_cross_v1
```

**流程**：
1. `import strategies.ma_cross_v1` → 觸發 `strategy.register("ma_cross_v1", make_signals)`
2. `make_registry()` → `flush_pending_into(registry)` 安裝 `BlockStrategyPlugin`
3. `HistoricalSnapshotAssembler` 建構 snapshots
4. `SnapshotBacktestRunner.run()` → 呼叫 `plugin.run(snapshot)` → `_call_signal_fn(df)` → `make_signals(df)`
5. 訊號 → `_envelope_from_signals()` → 產生 `SignalEnvelope(kind=TRADE, side=BUY/SELL)`
6. Runner 以 `next_bar_open` 模型執行

**結論**：✅ `run_strategy.py --mode backtest` 正確呼叫了 `mvp_backtest --engine python`，參數設置合理。

---

## 3. Paper Trade 路徑 — ✅ 正確

```
mvp_paper_daemon --engine python --strategy ma_cross_v1 --strategy-module strategies.ma_cross_v1
```

**流程**：
1. `PaperDaemon.__init__()` → import strategy module → 建立 `PythonLivePaperSession`
2. `PythonLivePaperSession.__init__()` → `_resolve_plugin("ma_cross_v1")` → 取得 `BlockStrategyPlugin`
3. `warm_up(bar)` × N → 建構歷史 bar 序列
4. 每次 poll → `tick(bar)`:
   - 執行 pending order (next-bar-open)
   - 追加新 bar
   - `_compute_latest_target()` → `_build_dataframe()` → `_call_signal_fn(df)` → `make_signals(df)`
   - 若 target 改變 → 建立 `PendingOrder`
5. daemon `_record_fill(fill)` → 寫入 `trades.jsonl`

**訊號一致性**：
- Paper session 用 `plugin._call_signal_fn(df)` 和 backtest 的 `BlockStrategyPlugin.run()` 內部呼叫的是**完全相同**的 `_call_signal_fn` 方法
- 執行模型都是 next-bar-open
- ✅ 完全一致

**結論**：✅ Paper daemon 設計正確，`run_strategy.py --mode paper` 參數吻合。

---

## 4. Live Trade 路徑 — ⚠️ 需要修正

### 4.1 目前的設計

`run_strategy.py --mode live` 啟動兩個 process：
1. **Paper Daemon** — 完全相同的 paper daemon，產生 `trades.jsonl`
2. **Signal Executor** — tail `trades.jsonl`，發現新 paper fill → 透過 `binance-cli` 下真實單

### 4.2 問題清單

| # | 嚴重度 | 問題 | 說明 |
|---|--------|------|------|
| 1 | 🔴 HIGH | **Paper daemon 用紙上 equity 計算倉位大小** | Paper daemon 的 `PythonLivePaperSession._execute_pending()` 使用 `self.cash + self.position_qty * open_price` 計算 `equity_ref`，再以 `equity_ref * size_fraction / price` 決定下單量。但 live executor 使用的是**真實帳戶餘額** `get_usdt_balance()`。兩者會漸漸 diverge（因為真實 slippage ≠ 模擬 slippage）。|
| 2 | 🔴 HIGH | **Position flip 遺失同步** | Paper daemon 執行 position-flip model（close_long → open_short 是一筆 fill），但 executor 只收到「一個 action」。若 flip 動作真實執行失敗（例如 close_long 成功但 open_short 因餘額不足失敗），paper state 和真實倉位會永久 desync。 |
| 3 | 🟡 MED | **Hardcoded 路徑** | `run_strategy.py` 和 shell scripts 使用 `/root/.openclaw/workspace` 路徑，在本地 macOS 環境無法直接使用。|
| 4 | 🟡 MED | **缺少 reconciliation 機制** | 沒有任何邏輯定期比對 paper position vs real position。如果 binance-cli 執行超時/失敗，不會有人發現。|
| 5 | 🟡 MED | **signal_executor 沒有 retry 機制** | `place_order()` 失敗只印 error，不重試。真實環境中 Binance API 可能暫時不可用。|
| 6 | 🟡 MED | **binance-cli 的 JSON parse 可能失敗** | `_cli()` 假設 stdout 是 JSON，但 `binance-cli` 在某些 error 情況可能輸出非 JSON 格式。|
| 7 | 🟢 LOW | **daemon → executor 靠 file polling** | 5 秒輪詢 trades.jsonl 的設計在 1h candle 策略下延遲可接受，但如果切換到 1m/5m 策略會有問題。|
| 8 | 🟢 LOW | **缺少 heartbeat / health check** | 沒有機制確認 executor 是否仍在健康運行。|

### 4.3 根本問題：雙重計算 vs 單一來源

目前的 live 設計是「**Paper daemon 自己算訊號 + 自己做紙上交易 + Executor 同步下真實單**」。這造成了 **Paper position ≠ Real position** 的 drift 風險。

框架中已有更好的路徑：
- `mvp_monitor_http` + `MarketOnlyPaperRunner` + `BinanceFuturesMainnetBrokerAdapter`
- 但這條路是 **request/response 模型**（HTTP 觸發一次，跑一次），不是 daemon 模式

---

## 5. 問題清單（按修正優先級排列）

### P0 — 必須修正才能安全 Live Trade

1. **移除 hardcoded 路徑**，改為可配置（CLI arg 或環境變數）
2. **建立 position reconciliation 機制** — 每次 executor 下單後比對
3. **executor 使用 paper fill 的 `action` 來決定方向，但用真實帳戶餘額決定數量**

### P1 — 強烈建議

4. 加入 **retry with exponential backoff** 到 `signal_executor.py`
5. 加入 **健康檢查 / heartbeat** 機制
6. 將 position-flip 拆成兩步（close → verify → open）加中間驗證

### P2 — 品質提升

7. 加入 **audit trail** — 每次 executor 的下單結果寫入 `executions.jsonl`
8. 加入 **alerting** — executor 失敗時推 Jarvis 通知

---

## 6. Live Trade 架構建議

### 方案 A：改良 Signal Executor 模式（推薦，改動最小）

保持「Paper Daemon 產生訊號 + Executor 翻譯成真實下單」的設計，但修正上述問題：

```
┌─────────────────────────────────────────────────────────────────┐
│ Paper Daemon (signal source, immutable)                         │
│ ├── PythonLivePaperSession                                     │
│ ├── make_signals(df) — 完全不改                                 │
│ └── 寫 trades.jsonl（只作為 SIGNAL 來源，不作為 sizing 依據）     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ trades.jsonl (action only)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ Signal Executor v2 (stateful, independent sizing)               │
│ ├── 讀 action (open_long / close_long / open_short / close_short)│
│ ├── 每次下單前 query 真實帳戶                                    │
│ │   ├── get_usdt_balance() → 計算 notional                      │
│ │   └── get_position() → 確認當前倉位方向                        │
│ ├── 安全閘（reconciliation）                                    │
│ │   ├── 若 action=open_long 但已有 long position → skip         │
│ │   ├── 若 action=close_long 但沒有 position → skip             │
│ │   └── 若 action=flip_to_short → close_long + verify + open_short │
│ ├── 下單 + retry（3 次 exponential backoff）                     │
│ ├── 寫 executions.jsonl（audit trail）                          │
│ └── 失敗 → Jarvis alert                                        │
└─────────────────────────────────────────────────────────────────┘
```

**優點**：
- Signal 來源（make_signals）完全不動，確保一致性
- Executor 獨立決定 sizing，不依賴 paper equity
- 增加 reconciliation 不會影響訊號品質

**缺點**：
- 仍有「兩個 process 需要 coordinate」的複雜度
- Paper daemon 的 paper equity 和真實 equity 會 diverge（但無所謂，只用 action）

### 方案 B：直接用 mvp_monitor_http + cron（更簡潔但犧牲 daemon state）

```
┌─────────────────────────────────────────────────────────────────┐
│ mvp_monitor_http                                                │
│ --broker binance_futures_mainnet                                │
│ --allow-mainnet-live                                            │
│ --interval 1h                                                   │
│ --strategy ma_cross_v1                                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ POST /run (每小時 cron trigger)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ MarketOnlyPaperRunner                                           │
│ ├── fetch bars → build snapshot                                 │
│ ├── BlockStrategyPlugin.step() → make_signals(df)               │
│ ├── ExecutionPlanner.build_intents()                            │
│ ├── BinanceFuturesMainnetBrokerAdapter.place_order()            │
│ └── Risk rules 已內建                                           │
└─────────────────────────────────────────────────────────────────┘
```

**優點**：
- 框架已有完整的 mainnet broker adapter（含 quantity rounding、risk rules）
- 單一 process，無 coordination 問題
- **一致性最高**：直接用 `BlockStrategyPlugin.step()` — 和 backtest 的 `plugin.run()` 是同一個 class 的不同 method

**缺點**：
- Request/response 模型 — 需要外部 cron/scheduler 觸發
- 若 cron miss 一次 → 錯過一根 bar 的訊號
- `MarketOnlyPaperRunner` 的 plugin state（cursor）只在 process 存活時保持，process 重啟會 warm-up 重算
- 使用 direct REST API（需要 API key 在 `.env`），而非 `binance-cli`

### 方案 C：Hybrid — Paper Daemon + 內建 Mainnet Broker（最佳但最大改動）

在 `PaperDaemon` 內新增一個 broker 層：

```python
class LiveDaemon(PaperDaemon):
    """繼承 PaperDaemon，覆寫 _record_fill() 加入真實下單。"""
    
    def __init__(self, *, broker: BrokerAdapter, **kwargs):
        super().__init__(**kwargs)
        self.broker = broker
    
    def _record_fill(self, fill: PaperFill) -> None:
        super()._record_fill(fill)  # 保持 paper 紀錄
        # 同時下真實單
        intent = self._fill_to_intent(fill)
        report = self.broker.place_order(intent)
        self._record_execution(report)
```

**優點**：
- 單一 process，position state 完全同步
- 可以用已有的 `BinanceFuturesMainnetBrokerAdapter`（含 quantity rounding、step_size 處理）
- Signal → fill → execution 全在同一個 tick cycle 內完成

**缺點**：
- 需要修改 `PaperDaemon` 或創建子類
- API key 需要在 daemon process 內（而非 binance-cli config）

---

## 7. Paper → Live 模式切換方案

### 你原先的想法：paper daemon 加 mode switch

```bash
python scripts/run_strategy.py --mode paper  # 只跑 paper daemon
python scripts/run_strategy.py --mode live   # paper daemon + signal executor
```

**這個設計是合理的！** 但需要幾個調整：

### 推薦方案：統一 CLI 入口 + 模式切換

```python
# run_strategy.py (修正版)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["backtest", "paper", "live"], default="paper")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    
    # Live-specific
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-notional", type=float, default=200.0)
    parser.add_argument("--live-backend", choices=["cli", "api"], default="cli",
                        help="cli = binance-cli subprocess; api = direct REST API")
    
    # 路徑（不再 hardcode）
    parser.add_argument("--workspace", default=os.environ.get("STRATEGY_WORKSPACE", "."))
    parser.add_argument("--state-dir", default=None)
    
    args = parser.parse_args()
    
    if args.mode == "backtest":
        return run_backtest(args)
    elif args.mode == "paper":
        return run_paper(args)
    else:
        return run_live(args)
```

### 模式一致性保證（最關鍵的設計決策）

```
                    make_signals(df) — 三條路完全相同
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐       ┌─────────┐        ┌─────────┐
   │Backtest │       │ Paper   │        │  Live   │
   │         │       │ Daemon  │        │ Daemon  │
   │(offline)│       │(online) │        │(online) │
   └────┬────┘       └────┬────┘        └────┬────┘
        │                  │                  │
        ▼                  ▼                  ▼
  SnapshotRunner    PythonLivePaper    PythonLivePaper
  (next_bar_open)    Session.tick()     Session.tick()
                    (paper fill)       (paper fill)
                          │                  │
                          ▼                  ▼
                     trades.jsonl       trades.jsonl
                     (紀錄用)                │
                                             ▼
                                      SignalExecutor v2
                                      (真實下單, 獨立 sizing)
```

**一致性保證機制**：
1. **Signal 一致**：三條路都跑 `make_signals(df)` — 在相同的 bar 序列下必然產生相同訊號
2. **Timing 一致**：三條路都用 next-bar-open 模型
3. **Sizing diverge 是預期行為**：backtest/paper 用 paper equity sizing；live 用真實 balance sizing
4. **關鍵分離**：signal executor 只看 `action`（方向），不看 paper daemon 的 qty/price

### 關於「透過 CLI 執行有沒有問題」

**完全沒問題**，但需要注意：

| 面向 | binance-cli 方式 | Direct API 方式 |
|------|-----------------|-----------------|
| 延遲 | ~200-500ms（spawn process + HTTP） | ~100-200ms（direct HTTPS） |
| 安全 | API key 由 CLI config 管理 | API key 在 .env |
| 複雜度 | 低（subprocess call） | 高（需要 HMAC signing） |
| 錯誤處理 | 需 parse stdout/stderr | 直接 exception |
| 適用策略 | 1h/4h/1d 等低頻策略 ✅ | 任何頻率 |

**結論**：對於 1h MA cross 策略，binance-cli 方式的延遲完全可接受。

---

## 8. 建議的目錄結構

將 `ma-cross-strategy/` 的概念整合進 `crypto_trading-main/` 時：

```
crypto_trading-main/
├── strategies/
│   ├── __init__.py
│   └── ma_cross_v1.py              # 策略核心（不動）
├── scripts/
│   ├── run_strategy.py              # 統一入口（修正版）
│   ├── signal_executor.py           # v2 with reconciliation
│   └── setup_env.py                 # binance-cli / .env setup
├── cyqnt_trd/                       # library（不改）
│   └── standard_bot/
│       └── entrypoints/
│           ├── mvp_backtest.py
│           ├── mvp_paper_daemon.py
│           └── mvp_monitor_http.py
└── data/
    └── historical/
        └── BTCUSDT_1h.parquet
```

---

## 9. 創意探索：可考慮的增強

### 9.1 Shadow Mode（影子模式）

在 live trade 前的「試運行期」：
- Paper daemon + Executor 同時跑
- Executor 設為 **perpetual dry-run**，但會 query 真實市場價格
- 比較「如果下了單，結果是什麼」vs paper daemon 的 fill
- 目的：驗證 executor 邏輯在真實市場條件下不會爆

```bash
python scripts/run_strategy.py --mode live --shadow  # dry-run + 比較
```

### 9.2 Gradual Rollout（漸進上線）

```bash
# 第 1 週：只允許 max_notional=50，單次不超過 50 USDT
python scripts/run_strategy.py --mode live --max-notional 50

# 確認 2 週後正常 → 放大
python scripts/run_strategy.py --mode live --max-notional 200
```

### 9.3 Kill Switch

加一個 `EMERGENCY_STOP` 檔案機制：
```python
# signal_executor.py 中加入
KILL_SWITCH = Path(state_dir) / "EMERGENCY_STOP"
if KILL_SWITCH.exists():
    print("[executor] KILL SWITCH activated — cancelling all orders and exiting")
    cancel_all_open_orders(symbol)
    sys.exit(0)
```

### 9.4 Signal Replay Validation

跑完一段 paper trade 後，用 backtest 跑同一段歷史，比較兩者的 signal sequence：

```python
# validate_consistency.py
paper_trades = load_jsonl("watcher/MA_CROSS_BTCUSDT_1h/trades.jsonl")
backtest_result = run_backtest("BTCUSDT", "1h", start=paper_start, end=paper_end)

for paper, bt in zip(paper_trades, backtest_result["trades"]):
    assert paper["action"] == bt["action"], f"Signal drift at {paper['ts']}!"
    # price 不需要完全相同（execution timing 差異），但 action 必須一致
```

### 9.5 Multi-strategy Orchestrator（未來擴展）

當你有多個策略時，一個 orchestrator 管理多個 daemon + executor：

```yaml
# strategies.yaml
strategies:
  - id: ma_cross_v1
    symbol: BTCUSDT
    interval: 1h
    max_notional: 200
    enabled: true
  - id: rsi_mean_reversion
    symbol: ETHUSDT
    interval: 15m
    max_notional: 100
    enabled: false
```

---

## 10. 下一步行動建議

| 步驟 | 行動 | 預估工作量 |
|------|------|-----------|
| 1 | 移植 `strategies/ma_cross_v1.py` 到 `crypto_trading-main/strategies/` | 5 min |
| 2 | 修正 `run_strategy.py` — 移除 hardcoded 路徑，加入本地可執行的 path config | 30 min |
| 3 | 改寫 `signal_executor.py` v2 — 加 reconciliation + retry + audit trail | 2 hr |
| 4 | 在 backtest 上驗證 ma_cross_v1 可正常跑 | 15 min |
| 5 | 跑 paper daemon，確認 trades.jsonl 正常產出 | 30 min |
| 6 | Shadow mode 測試 — live --dry-run 確認 executor 邏輯 | 30 min |
| 7 | 小額 live（--max-notional 50）上線 | 驗證中 |

---

## 附錄 A：框架內已有但未被 ma-cross-strategy 使用的能力

| 功能 | 所在位置 | 說明 |
|------|---------|------|
| `BinanceFuturesMainnetBrokerAdapter` | `execution/binance_futures_mainnet.py` | 完整的 mainnet REST adapter（含 signing、quantity rounding） |
| `MarketOnlyPaperRunner` | `runtime/runner.py` | 完整的 signal → intent → execution pipeline |
| `mvp_monitor_http` | `entrypoints/mvp_monitor_http.py` | HTTP 觸發的 live execution（含 risk rules） |
| `mvp_mainnet_execution` | `entrypoints/mvp_mainnet_execution.py` | 單次 mainnet 下單 CLI |
| `InstrumentWhitelistRule` | `execution/rules.py` | Symbol 白名單風控 |
| `MaxAbsoluteNotionalRule` | `execution/rules.py` | 單筆最大 notional 風控 |
| `MaxPositionFractionRule` | `execution/rules.py` | 持倉比例風控 |
| Exit management（stop/TP/max_bars）| `BlockStrategyPlugin._compute_exit_spec` | Phase 2 exit 系統 |
| Checkpoint/resume | `PythonLivePaperSession.checkpoint_state()` | Crash-safe daemon resume |
| `mvp_run_manager` | `entrypoints/mvp_run_manager.py` | Background process 管理 |

## 附錄 B：signal_executor.py 現有的 fill → action 映射

```
paper fill action     binance-cli side / reduce-only
─────────────────────────────────────────────────────
open_long             BUY   MARKET  (開多)
open_short            SELL  MARKET  (開空)
close_long            SELL  MARKET  reduce-only=true
close_short           BUY   MARKET  reduce-only=true
flip_to_long          ⚠️ 未處理！executor 不認識此 action
flip_to_short         ⚠️ 未處理！executor 不認識此 action
rebalance             ⚠️ 未處理！executor 不認識此 action
```

**⚠️ 重大發現**：`PythonLivePaperSession._action_label()` 可以產生 `flip_to_long`、`flip_to_short`、`rebalance`，但 `signal_executor.py` 的 `watch_trades()` 只認識 4 種 action：

```python
if action not in ("open_long", "open_short", "close_long", "close_short"):
    print(f"[executor] unknown action={action!r}, skip")
    continue
```

**這代表 position flip 會被 executor 跳過！** 如果 MA cross 策略從 long 直接 flip 到 short（金叉→死叉沒有中間 flat），daemon 產生的 fill 是 `flip_to_short`，executor 會 skip 這筆。

**修正方案**：在 executor 中處理 flip：

```python
if action == "flip_to_long":
    # 先平空，再開多
    place_order(symbol, "close_short", ...)
    place_order(symbol, "open_long", ...)
elif action == "flip_to_short":
    # 先平多，再開空
    place_order(symbol, "close_long", ...)
    place_order(symbol, "open_short", ...)
```

---

*報告結束。如有問題請標註需要深入展開的段落。*
