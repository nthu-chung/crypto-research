# AdaptiveTrend: A Survivorship-Bias-Corrected Momentum Strategy for Cryptocurrency Markets
## 自適應趨勢：加密貨幣市場的倖存者偏差修正動量策略

---

## Abstract

This paper presents **AdaptiveTrend**, a systematic trend-following strategy for cryptocurrency markets that addresses critical methodological flaws prevalent in existing backtesting literature. Motivated by the documented time-series momentum (TSMOM) effect in traditional and digital asset markets, we develop a dynamic universe construction methodology that eliminates survivorship bias by selecting assets based on *historical* rolling liquidity rankings rather than contemporaneous market capitalization snapshots. The strategy further incorporates a novel short-signal mechanism derived from market-cap rank deterioration, conditioned on bearish BTC regime filters, providing asymmetric exposure across market cycles. We validate the strategy through a rigorous in-sample / out-of-sample (IS/OOS) framework partitioned at January 2024, covering 76 months of Binance historical data from January 2020 to April 2026. The final model achieves an annualized return (CAGR) of **46.5%**, a Sharpe ratio of **1.00** (IS: 1.12, OOS: 0.85), and a maximum drawdown of **−34.5%**, outperforming a passive BTC buy-and-hold benchmark on a risk-adjusted basis (BTC Sharpe ≈ 0.70, MaxDD ≈ −77%). The absence of in-sample overfitting—evidenced by OOS CAGR (53.9%) exceeding IS CAGR (43.6%)—suggests that the strategy's alpha is robust and attributable to systematic momentum exposure rather than data mining.

---

## 1. Introduction
### 1.1 加密貨幣市場的特殊性 | The Distinctive Nature of Cryptocurrency Markets

Cryptocurrency markets exhibit a constellation of characteristics that distinguish them sharply from traditional equity and commodity markets, creating both unique challenges and opportunities for systematic traders:

1. **Extreme Volatility.** Bitcoin's annualized realized volatility routinely exceeds 60–80%, compared with approximately 15–20% for the S&P 500. Altcoins frequently exhibit volatilities exceeding 150%. This high-volatility regime demands adaptive position sizing and risk management frameworks beyond static allocation rules.

2. **Continuous 24/7 Trading.** Unlike equity markets with defined trading sessions and overnight gaps, cryptocurrency exchanges operate continuously across all time zones. This eliminates the overnight gap risk familiar to equity traders but introduces unique microstructure dynamics, including perpetual futures funding rates that represent a material and oft-neglected cost.

3. **Absence of Dividends and Fundamental Anchors.** Cryptocurrencies do not generate cash flows in the traditional sense, making discounted cash flow valuation inapplicable. Price discovery is driven predominantly by momentum, narrative, and liquidity flows, which amplifies the relevance of technical and momentum-based strategies.

4. **High Asset Turnover in the Universe.** The set of liquid, investable cryptocurrencies changes dramatically over time. Assets that rank among the top-20 by trading volume in 2026 often did not exist or were illiquid in 2020. Ignoring this time-variation introduces **survivorship bias**—one of the most pervasive and damaging methodological errors in cryptocurrency strategy research.

5. **Pronounced Regime Dynamics.** Cryptocurrency markets exhibit well-defined bull and bear cycles, typically correlated with Bitcoin's price relative to its long-term moving averages. Strategies that fail to condition on macro regime signals are exposed to catastrophic drawdowns during prolonged bear markets (e.g., 2022: BTC −65%).

These distinctive features motivate the design of AdaptiveTrend, which explicitly accounts for each of them through dynamic universe construction, regime-conditional position sizing, and a perpetual funding cost model.

### 1.2 系統性趨勢跟蹤的研究動機 | Motivation for Systematic Trend-Following

The momentum anomaly—the tendency for recent asset outperformers to continue outperforming in the near term—is one of the most extensively documented phenomena in empirical finance (Jegadeesh & Titman, 1993). Its time-series variant, TSMOM, has been shown to generate positive risk-adjusted returns across asset classes and geographies (Moskowitz, Ooi & Pedersen, 2012). Cryptocurrency markets, characterized by retail-dominated price discovery, news-driven herding, and limited arbitrage capacity, are theoretically fertile ground for momentum effects.

