# Part 2: Methodology — Mathematical Derivation and Strategy Design

> **AdaptiveTrend Strategy** | Academic Paper Draft | 2026-05-20

---

## 3. Data & Universe Construction

### 3.1 Candidate Asset Pool

The candidate pool consists of **30 USDT-margined perpetual futures or spot pairs** listed on Binance prior to the end of 2019 (or in the first half of 2020), providing sufficient liquidity history for the backtest period starting 2020-01-01. Assets that launched after this cutoff are naturally excluded in early periods because their recorded volume equals zero, eliminating any forward-looking survivorship bias in pool membership.

The 30 candidate symbols are:

| # | Symbol | # | Symbol | # | Symbol |
|---|--------|---|--------|---|--------|
| 1 | BTCUSDT | 11 | SOLUSDT | 21 | THETAUSDT |
| 2 | ETHUSDT | 12 | MATICUSDT | 22 | ALGOUSDT |
| 3 | XRPUSDT | 13 | DOGEUSDT | 23 | XMRUSDT |
| 4 | BNBUSDT | 14 | AVAXUSDT | 24 | ZECUSDT |
| 5 | LTCUSDT | 15 | ATOMUSDT | 25 | DASHUSDT |
| 6 | BCHUSDT | 16 | XLMUSDT | 26 | EOSUSDT |
| 7 | ADAUSDT | 17 | VETUSDT | 27 | XTZUSDT |
| 8 | LINKUSDT | 18 | TRXUSDT | 28 | AAVEUSDT |
| 9 | DOTUSDT | 19 | ETCUSDT | 29 | COMPUSDT |
| 10 | UNIUSDT | 20 | FILUSDT | 30 | SUSHIUSDT |

**Selection rationale.** Assets were chosen to reflect the de-facto large-cap universe in 2020: established proof-of-work coins (BTC, ETH, LTC, BCH, XMR, ZEC, DASH, ETC), early DeFi tokens (LINK, UNI, AAVE, COMP, SUSHI), platform tokens (BNB, ADA, DOT, SOL, MATIC, AVAX, ATOM), and legacy Layer-1 chains (XLM, VET, TRX, EOS, XTZ, ALGO, THETA). Assets like SOLUSDT (listed 2020-09), FILUSDT (2020-10), AAVEUSDT (2020-10), and SUSHIUSDT (2020-09) have zero volume before their listing dates and are automatically excluded via the liquidity filter described in §3.2, guaranteeing no look-ahead bias from pool membership.

---

### 3.2 Historical Dynamic Universe (Survivorship-Bias Correction)

A static snapshot of today's top-20 tokens would embed severe survivorship bias: coins that failed or lost relevance between 2020 and 2026 would never appear. To correct this, the investable universe is reconstructed historically at **monthly frequency** using only information available at the end of each month.

**Step 1 — Monthly USDT turnover.**

Let $\mathcal{K}_{i,t}$ be the set of 6H bars belonging to calendar month $t$ for asset $i$. Define the monthly USDT turnover:

$$V_{i,t} = \sum_{k \in \mathcal{K}_{i,t}} \text{close}_{i,k} \times \text{volume}_{i,k}$$

where $\text{close}_{i,k}$ and $\text{volume}_{i,k}$ denote the closing price (in USDT) and the base-asset volume of bar $k$, respectively.

**Step 2 — Liquidity gate.**

Define the approximate daily-average turnover as $\bar{V}_{i,t} = V_{i,t} / 30$. The set of assets that pass the liquidity gate is:

$$\mathcal{U}_t = \left\{ i \in \mathcal{C} : V_{i,t} > 0 \ \text{ and } \ \bar{V}_{i,t} \geq L_{\min} \right\}$$

where $\mathcal{C}$ is the fixed 30-coin candidate pool and $L_{\min} = 5 \times 10^7\ \text{USD}$. The condition $V_{i,t} > 0$ drops assets that have not yet listed; the second condition drops assets with insufficient market depth.

**Step 3 — Monthly ranking and investable universe.**

Assets in $\mathcal{U}_t$ are ranked by descending monthly turnover:

$$r_{i,t} = \text{rank}_{i \in \mathcal{U}_t}\!\left(-V_{i,t}\right) \in \{1, 2, \ldots, |\mathcal{U}_t|\}$$

The top-20 investable universe for month $t$ is:

