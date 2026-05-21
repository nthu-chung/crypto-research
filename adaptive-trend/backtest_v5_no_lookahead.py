#!/usr/bin/env python3
"""
AdaptiveTrend v5 no-lookahead validation.

This script keeps the v4 strategy rules but shifts all monthly information
sets so a month is traded only with data known before that month starts.
It is intentionally separate from v1-v4 to preserve the research audit trail.
"""

from __future__ import annotations

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


WORK_DIR = Path(__file__).resolve().parent
CACHE_DIR = WORK_DIR / "cache_v5"
CACHE_DIR.mkdir(exist_ok=True)

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT", "BCHUSDT", "ADAUSDT", "LINKUSDT",
    "DOTUSDT", "UNIUSDT", "SOLUSDT", "MATICUSDT", "DOGEUSDT", "AVAXUSDT", "ATOMUSDT",
    "XLMUSDT", "VETUSDT", "TRXUSDT", "ETCUSDT", "FILUSDT", "THETAUSDT", "ALGOUSDT",
    "XMRUSDT", "ZECUSDT", "DASHUSDT", "EOSUSDT", "XTZUSDT", "AAVEUSDT", "COMPUSDT", "SUSHIUSDT",
]

START = "2019-12-01"
END = "2026-04-30 23:59:59"
INITIAL_CAPITAL = 10_000.0
MAX_LONG = 5
MAX_SHORT = 3
SHARPE_LONG = 1.3
SHARPE_PRESERVE = 0.8
MONTHLY_STOP = -0.15
FUNDING_RATE_8H = 0.0001
DAILY_FUNDING = FUNDING_RATE_8H * 3


def request_json(url: str, params: dict) -> list:
    full_url = f"{url}?{urlencode(params)}"
    for attempt in range(5):
        try:
            with urlopen(full_url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if attempt == 4:
                raise RuntimeError(f"Request failed for {full_url}: {exc}") from exc
            time.sleep(2 + attempt * 2)
    return []


def cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}_6h.csv.gz"


def read_cached(symbol: str) -> pd.DataFrame | None:
    path = cache_path(symbol)
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["ts"])
    df = df.set_index("ts").sort_index()
    return df


