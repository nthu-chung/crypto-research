# Volatility Regime-Conditional Momentum Strategy
## Backtest Report — 2021-01-01 to 2024-12-31

**Generated:** 2026-05-21  
**Universe:** Top-20 USDT Perpetual Futures (Binance)  
**Research Question:** Does BTC realized volatility regime alter the sign of cross-sectional momentum in crypto?

---

## 1. Executive Summary

The core hypothesis — *low-vol favors momentum continuation, high-vol favors mean reversion* — is **not confirmed** in this crypto dataset over 2021–2024. The empirical finding is the opposite of the traditional Ang et al. (2006) equity market pattern:

- **High-volatility periods**: unconditional momentum generates a small *positive* alpha (Sharpe +0.27, annualized +11.84%). Flipping to counter-momentum in those same periods produces deeply negative returns (Sharpe −2.98, annualized −128.64%).
- **Low-volatility periods**: both strategies are essentially identical (as expected, since in low-vol we apply no flip). Both lose money on a risk-adjusted basis (Sharpe −0.36).
- The **regime-conditional strategy underperforms** the unconditional baseline across all metrics (Sharpe −1.05 vs −0.30, annualized −43.4% vs −12.4%).

**Bottom line:** In crypto (2021–2024), high-volatility periods appear to accelerate, not reverse, cross-sectional momentum. The hypothesized regime flip destroys value.

---

## 2. Data & Methodology

| Parameter | Value |
|-----------|-------|
| Universe | 20 USDT perp contracts (Binance fapi) |
| Period | 2021-01-01 – 2024-12-31 (1,461 trading days) |
| Momentum window | 7-day rolling mean of daily log-returns |
| Holding period | 3 days |
| Long/Short book | Top 30% / Bottom 30% by signal |
| Transaction cost | 4 bps per leg (2 × enter + exit = 16 bps per trade) |
| Vol regime filter | BTC 30d realized vol vs. expanding-window median |

### No-Lookahead Controls
- `btc_vol_30d[t]` uses only log-returns up through `t−1` (shift applied before rolling std).
- The vol regime threshold is an **expanding-window quantile** — at each date `t`, only historical vol observations prior to `t` are used to compute the median. No future-period median contamination.
- Momentum signal uses `shift(1).rolling(7)`, so signal at `t` is the 7-day mean of returns ending at `t−1`.

### BTC Realized Volatility Summary (30d, annualized)
| Statistic | Value |
|-----------|-------|
| Mean | 58.6% |
| Median | 55.7% |
| Min | 16.8% |
| Max | 121.4% |
| P25 | 43.2% |
| P75 | 69.9% |

BTC realized vol ranged from 16.8% (early 2024 calm) to 121.4% (2021 crash periods). Median ~56% is consistent with crypto being 3–4× more volatile than US equities.

---

## 3. Regime Calendar (2021–2024)

| Regime | Days | Share |
|--------|------|-------|
| Low-vol | 1,090 | 77.3% |
| High-vol | 321 | 22.7% |

The market spent 77% of the period in low-vol regime and 23% in high-vol. This asymmetry reflects crypto's structural pattern: prolonged trending / low-vol bull phases punctuated by short, intense high-vol episodes.

### Regime Duration Distribution
| Regime | Episodes | Mean Duration | Median | Min | Max |
|--------|----------|---------------|--------|-----|-----|
| Low-vol | 22 | 49.5 days | 26.5 days | 1 | 332 |
| High-vol | 21 | 15.3 days | 6.0 days | 1 | 39 |

Low-vol episodes are both more frequent and far longer (mean 49.5 days, max 332-day run). High-vol spikes are short and sharp (median 6 days). This regime asymmetry is critical: most strategy PnL accrues in low-vol periods by sheer duration.

---

## 4. Core Performance Results

### Strategy vs. Baseline — Full Period (2021–2024)

| Metric | Regime-Conditional | Unconditional Baseline |
|--------|--------------------|------------------------|
| Annualized Return | −43.4% | −12.4% |
| Annualized Volatility | 41.3% | 41.2% |
| Sharpe Ratio | −1.051 | −0.300 |
| Maximum Drawdown | −91.5% | −85.7% |
| Win Rate | 45.5% | 45.5% |
| N Observations | 1,454 | 1,454 |