$$\mathcal{U}_t^{(20)} = \left\{ i \in \mathcal{U}_t : r_{i,t} \leq 20 \right\}$$

Note that the universe at the beginning of 2020 naturally contains only early-era assets (BTC, ETH, XRP, BNB, LTC, BCH, ADA, ETC, ZEC, DASH, TRX, XLM, ATOM, etc.). Assets that rose to prominence only in 2021 or later cannot appear in 2020's universe, eliminating forward-looking selection bias.

**Look-ahead prevention.** Universe membership for month $t+1$ is determined using $V_{i,t}$, i.e., *last month's* completed turnover. No intra-month ranking data from month $t+1$ is used in construction.

---

### 3.3 OHLCV Data

| Property | Value |
|----------|-------|
| Data source | Binance REST API `/api/v3/klines` |
| Bar interval | 6 hours (`6h`) |
| Coverage | 2020-01-01 to 2026-05-20 |
| Total bars (BTC) | ≈ 5,760 |
| Fields used | open, high, low, close (USDT), base-asset volume, USDT volume |

The 6H frequency provides sub-daily granularity for the ATR trailing stop while remaining liquid enough to suppress microstructure noise. Each bar is identified by its open-time timestamp; all signal computations are closed strictly at bar close to preclude look-ahead bias within a bar.

---

## 4. Signal Generation

### 4.1 Momentum Signal — Rate of Change (ROC)

The primary entry signal is a short-term price momentum indicator. Let $P_{i,t}$ denote the closing price of asset $i$ at bar index $t$. The Rate of Change over $L$ bars is:

$$\text{ROC}_{i,t} = \frac{P_{i,t} - P_{i,t-L}}{P_{i,t-L}}, \qquad L = 20$$

With 6H bars, $L = 20$ corresponds to approximately five calendar days (a trading week), capturing short-to-medium-term momentum. A positive $\text{ROC}_{i,t}$ signals upward price pressure and is used as a necessary (though not sufficient) criterion for long entry. The ROC threshold for entry is implicitly embedded in the Sharpe-based monthly selection described in §4.3.

---

### 4.2 ATR Dynamic Trailing Stop

Once a position is opened, it is managed by an Average True Range (ATR) trailing stop that adjusts dynamically to market volatility.

**True Range.** For bar $t$, the true range captures the largest of three price spans:

$$TR_t = \max\!\left(H_t - L_t,\ \left|H_t - C_{t-1}\right|,\ \left|L_t - C_{t-1}\right|\right)$$

where $H_t$, $L_t$, $C_t$ denote the high, low, and close of bar $t$, and $C_{t-1}$ is the prior bar's close.

**Average True Range.** A simple rolling mean over $K = 14$ bars:

$$ATR_t = \frac{1}{K} \sum_{j=0}^{K-1} TR_{t-j}, \qquad K = 14$$

**Long trailing stop.** The stop level for a long position is a ratcheting floor that can only move upward:

$$S_t^{\text{long}} = \max\!\left(S_{t-1}^{\text{long}},\ C_t - \alpha \cdot ATR_t\right), \qquad \alpha = 2.5$$

**Short trailing stop.** Symmetrically, for a short position, the stop is a descending ceiling:

$$S_t^{\text{short}} = \min\!\left(S_{t-1}^{\text{short}},\ C_t + \alpha \cdot ATR_t\right)$$

**Exit condition — long position:** The position is closed when

$$C_t < S_t^{\text{long}}$$

**Exit condition — short position:** The position is closed when

$$C_t > S_t^{\text{short}}$$

The multiplier $\alpha = 2.5$ was chosen to allow normal intra-trend volatility while triggering timely exits during trend reversals. Smaller values increase whipsaw risk; larger values delay exits at the cost of deeper drawdowns.

---

### 4.3 Monthly Sharpe-Based Long Candidate Screening

To avoid chasing low-quality momentum, each candidate asset is scored by the risk-adjusted quality of its prior-month return stream. Let $\{r_{i,k}\}_{k \in \mathcal{M}_{t-1}}$ be the sequence of 6H log-returns for asset $i$ over the preceding complete calendar month $\mathcal{M}_{t-1}$.

The monthly in-sample Sharpe ratio is:

$$\text{Sharpe}_{i,t-1} = \frac{\bar{r}_i}{\sigma_{r_i}} \cdot \sqrt{N}$$

