#!/usr/bin/env python3
"""
AdaptiveTrend v1 Backtest - Clean Version
Uses return-series simulation approach for correctness.
"""

import requests
import pandas as pd
import numpy as np
import time
import json
import os
from datetime import datetime

WORKDIR = "/root/.openclaw/workspace/crypto-research/adaptive-trend"
os.makedirs(WORKDIR, exist_ok=True)
CACHE_DIR = os.path.join(WORKDIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

STABLECOINS = {
    'USDCUSDT','BUSDUSDT','TUSDUSDT','USDTUSDT','FDUSDUSDT','DAIUSDT',
    'EURUSDT','GBPUSDT','AEURUSDT','BRLLUSDT','PYUSDUSDT','USDSUSDT',
    'USDPUSDT','USSBUSDT','FRAXUSDT','SUSDUSDT','MUSDUSDT','USD1USDT',
    'RLUSDUSDT','PAXGUSDT'  # gold-backed, not equity crypto
}

def get_top20():
    resp = requests.get('https://api.binance.com/api/v3/ticker/24hr', timeout=30)
    tickers = pd.DataFrame(resp.json())
    tickers = tickers[tickers['symbol'].str.endswith('USDT')]
    tickers['quoteVolume'] = tickers['quoteVolume'].astype(float)
    tickers = tickers[~tickers['symbol'].isin(STABLECOINS)]
    tickers = tickers[~tickers['symbol'].str.contains('UP|DOWN|BULL|BEAR|3L|3S|5L|5S', regex=True)]
    # Filter out non-ASCII (e.g. Chinese characters)
    tickers = tickers[tickers['symbol'].str.match(r'^[A-Z0-9]+$')]
    top20 = tickers.nlargest(25, 'quoteVolume')['symbol'].tolist()[:20]
    print(f"Universe ({len(top20)}): {top20}")
    return top20

def fetch_klines(symbol, interval='6h', start_str='2020-01-01', end_str='2026-05-20', limit=1000):
    url = 'https://api.binance.com/api/v3/klines'
    start_ts = int(pd.Timestamp(start_str).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_str).timestamp() * 1000)
    all_klines = []
    while True:
        params = {'symbol': symbol, 'interval': interval,
                  'startTime': start_ts, 'endTime': end_ts, 'limit': limit}
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                print(f"  Rate limited, sleep 10s")
                time.sleep(10)
                continue
            if r.status_code != 200:
                break
            data = r.json()
            if not data or isinstance(data, dict):
                break
            all_klines.extend(data)
            if len(data) < limit:
                break
            start_ts = data[-1][0] + 1
            if start_ts >= end_ts:
                break
            time.sleep(0.12)
        except Exception as e:
            print(f"  Error {symbol}: {e}")
            break
    if not all_klines:
        return None
    df = pd.DataFrame(all_klines, columns=[
        'open_time','open','high','low','close','volume',
        'close_time','quote_vol','trades','tbbase','tbquote','ignore'])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    return df.set_index('open_time')[['open','high','low','close','volume']]