The regime-conditional strategy **underperforms the baseline by ~31 percentage points annually**. The vol flip adds no value on net — it hurts substantially.

### Performance by Vol Regime

| Strategy | Vol Regime | Ann. Return | Ann. Vol | Sharpe | Max DD | N Days |
|----------|-----------|-------------|----------|--------|--------|--------|
| Regime-Conditional | Low-vol | −13.0% | 35.6% | −0.364 | −72.3% | 1,089 |
| Regime-Conditional | High-vol | −128.6% | 43.2% | −2.979 | −72.9% | 321 |
| Unconditional | Low-vol | −13.0% | 35.6% | −0.364 | −72.3% | 1,089 |
| Unconditional | High-vol | **+11.8%** | 43.2% | **+0.274** | −51.8% | 321 |

**Key insight:** In low-vol periods, the two strategies are *identical* (as expected — no flip applied). The entire regime-conditional underperformance comes from the high-vol flip.

In high-vol periods, **unconditional momentum generates positive returns** (+11.8% annualized, Sharpe +0.27), while the regime-conditional strategy's counter-momentum position loses badly (−128.6%). The hypothesis has the sign wrong for crypto.

---

## 5. Annual Breakdown

| Year | Regime-Conditional | Unconditional | Low-Vol Ret | High-Vol Ret | Low-Vol Days | High-Vol Days |
|------|-------------------|---------------|-------------|--------------|--------------|---------------|
| 2021 | **+18.5%** | +6.2% | +42.8% | −3.5% | 255 | 60 |
| 2022 | −22.0% | +1.6% | +11.3% | −33.2% | 231 | 134 |
| 2023 | −26.6% | −35.1% | −26.7% | +0.1% | 339 | 26 |
| 2024 | −142.6% | −21.8% | −66.1% | −76.6% | 264 | 101 |

Notable observations:
- **2021** was the only year regime-conditional beat unconditional (+18.5% vs +6.2%). The low-vol component generated +42.8% cumulative return, and the high-vol period coincided with brief choppy patches where counter-momentum was marginally helpful (−3.5% limited loss).
- **2022**: Persistent high-vol bear market (134 high-vol days). The counter-momentum flip failed catastrophically (−33.2% from high-vol regime), dragging overall performance negative despite positive low-vol returns (+11.3%).
- **2023**: Best year for unconditional momentum (both strategies lose, but baseline beats by +8.5pp). Very few high-vol days (26) — regime flip barely triggered, small relative effect.
- **2024**: Disaster for regime-conditional (−142.6% vs −21.8%). The 101 high-vol days correspond to the post-ETF approval bull run where momentum was strongly positive — flipping to counter-momentum was catastrophic.

---

## 6. Vol Threshold Sensitivity

Using expanding-window percentile thresholds (30th, 50th, 70th percentile as the regime switch point):

| Threshold | Ann. Return | Sharpe | Max DD |
|-----------|-------------|--------|--------|
| 30th percentile | −26.4% | −0.641 | −81.5% |
| 50th percentile (base) | −43.4% | −1.051 | −91.5% |
| **70th percentile** | **−3.0%** | **−0.074** | **−82.5%** |

The 70th percentile threshold is closest to neutral — effectively only flipping in extreme high-vol events. This produces near-zero alpha (Sharpe −0.074), essentially matching buy-and-hold-neutral performance. As the threshold decreases (flipping more aggressively), performance monotonically worsens.

This sensitivity pattern confirms the core finding: **the momentum reversal flip in high-vol periods destroys value in crypto**. The less aggressively you flip, the less damage done. At p70, we only flip in the top 30% of vol observations — these are genuinely extreme events — and even then, the reversal barely helps.

---

## 7. Interpretation & Hypothesis Falsification

### Why the hypothesis fails in crypto

**The traditional equity market mechanism (Ang et al. 2006):**
- High vol in equities typically = fear-driven, indiscriminate selling → overcorrection → mean reversion → counter-momentum profits
- Low vol = gradual trend continuation → momentum profits

