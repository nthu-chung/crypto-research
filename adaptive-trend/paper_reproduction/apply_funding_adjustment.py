#!/usr/bin/env python3
"""
Apply an approximate Binance Futures funding adjustment to reproduction results.

This is a post-hoc approximation: it assumes selected monthly futures positions
are held for the whole month. It is deliberately conservative as an audit tool:
if funding cannot close the gap to the paper under this favorable simplification,
the headline Sharpe remains unsupported.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
from pathlib import Path

import pandas as pd

from reproduce_level1_futures import CACHE, ROOT, metrics, request_json


def funding_path(symbol: str) -> Path:
    return CACHE / f"{symbol}_funding.csv.gz"


def fetch_funding(symbol: str, start: str, end: str) -> pd.Series:
    path = funding_path(symbol)
    if path.exists():
        df = pd.read_csv(path, parse_dates=["ts"])
        if df.empty:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.dropna(subset=["ts"])
        if df.empty:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        return df.set_index("ts")["funding_rate"].astype(float).sort_index()

    start_ts = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ts = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    rows = []
    while start_ts <= end_ts:
        payload = request_json("/fapi/v1/fundingRate", {
            "symbol": symbol,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 1000,
        })
        if not payload or isinstance(payload, dict):
            break
        rows.extend(payload)
        if len(payload) < 1000:
            break
        start_ts = int(payload[-1]["fundingTime"]) + 1
        time.sleep(0.08)

    with gzip.open(path, "wt", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ts", "funding_rate"])
        for row in rows:
            writer.writerow([pd.to_datetime(row["fundingTime"], unit="ms"), row["fundingRate"]])

    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms")
    df["funding_rate"] = df["fundingRate"].astype(float)
    return df.set_index("ts")["funding_rate"].sort_index()


def funding_sum(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if series.empty:
        return 0.0
    window = series[(series.index >= start) & (series.index <= end)]
    return float(window.sum()) if len(window) else 0.0


def run(args: argparse.Namespace) -> dict:
    source_path = ROOT / args.input
    result = json.loads(source_path.read_text())
    history = result["history"]
    symbols = sorted({s for row in history for s in row.get("longs", []) + row.get("shorts", [])})
    funding = {}
    for i, symbol in enumerate(symbols, 1):
        funding[symbol] = fetch_funding(symbol, args.start, args.end)
        if i % 20 == 0 or i == len(symbols):
            print(f"  funding {i}/{len(symbols)}")

    adjusted_returns = []
    adjusted_history = []
    for row in history:
        month_end = pd.Timestamp(row["date"])
        month_start = month_end - pd.offsets.MonthBegin(1)
        base_ret = float(row["return"])
        adjustment = 0.0
        longs = row.get("longs", [])
        shorts = row.get("shorts", [])
        if longs:
            long_weight = 0.70 / len(longs)
            for symbol in longs:
                # Positive funding: longs pay. Negative funding: longs receive.
                adjustment += long_weight * (-funding_sum(funding[symbol], month_start, month_end))
        if shorts:
            short_weight = 0.30 / len(shorts)
            for symbol in shorts:
                # Positive funding: shorts receive. Negative funding: shorts pay.
                adjustment += short_weight * funding_sum(funding[symbol], month_start, month_end)
        adjusted = base_ret + adjustment
        adjusted_returns.append(adjusted)
        adjusted_row = dict(row)
        adjusted_row["funding_adjustment"] = adjustment
        adjusted_row["return_with_funding"] = adjusted
        adjusted_history.append(adjusted_row)

    output = {
        "source": args.input,
        "assumption": "Selected monthly long/short positions are held for the full month for funding adjustment.",
        "base_metrics": result["metrics"],
        "funding_adjusted_metrics": metrics(adjusted_returns),
        "history": adjusted_history,
    }
    (ROOT / args.output).write_text(json.dumps(output, indent=2))
    print(json.dumps({
        "base": output["base_metrics"],
        "funding_adjusted": output["funding_adjusted_metrics"],
    }, indent=2))
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2024-12-31 23:59:59")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
