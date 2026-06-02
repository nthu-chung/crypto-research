# Paper → Live 訊號一致性：業界主流框架設計比較

> 研究日期：2026-06-02  
> 來源：Freqtrade, QuantConnect LEAN, Backtrader, Jesse, NautilusTrader, QuantInsti 等

---

## 核心結論（先看這段）

所有成熟框架都用同一個設計哲學：

> **策略程式碼完全不改，只替換 Broker/Execution 層。**

你目前的 `ma-cross-strategy` 設計已經符合這個原則。差異只在實現細節上。

---

## 1. 各框架的架構模式比較

### 共通抽象層結構

```
┌─────────────────────────────────────────────┐
│         Strategy Logic（不動）                │
│   generate_signal(market_data) → Signal      │
└──────────────────┬──────────────────────────┘
                   │ 完全相同的 Signal
        ┌──────────┼──────────────┐
        ▼          ▼              ▼
   Backtest    Paper Broker    Live Broker
   (模擬 fills)  (模擬 fills    (真實 API)
                  + 真實數據)
```

### 框架實現比較

| 框架 | 訊號一致機制 | 模式切換方式 | 特色 |
|------|------------|-------------|------|
| **Freqtrade** | `populate_indicators()` / `populate_entry_trend()` 完全不動；`dry_run: true/false` 切換 | Config 裡一個 boolean | 資料庫分離、hierarchical config override |
| **QuantConnect LEAN** | 同一個 Algorithm class；BrokerageModel 注入 | 環境切換（Research/Paper/Live） | Reality Models（slippage、fee、fill model 都是可插拔的） |
| **Backtrader** | Strategy 的 `next()` 不動；Cerebro swap broker | `cerebro.setbroker(SimBroker/LiveBroker)` | Store-Broker-Feed 三層；live data + SimBroker = paper |
| **Jesse** | `should_long()` / `go_long()` 完全不動 | Dashboard 上切 Paper/Live | Smart Ordering（策略聲明意圖，框架選 order type） |
| **NautilusTrader** | Common Core across all contexts；Rust engine | `BacktestNode` / `TradingNode` | 事件驅動 + ns 精度；研究到生產零改動 |

---

## 2. 關鍵設計模式

### 模式 A：Single Boolean Switch（Freqtrade 模式）

```json
// 只改一行就從 paper 切到 live
{ "dry_run": false }
```

**適用場景**：框架已經有完整的 broker adapter，只需要告訴它「這次是真的」。

**你的對標**：`run_strategy.py --mode paper` vs `--mode live`。你已經做到了。

---

### 模式 B：Broker Injection（Backtrader / LEAN 模式）

```python
# Paper
cerebro.setbroker(SimulatedBroker(initial_cash=10000))

# Live  
cerebro.setbroker(InteractiveBrokersBroker(host='127.0.0.1'))
```

**關鍵特性**：
- Strategy 透過統一 interface 下單（`self.buy()` / `self.sell()`）
- Strategy 永遠不知道自己是在 paper 還是 live
- Broker 層處理所有環境差異

**你的對標**：你的 `cyqnt_trd` 框架已經有 `PaperBrokerAdapter` 和 `BinanceFuturesMainnetBrokerAdapter`，都實現了同一個 `BrokerAdapter` interface。`mvp_monitor_http` 就是這個模式。

---

### 模式 C：Signal → Execution 分離（你的模式）

```
Paper Daemon (signal source) → trades.jsonl → Signal Executor (real orders)
```

**業界對照**：這其實是一種 **Message Queue** 模式，類似 production trading system 裡：
- Signal Generator → Kafka/Redis → Order Management System (OMS)

**優點**（業界認可的）：
- Signal source 完全隔離，無法被 execution failure 污染
- 可以 replay / audit signal 序列
- 支援「同一個 signal 路由到多個 executor」（例如多帳戶）

**缺點**（業界公認的）：
- 兩個 process 之間有 latency
- 需要 reconciliation 確保 state 同步
- 需要處理 executor down 但 signal generator 繼續跑的情況

---

### 模式 D：Event-Driven Unified Core（NautilusTrader 模式）

```rust
// Rust core 完全相同的 event processing
// 差別只在 Adapter 接口連到哪裡
```

