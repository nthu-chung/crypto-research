## Cross-Sectional Long/Short (Direction 2) — Negative Result

**Date:** 2026-05-15 | **Status:** ❌ Strategy failed, but failure is informative

### What We Tested

Every 8h bar:
- Rank all 5 coins by rolling z-score of funding rate
- Long the lowest z-score coin (most negative funding)
- Short the highest z-score coin (most positive funding)
- Hold N bars, equal notional both sides (market neutral)

### Results

| Hold | CAGR | MaxDD | Sharpe |
|------|------|-------|--------|
| 8h | -54.1% | -92.2% | -3.13 |
| 96h | -7.3% | -46.6% | -0.05 |

vs Strategy A (BTC long-only): CAGR +21%, Sharpe 1.29 ✅

### Why It Failed

**The short leg is the problem.**

In crypto, high funding ≠ imminent reversal.
High funding periods coincide with the strongest bull momentum.
Shorting the highest-funding coin = shorting the strongest momentum = consistently wrong.

Key finding from pair breakdown:
- `BNB vs SOL` short: win rate 11%, PnL -$1,942 (worst pair)
- BNB's inverted structure pollutes every pair it appears in
- The long leg alpha (low funding → reversal) IS real
- The short leg alpha (high funding → reversal) IS NOT real

**Crypto alpha is asymmetric:**
- ✅ Low funding → mean reversion (works)
- ❌ High funding → mean reversion (doesn't work, momentum dominates)

### Next Directions

1. **Fix the short leg**: Short based on momentum/relative strength, not funding
2. **Regime-conditional**: Only activate short leg in bear/ranging markets
3. **BTC as fixed hedge**: Long low-funding altcoin + short equivalent BTC (beta hedge)
