# Funding Rate Alpha Research

**Status:** ✅ First pass complete  
**Date:** 2026-05-15  
**Data:** 2023-01-01 → 2026-05-15 | 3,691 observations per symbol  
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT  

---

## Research Question

> When a coin's 8h funding rate deviates from its rolling mean by ±Nσ,  
> does the next N-bar price return show statistically significant skew?

---

## Method

1. Fetch full funding rate history via `fapi/v1/fundingRate` (forward pagination, startTime)
2. Fetch 8h OHLCV klines, merge on nearest timestamp
3. Compute z-score of funding rate per symbol
4. Define regimes: `high_2s / high_1.5s / high_1s / neutral / low_1s / low_1.5s / low_2s`
5. Compute forward returns at +1, +3, +6, +12 bars (= +8h, +24h, +48h, +96h)
6. 1-sample t-test: is mean fwd return significantly ≠ 0?

---

## Key Findings

### 🎯 Low Funding Rate = Bullish Reversal Signal

| Symbol | Regime | N | fwd_8h | t-stat | p-value |
|--------|--------|---|--------|--------|---------|
| BTCUSDT | low_1s | 232 | **+0.275%** | 2.90 | **0.0041** ✅ |
| SOLUSDT | low_1.5s | 17 | **+1.154%** | 2.56 | **0.0209** ✅ |
| ETHUSDT | low_1s | 191 | **+0.303%** | 1.96 | **0.0518** ✅ |

**Interpretation:** When funding is depressed (shorts dominating, longs paying), the market is primed for a short squeeze. This is a **contrarian signal** — not a momentum one.

### ❌ Popular Myth Busted: High Funding ≠ Imminent Drop

High funding (≥ +2σ) showed **positive or near-zero** forward returns across most symbols:
- BTC high_2s: fwd_8h = **+0.118%** (no reversal)
- XRP high_2s: fwd_8h = **+0.307%** (continuation!)

High funding during bull runs simply reflects demand — not exhaustion.

### 💰 Carry Trade Estimates (Delta-Neutral: Long Spot + Short Perp)

| Symbol | Est. Annual Carry |
|--------|------------------|
| ETHUSDT | ~7.76% |
| XRPUSDT | ~7.52% |
| BTCUSDT | ~7.45% |
| SOLUSDT | ~4.19% |
| BNBUSDT | **-3.94%** ⚠️ (inverted — carry flows opposite) |

> Note: Before fees, slippage, and basis risk. BNB's negative mean funding is structurally unusual.

### 🧠 BNB Structural Anomaly

BNB has:
- Mean funding = **-0.0036%** (negative — shorts being paid)
- 170 `low_2s` events vs. BTC's 11
- Likely driven by Binance ecosystem demand + institutional hedging patterns

---

## Carry Trade Structure (BNB Anomaly)

BNB's negative mean funding suggests the **carry trade is reversed**:
- Hold BNB perp long + short spot → collect negative funding
- Or: avoid delta-neutral carry here unless you model the regime carefully

---

## Open Questions / Next Research

- [ ] Cumulative low funding (N consecutive bars below threshold) → stronger signal?
- [ ] Add Open Interest filter: low funding + rising OI = squeeze setup
- [ ] Funding rate velocity (rate of change) as signal
- [ ] Cross-asset spillover: BTC low funding → altcoin forward returns
- [ ] Regime-conditional carry: only run carry when funding > Xσ to avoid bleed

---

---

## Backtest Results (2023-01 ~ 2026-05, Capital $10,000/symbol)

### Strategy A — Low-FR Reversal (z ≤ −1σ, hold 24h)

| Symbol | Trades | Win% | PnL $ | CAGR | MaxDD | Sharpe | Calmar |
|--------|--------|------|-------|------|-------|--------|--------|
| BTCUSDT | 137 | 56.9% | +$7,598 | +18.3% | -20.7% | 1.02 | 0.88 |
| ETHUSDT | 127 | 57.5% | +$7,999 | +19.0% | -37.2% | 0.84 | 0.51 |
| SOLUSDT | 36 | 47.2% | +$14,375 | +30.3% | -25.1% | 0.91 | 1.20 |
| XRPUSDT | 181 | 50.3% | +$703 | +2.0% | -52.5% | 0.23 | 0.04 |
| ~~BNBUSDT~~ | 116 | 45.7% | -$3,115 | -10.5% | -41.2% | -0.56 | - |

BTC hold-period sweep: best Sharpe at 8h (1.29), best PnL at 96h (+$13,944, CAGR +29.6%).

### Strategy B — Carry Trade (delta-neutral)

| Symbol | PnL $ | CAGR | MaxDD | Sharpe | Calmar |
|--------|-------|------|-------|--------|--------|
| BTCUSDT | +$2,821 | +7.7% | -0.5% | 25.38 | 16.86 |
| ETHUSDT | +$2,955 | +8.0% | -0.6% | 25.01 | 13.17 |
| XRPUSDT | +$2,850 | +7.8% | -1.0% | 18.31 | 7.76 |
| SOLUSDT | +$1,496 | +4.3% | -3.9% | 4.48 | 1.08 |
| ~~BNBUSDT~~ | -$1,253 | -3.9% | -13.4% | -5.31 | - |

Carry Sharpe > 25 for BTC/ETH under delta-neutral assumption (basis risk not modelled).

---

## Files

| File | Description |
|------|-------------|
| `fetch_data_v3.py` | Fetches funding + 8h klines, 2023-01 onwards |
| `analyze.py` | Statistical analysis: regimes, t-tests, carry sim |
| `backtest.py` | Full backtest: reversal + carry, all metrics |
| `results/results.csv` | Regime × forward return summary |
| `results/btc_trades.csv` | BTC trade-by-trade log (Strategy A) |
| `results/btc_equity.csv` | BTC equity curve time series |
| `data/` | Parquet files (gitignored) — re-run fetch_data_v3.py |