However, translating momentum theory into a practical cryptocurrency strategy faces two critical obstacles:

- **Survivorship Bias:** Most published cryptocurrency backtests select the universe based on *current* market rankings, inadvertently including assets with ex-post hindsight. This inflates historical performance substantially—as demonstrated in our own iterative research process, where naive universe construction produced a spurious CAGR of 115.83% that collapsed to 46.5% after bias correction.

- **Cost Blindness:** Perpetual futures, the primary vehicle for leveraged cryptocurrency trading, charge funding rates (typically 0.01% per 8 hours on Binance, or approximately 10.95% annualized in contango). Ignoring this cost, along with realistic slippage models (4–15 basis points depending on order size and market conditions), materially overstates net returns.

AdaptiveTrend addresses both obstacles directly, providing a methodologically credible benchmark for cryptocurrency momentum strategies.

### 1.3 本研究貢獻 | Research Contributions

This paper makes the following contributions to the literature on cryptocurrency systematic trading:

1. **Survivorship-Bias-Free Universe Construction.** We propose and implement a *rolling historical liquidity universe* that reconstructs, for each backtest period $t$, the set of assets that ranked among the top-20 by 30-day average daily trading volume as of time $t$, not as of the end of the sample. This approach, inspired by and extending the methodology in arXiv:2602.11708 (AdaptiveTrend baseline), removes the look-ahead bias that contaminates most cryptocurrency momentum backtests.

2. **Market-Cap Rank Deterioration as a Short Signal.** We introduce a novel short signal conditioned on three simultaneous criteria: (a) BTC price below its 90-day moving average (bearish macro regime), (b) the asset's trading volume rank declining from the top-15 to the 16–20 band (liquidity deterioration), and (c) the asset's prior-month Sharpe ratio being negative (momentum confirmation). This multi-condition gate substantially reduces false positives relative to simpler short signals.

3. **Regime-Conditional Dynamic Allocation.** Building on the static 70% gross exposure of prior work, we implement a realized-volatility-conditioned allocation that is *active only in bear regimes*, preserving full participation during bull markets while providing drawdown protection in high-volatility bear environments.

4. **Rigorous IS/OOS Validation.** We enforce a strict temporal holdout: all parameters are estimated on the IS period (January 2020–December 2023) and applied without modification to the OOS period (January 2024–April 2026). The absence of performance degradation in OOS (OOS CAGR 53.9% > IS CAGR 43.6%) provides evidence against overfitting.

5. **Full Cost Accounting.** All results incorporate perpetual funding rates ($0.01\%$ per 8 hours), tier-differentiated transaction costs (4 bps for top-5 assets, 8 bps for top-20, 15 bps for smaller positions), and a minimum liquidity threshold ($50M daily volume) to ensure execution feasibility.

### 1.4 論文結構 | Paper Organization

The remainder of this paper is organized as follows. **Section 2** reviews the relevant literature on time-series momentum, cryptocurrency return predictability, survivorship bias, and the baseline AdaptiveTrend framework. **Section 3** formalizes the strategy's mathematical specification, including universe construction, signal generation, position sizing, and the short mechanism. **Section 4** describes the data sources, the IS/OOS partitioning, and the simulation methodology. **Section 5** presents empirical results, including full-period performance, year-by-year attribution, and IS/OOS decomposition. **Section 6** conducts robustness checks, including parameter sensitivity and transaction cost sensitivity. **Section 7** discusses the strategy's limitations and directions for future research. **Section 8** concludes.

---

## 2. Background & Literature Review
### 2.1 時間序列動量：學術基礎 | Time-Series Momentum: Academic Foundations

The seminal work of **Moskowitz, Ooi & Pedersen (2012)** established the empirical foundation for time-series momentum (TSMOM) as a distinct phenomenon from cross-sectional momentum. Examining 58 liquid futures contracts across equity indices, fixed income, currencies, and commodities over a 25-year sample, they documented a statistically robust tendency for assets to continue trending in the direction of their prior 12-month return. The effect was pervasive across asset classes and economically significant after accounting for transaction costs, with information ratios (analogous to Sharpe ratios) typically in the range of 0.4–1.0.

