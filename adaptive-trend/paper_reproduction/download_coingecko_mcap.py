#!/usr/bin/env python3
"""
Slow, resumable CoinGecko historical market-cap downloader.

The free CoinGecko API rate limit is strict. This script downloads only a
small batch per run, writes every successful coin immediately, and can resume
later without repeating completed coins.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from reproduce_level1_futures import (
    CACHE,
    ROOT,
    base_from_symbol,
    get_candidate_symbols,
    load_coingecko_markets,
)


COINGECKO = "https://api.coingecko.com/api/v3"


def request_json(url: str, params: dict, attempts: int = 3) -> object | None:
    full_url = f"{url}?{urlencode(params)}"
    for attempt in range(attempts):
        try:
            with urlopen(full_url, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if "429" in str(exc):
                print(f"  rate limited; cooling down 90s")
                time.sleep(90)
                continue
            if attempt == attempts - 1:
                print(f"  request failed: {exc}")
                return None
            time.sleep(10 + attempt * 10)
    return None


def map_symbols(symbols: list[str]) -> tuple[dict[str, str], list[str]]:
    markets = load_coingecko_markets()
    by_symbol: dict[str, list[dict]] = {}
    for row in markets:
        by_symbol.setdefault(str(row.get("symbol", "")).upper(), []).append(row)

    mapped: dict[str, str] = {}
    misses: list[str] = []
    for symbol in symbols:
        base = base_from_symbol(symbol)
        candidates = by_symbol.get(base, [])
        if not candidates:
            misses.append(symbol)
            continue
        candidates = sorted(candidates, key=lambda r: r.get("market_cap") or 0, reverse=True)
        mapped[symbol] = candidates[0]["id"]

    (ROOT / "coingecko_symbol_mapping.json").write_text(json.dumps({
        "mapped": mapped,
        "misses": misses,
        "method": "highest current market cap among matching CoinGecko symbols",
    }, indent=2))
    return mapped, misses


def coin_path(symbol: str, coin_id: str) -> Path:
    return CACHE / f"coingecko_mcap_{symbol}_{coin_id}.csv.gz"


def is_done(symbol: str, coin_id: str) -> bool:
    path = coin_path(symbol, coin_id)
    if not path.exists():
        return False
    try:
        df = pd.read_csv(path)
        return len(df) > 10
    except Exception:
        return False


def download_coin(symbol: str, coin_id: str, start: str, end: str) -> bool:
    start_ts = int(pd.Timestamp(start, tz="UTC").timestamp())
    end_ts = int(pd.Timestamp(end, tz="UTC").timestamp())
    payload = request_json(f"{COINGECKO}/coins/{coin_id}/market_chart/range", {
        "vs_currency": "usd",
        "from": start_ts,
        "to": end_ts,
    })
    if not isinstance(payload, dict) or not payload.get("market_caps"):
        print(f"  no market_caps for {symbol}/{coin_id}")
        return False
    df = pd.DataFrame(payload["market_caps"], columns=["ts", "market_cap"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df.to_csv(coin_path(symbol, coin_id), index=False, compression="gzip")
    print(f"  saved {symbol}/{coin_id}: {len(df)} rows")
    return True


def build_matrix(max_symbols: int, start: str, end: str) -> Path:
    symbols = get_candidate_symbols(max_symbols)
    mapped, _ = map_symbols(symbols)
    series = {}
    for symbol, coin_id in mapped.items():
        path = coin_path(symbol, coin_id)
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["ts"])
        if df.empty:
            continue
        series[symbol] = df.set_index("ts")["market_cap"].resample("ME").last()
    out = CACHE / f"coingecko_historical_mcap_matrix_{max_symbols}.csv.gz"
    matrix = pd.DataFrame(series).fillna(0)
    matrix.reset_index(names="ts").to_csv(out, index=False, compression="gzip")
    print(f"matrix {out}: shape={matrix.shape}")
    return out


def run(args: argparse.Namespace) -> None:
    symbols = get_candidate_symbols(args.max_symbols)
    mapped, misses = map_symbols(symbols)
    print(f"mapped={len(mapped)} misses={len(misses)}")
    if misses:
        print(f"misses={misses[:25]}")

    pending = [(symbol, coin_id) for symbol, coin_id in mapped.items() if not is_done(symbol, coin_id)]
    print(f"pending={len(pending)} completed={len(mapped)-len(pending)}")

    if args.build_matrix_only:
        build_matrix(args.max_symbols, args.start, args.end)
        return

    downloaded = 0
    for symbol, coin_id in pending[:args.limit]:
        print(f"download {symbol}/{coin_id}")
        ok = download_coin(symbol, coin_id, args.start, args.end)
        if ok:
            downloaded += 1
        if downloaded < args.limit:
            print(f"  sleeping {args.sleep_seconds}s")
            time.sleep(args.sleep_seconds)

    build_matrix(args.max_symbols, args.start, args.end)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-symbols", type=int, default=180)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2024-12-31 23:59:59")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--sleep-seconds", type=float, default=75.0)
    parser.add_argument("--build-matrix-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
