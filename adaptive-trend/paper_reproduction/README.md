# AdaptiveTrend Paper Clean-Room Reproduction

This folder contains an independent reproduction attempt for:

> Systematic Trend-Following with Adaptive Portfolio Construction: Enhancing Risk-Adjusted Alpha in Cryptocurrency Markets, arXiv:2602.11708

The paper does not publish code, symbol lists, trade logs, market-cap snapshots, funding data, or slippage calibration. This reproduction is therefore a **clean-room approximation**, not an official replication.

## Level 1.5 Scope

Implemented in `reproduce_level1_futures.py`:

- Binance USD-M perpetual futures, 6H bars
- 2022-01 to 2024-12 OOS period
- 180 earliest-listed currently trading USDT perpetual contracts
- Monthly universe construction with prior-month quote volume as a public market-cap proxy
- Monthly no-lookahead parameter search on prior-month data
- ROC entry, ATR trailing stop, 70/30 long-short allocation
- Constant transaction cost in bps

Known gaps versus the paper:

- Uses quote volume, not CoinGecko market capitalization.
- Current Binance `exchangeInfo` does not include delisted futures, so survivorship bias remains.
- Funding is implemented as a post-hoc approximation, not exact trade-duration funding.
- Does not yet use 5-minute volume or order-book slippage calibration.
- Entry/exit rules are reconstructed from text because the authors did not publish code.

## First Results

| Variant | CAGR | Sharpe | MaxDD | Calmar | Total Return | Avg Trades/M |
|---------|------|--------|-------|--------|--------------|--------------|
| Paper-like thresholds (`long_sr=1.3`, `short_sr=1.7`, max 5) | 15.70% | 0.49 | -25.40% | 0.62 | 54.86% | 28.00 |
| Relaxed long-only (`long_sr=0.0`, no shorts, max 10) | 33.81% | 0.91 | -29.15% | 1.16 | 139.60% | 58.58 |
| Relaxed long-short (`long_sr=0.5`, `short_sr=0.5`, max 10) | 37.63% | 1.03 | -17.10% | 2.20 | 160.68% | 98.75 |
| Paper claim | 40.50% | 2.41 | -12.70% | 3.18 | ~140% | 142 |

## CoinGecko Market-Cap Sanity Check

I added `--universe-source coingecko-current`, which maps Binance futures symbols to CoinGecko coin ids using the highest current market cap among matching symbols. This is **not** a clean historical market-cap reconstruction, but it tests whether switching from quote-volume ranking to CoinGecko market-cap ranking moves results toward the paper.

| Variant | CAGR | Sharpe | MaxDD | Calmar | Total Return |
|---------|------|--------|-------|--------|--------------|
| CoinGecko-current, paper-like thresholds | 6.73% | 0.36 | -35.93% | 0.19 | 21.58% |
| CoinGecko-current, relaxed long-short | 31.61% | 1.12 | -20.83% | 1.52 | 127.95% |

CoinGecko historical range fetching was attempted with `download_coingecko_mcap.py`, but the public API returned `401 Unauthorized` with error code `10012`: public API users are limited to historical data within the past 365 days. A true Level 2 replication needs a paid CoinGecko plan/API key or a local historical market-cap dataset.

## Binance Synthetic Universe Variant

The paper's short book uses lower-market-cap assets. In the volume-proxy version, using the literal lowest-volume tail is noisy and not very tradeable. I added `--short-pool-mode next`, which uses the next liquidity bucket after the long universe: long pool = ranks 1-15 by prior-month quote volume; short pool = ranks 16-30.

| Variant | CAGR | Sharpe | MaxDD | Calmar | Total Return |
|---------|------|--------|-------|--------|--------------|
| Volume-next, paper-like thresholds | 18.99% | 0.55 | -26.30% | 0.72 | 68.45% |
| Volume-next, relaxed long-short | 44.45% | 1.20 | -13.18% | 3.37 | 201.41% |
| Volume-next, relaxed long-short + funding approx. | 45.52% | 1.21 | -12.78% | 3.56 | 208.13% |