def write_cached(symbol: str, rows: list[list]) -> None:
    path = cache_path(symbol)
    with gzip.open(path, "wt", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ts", "open", "high", "low", "close", "volume", "quote_vol"])
        for row in rows:
            writer.writerow([
                pd.to_datetime(row[0], unit="ms"),
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[7],
            ])


def fetch_6h_klines(symbol: str) -> pd.DataFrame | None:
    cached = read_cached(symbol)
    if cached is not None and len(cached) > 100:
        return cached

    url = "https://api.binance.com/api/v3/klines"
    start_ts = int(pd.Timestamp(START).timestamp() * 1000)
    end_ts = int(pd.Timestamp(END).timestamp() * 1000)
    all_rows: list[list] = []

    while start_ts <= end_ts:
        payload = request_json(url, {
            "symbol": symbol,
            "interval": "6h",
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 1000,
        })
        if not payload or isinstance(payload, dict):
            break
        all_rows.extend(payload)
        if len(payload) < 1000:
            break
        start_ts = int(payload[-1][0]) + 1
        time.sleep(0.12)

    if not all_rows:
        return None
    write_cached(symbol, all_rows)
    return read_cached(symbol)


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    df["tr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(14).mean()
    return df


def get_monthly_universe(vol_df: pd.DataFrame, info_month: pd.Timestamp, top_n: int = 20) -> tuple[list[str], pd.Series]:
    available = vol_df.index[vol_df.index <= info_month]
    if len(available) == 0:
        return [], pd.Series(dtype=float)
    row = vol_df.loc[available[-1]]
    active = row[row > 0]
    active = active[active / 30 > 5e7]
    ranked = active.nlargest(top_n)
    return ranked.index.tolist(), ranked


def get_btc_state(btc: pd.DataFrame, btc_rv30_daily: pd.Series, decision_date: pd.Timestamp) -> tuple[bool, float]:
    available = btc.index[btc.index < decision_date]
    if len(available) == 0:
        return False, 0.5
    decision_bar = available[-1]
    bear = bool(btc.loc[decision_bar, "bear_market"])

    available_daily = btc_rv30_daily.index[btc_rv30_daily.index < decision_date]
    rv30 = float(btc_rv30_daily.loc[available_daily[-1]]) if len(available_daily) else 0.5
    if math.isnan(rv30):
        rv30 = 0.5
    return bear, rv30


def get_long_allocation(bear: bool, rv30: float) -> float:
    if not bear:
        return 0.70
    if rv30 < 0.50:
        return 0.70
    if rv30 < 0.80:
        return 0.55
    return 0.40


def get_fee(monthly_vol_usd: float) -> float:
    daily_vol = monthly_vol_usd / 30
    if daily_vol > 5e8:
        return 0.0004
    if daily_vol > 5e7:
        return 0.0008
    return 0.0015


def month_return(df: pd.DataFrame, month_start: pd.Timestamp, month_end: pd.Timestamp, fee: float, is_short: bool = False) -> float | None:
    month_data = df[(df.index >= month_start) & (df.index <= month_end)]
    if len(month_data) < 2:
        return None
    entry = float(month_data["close"].iloc[0])
    exit_price = float(month_data["close"].iloc[-1])

    if not is_short:
        max_price = entry
        for bar in month_data.itertuples():
            max_price = max(max_price, float(bar.close))
            atr = 0.0 if np.isnan(bar.atr) else float(bar.atr)
            if bar.close < max_price - 2.5 * atr and bar.Index != month_data.index[0]:
                exit_price = float(bar.close)
                break
        return (exit_price - entry) / entry - 2 * fee

    min_price = entry
    for bar in month_data.itertuples():
        min_price = min(min_price, float(bar.close))
        atr = 0.0 if np.isnan(bar.atr) else float(bar.atr)
        if bar.close > min_price + 2.5 * atr and bar.Index != month_data.index[0]:
            exit_price = float(bar.close)
            break
    days = (month_data.index[-1] - month_data.index[0]).days
    return (entry - exit_price) / entry - 2 * fee - DAILY_FUNDING * days


def compute_metrics(df: pd.DataFrame) -> dict:
    if len(df) < 2:
        return {}
    returns = df["return"].to_numpy()
    n = len(returns)
    total = float(np.prod(1 + returns) - 1)
    cagr = (1 + total) ** (12 / n) - 1
    std = np.std(returns, ddof=1)
    sharpe = np.mean(returns) / std * np.sqrt(12) if std > 0 else 0
    cumulative = np.cumprod(1 + returns)
    max_dd = ((cumulative - np.maximum.accumulate(cumulative)) / np.maximum.accumulate(cumulative)).min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    return {
        "cagr": round(cagr * 100, 2),
        "sharpe": round(float(sharpe), 2),
        "max_dd": round(float(max_dd) * 100, 2),
        "calmar": round(float(calmar), 2),
        "win_rate": round(float((returns > 0).mean()) * 100, 1),
        "n_months": int(n),
        "total_return": round(total * 100, 2),
    }


def run() -> dict:
    print("Loading Binance 6H data...")
    data: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        df = fetch_6h_klines(symbol)
        if df is not None and len(df) > 100:
            for col in ["open", "high", "low", "close", "volume", "quote_vol"]:
                df[col] = df[col].astype(float)
            data[symbol] = df
            print(f"  {symbol}: {len(df)} bars, {df.index[0].date()} to {df.index[-1].date()}")
        else:
            print(f"  {symbol}: no usable data")

    monthly_vol = {symbol: df["quote_vol"].resample("ME").sum() for symbol, df in data.items()}
    vol_df = pd.DataFrame(monthly_vol).fillna(0)
    signals = {symbol: compute_signals(df) for symbol, df in data.items()}

    btc = data["BTCUSDT"].copy()
    btc["ma90"] = btc["close"].rolling(360).mean()
    btc["bear_market"] = btc["close"] < btc["ma90"]
    btc_daily = btc["close"].resample("D").last()
    btc_rv30_daily = btc_daily.pct_change().rolling(30).std() * np.sqrt(365)

    capital = INITIAL_CAPITAL
    portfolio_history: list[dict] = []
    all_months = pd.date_range("2020-01-31", "2026-04-30", freq="ME")

    for i, month_end in enumerate(all_months):
        month_start = month_end - pd.offsets.MonthBegin(1)

        # Core v5 correction: trade month m using only data known before m starts.
        info_month = all_months[i - 1] if i > 0 else pd.Timestamp("2019-12-31")
        prev_info_month = all_months[i - 2] if i > 1 else pd.Timestamp("2019-11-30")
        current_universe, current_vol_ranked = get_monthly_universe(vol_df, info_month)
        _, prev_vol_ranked = get_monthly_universe(vol_df, prev_info_month)

        if not current_universe:
            portfolio_history.append({"date": month_end, "capital": capital, "return": 0.0, "mode": "no_universe"})
            continue

        btc_bear, rv30 = get_btc_state(btc, btc_rv30_daily, month_start)
        long_alloc = get_long_allocation(btc_bear, rv30)

        sharpe_scores: dict[str, float] = {}
        prev_start = month_start - pd.DateOffset(months=1)
        for symbol in current_universe:
            if symbol not in signals:
                continue
            symbol_df = signals[symbol]
            returns = symbol_df[(symbol_df.index >= prev_start) & (symbol_df.index < month_start)]["close"].pct_change().dropna()
            if len(returns) < 10 or returns.std() == 0:
                continue
            sharpe_scores[symbol] = float(returns.mean() / returns.std() * np.sqrt(len(returns)))

        if not sharpe_scores:
            portfolio_history.append({"date": month_end, "capital": capital, "return": 0.0, "mode": "no_signals"})
            continue

        sharpe_series = pd.Series(sharpe_scores)
        long_candidates = sharpe_series[sharpe_series >= SHARPE_LONG].nlargest(MAX_LONG).index.tolist()
        mode = "normal"
        if not long_candidates and not btc_bear:
            preserve = sharpe_series[sharpe_series >= SHARPE_PRESERVE].nlargest(2).index.tolist()
            if preserve:
                long_candidates = preserve
                long_alloc *= 0.60
                mode = "preservation"

        short_candidates: list[str] = []
        if btc_bear and len(prev_vol_ranked) > 0:
            curr_list = current_vol_ranked.index.tolist()
            prev_list = prev_vol_ranked.index.tolist()
            for symbol in curr_list[15:20]:
                if symbol in prev_list[:15] and sharpe_scores.get(symbol, 0) < 0:
                    short_candidates.append(symbol)
            short_candidates = short_candidates[:MAX_SHORT]

        def known_fee(symbol: str) -> float:
            if symbol in vol_df.columns and info_month in vol_df.index:
                return get_fee(float(vol_df.loc[info_month, symbol]))
            return get_fee(1e8)

        long_returns = {
            symbol: ret
            for symbol in long_candidates
            if (ret := month_return(signals[symbol], month_start, month_end, known_fee(symbol))) is not None
        }
        short_returns = {
            symbol: ret
            for symbol in short_candidates
            if (ret := month_return(signals[symbol], month_start, month_end, known_fee(symbol), True)) is not None
        }

        long_ret = float(np.mean(list(long_returns.values()))) if long_returns else 0.0
        short_ret = float(np.mean(list(short_returns.values()))) if short_returns else 0.0
        long_weight = long_alloc if long_candidates else 0.0
        short_weight = 0.30 if short_candidates else 0.0
        port_ret = long_weight * long_ret + short_weight * short_ret
        if port_ret < MONTHLY_STOP:
            port_ret = MONTHLY_STOP

        capital *= 1 + port_ret
        portfolio_history.append({
            "date": month_end,
            "capital": capital,
            "return": port_ret,
            "long_symbols": long_candidates,
            "short_symbols": short_candidates,
            "info_month": info_month.strftime("%Y-%m"),
            "btc_bear": btc_bear,
            "rv30": round(rv30, 3),
            "long_alloc": long_weight,
            "mode": mode,
        })

    perf_df = pd.DataFrame(portfolio_history)
    perf_df["date"] = pd.to_datetime(perf_df["date"])
    perf_df = perf_df.set_index("date")

    yearly = {}
    for year in range(2020, 2027):
        year_df = perf_df[perf_df.index.year == year]
        if len(year_df) == 0:
            continue
        returns = year_df["return"].to_numpy()
        total = np.prod(1 + returns) - 1
        std = np.std(returns, ddof=1)
        sharpe = np.mean(returns) / std * np.sqrt(12) if std > 0 else 0
        yearly[str(year)] = {"return": round(float(total) * 100, 1), "sharpe": round(float(sharpe), 2)}

    results = {
        "full": compute_metrics(perf_df),
        "is": compute_metrics(perf_df[perf_df.index.year <= 2023]),
        "oos": compute_metrics(perf_df[perf_df.index.year >= 2024]),
        "yearly": yearly,
        "short_months": int(sum(bool(item.get("short_symbols")) for item in portfolio_history)),
        "preservation_months": int(sum(item.get("mode") == "preservation" for item in portfolio_history)),
        "total_months": len(portfolio_history),
        "notes": [
            "Month m universe, rank-decay, and fee tier use month m-1 data.",
            "Rank-decay short uses the known m-2 to m-1 ranking transition and trades in month m.",
            "BTC regime and RV30 use bars strictly before month_start.",
        ],
    }

    with (WORK_DIR / "results_v5_no_lookahead.json").open("w") as fh:
        json.dump(results, fh, indent=2)
    perf_df.reset_index().to_json(WORK_DIR / "portfolio_v5_no_lookahead.json", orient="records", indent=2, date_format="iso")

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    run()