def load_or_fetch(symbol):
    path = os.path.join(CACHE_DIR, f"{symbol}_6h.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)
    print(f"  Fetching {symbol}...")
    df = fetch_klines(symbol)
    if df is not None and len(df) > 100:
        df.to_parquet(path)
    return df

def compute_atr(df, k=14):
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(k).mean()

def sharpe_6h(rets, periods_per_year=1460):
    """Annualized Sharpe from 6H returns. 1460 = 4*365."""
    if len(rets) < 5 or rets.std() == 0:
        return 0.0
    return rets.mean() / rets.std() * np.sqrt(periods_per_year)

def run_backtest():
    # ---- Load data ----
    universe = get_top20()
    # Ensure BTC is always available for benchmark
    if 'BTCUSDT' not in universe:
        universe.append('BTCUSDT')

    data = {}
    for sym in universe:
        path = os.path.join(CACHE_DIR, f"{sym}_6h.parquet")
        if os.path.exists(path):
            df = pd.read_parquet(path)
        else:
            df = load_or_fetch(sym)
        if df is not None and len(df) > 500:
            data[sym] = df
            print(f"  {sym}: {len(df)} bars {df.index[0].date()}–{df.index[-1].date()}")
        else:
            print(f"  Skip {sym}: too short")

    trading_syms = [s for s in universe if s in data and s != 'BTCUSDT']
    print(f"\n{len(trading_syms)} tradeable symbols, BTC for benchmark")

    # ---- Build aligned price matrix ----
    close = pd.DataFrame({s: data[s]['close'] for s in trading_syms + ['BTCUSDT']})
    close = close.sort_index()
    high_df  = pd.DataFrame({s: data[s]['high'] for s in trading_syms})
    low_df   = pd.DataFrame({s: data[s]['low']  for s in trading_syms})

    # 6H returns (forward: return[t] = close[t]/close[t-1] - 1)
    rets = close[trading_syms].pct_change()

    # ---- ATR Trailing Stop signals ----
    # For each symbol compute ATR
    atr_df = pd.DataFrame(index=close.index)
    for s in trading_syms:
        h = data[s]['high'].reindex(close.index)
        l = data[s]['low'].reindex(close.index)
        c = data[s]['close'].reindex(close.index)
        hl = h - l
        hc = (h - c.shift()).abs()
        lc = (l - c.shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        atr_df[s] = tr.rolling(14).mean()

    # ---- Parameters ----
    ROC_L = 20        # 5 days at 6H
    ATR_K = 2.5       # multiplier
    FEE   = 0.0004    # 4 bps per side
    LONG_ALLOC  = 0.70
    SHORT_ALLOC = 0.30
    MAX_LONG  = 5
    MAX_SHORT = 5
    SHARPE_LONG = 1.3

    # ---- Walk-Forward Simulation ----
    # Rebalance on first bar of each month
    # Use previous month's Sharpe to select longs; worst momentum for shorts
    # No look-ahead: selection at bar t uses data through bar t-1

    # Index: all bars from 2020-06-01 onwards
    sim_start = pd.Timestamp('2020-06-01')
    close_sim = close.loc[close.index >= sim_start]
    rets_sim  = rets.loc[rets.index >= sim_start]

    n_bars = len(close_sim)
    portfolio_rets = np.zeros(n_bars)

    # State
    weights = pd.Series(0.0, index=trading_syms)  # current weight per symbol
    in_position = pd.Series(False, index=trading_syms)
    trailing_stop = pd.Series(np.nan, index=trading_syms)
    position_side = pd.Series('none', index=trading_syms)
    current_month = None
    n_trades = 0
    rebal_months = []

    for i in range(1, n_bars):
        t     = close_sim.index[i]
        t_prev = close_sim.index[i-1]

        # ---- Monthly rebalance ----
        this_month = (t.year, t.month)
        if this_month != current_month:
            current_month = this_month

            # Compute prior-month Sharpe for each symbol (using ALL data before t)
            lookback = 120  # 30 days of 6H bars
            sharpes = {}
            for s in trading_syms:
                hist_rets = rets.loc[rets.index < t, s].dropna().tail(lookback)
                if len(hist_rets) >= 30:
                    sharpes[s] = sharpe_6h(hist_rets)

            if sharpes:
                # Longs: Sharpe >= SHARPE_LONG, top MAX_LONG
                long_cands = sorted(
                    [(s, v) for s, v in sharpes.items() if v >= SHARPE_LONG],
                    key=lambda x: x[1], reverse=True
                )[:MAX_LONG]

                # Shorts: most negative Sharpe (trend down)
                short_cands = sorted(
                    [(s, v) for s, v in sharpes.items() if s not in [x[0] for x in long_cands]],
                    key=lambda x: x[1]
                )[:MAX_SHORT]
                # Only short if Sharpe is meaningfully negative
                short_cands = [(s, v) for s, v in short_cands if v < -0.3]

                new_longs  = [s for s, _ in long_cands]
                new_shorts = [s for s, _ in short_cands]
            else:
                new_longs  = []
                new_shorts = []

            # Build new weights
            new_weights = pd.Series(0.0, index=trading_syms)
            if new_longs:
                w_each_long = LONG_ALLOC / len(new_longs)
                for s in new_longs:
                    new_weights[s] = w_each_long
            if new_shorts:
                w_each_short = -SHORT_ALLOC / len(new_shorts)
                for s in new_shorts:
                    new_weights[s] = w_each_short

            # Count trades (position changes)
            changed = (new_weights != weights)
            n_trades += changed.sum()

            # Apply turnover cost: FEE * |delta_weight| for each symbol
            turnover_cost = (new_weights - weights).abs().sum() * FEE
            weights = new_weights.copy()

            # Reset trailing stops for new positions
            c_t = close_sim.loc[t]
            a_t = atr_df.loc[t] if t in atr_df.index else pd.Series(np.nan, index=trading_syms)
            for s in trading_syms:
                if weights[s] > 0:  # long
                    ts_val = c_t.get(s, np.nan) - ATR_K * a_t.get(s, np.nan)
                    trailing_stop[s] = ts_val if not np.isnan(ts_val) else c_t.get(s, np.nan) * 0.9
                    position_side[s] = 'long'
                elif weights[s] < 0:  # short
                    ts_val = c_t.get(s, np.nan) + ATR_K * a_t.get(s, np.nan)
                    trailing_stop[s] = ts_val if not np.isnan(ts_val) else c_t.get(s, np.nan) * 1.1
                    position_side[s] = 'short'
                else:
                    trailing_stop[s] = np.nan
                    position_side[s] = 'none'

            rebal_months.append({
                'date': str(t.date()),
                'longs': new_longs,
                'shorts': [s for s, _ in short_cands] if short_cands else [],
                'turnover_cost': turnover_cost
            })
            portfolio_rets[i] -= turnover_cost
        else:
            # ---- Intra-month: update trailing stops, apply stops ----
            c_t = close_sim.loc[t]
            a_t = atr_df.loc[t] if t in atr_df.index else pd.Series(np.nan, index=trading_syms)

            stops_triggered = []
            for s in trading_syms:
                if weights[s] == 0 or np.isnan(trailing_stop[s]):
                    continue
                p = c_t.get(s, np.nan)
                if np.isnan(p):
                    continue
                atr_val = a_t.get(s, np.nan)

                if weights[s] > 0:  # long position
                    # Update trailing stop upward
                    if not np.isnan(atr_val):
                        new_ts = p - ATR_K * atr_val
                        trailing_stop[s] = max(trailing_stop[s], new_ts)
                    # Check stop
                    if p <= trailing_stop[s]:
                        stops_triggered.append(s)
                else:  # short position
                    if not np.isnan(atr_val):
                        new_ts = p + ATR_K * atr_val
                        trailing_stop[s] = min(trailing_stop[s], new_ts)
                    if p >= trailing_stop[s]:
                        stops_triggered.append(s)

            for s in stops_triggered:
                weights[s] = 0.0
                trailing_stop[s] = np.nan
                position_side[s] = 'none'
                portfolio_rets[i] -= FEE  # exit fee
                n_trades += 1

        # ---- Bar return ----
        bar_rets = rets_sim.iloc[i]
        port_bar = (weights * bar_rets).sum()
        portfolio_rets[i] += port_bar

    # ---- Convert to daily ----
    port_series = pd.Series(portfolio_rets, index=close_sim.index)
    # Resample to daily
    daily_nav = (1 + port_series).cumprod()
    daily_nav_d = daily_nav.resample('1D').last().dropna()
    daily_rets_d = daily_nav_d.pct_change().dropna()

    # ---- Metrics ----
    total_days = (daily_nav_d.index[-1] - daily_nav_d.index[0]).days
    total_years = total_days / 365.25

    cagr = (daily_nav_d.iloc[-1] / daily_nav_d.iloc[0]) ** (1 / total_years) - 1
    sharpe = daily_rets_d.mean() / daily_rets_d.std() * np.sqrt(365)
    cum = (1 + daily_rets_d).cumprod()
    max_dd = (cum / cum.cummax() - 1).min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    total_ret = daily_nav_d.iloc[-1] - 1

    # ---- Yearly breakdown ----
    yearly_stats = {}
    for yr, grp in daily_rets_d.groupby(daily_rets_d.index.year):
        if len(grp) < 20:
            continue
        yr_cagr = (1 + grp).prod() ** (365 / len(grp)) - 1
        yr_sharpe = grp.mean() / grp.std() * np.sqrt(365) if grp.std() > 0 else 0
        yr_cum = (1 + grp).cumprod()
        yr_dd = (yr_cum / yr_cum.cummax() - 1).min()
        yearly_stats[str(yr)] = {
            'cagr': round(float(yr_cagr), 4),
            'sharpe': round(float(yr_sharpe), 2),
            'max_dd': round(float(yr_dd), 4)
        }

    # ---- BTC benchmark ----
    btc_bench = None
    if 'BTCUSDT' in close:
        btc_close = close.loc[close.index >= sim_start, 'BTCUSDT'].dropna()
        btc_d = btc_close.resample('1D').last().dropna()
        btc_d = btc_d[btc_d.index >= daily_nav_d.index[0]]
        btc_d = btc_d[btc_d.index <= daily_nav_d.index[-1]]
        if len(btc_d) > 30:
            btc_r = btc_d.pct_change().dropna()
            btc_years = (btc_d.index[-1] - btc_d.index[0]).days / 365.25
            btc_cagr = (btc_d.iloc[-1] / btc_d.iloc[0]) ** (1/btc_years) - 1
            btc_sh = btc_r.mean() / btc_r.std() * np.sqrt(365)
            btc_c = (1 + btc_r).cumprod()
            btc_dd = (btc_c / btc_c.cummax() - 1).min()
            btc_bench = {
                'cagr': round(float(btc_cagr), 4),
                'sharpe': round(float(btc_sh), 2),
                'max_dd': round(float(btc_dd), 4),
                'total_return': round(float(btc_d.iloc[-1]/btc_d.iloc[0]-1), 4)
            }

    print("\n=== BACKTEST RESULTS ===")
    print(f"Period : {daily_nav_d.index[0].date()} → {daily_nav_d.index[-1].date()}")
    print(f"CAGR   : {cagr:.2%}")
    print(f"Sharpe : {sharpe:.2f}")
    print(f"Max DD : {max_dd:.2%}")
    print(f"Calmar : {calmar:.2f}")
    print(f"Total R: {total_ret:.2%}")
    print(f"Trades : {n_trades}")
    print(f"Rebal  : {len(rebal_months)}")
    if btc_bench:
        print(f"\nBTC B&H: CAGR={btc_bench['cagr']:.2%}  Sharpe={btc_bench['sharpe']:.2f}  MaxDD={btc_bench['max_dd']:.2%}")

    print("\nYearly breakdown:")
    for yr, s in yearly_stats.items():
        print(f"  {yr}: CAGR={s['cagr']:.2%}  Sharpe={s['sharpe']:.2f}  MaxDD={s['max_dd']:.2%}")

    # Show last few rebalances for validation
    print("\nLast 3 rebalances:")
    for r in rebal_months[-3:]:
        print(f"  {r['date']}: longs={r['longs']}  shorts={r['shorts']}")

    results = {
        'period_start': str(daily_nav_d.index[0].date()),
        'period_end': str(daily_nav_d.index[-1].date()),
        'cagr': round(float(cagr), 4),
        'sharpe': round(float(sharpe), 2),
        'max_dd': round(float(max_dd), 4),
        'calmar': round(float(calmar), 2),
        'total_return': round(float(total_ret), 4),
        'n_trades': int(n_trades),
        'rebalances': len(rebal_months),
        'symbols_used': trading_syms,
        'btc_benchmark': btc_bench,
        'yearly': yearly_stats,
        'rebal_history': rebal_months[-12:]  # last 12 months
    }

    with open(os.path.join(WORKDIR, 'results_v1.json'), 'w') as f:
        json.dump(results, f, indent=2, default=str)

    return results, rebal_months, btc_bench

if __name__ == '__main__':
    r, rebal, btc = run_backtest()
    print("\nSaved to results_v1.json")