**特性**：
- 最極端的一致性——ns 精度 timestamp，deterministic replay
- 完全沒有「paper 和 live 行為不同」的可能性
- 代價：最複雜，需要 Rust/compiled core

---

## 3. 業界公認的 Paper → Live 陷阱

### 陷阱 1：Fill Assumption Divergence

| 面向 | Paper 假設 | Live 現實 |
|------|-----------|----------|
| Fill price | mid-price 或 close | bid/ask spread + slippage |
| Fill time | 瞬間 | 可能 partial fill / timeout |
| Liquidity | 無限 | 受限於 orderbook depth |

**Freqtrade 的解法**：Paper mode 加入 slippage model（最多 5% slippage）
**你的解法**：回測和 paper 都加了 `slippage_bps=2`，executor 用 MARKET order。✅

### 陷阱 2：Position Sizing Drift

Paper equity 和 real equity 會因為 slippage / fill price 差異而漸漸 diverge。

**業界最佳實踐**：

> **Executor 永遠用真實帳戶餘額計算 sizing，不要依賴 paper equity。**

- Freqtrade: `dry_run_wallet` vs 真實餘額完全分離
- LEAN: `Portfolio.Cash` 在 live 模式從真實帳戶 sync
- 你的 executor v2: `get_usdt_balance()` ✅（v1 也已經這麼做）

### 陷阱 3：Market Impact Correlation（大資金陷阱）

Paper trading 不影響市場；Live trading 你的 order 會消耗 orderbook depth。

**業界解法**：
- `max_bar_volume_fraction`（你已經有 ✅）
- Binance 的 `algo` TWAP 分批（你的 reference 文件有 ✅）
- MaxAbsoluteNotionalRule（你的框架有 ✅）

### 陷阱 4：Reconnection / State Loss

Paper daemon crash 後 restart，如果沒有 checkpoint，可能重發已經下過的 signal。

**業界解法**：
- NautilusTrader: Redis-backed state persistence
- Freqtrade: SQLite trade database
- 你的框架: `session_checkpoint.json` + `trades.jsonl` fill_id 去重 ✅

### 陷阱 5：Order Type Incompatibility

Paper 模擬可能不支援 live broker 支援的 order type（或反過來）。

**QuantConnect 的解法**：BrokerageModel 驗證 order type 是否支援，backtest 和 live 用同一套驗證。

**你的策略**：MA cross 只用 MARKET order（最簡單、最不可能不一致）✅

---

## 4. 對照你的系統：做得好的 & 建議改進的

### ✅ 已經符合業界最佳實踐的

| 面向 | 你的實現 | 對標 |
|------|---------|------|
| 策略碼不動 | `make_signals()` 三條路共用 | 所有框架的核心原則 |
| Next-bar-open model | backtest/paper/live 都用 | NautilusTrader 的 deterministic execution |
| Checkpoint/resume | `session_checkpoint.json` | Freqtrade SQLite / NautilusTrader Redis |
| Fill dedup | `fill_id` set | 所有框架都有 |
| Slippage modeling | `slippage_bps` | Freqtrade's 5% max slippage |
| Volume cap | `max_bar_volume_fraction` | LEAN's MaxAbsoluteNotionalRule |
| Signal/execution 分離 | trades.jsonl 作為 message queue | 專業 OMS 架構 |

### ⚠️ 建議改進的（對照業界）

| 問題 | 業界標準 | 建議 |
|------|---------|------|
| flip action 未處理 | Backtrader: `notify_order` 處理所有 state transition | executor v2 已修正 |
| 無 parallel run / shadow mode | Freqtrade: dry_run 和 live 可以同時跑比較 | 加入 `--shadow` 模式 |
| 無 fill model 差異告警 | LEAN: BrokerageModel 在 backtest 就模擬 broker 限制 | 加入 paper vs live PnL 比較 |
| 無 graduated exposure | QuantInsti 推薦 10% → 50% → 100% | 已有 `--max-notional` ✅ |
| 無 regime detection | Paper trading 可能恰好在好行情 | 考慮加入 market regime indicator |

---

## 5. 推薦你的最終架構