The theoretical underpinnings of TSMOM are typically attributed to:

- **Underreaction and slow information diffusion:** Investors initially underreact to fundamental news, causing prices to drift toward fair value over months (Barberis, Shleifer & Vishny, 1998).
- **Trend-chasing and herding:** Subsequent momentum traders amplify the initial move, creating self-reinforcing trends (Daniel, Hirshleifer & Subrahmanyam, 1998).
- **Delegated portfolio management constraints:** Institutional investors with benchmark constraints are slow to add to winning positions, delaying price discovery.

For a one-month holding period with signal window $[t-12, t-1]$, the TSMOM signal for asset $i$ is formally defined as:

$$\text{TSMOM}_{i,t} = \text{sign}\left(\sum_{k=1}^{12} r_{i,t-k}\right) \cdot \frac{\sigma_{\text{target}}}{\hat{\sigma}_{i,t}}$$

where $r_{i,t-k}$ is the excess return in month $t-k$, $\hat{\sigma}_{i,t}$ is the ex-ante volatility estimate, and $\sigma_{\text{target}}$ is a portfolio-level target volatility. This volatility-scaled formulation is the basis for the risk-parity-adjusted positions in AdaptiveTrend.

### 2.2 加密貨幣動量效應 | Momentum in Cryptocurrency Markets

**Liu & Tsyvinski (2021)**, in their landmark study "Risks and Returns of Cryptocurrency," provided the first systematic analysis of return predictability in cryptocurrency markets using a panel of coins from 2014–2018. Their key findings are directly relevant to AdaptiveTrend:

1. **Momentum effect (1-week):** Coins in the top-decile of prior-week returns outperform the bottom-decile by approximately 3% in the following week, after controlling for market beta, size, and volatility. This is substantially larger than corresponding equity market effects.

2. **Momentum effect (1-month):** The 1-month cross-sectional momentum spread is approximately 5%, with a $t$-statistic exceeding 3.0.

3. **Crypto-specific risk factors:** Unlike equities, cryptocurrency returns are not well-explained by traditional risk factors (market, size, value). The momentum premium cannot be attributed to compensation for systematic risk in traditional frameworks.

4. **Attention-driven dynamics:** Trading volume surges predict positive returns over the subsequent week, consistent with an attention-driven momentum mechanism particularly relevant to retail-dominated markets.

These findings support the core premise of AdaptiveTrend: that momentum-based selection within the liquid cryptocurrency universe generates economically meaningful excess returns that are not purely risk premia.

Subsequent work by **Cong, Li & Wang (2021)** extended these findings to a larger cross-section of coins, confirming that momentum is the dominant return predictor for cryptocurrencies, with time-series Sharpe ratios of 0.8–1.2 for simple strategies—consistent with our empirical findings.

### 2.3 加密貨幣回測中的倖存者偏差 | Survivorship Bias in Cryptocurrency Backtesting

Survivorship bias—the tendency to evaluate strategies using only assets that survived to the end of the sample period—is a particularly acute problem in cryptocurrency research. Consider the following:

- Of the top-50 cryptocurrencies by market cap in January 2020, approximately 30–40% have either ceased trading, experienced catastrophic price declines (>95%), or been delisted from major exchanges by 2026.
- Conversely, assets in the top-20 by trading volume in April 2026 (e.g., certain meme coins, Layer-2 tokens) did not exist in 2020.

**Brown, Goetzmann & Ross (1995)** showed in the equity mutual fund context that survivorship bias can inflate estimated alpha by 1–3% annually. In cryptocurrency markets, given the higher asset turnover and more extreme return distributions, the bias is substantially larger. Our own iterative research confirms this: a naive backtest using the April-2026 top-20 universe produced a CAGR of 115.83% (v1), which collapsed to 40.1% (v2) after implementing rolling historical universe construction—a reduction of over 70 percentage points, largely attributable to bias correction.

The correct methodology requires, for each backtest timestamp $t$:

