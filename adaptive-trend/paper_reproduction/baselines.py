#!/usr/bin/env python3
"""
Baseline strategies for the AdaptiveTrend clean-room reproduction.

Uses the same Binance Futures 6H cache and no-lookahead monthly timing as
`reproduce_level1_futures.py`.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from reproduce_level1_futures import add_indicators, fetch_klines, get_candidate_symbols, metrics


ROOT = Path(__file__).resolve().parent


def month_asset_return(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, fee: float = 0.0) -> float | None:
    month = df[(df.index >= start) & (df.index <= end)]
    if len(month) < 2:
        return None
    raw = float(month["close"].iloc[-1] / month["close"].iloc[0] - 1)
    return raw - 2 * fee if fee else raw


def prior_return(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    window = df[(df.index >= start) & (df.index <= end)]
    if len(window) < 2:
        return None
    return float(window["close"].iloc[-1] / window["close"].iloc[0] - 1)


def load_data(max_symbols: int, interval: str, start: str, end: str) -> dict[str, pd.DataFrame]:
    symbols = get_candidate_symbols(max_symbols)
    data = {}
    for i, symbol in enumerate(symbols, 1):
        df = fetch_klines(symbol, interval, start, end)
        if df is not None and len(df) > 200:
            data[symbol] = add_indicators(df)
        if i % 50 == 0 or i == len(symbols):
            print(f"  loaded {i}/{len(symbols)} symbols; usable={len(data)}")
    return data


def top_volume_symbols(vol_df: pd.DataFrame, info_month: pd.Timestamp, n: int, min_daily_volume: float) -> list[str]:
    available = vol_df.index[vol_df.index <= info_month]
    if len(available) == 0:
        return []
    row = vol_df.loc[available[-1]]
    active = row[row / 30 >= min_daily_volume].sort_values(ascending=False)
    return active.head(n).index.tolist()


def run(args: argparse.Namespace) -> dict:
    data = load_data(args.max_symbols, args.interval, args.start, args.end)
    vol_df = pd.DataFrame({s: df["quote_vol"].resample("ME").sum() for s, df in data.items()}).fillna(0)
    all_months = pd.date_range("2022-01-31", "2024-12-31", freq="ME")
    fee = args.fee_bps / 10000

    returns = {
        "btc_bh": [],
        "ew_top20_bh": [],
        "tsmom_1m_top20": [],
        "tsmom_3m_top20": [],
    }
    history = []

    for month_end in all_months:
        month_start = month_end - pd.offsets.MonthBegin(1)
        info_month = month_start - pd.offsets.MonthEnd(1)
        top20 = top_volume_symbols(vol_df, info_month, args.top_n, args.min_daily_volume)

        btc_ret = month_asset_return(data["BTCUSDT"], month_start, month_end, fee=0)
        returns["btc_bh"].append(btc_ret if btc_ret is not None else 0.0)

        ew_rets = [ret for symbol in top20 if (ret := month_asset_return(data[symbol], month_start, month_end, fee=fee)) is not None]
        returns["ew_top20_bh"].append(float(np.mean(ew_rets)) if ew_rets else 0.0)

        tsmom_returns = {}
        for lookback_months, key in [(1, "tsmom_1m_top20"), (3, "tsmom_3m_top20")]:
            signal_start = month_start - pd.DateOffset(months=lookback_months)
            signal_end = month_start - pd.Timedelta(seconds=1)
            legs = []
            for symbol in top20:
                sig = prior_return(data[symbol], signal_start, signal_end)
                actual = month_asset_return(data[symbol], month_start, month_end, fee=fee)
                if sig is None or actual is None or sig == 0:
                    continue
                legs.append(math.copysign(actual, sig))
            tsmom_returns[key] = float(np.mean(legs)) if legs else 0.0
            returns[key].append(tsmom_returns[key])

        history.append({
            "date": str(month_end.date()),
            "top20": top20,
            "btc_bh": returns["btc_bh"][-1],
            "ew_top20_bh": returns["ew_top20_bh"][-1],
            "tsmom_1m_top20": returns["tsmom_1m_top20"][-1],
            "tsmom_3m_top20": returns["tsmom_3m_top20"][-1],
        })
        print(
            f"{month_end:%Y-%m}: BTC={returns['btc_bh'][-1]*100:6.2f}% "
            f"EW={returns['ew_top20_bh'][-1]*100:6.2f}% "
            f"TS1={returns['tsmom_1m_top20'][-1]*100:6.2f}% "
            f"TS3={returns['tsmom_3m_top20'][-1]*100:6.2f}%"
        )

    result = {
        "config": vars(args),
        "metrics": {name: metrics(vals) for name, vals in returns.items()},
        "history": history,
    }
    (ROOT / args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result["metrics"], indent=2))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-symbols", type=int, default=180)
    parser.add_argument("--interval", default="6h")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2024-12-31 23:59:59")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--min-daily-volume", type=float, default=5e6)
    parser.add_argument("--output", default="results_baselines.json")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