基於所有框架的共識，你的系統可以用這個分層：

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Layer 0: Strategy Definition (不動)                                      │
│                                                                         │
│   strategy.register("ma_cross_v1", make_signals)                        │
│   make_signals(df) → (long_signal, short_signal)                        │
└──────────────────────────────────────────────┬──────────────────────────┘
                                               │
┌──────────────────────────────────────────────┼──────────────────────────┐
│ Layer 1: Signal Engine (不動)                 │                          │
│                                               │                          │
│   PythonLivePaperSession._compute_latest_target()                       │
│   → _build_dataframe() → _call_signal_fn(df) → make_signals(df)        │
│   → target = LONG / SHORT / KEEP                                        │
└──────────────────────────────────────────────┬──────────────────────────┘
                                               │ target (方向)
┌──────────────────────────────────────────────┼──────────────────────────┐
│ Layer 2: Execution Router (模式切換點)         │                          │
│                                               │                          │
│   if mode == "backtest":                                                │
│       SnapshotBacktestRunner (next_bar_open, simulated fill)            │
│   elif mode == "paper":                                                 │
│       PaperDaemon → PythonLivePaperSession (simulated fill)             │
│   elif mode == "live":                                                  │
│       PaperDaemon → trades.jsonl → SignalExecutor v2 (real order)       │
│                                                                         │
│   # 未來擴展：                                                           │
│   elif mode == "live-api":                                              │
│       LiveDaemon → BinanceFuturesMainnetBrokerAdapter (direct API)      │
└──────────────────────────────────────────────┬──────────────────────────┘
                                               │
┌──────────────────────────────────────────────┼──────────────────────────┐
│ Layer 3: Safety & Monitoring                  │                          │
│                                               │                          │
│   - MaxNotionalRule                                                     │
│   - Position reconciliation                                             │
│   - Kill switch (EMERGENCY_STOP)                                        │
│   - Audit trail (executions.jsonl)                                      │
│   - Alert on divergence (paper PnL vs live PnL)                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 如果你想更進一步（NautilusTrader 級別）

NautilusTrader 代表了業界最極端的一致性追求——用同一個 Rust event engine 跑所有模式。

如果你想在 `cyqnt_trd` 達到這個級別，需要：

1. **統一 daemon**：不再是「paper daemon + executor」，而是一個 daemon 根據 config 決定 broker：
   ```python
   class UnifiedDaemon(PaperDaemon):
       def __init__(self, broker: BrokerAdapter, **kwargs):
           super().__init__(**kwargs)
           self.live_broker = broker  # None for paper, real adapter for live
       
       def _record_fill(self, fill):
           super()._record_fill(fill)
           if self.live_broker is not None:
               intent = self._fill_to_intent(fill)
               self.live_broker.place_order(intent)
   ```

2. **使用已有的 BrokerAdapter interface**：`BinanceFuturesMainnetBrokerAdapter` 已經實現了 `place_order(intent)`，可以直接注入

3. **使用 Risk Rules**：`MaxAbsoluteNotionalRule`, `InstrumentWhitelistRule` 已經就緒

但考慮到你使用 `binance-cli`（API key 由 OpenClaw Gateway 管理），目前的 **Signal/Executor 分離模式** 仍然是最適合的。
它已經是業界認可的 OMS 架構模式。

---

## 附錄：各框架模式切換指令對照

| 框架 | Backtest | Paper | Live |
|------|----------|-------|------|
| Freqtrade | `freqtrade backtesting` | `freqtrade trade --config dry.json` | `freqtrade trade --config live.json` |
| Backtrader | `cerebro.run()` (historical data) | `cerebro.run()` (live data + SimBroker) | `cerebro.run()` (live data + LiveBroker) |
| Jesse | `jesse backtest` | Dashboard: Paper Trade ON | Dashboard: Paper Trade OFF |
| LEAN | `lean backtest` | `lean live --paper-trading` | `lean live --brokerage X` |
| NautilusTrader | `BacktestNode.run()` | `TradingNode(sandbox)` | `TradingNode(live)` |
| **你的系統** | `run_strategy.py --mode backtest` | `run_strategy.py --mode paper` | `run_strategy.py --mode live` |

你的 CLI 設計已經對齊業界標準。👍

---

*業界比較報告完畢。*