This is the closest reconstruction so far on return/drawdown: CAGR and MaxDD are near the paper's headline. However, Sharpe remains around 1.2, roughly half of the paper's 2.41.

## 2025+ Out-of-Sample Check

Per user request, I treated 2025-01 onward as the OOS period and everything before 2025 as IS. Because 2026-05 is incomplete as of 2026-05-21, the formal OOS uses complete months from 2025-01 through 2026-04.

Tested candidate: the closest Binance-synthetic variant so far:

```text
--short-pool-mode next --long-sr 0.5 --short-sr 0.5 --max-positions 10
```

| Period | CAGR | Sharpe | MaxDD | Calmar | Total Return | Months |
|--------|------|--------|-------|--------|--------------|--------|
| IS 2022-01 to 2024-12 | 44.45% | 1.20 | -13.18% | 3.37 | 201.41% | 36 |
| OOS 2025-01 to 2026-04 | -17.23% | -0.73 | -32.89% | -0.52 | -22.29% | 16 |
| IS + approximate funding | 45.45% | 1.21 | -12.76% | 3.56 | 207.72% | 36 |
| OOS + approximate funding | -17.23% | -0.73 | -32.89% | -0.52 | -22.29% | 16 |

This is a serious failure of the candidate strategy under the requested OOS split. The strong 2022-2024 result does not carry forward into 2025-2026.

## Same-Data Baselines

Implemented in `baselines.py` using the same Binance Futures 6H cache and no-lookahead monthly timing.

| Baseline | CAGR | Sharpe | MaxDD | Total Return |
|----------|------|--------|-------|--------------|
| BTC-BH | 33.02% | 0.76 | -60.29% | 135.37% |
| EW top20 volume BH | -14.72% | 0.23 | -73.62% | -37.98% |
| TSMOM 1M top20 | -44.85% | -0.34 | -91.43% | -83.23% |
| TSMOM 3M top20 | -7.86% | 0.17 | -82.86% | -21.78% |

Interpretation: the clean-room strategy variants do beat simple EW-BH and TSMOM baselines on this data, and relaxed variants beat BTC-BH on Sharpe/drawdown. The gap is not "strategy has no edge"; the gap is specifically that no tested reconstruction gets close to the paper's Sharpe 2.41.

## Funding Adjustment

Implemented in `apply_funding_adjustment.py`.

This is a post-hoc approximation that assumes selected monthly futures positions are held for the full month for funding. It is favorable to the strategy in some months and is meant as an audit check, not a final execution model.

| Variant | Base Sharpe | Funding-Adjusted Sharpe | Base CAGR | Funding-Adjusted CAGR |
|---------|-------------|-------------------------|-----------|-----------------------|
| Quote-volume relaxed long-short | 1.03 | 1.04 | 37.63% | 38.32% |
| CoinGecko-current relaxed long-short | 1.12 | 1.16 | 31.61% | 31.88% |
| Volume-next relaxed long-short | 1.20 | 1.21 | 44.45% | 45.52% |

Funding does not explain the gap to the paper's Sharpe 2.41.

## Initial Judgment

The clean-room approximation does **not** reproduce the paper's Sharpe 2.41. The best Binance-synthetic variant gets close on CAGR and MaxDD during 2022-2024 (45.52% CAGR, -12.78% MaxDD after approximate funding), but Sharpe remains only 1.21 and the same candidate fails on the 2025+ OOS split.

This does not prove the paper is wrong, because important components are still approximated. It does show that the headline result does not naturally emerge from the public, text-described core framework under strict no-lookahead timing.

## Next Iterations

1. Replace quote-volume proxy with true CoinGecko monthly market-cap snapshots.
2. Add exact trade-duration funding inside the trade simulator.
3. Add a high-liquidity-only universe variant to reduce noisy short-leg behavior.
4. Add timeframe comparison H4/H6/H8/D1 using the same no-lookahead rules.
5. Add 5-minute volume slippage proxy.