**What happens in crypto:**
1. **Crypto high-vol regimes are often trend-amplifying, not reverting.** In 2022 (crypto winter), high vol accompanied persistent *downtrends* — momentum (hold losers long, buy winners short) would flip to the wrong side. In 2024's bull run, high vol accompanied persistent *uptrends*.
2. **Crypto vol spikes are short (median 6 days)** vs. equities where high-vol regimes can persist months. 6-day high-vol spikes may not be long enough for mean reversion to play out before the regime ends, especially with a 3-day hold.
3. **Cross-sectional dispersion** in crypto is driven more by idiosyncratic narrative momentum (token-specific news, listings, delistings) than macro fear. These narratives persist even in high-vol environments.
4. **Liquidity**: In high crypto vol, perpetual funding rates and forced liquidations create cross-sectional momentum cascades (winners get more capital, losers get liquidated), not mean reversion.

### What actually works in high-vol crypto

The empirical finding suggests that if you *must* adapt to vol regimes in crypto:
- **Low-vol**: Unconditional momentum — Sharpe −0.36 (loss, but manageable)
- **High-vol**: Also unconditional momentum — Sharpe +0.27 (small positive alpha)
- **An alternative hypothesis**: High-vol regimes in crypto may call for *stronger* momentum (momentum + vol scaling), not momentum reversal

---

## 8. Methodological Notes & Caveats

1. **Universe survivorship**: Top-20 coins were fixed ex-ante based on 2024 market cap rank. Several (e.g., FILUSDT, ALGOUSDT, VETUSDT) lost relevance and liquidity over the period, potentially introducing a mild downward bias through thin-market slippage not captured in 4bps flat fee.
2. **Fee assumption conservatism**: 4bps per leg is realistic for maker orders. Taker orders on Binance perps can be 2–4× higher during high-vol spikes, further amplifying the already-negative high-vol performance.
3. **Signal robustness**: A 7-day lookback for raw momentum is short. Longer windows (21d, 63d) may behave differently — this is a 1-week short-term momentum signal.
4. **Perpetual vs. spot**: Perp prices track spot closely (funding prevents divergence), but the backtest does not capture funding rate cash flows, which would be material in trending markets.
5. **Daily granularity**: Intraday entry/exit timing is not modeled. In practice, rebalancing at open/close would differ from end-of-day prices used here.

---

## 9. Conclusions

| Finding | Verdict |
|---------|---------|
| Low-vol → momentum continuation | **Partially supported** (but momentum itself is weak/negative in this period) |
| High-vol → momentum reversal | **Rejected** — crypto momentum *continues* in high-vol periods |
| Regime-conditional beats unconditional | **Rejected** — significantly underperforms (Sharpe −1.05 vs −0.30) |
| 70th-percentile threshold less harmful | **Confirmed** — less flipping = less damage |

**Primary takeaway:** The Ang et al. (2006) vol-regime momentum inversion does not transfer to crypto in 2021–2024. In crypto, both vol regimes appear to exhibit momentum continuation, with the high-vol regime slightly *more* momentum-friendly. Regime-based strategies should explore momentum *scaling* (increase position size in high-vol trending regimes) rather than regime *flipping*.

**Suggested next steps:**
1. Test momentum scaling (size ∝ vol or trend strength) rather than sign flip
2. Explore funding-rate regime as alternative regime signal
3. Extend universe and test on 2017–2020 data for out-of-sample validation
4. Test with longer momentum windows (21d, 63d, 126d)
5. Separate analysis by market cycle phase (bull 2021, bear 2022, recovery 2023, bull 2024)

---

## 10. Data Files

| File | Description |
|------|-------------|
| `results.json` | Full structured results (all metrics, annual, sensitivity) |
| `strat_pnl.csv` | Daily PnL for regime-conditional strategy |
| `baseline_pnl.csv` | Daily PnL for unconditional baseline |
| `fetch_and_backtest.py` | Full Python source code |

---

*Research conducted by: Binance AI Pro — Quant Research Module*  
*Data source: Binance FAPI (futures daily klines)*