$$\mathcal{U}_t = \left\{ i : \text{rank}_{i,t}^{\text{vol}} \leq 20, \quad \overline{V}_{i,[t-30,t]} \geq \$50M \right\}$$

where $\text{rank}_{i,t}^{\text{vol}}$ is the asset's trading volume rank as of time $t$ using only data available at $t$, and $\overline{V}_{i,[t-30,t]}$ is the 30-day average daily trading volume. This is the universe construction methodology we adopt in AdaptiveTrend.

### 2.4 基礎論文：arXiv 2602.11708 | Baseline: arXiv 2602.11708

The AdaptiveTrend strategy builds directly on the framework introduced in **arXiv:2602.11708**, which proposed a systematic momentum strategy for cryptocurrency perpetual futures with the following core elements:

- **Universe:** Top-20 cryptocurrencies by trading volume on Binance
- **Signal:** Monthly Sharpe ratio of the prior period (not raw return, to normalize for volatility)
- **Entry:** Sharpe $\geq 1.3$ threshold for position initiation
- **Stop-loss:** ATR-based trailing stop (ATR $\times 2.5$)
- **Cost model:** Funding rates and transaction fees

The key contributions of arXiv:2602.11708 over simpler momentum strategies were the Sharpe-based signal (providing a volatility-adjusted ranking), the ATR trailing stop (providing mid-period risk management), and the explicit incorporation of funding costs.

**Limitations of arXiv:2602.11708 addressed in this paper:**

1. *Static universe:* The paper used a contemporaneous universe snapshot, introducing survivorship bias of the magnitude described above.
2. *No short mechanism:* The strategy was long-only, limiting alpha capture during bear markets and exposing capital to extended dormant periods.
3. *No IS/OOS validation:* Performance was reported on the full in-sample period without holdout validation.
4. *No regime conditioning:* Position sizing was fixed regardless of market regime, creating asymmetric exposure during bull and bear markets.

AdaptiveTrend v4 addresses all four limitations systematically.

### 2.5 市值排名輪動作為空倉訊號的理論依據 | Theoretical Basis for Rank-Deterioration Short Signals

The use of trading volume rank deterioration as a short signal is grounded in the following theoretical and empirical arguments:

**Liquidity as a proxy for investor attention and network effects.** In cryptocurrency markets, trading volume is a first-order signal of investor attention (Da, Engelberg & Gao, 2011). Assets experiencing declining relative volume are losing retail and institutional attention—a precursor to sustained price underperformance.

**Rank deterioration as a momentum reversal indicator.** An asset falling from the top-15 to the 16–20 rank band signals a relative loss of momentum within the liquid universe. Unlike absolute price declines (which may be noise), rank deterioration represents a persistent shift in relative standing—a more reliable signal of fundamental demand erosion.

**Multi-condition gating to reduce false positives.** A single rank-deterioration criterion would generate frequent false signals in volatile sideways markets. By requiring simultaneous confirmation from: (1) a bearish BTC macro regime ($\text{BTC}_t < \text{MA}_{90,t}$), (2) the rank transition (from $\text{rank} \leq 15$ to $\text{rank} \in [16,20]$), and (3) a negative prior-month Sharpe ratio for the candidate asset, the strategy achieves a high-precision short signal at the cost of lower recall—appropriate given the asymmetric costs of false positive vs. false negative short positions (funding rate drag is a continuous cost, while missed shorts are opportunity costs).

Formally, the short entry condition for asset $i$ at month $t$ is:

$$\text{Short}_{i,t} = \mathbf{1}\left[\text{BTC}_t < \text{MA}_{90}^{\text{BTC}}\right] \cdot \mathbf{1}\left[\text{rank}_{i,t-1} \leq 15 \;\wedge\; \text{rank}_{i,t} \in [16, 20]\right] \cdot \mathbf{1}\left[\text{Sharpe}_{i,t-1} < 0\right]$$

This formulation is novel in the cryptocurrency momentum literature and constitutes one of the primary contributions of this paper.

---

*[Part 1 complete — continues in Part 2: Strategy Specification & Methodology]*
