#!/usr/bin/env python3
"""
AdaptiveTrend v1 Backtest
- Universe: Binance USDT spot (top-20 by 24h quoteVolume as market-cap proxy)
- Timeframe: 6H
- Period: 2020-01-01 to 2026-05-20
- Signal: ROC(20) momentum + ATR(14) trailing stop
- Selection: Walk-Forward monthly, long Sharpe >= 1.3, short worst momentum
- Allocation: 70% long / 30% short, equal-weight within each leg
- Fees: 4 bps per side
"""

import requests
import pandas as pd
import numpy as np
import time
import json
import os
from datetime import datetime, timedelta

WORKDIR = "/root/.openclaw/workspace/crypto-research/adaptive-trend"
os.makedirs(WORKDIR, exist_ok=True)

STABLECOINS = {
    'USDCUSDT','BUSDUSDT','TUSDUSDT','USDTUSDT','FDUSDUSDT','DAIUSDT',
    'EURUSDT','GBPUSDT','AEURUSDT','BRLLUSDT','PYUSDUSDT','USDSUSDT',
    'USDPUSDT','USSBUSDT','FRAXUSDT','SUSDUSDT','MUSDUSDT','WBETHUSDT'
}

def get_top20():
    """Get top 20 USDT pairs by 24h quoteVolume (proxy for market cap)."""
    print("Fetching top-20 tickers...")
    resp = requests.get('https://api.binance.com/api/v3/ticker/24hr', timeout=30)
    tickers = pd.DataFrame(resp.json())
    tickers = tickers[tickers['symbol'].str.endswith('USDT')]
    tickers['quoteVolume'] = tickers['quoteVolume'].astype(float)
    tickers = tickers[~tickers['symbol'].isin(STABLECOINS)]
    # Also filter out leveraged tokens
    tickers = tickers[~tickers['symbol'].str.contains('UP|DOWN|BULL|BEAR|3L|3S|5L|5S')]
    top20 = tickers.nlargest(25, 'quoteVolume')['symbol'].tolist()[:20]
    print(f"Top-20: {top20}")
    return top20

