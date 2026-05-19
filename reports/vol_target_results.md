# Volatility Targeting Backtest Results
**Generated:** 2026-05-19 09:24 UTC

## Summary Table

| Strategy | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Days |
|----------|------|-----|--------|---------|-------|--------|------|
| VT_15pct (ALL) | 26.21% | 19.31% | 1.303 | 1.648 | -33.26% | 0.788 | 5784 |
| VT_15pct (IS) | 34.7% | 20.27% | 1.572 | 1.924 | -33.26% | 1.043 | 3454 |
| VT_15pct (OOS) | 14.59% | 17.78% | 0.855 | 1.152 | -31.21% | 0.467 | 2330 |
| VT_20pct (ALL) | 34.85% | 25.42% | 1.304 | 1.668 | -42.19% | 0.826 | 5784 |
| VT_20pct (IS) | 46.56% | 26.66% | 1.568 | 1.94 | -42.19% | 1.104 | 3454 |
| VT_20pct (OOS) | 19.19% | 23.44% | 0.867 | 1.18 | -39.72% | 0.483 | 2330 |
| MVRV_VT_20pct (ALL) | 18.29% | 18.21% | 1.013 | 1.243 | -39.96% | 0.458 | 5784 |
| MVRV_VT_20pct (IS) | 23.48% | 20.0% | 1.154 | 1.41 | -39.96% | 0.588 | 3454 |
| MVRV_VT_20pct (OOS) | 11.0% | 15.16% | 0.765 | 0.944 | -28.19% | 0.39 | 2330 |
| MVRV_VT_ZStop (ALL) | 18.29% | 18.21% | 1.013 | 1.243 | -39.96% | 0.458 | 5784 |
| MVRV_VT_ZStop (IS) | 23.48% | 20.0% | 1.154 | 1.41 | -39.96% | 0.588 | 3454 |
| MVRV_VT_ZStop (OOS) | 11.0% | 15.16% | 0.765 | 0.944 | -28.19% | 0.39 | 2330 |
| BTC_BuyHold (ALL) | 137.52% | 89.57% | 1.413 | 1.88 | -92.75% | 1.483 | 5783 |
| BTC_BuyHold (IS) | 231.32% | 104.73% | 1.666 | 2.219 | -92.75% | 2.494 | 3453 |
| BTC_BuyHold (OOS) | 45.05% | 60.31% | 0.924 | 1.238 | -76.67% | 0.588 | 2330 |

## Best OOS Strategy
**BTC_BuyHold (OOS)** — Sharpe=0.924, MaxDD=-76.67%, CAGR=45.05%

## Methodology
- Initial capital: $10,000 | Fee: 4bps per leg
- IS: 2012–2019 | OOS: 2020–2026
- Position = min(sigma_target / realized_vol_20d, 1.0)  (no leverage)
- MVRV Zone: expanding-window percentile rank → weight [0.1, 0.25, 0.5, 0.75, 1.0]
- Z-Score stop: force position to 0.3 when MVRV Z-Score > 2.5
- T-1 signal → T execution

## Chart
![Equity + Position](/root/.openclaw/workspace/openclaw-media/jarvis-image-1779182639-d45338f6.png)
