#!/usr/bin/env python3
"""
Clean-room reproduction attempt for arXiv:2602.11708.

This is not the authors' implementation. It reconstructs the paper's core
claims from public Binance Futures data with strict no-lookahead timing:

- Binance USD-M perpetual futures, 6H bars
- Monthly universe construction using the previous month's quote volume
- Long candidates: highest-volume liquid contracts
- Short candidates: lowest-volume liquid contracts
- Per-symbol monthly parameter search on the previous month only
- Trade the next month using the selected parameters
- 70/30 long-short allocation, equal-weighted within each leg

Known approximation: the paper uses CoinGecko market cap and calibrated
5-minute/order-book slippage. This first pass uses quote volume as a public,
fully reproducible proxy.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

FAPI = "https://fapi.binance.com"
COINGECKO = "https://api.coingecko.com/api/v3"
START = "2021-01-01"
END = "2024-12-31 23:59:59"
INITIAL_CAPITAL = 10_000.0

LOOKBACK_GRID = [10, 20, 30]
ENTRY_GRID = [0.0, 0.005, 0.01]
ATR_GRID = [2.0, 2.5, 3.0]


def request_json(path: str, params: dict | None = None) -> object:
    params = params or {}
    url = f"{FAPI}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    for attempt in range(5):
        try:
            with urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if attempt == 4:
                raise RuntimeError(f"Request failed for {url}: {exc}") from exc
            time.sleep(2 + attempt * 2)
    return {}


def request_url_json(url: str, params: dict | None = None, rate_limit_sleep: float = 0.0) -> object:
    params = params or {}
    full_url = f"{url}?{urlencode(params)}" if params else url
    for attempt in range(8):
        try:
            with urlopen(full_url, timeout=45) as response:
                if rate_limit_sleep:
                    time.sleep(rate_limit_sleep)
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            wait = 60 if "429" in str(exc) else 3 + attempt * 3
            if attempt == 7:
                raise RuntimeError(f"Request failed for {full_url}: {exc}") from exc
            time.sleep(wait)
    return {}


def get_candidate_symbols(max_symbols: int) -> list[str]:
    info = request_json("/fapi/v1/exchangeInfo")
    symbols = [
        s for s in info["symbols"]
        if s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("status") == "TRADING"
    ]
    # Earliest-listed current contracts are the closest public proxy for the
    # paper's 150+ futures universe without delisted-symbol history.
    symbols.sort(key=lambda s: (s.get("onboardDate", 0), s["symbol"]))
    return [s["symbol"] for s in symbols[:max_symbols]]


def base_from_symbol(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    for prefix in ["1000000", "1000"]:
        if base.startswith(prefix):
            return base[len(prefix):]
    return base


def coingecko_markets_cache() -> Path:
    return CACHE / "coingecko_markets_top2500.json"


def load_coingecko_markets() -> list[dict]:
    path = coingecko_markets_cache()
    if path.exists():
        return json.loads(path.read_text())

    rows: list[dict] = []
    for page in range(1, 11):
        payload = request_url_json(f"{COINGECKO}/coins/markets", {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": page,
            "sparkline": "false",
        }, rate_limit_sleep=1.2)
        if not payload:
            break
        rows.extend(payload)
    path.write_text(json.dumps(rows, indent=2))
    return rows


def map_symbols_to_coingecko(symbols: list[str]) -> dict[str, str]:
    markets = load_coingecko_markets()
    by_symbol: dict[str, list[dict]] = {}
    for row in markets:
        by_symbol.setdefault(str(row.get("symbol", "")).upper(), []).append(row)

    mapping: dict[str, str] = {}
    misses: list[str] = []
    for symbol in symbols:
        base = base_from_symbol(symbol)
        candidates = by_symbol.get(base, [])
        if not candidates:
            misses.append(symbol)
            continue
        # Markets endpoint is already market-cap sorted, but sorting keeps this explicit.
        candidates = sorted(candidates, key=lambda r: r.get("market_cap") or 0, reverse=True)
        mapping[symbol] = candidates[0]["id"]

    (ROOT / "coingecko_symbol_mapping.json").write_text(json.dumps({
        "mapped": mapping,
        "misses": misses,
    }, indent=2))
    print(f"CoinGecko mapped={len(mapping)} misses={len(misses)}")
    if misses:
        print("  misses:", misses[:30])
    return mapping


def coingecko_market_cap_path(coin_id: str) -> Path:
    return CACHE / f"coingecko_mcap_{coin_id}.csv.gz"


def fetch_coingecko_monthly_mcap(coin_id: str, start: str, end: str) -> pd.Series | None:
    path = coingecko_market_cap_path(coin_id)
    if path.exists():
        df = pd.read_csv(path, parse_dates=["ts"])
        if not df.empty:
            return df.set_index("ts")["market_cap"].resample("ME").last()

    start_ts = int(pd.Timestamp(start, tz="UTC").timestamp())
    end_ts = int(pd.Timestamp(end, tz="UTC").timestamp())
    payload = request_url_json(f"{COINGECKO}/coins/{coin_id}/market_chart/range", {
        "vs_currency": "usd",
        "from": start_ts,
        "to": end_ts,
    }, rate_limit_sleep=1.5)
    market_caps = payload.get("market_caps") if isinstance(payload, dict) else None
    if not market_caps:
        return None
    df = pd.DataFrame(market_caps, columns=["ts", "market_cap"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms")
    df.to_csv(path, index=False, compression="gzip")
    return df.set_index("ts")["market_cap"].resample("ME").last()


def build_coingecko_mcap_df(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    matrix_path = CACHE / f"coingecko_mcap_matrix_{len(symbols)}.csv.gz"
    if matrix_path.exists():
        return pd.read_csv(matrix_path, parse_dates=["ts"]).set_index("ts")

    mapping = map_symbols_to_coingecko(symbols)
    series = {}
    for i, symbol in enumerate(symbols, 1):
        coin_id = mapping.get(symbol)
        if not coin_id:
            continue
        try:
            mcap = fetch_coingecko_monthly_mcap(coin_id, start, end)
        except Exception as exc:
            print(f"  CoinGecko failed {symbol}/{coin_id}: {exc}")
            mcap = None
        if mcap is not None and len(mcap) > 0:
            series[symbol] = mcap
        if i % 20 == 0 or i == len(symbols):
            print(f"  CoinGecko mcap {i}/{len(symbols)} usable={len(series)}")
    df = pd.DataFrame(series).fillna(0)
    df.reset_index(names="ts").to_csv(matrix_path, index=False, compression="gzip")
    return df


def build_current_coingecko_mcap_df(symbols: list[str], template_index: pd.Index) -> pd.DataFrame:
    markets = load_coingecko_markets()
    by_id = {row["id"]: row for row in markets}
    mapping = map_symbols_to_coingecko(symbols)
    values = {}
    for symbol, coin_id in mapping.items():
        values[symbol] = float(by_id.get(coin_id, {}).get("market_cap") or 0)
    return pd.DataFrame({symbol: pd.Series(value, index=template_index) for symbol, value in values.items()}).fillna(0)


def cache_path(symbol: str, interval: str) -> Path:
    return CACHE / f"{symbol}_{interval}.csv.gz"


def read_cached(symbol: str, interval: str) -> pd.DataFrame | None:
    path = cache_path(symbol, interval)
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["ts"])
    return df.set_index("ts").sort_index()


def write_cached(symbol: str, interval: str, rows: list[list]) -> None:
    with gzip.open(cache_path(symbol, interval), "wt", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ts", "open", "high", "low", "close", "volume", "quote_vol"])
        for row in rows:
            writer.writerow([
                pd.to_datetime(row[0], unit="ms"),
                row[1], row[2], row[3], row[4], row[5], row[7],
            ])


def fetch_klines(symbol: str, interval: str, start: str, end: str) -> pd.DataFrame | None:
    cached = read_cached(symbol, interval)
    requested_end = pd.Timestamp(end)
    if cached is not None and len(cached) > 50 and cached.index.max() >= requested_end - pd.Timedelta(days=1):
        return cached

    fetch_start = cached.index.max() + pd.Timedelta(milliseconds=1) if cached is not None and len(cached) else pd.Timestamp(start)
    start_ts = int(fetch_start.tz_localize("UTC").timestamp() * 1000) if fetch_start.tzinfo is None else int(fetch_start.timestamp() * 1000)
    end_ts = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    rows: list[list] = []
    while start_ts <= end_ts:
        payload = request_json("/fapi/v1/klines", {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 1500,
        })
        if not payload or isinstance(payload, dict):
            break
        rows.extend(payload)
        if len(payload) < 1500:
            break
        start_ts = int(payload[-1][0]) + 1
        time.sleep(0.05)

    if not rows:
        return cached
    new_df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    new_df["ts"] = pd.to_datetime(new_df["open_time"], unit="ms")
    new_df = new_df.set_index("ts")[["open", "high", "low", "close", "volume", "quote_vol"]]
    combined = pd.concat([cached, new_df]) if cached is not None else new_df
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.reset_index().to_csv(cache_path(symbol, interval), index=False, compression="gzip")
    return read_cached(symbol, interval)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ["open", "high", "low", "close", "volume", "quote_vol"]:
        df[col] = df[col].astype(float)
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    df["tr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(14).mean()
    for lookback in LOOKBACK_GRID:
        df[f"roc_{lookback}"] = df["close"].pct_change(lookback)
    return df


def trade_symbol(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, side: str, lookback: int, entry: float, atr_mult: float, fee: float) -> tuple[float, int]:
    month = df[(df.index >= start) & (df.index <= end)]
    if len(month) < max(lookback + 2, 20):
        return 0.0, 0

    position = 0
    entry_price = 0.0
    stop = 0.0
    capital = 1.0
    trades = 0
    roc_col = f"roc_{lookback}"

    for bar in month.itertuples():
        close = float(bar.close)
        atr = 0.0 if math.isnan(bar.atr) else float(bar.atr)
        roc = getattr(bar, roc_col)
        if math.isnan(roc):
            continue

        if position == 0:
            if side == "long" and roc > entry:
                position = 1
                entry_price = close
                stop = close - atr_mult * atr
                capital *= 1 - fee
                trades += 1
            elif side == "short" and roc < -entry:
                position = -1
                entry_price = close
                stop = close + atr_mult * atr
                capital *= 1 - fee
                trades += 1
            continue

        if position == 1:
            stop = max(stop, close - atr_mult * atr)
            if close < stop or roc <= 0:
                capital *= 1 + (close / entry_price - 1)
                capital *= 1 - fee
                position = 0
        elif position == -1:
            stop = min(stop, close + atr_mult * atr)
            if close > stop or roc >= 0:
                capital *= 1 + (entry_price / close - 1)
                capital *= 1 - fee
                position = 0

    if position == 1:
        close = float(month["close"].iloc[-1])
        capital *= 1 + (close / entry_price - 1)
        capital *= 1 - fee
    elif position == -1:
        close = float(month["close"].iloc[-1])
        capital *= 1 + (entry_price / close - 1)
        capital *= 1 - fee

    return capital - 1, trades


def sharpe_from_returns(returns: list[float]) -> float:
    if len(returns) < 4:
        return -999.0
    arr = np.array(returns)
    std = arr.std(ddof=1)
    if std == 0:
        return -999.0
    return float(arr.mean() / std * math.sqrt(len(arr)))


def optimize_params(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, side: str, fee: float) -> tuple[dict, float]:
    best = {"lookback": 20, "entry": 0.005, "atr_mult": 2.5}
    best_score = -999.0
    # Score on weekly slices inside the previous month to avoid a single-return Sharpe.
    period_end = end + pd.Timedelta(seconds=1)
    weeks = list(pd.date_range(start, period_end, freq="7D"))
    if not weeks or weeks[-1] < period_end:
        weeks.append(period_end)
    if len(weeks) < 2:
        return best, best_score
    for lookback in LOOKBACK_GRID:
        for entry in ENTRY_GRID:
            for atr_mult in ATR_GRID:
                returns = []
                for i in range(len(weeks) - 1):
                    ret, _ = trade_symbol(df, weeks[i], weeks[i + 1] - pd.Timedelta(seconds=1), side, lookback, entry, atr_mult, fee)
                    returns.append(ret)
                score = sharpe_from_returns(returns)
                if score > best_score:
                    best_score = score
                    best = {"lookback": lookback, "entry": entry, "atr_mult": atr_mult}
    return best, best_score


def metrics(monthly_returns: list[float]) -> dict:
    arr = np.array(monthly_returns)
    n = len(arr)
    total = float(np.prod(1 + arr) - 1)
    cagr = (1 + total) ** (12 / n) - 1
    std = arr.std(ddof=1)
    sharpe = arr.mean() / std * math.sqrt(12) if std else 0.0
    curve = np.cumprod(1 + arr)
    dd = (curve - np.maximum.accumulate(curve)) / np.maximum.accumulate(curve)
    max_dd = float(dd.min())
    return {
        "cagr": round(cagr * 100, 2),
        "sharpe": round(float(sharpe), 2),
        "max_dd": round(max_dd * 100, 2),
        "calmar": round((cagr / abs(max_dd)) if max_dd else 0, 2),
        "total_return": round(total * 100, 2),
        "win_rate": round(float((arr > 0).mean()) * 100, 1),
        "months": n,
    }


def slice_metrics(history: list[dict], start: str, end: str) -> dict:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    returns = [
        float(row["return"])
        for row in history
        if start_ts <= pd.Timestamp(row["date"]) <= end_ts
    ]
    return metrics(returns) if returns else {}


def run(args: argparse.Namespace) -> dict:
    symbols = get_candidate_symbols(args.max_symbols)
    print(f"Candidate symbols: {len(symbols)}")

    data = {}
    for i, symbol in enumerate(symbols, 1):
        df = fetch_klines(symbol, args.interval, args.start, args.end)
        if df is not None and len(df) > 200:
            data[symbol] = add_indicators(df)
        if i % 25 == 0 or i == len(symbols):
            print(f"  loaded {i}/{len(symbols)} symbols; usable={len(data)}")

    vol_df = pd.DataFrame({s: df["quote_vol"].resample("ME").sum() for s, df in data.items()}).fillna(0)
    mcap_df = None
    if args.universe_source == "coingecko":
        mcap_df = build_coingecko_mcap_df(list(data.keys()), args.start, args.end)
    elif args.universe_source == "coingecko-current":
        mcap_df = build_current_coingecko_mcap_df(list(data.keys()), vol_df.index)
    all_months = list(pd.date_range(args.trade_start, args.trade_end, freq="ME"))
    partial_end = pd.Timestamp(args.trade_end)
    if args.include_partial and (not all_months or all_months[-1].normalize() != partial_end.normalize()):
        all_months.append(partial_end)

    capital = INITIAL_CAPITAL
    history = []
    for month_end in all_months:
        month_start = month_end - pd.offsets.MonthBegin(1)
        info_month = month_start - pd.offsets.MonthEnd(1)
        opt_start = month_start - pd.DateOffset(months=1)
        opt_end = month_start - pd.Timedelta(seconds=1)

        rank_df = mcap_df if mcap_df is not None else vol_df
        available = rank_df.index[rank_df.index <= info_month]
        if len(available) == 0:
            history.append({"date": str(month_end.date()), "return": 0.0, "capital": capital, "mode": "no_universe"})
            continue
        ranked = rank_df.loc[available[-1]]
        if mcap_df is not None:
            liquid = vol_df.loc[vol_df.index[vol_df.index <= info_month][-1]]
            ranked = ranked[(ranked > 0) & (liquid / 30 >= args.min_daily_volume)]
        else:
            ranked = ranked[ranked / 30 >= args.min_daily_volume]
        active = ranked.sort_values(ascending=False)
        if len(active) < args.long_k + args.short_k:
            history.append({"date": str(month_end.date()), "return": 0.0, "capital": capital, "mode": "thin_universe"})
            continue

        long_pool = active.head(args.long_k).index.tolist()
        if args.short_pool_mode == "tail":
            short_pool = active.tail(args.short_k).index.tolist()
        else:
            short_pool = active.iloc[args.long_k:args.long_k + args.short_k].index.tolist()

        long_selected = []
        short_selected = []
        for side, pool, threshold, selected in [
            ("long", long_pool, args.long_sr, long_selected),
            ("short", short_pool, args.short_sr, short_selected),
        ]:
            scored = []
            for symbol in pool:
                params, score = optimize_params(data[symbol], opt_start, opt_end, side, args.fee_bps / 10000)
                if score >= threshold:
                    scored.append((symbol, score, params))
            scored.sort(key=lambda item: item[1], reverse=True)
            selected.extend(scored[:args.max_positions])

        long_returns = []
        short_returns = []
        long_trades = 0
        short_trades = 0
        for symbol, score, params in long_selected:
            ret, trades = trade_symbol(data[symbol], month_start, month_end, "long", params["lookback"], params["entry"], params["atr_mult"], args.fee_bps / 10000)
            long_returns.append(ret)
            long_trades += trades
        for symbol, score, params in short_selected:
            ret, trades = trade_symbol(data[symbol], month_start, month_end, "short", params["lookback"], params["entry"], params["atr_mult"], args.fee_bps / 10000)
            short_returns.append(ret)
            short_trades += trades

        long_ret = float(np.mean(long_returns)) if long_returns else 0.0
        short_ret = float(np.mean(short_returns)) if short_returns else 0.0
        month_ret = (0.70 if long_returns else 0.0) * long_ret + (0.30 if short_returns else 0.0) * short_ret
        capital *= 1 + month_ret
        history.append({
            "date": str(month_end.date()),
            "info_month": str(available[-1].date()),
            "return": month_ret,
            "capital": capital,
            "longs": [x[0] for x in long_selected],
            "shorts": [x[0] for x in short_selected],
            "long_trades": long_trades,
            "short_trades": short_trades,
        })
        print(f"{month_end:%Y-%m}: ret={month_ret*100:6.2f}% longs={len(long_returns)} shorts={len(short_returns)} cap={capital:,.0f}")

    monthly_returns = [row["return"] for row in history]
    result = {
        "config": vars(args),
        "universe_symbols": len(symbols),
        "usable_symbols": len(data),
        "metrics": metrics(monthly_returns),
        "period_metrics": {
            "is": slice_metrics(history, args.is_start, args.is_end),
            "oos": slice_metrics(history, args.oos_start, args.oos_end),
        },
        "active_months": sum(bool(row.get("longs") or row.get("shorts")) for row in history),
        "avg_trades_per_month": round(float(np.mean([row.get("long_trades", 0) + row.get("short_trades", 0) for row in history])), 2),
        "history": history,
        "known_gaps_vs_paper": [
            "Uses quote volume instead of CoinGecko market capitalization.",
            "Uses current Binance trading symbols; delisted futures are unavailable through exchangeInfo.",
            "Uses constant fee/slippage bps and does not include historical funding rates yet.",
            "Reconstructed entry/exit rules from paper description; authors did not publish code.",
        ],
    }
    out = ROOT / args.output
    out.write_text(json.dumps(result, indent=2))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-symbols", type=int, default=180)
    parser.add_argument("--interval", default="6h")
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--trade-start", default="2022-01-31")
    parser.add_argument("--trade-end", default="2024-12-31")
    parser.add_argument("--include-partial", action="store_true")
    parser.add_argument("--is-start", default="2022-01-31")
    parser.add_argument("--is-end", default="2024-12-31")
    parser.add_argument("--oos-start", default="2025-01-31")
    parser.add_argument("--oos-end", default="2026-04-30")
    parser.add_argument("--long-k", type=int, default=15)
    parser.add_argument("--short-k", type=int, default=15)
    parser.add_argument("--short-pool-mode", choices=["tail", "next"], default="tail")
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--long-sr", type=float, default=1.3)
    parser.add_argument("--short-sr", type=float, default=1.7)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--min-daily-volume", type=float, default=5e6)
    parser.add_argument("--output", default="results_level1_futures.json")
    parser.add_argument("--universe-source", choices=["volume", "coingecko", "coingecko-current"], default="volume")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args())["metrics"], indent=2))
