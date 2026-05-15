# crypto-research

A living research repository for crypto market microstructure, alpha discovery, and quantitative strategies.

> Research partner: **Binance AI Pro** 🦞  
> Owner: nthu-chung

---

## Philosophy

> "We don't just run strategies — we discover market regularities."

Research flows: **Observe → Quantify → Validate → Strategize**

---

## Repository Structure

```
crypto-research/
├── README.md
├── funding-rate/           # Funding rate alpha research
│   ├── README.md
│   ├── data/               # Parquet files (gitignored, too large)
│   ├── fetch_data_v3.py    # Data fetcher (2023-01 onwards, 5 symbols)
│   ├── analyze.py          # Core statistical analysis
│   └── results/
│       └── results.csv     # Regime → forward return summary
├── microstructure/         # Order book, bid-ask, liquidation research (TBD)
├── new-listings/           # New coin price discovery patterns (TBD)
└── notebooks/              # Ad-hoc exploration (TBD)
```

---

## Research Index

| # | Topic | Status | Key Finding |
|---|-------|--------|-------------|
| 1 | [Funding Rate Alpha](./funding-rate/README.md) | ✅ First pass complete | Low funding → bullish reversal (BTC p=0.004) |

---

## How We Work

- All research lives in this repo
- Code + results + interpretation together
- Data files (parquet) gitignored — re-fetch with provided scripts
- Every significant finding gets a README