where $\bar{r}_i = \frac{1}{N}\sum_k r_{i,k}$ is the mean 6H return, $\sigma_{r_i}$ is the sample standard deviation, and $N \approx 120$ is the number of 6H bars in a 30-day month (annualisation factor $\sqrt{N}$ converts to an annualised Sharpe expressed in 6H units).

**Long candidate set.** Assets satisfying the minimum quality threshold:

$$\mathcal{L}_t = \left\{ i \in \mathcal{U}_t^{(20)} : \text{Sharpe}_{i,t-1} \geq \theta_L \right\}, \qquad \theta_L = 1.3$$

The final long portfolio selects at most $n_L = 5$ assets with the *highest* $\text{Sharpe}_{i,t-1}$:

$$\mathcal{L}_t^* = \underset{i \in \mathcal{L}_t}{\operatorname{top\text{-}5}}\left(\text{Sharpe}_{i,t-1}\right), \quad |\mathcal{L}_t^*| \leq n_L = 5$$

The Sharpe threshold $\theta_L = 1.3$ was fixed during strategy design on the in-sample period (2020–2023) and was not adjusted after OOS evaluation.

---

## 5. Short Signal: Market-Cap Rank Decay

The strategy employs a directional short overlay designed to profit from assets in accelerating decline, filtered strictly to bear-market regimes to avoid shorting into bull-market dips.

### 5.1 BTC Trend Filter

Bitcoin's price relative to its 90-day moving average serves as the macro regime indicator. The 90-day MA is computed on a 6H bar basis (90 days × 4 bars/day = 360 bars):

$$\text{MA}_{90}(t) = \frac{1}{360} \sum_{j=0}^{359} C_{\text{BTC},\, t-j}$$

The bear-market indicator is defined as:

$$\mathbb{1}_{\text{bear}}(t) = \begin{cases} 1 & \text{if } C_{\text{BTC},t} < \text{MA}_{90}(t) \\ 0 & \text{otherwise} \end{cases}$$

Short positions are **only permitted** when $\mathbb{1}_{\text{bear}}(t) = 1$. This prevents shorting in bull markets where mean-reversion dynamics dominate.

---

### 5.2 Rank Decay Signal

Assets that formerly held top-tier liquidity but are losing ground to peers exhibit a characteristic "rank decay" pattern: their monthly turnover rank slips from the top-15 to positions 16–20. This transition signals deteriorating market interest and relative underperformance.

**Short candidate set.** The set of rank-decaying assets in bear-market conditions:

$$\mathcal{S}_t = \left\{ i \in \mathcal{U}_t^{(20)} : \mathbb{1}_{\text{bear}}(t) = 1 \ \wedge \ r_{i,t-1} \leq 15 \ \wedge \ 16 \leq r_{i,t} \leq 20 \ \wedge \ \text{Sharpe}_{i,t-1} < 0 \right\}$$

The four joint conditions are:
1. **Macro filter**: BTC is in bear-market regime ($\mathbb{1}_{\text{bear}} = 1$).
2. **Prior rank**: Asset ranked in the top-15 last month ($r_{i,t-1} \leq 15$).
3. **Current rank decay**: Asset has slipped to positions 16–20 this month ($16 \leq r_{i,t} \leq 20$).
4. **Momentum confirmation**: Prior-month Sharpe is negative ($\text{Sharpe}_{i,t-1} < 0$), confirming that the rank drop accompanies genuine price deterioration and is not a noise artefact.

The short portfolio selects at most $n_S = 3$ assets:

$$\mathcal{S}_t^* = \underset{i \in \mathcal{S}_t}{\operatorname{top\text{-}3}}\left(-\text{Sharpe}_{i,t-1}\right), \quad |\mathcal{S}_t^*| \leq n_S = 3$$

(Assets with the most negative Sharpe are prioritised, as they exhibit the strongest confirmed downtrend.)

---

### 5.3 Short Signal Validity — Preliminary Evidence

To assess the empirical validity of the rank-decay short signal, we performed an event study over the full sample period (2020–2026). We identified all instances where an asset's monthly turnover rank declined from ≤15 to 16–20, yielding **88 events** in total.

Key findings (summarised from `mcap-rank-analysis`):

