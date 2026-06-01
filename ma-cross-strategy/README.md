# MA Cross Strategy

Moving Average golden/death cross strategy built on `cyqnt-trd==0.1.9.dev6` blocks engine.

## Structure

```
ma-cross-strategy/
├── strategies/
│   └── ma_cross_v1.py       # Strategy core (make_signals)
└── scripts/
    ├── run_strategy.py       # Unified entry: backtest / paper / live
    ├── signal_executor.py    # trades.jsonl watcher → binance-cli orders
    ├── run_paper_daemon.sh   # Paper daemon launcher (shell)
    ├── setup_env.py          # Sync TOOLS.md → .env
    └── curl_monitor.sh       # HTTP trigger helpers
```

## Strategy Logic

- **Long**: fast SMA (20) crosses above slow SMA (60) — golden cross
- **Short**: fast SMA (20) crosses below slow SMA (60) — death cross
- **No-lookahead**: signals use `shift(1)`, confirmed at bar close, executed at next bar open

## Signal Consistency (backtest ≈ paper ≈ live)

All three modes call the **same** `make_signals()` function from `ma_cross_v1.py`.
Only the broker layer differs:

| Mode | Broker |
|------|--------|
| backtest | none (local parquet) |
| paper | PaperBrokerAdapter (simulated) |
| live | paper daemon + signal_executor → binance-cli |

## Requirements

```
cyqnt-trd==0.1.9.dev6
pandas
```

Install to local target:
```bash
pip install cyqnt-trd==0.1.9.dev6 --target ./venv-pip
```

## Usage

```bash
export PYTHONPATH=./venv-pip:.

# Backtest
python3.11 scripts/run_strategy.py --mode backtest --data-path data/BTCUSDT_1h.parquet

# Paper trade
python3.11 scripts/run_strategy.py --mode paper

# Live trade — dry-run first
python3.11 scripts/run_strategy.py --mode live --dry-run

# Live trade — real orders
python3.11 scripts/run_strategy.py --mode live --max-notional 200
```

## Setup

1. Add API keys to `TOOLS.md` under `## Binance API` block
2. Run `python3.11 scripts/setup_env.py` to sync to `.env`
3. Configure `binance-cli` profile: `binance-cli profile create --name mainnet --env prod`

## Safety Gates (live mode)

- `--dry-run`: prints binance-cli commands without submitting
- `--max-notional`: hard cap per order in USDT (default 200)
- `--notional-fraction`: fraction of available balance per trade (default 0.95)
- Zero-balance guard: skips open orders when USDT balance = 0
- Position conflict guard: checks existing position before placing order
