# MVRV + Trend Filter Backtest Results
*Generated: 2026-05-19*

## Strategy Descriptions
1. **S1: MVRV v2 + EMA200** — MVRV zone position × 0.3 when price < EMA200
2. **S2: MVRV v2 + Monthly Trend** — MVRV zone position × 0.3 when 2 consecutive down months
3. **S3: MVRV v2 + EMA200 + ADX** — ADX>25 bull=full MVRV, bear=20%, ranging=50%
4. **S4: MVRV Z-Score P90 + EMA200** — Z-Score thresholds at P85/P90 + EMA200 filter

## IS Calibration Parameters
- MVRV Percentiles (IS 2012-2019): P20=1.06, P40=1.44, P60=1.85, P80=2.64, P90=3.37
- Z-Score Thresholds (IS): P85=0.276, P90=0.412, P95=0.758

## Full Period Results
| Strategy | Ann Return | Sharpe | Max DD |
|----------|-----------|--------|--------|
| S1_MVRV_EMA200 | 33.0% | 1.08 | -60.3% |
| S2_MVRV_Monthly | 64.3% | 1.78 | -36.3% |
| S3_MVRV_EMA200_ADX | 30.7% | 1.08 | -58.3% |
| S4_ZScore_EMA200 | 32.6% | 1.11 | -55.8% |
| BuyAndHold | 137.4% | 1.53 | -92.7% |

## Period Breakdown

### IS 2012-2019
| Strategy | Ann Return | Sharpe | Max DD |
|----------|-----------|--------|--------|
| S1_MVRV_EMA200 | 54.5% | 1.59 | -44.5% |
| S2_MVRV_Monthly | 80.9% | 1.96 | -35.1% |
| S3_MVRV_EMA200_ADX | 48.3% | 1.51 | -46.8% |
| S4_ZScore_EMA200 | 52.7% | 1.57 | -43.6% |

### OOS 2020-2026
| Strategy | Ann Return | Sharpe | Max DD |
|----------|-----------|--------|--------|
| S1_MVRV_EMA200 | 21.3% | 0.98 | -32.9% |
| S2_MVRV_Monthly | 47.1% | 1.65 | -33.2% |
| S3_MVRV_EMA200_ADX | 22.6% | 1.12 | -27.0% |
| S4_ZScore_EMA200 | 20.5% | 0.95 | -32.6% |

### 2022 Bear
| Strategy | Ann Return | Sharpe | Max DD |
|----------|-----------|--------|--------|
| S1_MVRV_EMA200 | -19.5% | -1.21 | -22.1% |
| S2_MVRV_Monthly | -21.3% | -0.53 | -33.2% |
| S3_MVRV_EMA200_ADX | -11.1% | -0.72 | -20.0% |
| S4_ZScore_EMA200 | -17.5% | -1.44 | -19.4% |

### 2024 Bull
| Strategy | Ann Return | Sharpe | Max DD |
|----------|-----------|--------|--------|
| S1_MVRV_EMA200 | 35.8% | 1.81 | -11.6% |
| S2_MVRV_Monthly | 52.0% | 2.35 | -8.8% |
| S3_MVRV_EMA200_ADX | 20.8% | 1.16 | -13.3% |
| S4_ZScore_EMA200 | 38.0% | 1.63 | -14.8% |

## Key Findings
- **Best Sharpe overall**: S2_MVRV_Monthly (Sharpe=1.78)
- **Smallest Max DD**: S2_MVRV_Monthly (MaxDD=-36.3%)

### 2022 Bear Market Protection
- S1_MVRV_EMA200: MaxDD=-22.1%, Sharpe=-1.21
- S2_MVRV_Monthly: MaxDD=-33.2%, Sharpe=-0.53
- S3_MVRV_EMA200_ADX: MaxDD=-20.0%, Sharpe=-0.72
- S4_ZScore_EMA200: MaxDD=-19.4%, Sharpe=-1.44

### 2024 Bull Market Participation
- S1_MVRV_EMA200: AnnReturn=35.8%, Sharpe=1.81
- S2_MVRV_Monthly: AnnReturn=52.0%, Sharpe=2.35
- S3_MVRV_EMA200_ADX: AnnReturn=20.8%, Sharpe=1.16
- S4_ZScore_EMA200: AnnReturn=38.0%, Sharpe=1.63

### Z-Score P90 Analysis (S4 vs S1)
- S1 (MVRV v2+EMA200): Sharpe=1.08, MaxDD=-60.3%
- S4 (Z-Score P90+EMA200): Sharpe=1.11, MaxDD=-55.8%
- Z-Score P90 improves Sharpe by 0.03 vs v2

## Conclusion
⚠️ No strategy fully meets Sharpe>1 AND MaxDD<-20%. Closest: **S1_MVRV_EMA200, S2_MVRV_Monthly, S3_MVRV_EMA200_ADX, S4_ZScore_EMA200**

- **S1_MVRV_EMA200**: ✅ Sharpe=1.08>1 | ❌ MaxDD=-60.3%
- **S2_MVRV_Monthly**: ✅ Sharpe=1.78>1 | ❌ MaxDD=-36.3%
- **S3_MVRV_EMA200_ADX**: ✅ Sharpe=1.08>1 | ❌ MaxDD=-58.3%
- **S4_ZScore_EMA200**: ✅ Sharpe=1.11>1 | ❌ MaxDD=-55.8%

## Charts
- Equity curves: `openclaw-media/trend_filter_equity_curves.png`
- Period heatmap: `openclaw-media/trend_filter_period_heatmap.png`