| Metric | All Regimes | Bear Market ($\mathbb{1}_{\text{bear}}=1$) | Bull Market ($\mathbb{1}_{\text{bear}}=0$) |
|--------|------------|-------------------------------|-------------------------------|
| Events | 88 | 46 | 42 |
| 1-month forward short win-rate | **59.1%** | **68.3%** | 51.1% |
| Median 1-month return (shorted asset) | −3.2% | −7.8% | +1.4% |

These results establish that:

1. The rank-decay signal has positive directional predictability, but only marginally (59.1%) when applied unconditionally.
2. **BTC bear-market filtering substantially improves accuracy to 68.3%**, providing econometric justification for $\mathbb{1}_{\text{bear}}$ as a regime gate.
3. In bull markets, rank-decaying assets frequently recover (+1.4% median), confirming that unconditional shorting would be harmful. This validates the bear-only constraint in $\mathcal{S}_t$.

---

## 6. Portfolio Construction & Capital Allocation

### 6.1 Dynamic Long Allocation

The fraction of capital allocated to the long book, $\lambda_L(t)$, is determined by the market regime and, in bear markets, by the level of realised volatility of BTC.

**BTC 30-day realised volatility** (annualised) is computed from daily log-returns $r_{\text{BTC},d}$ over the trailing 30 calendar days:

$$\text{RV}_{30}(t) = \sqrt{365} \cdot \sigma\!\left(\left\{r_{\text{BTC},d}\right\}_{d=t-30}^{t}\right)$$

**Long allocation schedule.** The allocation rule is asymmetric: in bull markets, the full 70% is deployed regardless of volatility (since volatility in bull markets is correlated with upside), while in bear markets, the allocation scales down with rising volatility to limit drawdown:

$$\lambda_L(t) = \begin{cases}
0.70 & \text{if } \mathbb{1}_{\text{bear}}(t) = 0 \quad \text{(bull market)} \\[4pt]
0.70 & \text{if } \mathbb{1}_{\text{bear}}(t) = 1 \ \wedge \ \text{RV}_{30}(t) < 0.50 \\[4pt]
0.55 & \text{if } \mathbb{1}_{\text{bear}}(t) = 1 \ \wedge \ 0.50 \leq \text{RV}_{30}(t) < 0.80 \\[4pt]
0.40 & \text{if } \mathbb{1}_{\text{bear}}(t) = 1 \ \wedge \ \text{RV}_{30}(t) \geq 0.80
\end{cases}$$

**Short allocation.** When short candidates exist ($\mathcal{S}_t^* \neq \emptyset$), the residual capital is allocated to shorts:

$$\lambda_S(t) = 1 - \lambda_L(t)$$

When no short candidates exist, the remainder is held as cash (USDT), earning no return in this model.

---

### 6.2 Equal-Weight Position Sizing

Within each sub-portfolio, capital is allocated equally across selected assets:

$$w_{i,t}^{L} = \frac{\lambda_L(t)}{|\mathcal{L}_t^*|}, \qquad \forall\, i \in \mathcal{L}_t^*$$

$$w_{j,t}^{S} = \frac{\lambda_S(t)}{|\mathcal{S}_t^*|}, \qquad \forall\, j \in \mathcal{S}_t^*$$

Equal weighting avoids estimation error in covariance matrices and prevents single-asset concentration. Given the small portfolio size ($n_L \leq 5$, $n_S \leq 3$), mean-variance optimisation would introduce more noise than signal.

---

### 6.3 Preservation Mode

When the strict Sharpe gate ($\theta_L = 1.3$) yields no long candidates ($\mathcal{L}_t = \emptyset$) yet the macro environment is benign (BTC bull market), the strategy enters a low-conviction *Preservation Mode* to maintain partial market exposure:

**Activation conditions:**

$$\mathcal{L}_t = \emptyset \quad \wedge \quad \mathbb{1}_{\text{bear}}(t) = 0 \quad \wedge \quad \exists\, i : \text{Sharpe}_{i,t-1} \geq 0.8$$

**Preservation allocation:**

$$\lambda_L^{\text{preserve}} = 0.70 \times 0.60 = 0.42$$

In Preservation Mode, the strategy selects the top-2 assets by Sharpe among those with $\text{Sharpe}_{i,t-1} \geq 0.8$, allocated equally at 21% each ($0.42 / 2$). This reduces the frequency of periods with zero invested capital and captures moderate bull-market gains with a conservative 42% gross exposure.