def fetch_klines(symbol, interval='6h', start_str='2020-01-01', end_str='2026-05-20', limit=1000):
    """Fetch OHLCV from Binance REST API."""
    url = 'https://api.binance.com/api/v3/klines'
    start_ts = int(pd.Timestamp(start_str).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_str).timestamp() * 1000)
    all_klines = []
    retries = 0
    while True:
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': start_ts,
            'endTime': end_ts,
            'limit': limit
        }
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                print(f"  Rate limited, sleeping 10s...")
                time.sleep(10)
                continue
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} for {symbol}")
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
            retries = 0
        except Exception as e:
            retries += 1
            if retries > 3:
                print(f"  Failed after 3 retries for {symbol}: {e}")
                break
            time.sleep(2)

    if not all_klines:
        return None

    df = pd.DataFrame(all_klines, columns=[
        'open_time','open','high','low','close','volume',
        'close_time','quote_vol','trades','taker_buy_base',
        'taker_buy_quote','ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    for c in ['open','high','low','close','volume']:
        df[c] = df[c].astype(float)
    df = df.set_index('open_time')
    return df[['open','high','low','close','volume']]

def compute_atr(df, k=14):
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(k).mean()

def compute_sharpe_from_returns(rets, periods_per_year=4*365):
    """periods_per_year for 6H bars: 4 bars/day * 365 days"""
    if len(rets) < 2 or rets.std() == 0:
        return 0.0
    return rets.mean() / rets.std() * np.sqrt(periods_per_year)

def load_or_fetch(symbol, cache_dir):
    cache_path = os.path.join(cache_dir, f"{symbol}_6h.parquet")
    if os.path.exists(cache_path):
        print(f"  Loading cached {symbol}...")
        return pd.read_parquet(cache_path)
    print(f"  Fetching {symbol}...")
    df = fetch_klines(symbol, '6h', '2020-01-01', '2026-05-20')
    if df is not None and len(df) > 100:
        df.to_parquet(cache_path)
    return df

def run_backtest():
    cache_dir = os.path.join(WORKDIR, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    top20 = get_top20()

    # Fetch data for all symbols
    price_data = {}
    for sym in top20:
        df = load_or_fetch(sym, cache_dir)
        if df is not None and len(df) > 500:
            price_data[sym] = df
            print(f"  {sym}: {len(df)} bars ({df.index[0].date()} to {df.index[-1].date()})")
        else:
            print(f"  Skipping {sym}: insufficient data")

    print(f"\nLoaded data for {len(price_data)} symbols")
    symbols = list(price_data.keys())

    # Align all close prices to a common time index
    close_df = pd.DataFrame({s: price_data[s]['close'] for s in symbols})
    close_df = close_df.sort_index().dropna(how='all')

    # Also build a high/low dataframe for ATR trailing stop per symbol
    # We'll track position state per symbol

    # === BACKTEST PARAMETERS ===
    L_mom = 20         # ROC lookback (6H * 20 = 5 days)
    ATR_K = 14         # ATR period
    ALPHA = 2.5        # ATR multiplier for trailing stop
    FEE = 0.0004       # 4 bps per side (round trip = 8 bps)
    LONG_ALLOC = 0.70
    SHORT_ALLOC = 0.30
    MAX_LONG = 5
    MAX_SHORT = 5
    SHARPE_LONG_THRESH = 1.3
    SHARPE_SHORT_THRESH = -1.3  # most negative momentum = short

    # Build per-symbol indicators
    mom = {}
    atr = {}
    for s in symbols:
        df = price_data[s]
        mom[s] = df['close'].pct_change(L_mom)
        atr[s] = compute_atr(df, ATR_K)

    # Common 6H timestamps
    all_times = close_df.index
    start_dt = pd.Timestamp('2020-06-01')  # give 5 months of warmup for walk-forward
    trading_times = all_times[all_times >= start_dt]

    # Portfolio state
    capital = 10000.0
    positions = {}    # symbol -> {'side': 'long'/'short', 'qty': float, 'entry_price': float, 'trailing_stop': float}
    portfolio_value = []
    trade_log = []

    # Walk-forward: rebalance monthly
    current_month = None
    target_longs = []
    target_shorts = []

    def select_universe(as_of_time):
        """Select long/short candidates based on prior month performance."""
        # Use data up to but NOT including this bar (t-1)
        sharpes = {}
        for s in symbols:
            if s not in price_data:
                continue
            sym_close = price_data[s]['close']
            # Get last 30 days of 6H bars = 120 bars
            hist = sym_close[sym_close.index < as_of_time].tail(120)
            if len(hist) < 40:
                continue
            rets = hist.pct_change().dropna()
            sharpes[s] = compute_sharpe_from_returns(rets)

        if not sharpes:
            return [], []

        # Long candidates: Sharpe >= 1.3
        long_cands = [(s, v) for s, v in sharpes.items() if v >= SHARPE_LONG_THRESH]
        long_cands.sort(key=lambda x: x[1], reverse=True)
        long_selected = [s for s, _ in long_cands[:MAX_LONG]]

        # Short candidates: most negative Sharpe (worst performers)
        short_cands = [(s, v) for s, v in sharpes.items() if v <= -0.5]
        short_cands.sort(key=lambda x: x[1])  # ascending
        short_selected = [s for s, _ in short_cands[:MAX_SHORT]]

        return long_selected, short_selected

    def get_price(symbol, t):
        try:
            return close_df.loc[t, symbol]
        except:
            return None

    def close_position(symbol, t, side, qty, entry_price):
        price = get_price(symbol, t)
        if price is None or np.isnan(price):
            return 0.0
        if side == 'long':
            pnl = qty * (price - entry_price) - qty * price * FEE - qty * entry_price * FEE
        else:  # short
            pnl = qty * (entry_price - price) - qty * price * FEE - qty * entry_price * FEE
        trade_log.append({
            'time': t, 'symbol': symbol, 'side': side,
            'entry': entry_price, 'exit': price, 'qty': qty, 'pnl': pnl
        })
        return qty * price  # return position value (capital recovered)

    prev_capital = capital
    rebal_count = 0

    for i, t in enumerate(trading_times):
        # Monthly rebalance check
        this_month = (t.year, t.month)
        if this_month != current_month:
            current_month = this_month

            # Close all existing positions
            for sym, pos in list(positions.items()):
                price = get_price(sym, t)
                if price and not np.isnan(price):
                    recovered = close_position(sym, t, pos['side'], pos['qty'], pos['entry_price'])
                    if pos['side'] == 'long':
                        capital += recovered - pos['qty'] * pos['entry_price']
                    else:
                        capital += pos['qty'] * pos['entry_price'] - pos['qty'] * (price - pos['entry_price'])
                    # Simpler: just track portfolio value directly
            positions = {}

            # Select new universe
            target_longs, target_shorts = select_universe(t)
            rebal_count += 1

            # Open new positions
            long_budget = capital * LONG_ALLOC / max(len(target_longs), 1) if target_longs else 0
            short_budget = capital * SHORT_ALLOC / max(len(target_shorts), 1) if target_shorts else 0

            for sym in target_longs:
                price = get_price(sym, t)
                if price and not np.isnan(price) and price > 0:
                    qty = (long_budget * (1 - FEE)) / price
                    atr_val = atr[sym].get(t, np.nan) if hasattr(atr[sym], 'get') else (atr[sym][t] if t in atr[sym].index else np.nan)
                    ts = price - ALPHA * atr_val if not np.isnan(atr_val) else price * 0.90
                    positions[sym] = {
                        'side': 'long', 'qty': qty,
                        'entry_price': price, 'trailing_stop': ts,
                        'budget': long_budget
                    }

            for sym in target_shorts:
                if sym in positions:
                    continue  # already long, skip
                price = get_price(sym, t)
                if price and not np.isnan(price) and price > 0:
                    qty = (short_budget * (1 - FEE)) / price
                    positions[sym] = {
                        'side': 'short', 'qty': qty,
                        'entry_price': price, 'trailing_stop': price + ALPHA * (atr[sym].get(t, price*0.1) if hasattr(atr[sym], 'get') else price*0.1),
                        'budget': short_budget
                    }

        # Update trailing stops and check for stop hits
        stops_hit = []
        for sym, pos in positions.items():
            price = get_price(sym, t)
            if price is None or np.isnan(price):
                continue

            if pos['side'] == 'long':
                # Update trailing stop upward
                atr_sym = atr[sym]
                atr_val = atr_sym[t] if t in atr_sym.index else np.nan
                if not np.isnan(atr_val):
                    new_ts = price - ALPHA * atr_val
                    pos['trailing_stop'] = max(pos['trailing_stop'], new_ts)
                # Check stop
                if price <= pos['trailing_stop']:
                    stops_hit.append(sym)
            else:  # short
                atr_sym = atr[sym]
                atr_val = atr_sym[t] if t in atr_sym.index else np.nan
                if not np.isnan(atr_val):
                    new_ts = price + ALPHA * atr_val
                    pos['trailing_stop'] = min(pos['trailing_stop'], new_ts)
                # Check stop
                if price >= pos['trailing_stop']:
                    stops_hit.append(sym)

        # Execute stops
        for sym in stops_hit:
            pos = positions[sym]
            price = get_price(sym, t)
            if price and not np.isnan(price):
                trade_log.append({
                    'time': t, 'symbol': sym, 'side': pos['side'],
                    'entry': pos['entry_price'], 'exit': price,
                    'qty': pos['qty'], 'pnl': None, 'reason': 'stop'
                })
                del positions[sym]

        # Calculate portfolio value at this bar
        pv = 0.0
        for sym, pos in positions.items():
            price = get_price(sym, t)
            if price is None or np.isnan(price):
                continue
            if pos['side'] == 'long':
                pv += pos['qty'] * price
            else:
                # Short PnL: entry - current
                pv += pos['qty'] * (2 * pos['entry_price'] - price)
        # Add uninvested cash (approximation)
        invested = sum(p['budget'] for p in positions.values())
        pv += max(0, capital - invested)
        portfolio_value.append({'time': t, 'value': pv})

    # === PERFORMANCE METRICS ===
    pv_df = pd.DataFrame(portfolio_value).set_index('time')
    pv_df['returns'] = pv_df['value'].pct_change()
    pv_df = pv_df.dropna()

    # Convert 6H returns to daily
    daily_pv = pv_df['value'].resample('1D').last().dropna()
    daily_rets = daily_pv.pct_change().dropna()

    total_days = (daily_pv.index[-1] - daily_pv.index[0]).days
    total_years = total_days / 365.25

    final_value = daily_pv.iloc[-1]
    initial_value = daily_pv.iloc[0]
    total_return = (final_value / initial_value) - 1
    cagr = (final_value / initial_value) ** (1 / total_years) - 1

    sharpe = daily_rets.mean() / daily_rets.std() * np.sqrt(365) if daily_rets.std() > 0 else 0

    cum_rets = (1 + daily_rets).cumprod()
    rolling_max = cum_rets.cummax()
    drawdown = (cum_rets / rolling_max) - 1
    max_dd = drawdown.min()

    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    n_trades = len(trade_log)

    # Yearly performance
    yearly = daily_rets.groupby(daily_rets.index.year).apply(
        lambda x: {
            'cagr': (1 + x).prod() ** (365 / len(x)) - 1,
            'sharpe': x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else 0,
            'max_dd': ((1 + x).cumprod() / (1 + x).cumprod().cummax() - 1).min()
        }
    )

    # BTC benchmark
    btc_data = load_or_fetch('BTCUSDT', cache_dir)
    btc_bench = None
    if btc_data is not None:
        btc_daily = btc_data['close'].resample('1D').last().dropna()
        btc_daily = btc_daily[btc_daily.index >= daily_pv.index[0]]
        btc_daily = btc_daily[btc_daily.index <= daily_pv.index[-1]]
        if len(btc_daily) > 10:
            btc_rets = btc_daily.pct_change().dropna()
            btc_total = (btc_daily.iloc[-1] / btc_daily.iloc[0]) - 1
            btc_years = (btc_daily.index[-1] - btc_daily.index[0]).days / 365.25
            btc_cagr = (btc_daily.iloc[-1] / btc_daily.iloc[0]) ** (1/btc_years) - 1
            btc_sharpe = btc_rets.mean() / btc_rets.std() * np.sqrt(365)
            btc_cum = (1 + btc_rets).cumprod()
            btc_dd = (btc_cum / btc_cum.cummax() - 1).min()
            btc_bench = {
                'cagr': btc_cagr,
                'sharpe': btc_sharpe,
                'max_dd': btc_dd,
                'total_return': btc_total
            }

    # Long/short selection history
    print("\n=== BACKTEST COMPLETE ===")
    print(f"Period: {daily_pv.index[0].date()} to {daily_pv.index[-1].date()}")
    print(f"CAGR:    {cagr:.2%}")
    print(f"Sharpe:  {sharpe:.2f}")
    print(f"Max DD:  {max_dd:.2%}")
    print(f"Calmar:  {calmar:.2f}")
    print(f"Trades:  {n_trades}")
    print(f"Rebalances: {rebal_count}")

    if btc_bench:
        print(f"\nBTC B&H:")
        print(f"  CAGR: {btc_bench['cagr']:.2%}")
        print(f"  Sharpe: {btc_bench['sharpe']:.2f}")
        print(f"  Max DD: {btc_bench['max_dd']:.2%}")

    # Save results
    results = {
        'period_start': str(daily_pv.index[0].date()),
        'period_end': str(daily_pv.index[-1].date()),
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'calmar': calmar,
        'total_return': total_return,
        'n_trades': n_trades,
        'rebalances': rebal_count,
        'symbols_used': symbols,
        'btc_benchmark': btc_bench,
        'yearly': {str(yr): {k: float(v) for k, v in stats.items()} for yr, stats in yearly.items()}
    }
    with open(os.path.join(WORKDIR, 'results_v1.json'), 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nResults saved to results_v1.json")
    return results, symbols, pv_df, btc_bench, yearly, trade_log

if __name__ == '__main__':
    results, symbols, pv_df, btc_bench, yearly, trade_log = run_backtest()
    print("Done!")
