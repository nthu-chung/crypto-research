# crypto-research

Systematic crypto trading strategy research using multi-agent AI loops (Research + Judge).

## Repository Structure

```
crypto-research/
├── mvrv-zscore/          # MVRV Z-Score on-chain valuation strategy (v1~v4)
│   ├── reports/          # Research reports & Judge feedback (v1~v4)
│   ├── scripts/          # Backtest scripts
│   ├── results/          # JSON result files
│   └── charts/           # Performance charts
├── funding-rate/         # Funding rate cross-sectional strategy
├── mom-reversal/         # Momentum reversal strategy
├── on-chain-flow/        # On-chain flow strategy
├── altcoin-rotation/     # Altcoin rotation strategy
├── cross-market/         # Cross-market research
├── regime-detection/     # Market regime detection
├── ensemble/             # Ensemble strategy
├── trend-filter/         # Trend filter strategy
├── vol-target/           # Volatility targeting strategy
├── multifactor/          # Multi-factor model results
├── btc-analysis/         # BTC cycle analysis
├── notebooks/            # Jupyter notebooks (WIP)
├── new-listings/         # New listings research (WIP)
├── microstructure/       # Microstructure research (WIP)
├── scripts/              # Shared utility scripts
└── references/           # Agent configs, data sources, state schema
```

## Current Status

| Strategy | Latest Version | Judge Score | Status |
|----------|---------------|-------------|--------|
| MVRV Z-Score | v4 | 79/100 | Research complete |
| Funding Rate | v1 | — | Research complete |
| Mom Reversal | v1 | — | Research complete |
| On-Chain Flow | v1 | — | Research complete |

## Research Loop

Each strategy is researched using an automated Research + Judge loop:
1. **Research Agent** builds and backtests a strategy
2. **Judge Agent** scores it (0-100) and provides detailed feedback
3. Loop continues until score ≥ 80 or max rounds reached