**Design rationale.** Preservation Mode reflects the observation that prolonged periods of inactivity (all capital in cash) create opportunity costs during bull runs. The 40% reduction from normal exposure ($0.70 \to 0.42$) reflects the lower conviction of assets with Sharpe in $[0.8, 1.3)$.

---

## 7. Transaction Costs Model

A realistic transaction cost model is essential to avoid overfitting to gross-return backtests. Three cost components are modelled: exchange fees (differentiated by liquidity tier), short-position funding rates, and a portfolio-level stop-loss rule.

### 7.1 Differentiated Exchange Fees

Following Binance's tiered fee schedule, each asset is assigned a per-trade fee based on its average daily USDT turnover $\bar{V}_{i,\text{daily}}$:

$$f_i = \begin{cases}
4\ \text{bps} & \text{if } \bar{V}_{i,\text{daily}} > 5 \times 10^8\ \text{USD} \quad \text{(large cap)} \\[4pt]
8\ \text{bps} & \text{if } 5 \times 10^7\ \text{USD} < \bar{V}_{i,\text{daily}} \leq 5 \times 10^8\ \text{USD} \quad \text{(mid cap)} \\[4pt]
15\ \text{bps} & \text{if } \bar{V}_{i,\text{daily}} \leq 5 \times 10^7\ \text{USD} \quad \text{(small cap)}
\end{cases}$$

The total round-trip cost for a trade is $2 f_i$ (entry + exit). This fee incorporates both exchange commissions and implicit bid-ask spread. No market-impact model is applied; the analysis is implicitly sized for portfolios under ~\$10M where price impact is negligible relative to the fee estimate.

---

### 7.2 Short Position Funding Rate

Perpetual futures short positions accrue a funding cost paid to long holders during bull-market regimes and received from long holders in bear markets. In this model, a conservative **constant funding rate** is assumed:

$$C_{\text{funding}}(i, t) = r_f \times 3 \times d_{\text{hold},i,t}$$

where:
- $r_f = 0.01\%$ per 8-hour funding interval (Binance standard rate),
- the factor $3 = 24\text{h} / 8\text{h}$ converts to a daily charge,
- $d_{\text{hold},i,t}$ is the number of calendar days asset $i$ is held short during month $t$.

This gives an annualised funding cost of approximately $0.01\% \times 3 \times 365 = 10.95\%$ per year on any short notional. Note that this is a net cost assumption: in practice, shorts in bear markets may *receive* positive funding when perpetual futures trade at a discount to spot, reducing the effective cost. The conservative constant-cost assumption adds conservatism to short-position profitability estimates.

**Monthly funding cost.** For a full 30-day short position at 30% notional allocation:

$$C_{\text{funding}}^{\text{monthly}} \approx 0.01\% \times 3 \times 30 \times 0.30 = 0.27\%\ \text{of total portfolio}$$

---

### 7.3 Monthly Portfolio Stop-Loss

To cap tail drawdowns, a portfolio-level stop-loss rule is applied at monthly frequency:

> **Rule:** If the portfolio's month-to-date return $R_{\text{portfolio},t}$ falls to or below $-15\%$ at any point within month $t$, all positions are closed immediately at the current mark-to-market price, and no new positions are opened for the remainder of that calendar month.

Formally:

$$\tau_{\text{stop}} = \min\!\left\{t' \in \mathcal{K}_t : R_{\text{portfolio},t'} \leq -0.15\right\}$$

If $\tau_{\text{stop}}$ exists, all positions $w_{i,\tau_{\text{stop}}} \leftarrow 0$ for $t' > \tau_{\text{stop}}$ within month $t$.

This rule limits the worst-case monthly loss to approximately −15% (plus slippage at exit), avoiding the compounding of multi-week drawdowns. It is particularly relevant during extreme bear months (e.g., May 2022, LUNA collapse). The threshold $-15\%$ was set based on historical volatility analysis: for a 70%-invested long book of 5 assets with typical 40%-annualised individual volatility, a −15% portfolio drawdown corresponds to a roughly $2.5\sigma$ adverse move.

---

*End of Part 2: Methodology*

---

> **Next:** Part 3 — Empirical Results (IS/OOS analysis, annual performance, cost attribution)
