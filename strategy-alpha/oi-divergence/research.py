#!/usr/bin/env python3
"""
OI-Price Divergence Strategy Research
Binance USDT Perpetual Futures
2023-01-01 to 2024-12-31 backtest

NOTE ON DATA: Binance futures/data/openInterestHist API only provides 30 days of
daily OI history (hard API limit, no pagination supported). For the 2023-2024 
backtest, we use **taker buy/sell volume ratio** as the OI proxy, which correlates
with open interest because:
  - Aggressive taker buying accumulates long OI
  - Aggressive taker selling accumulates short OI  
  - Net taker pressure over 5 days mirrors net OI change direction

We also run a validation section on the available 30-day OI data to confirm
the taker proxy aligns with actual OI dynamics.
"""

import requests
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

BASE_FUTURES = "https://fapi.binance.com"

# Top 20 liquid USDT perp symbols by typical OI ranking
TOP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "LTCUSDT", "NEARUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT",
    "BCHUSDT", "FILUSDT", "AAVEUSDT", "MATICUSDT", "OPUSDT"
]

BACKTEST_START = pd.Timestamp("2023-01-01")
BACKTEST_END = pd.Timestamp("2024-12-31")
TAKER_FEE = 0.0004  # 4bps per side

# ─────────────────────────────────────────────────────────────────────────────
# Data Fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_klines_range(symbol, start_ts, end_ts, interval='1d'):
    """Fetch klines with pagination to cover full date range."""
    all_rows = []
    cur_start = start_ts
    
    while cur_start < end_ts:
        url = f"{BASE_FUTURES}/fapi/v1/klines"
        params = {
            'symbol': symbol, 'interval': interval,
            'startTime': cur_start, 'endTime': end_ts,
            'limit': 1500
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if not data:
                break
            all_rows.extend(data)
            # Next batch after last candle
            cur_start = data[-1][0] + 1
            if len(data) < 1500:
                break
            time.sleep(0.1)
        except Exception as e:
            print(f"    klines error {symbol}: {e}")
            break
    
    if not all_rows:
        return None
    
    df = pd.DataFrame(all_rows, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['date'] = pd.to_datetime(df['open_time'], unit='ms').dt.normalize()
    for col in ['close', 'volume', 'taker_buy_base']:
        df[col] = df[col].astype(float)
    
    # taker sell = total - taker buy
    df['taker_sell_base'] = df['volume'] - df['taker_buy_base']
    df['taker_ratio'] = df['taker_buy_base'] / df['volume'].replace(0, np.nan)
    
    df = df[['date', 'close', 'volume', 'taker_buy_base', 'taker_sell_base', 'taker_ratio']]
    df = df.set_index('date').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    return df

def fetch_oi_hist_recent(symbol):
    """Fetch recent 30-day OI history (max available from API)."""
    url = f"{BASE_FUTURES}/futures/data/openInterestHist"
    params = {'symbol': symbol, 'period': '1d', 'limit': 30}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.normalize()
        df['oi'] = df['sumOpenInterest'].astype(float)
        df['oi_value'] = df['sumOpenInterestValue'].astype(float)
        df = df[['date', 'oi', 'oi_value']].set_index('date').sort_index()
        return df
    except Exception as e:
        print(f"    OI hist error {symbol}: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Fetch data
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 65)
print("OI-Price Divergence Strategy Research (2023-2024 Backtest)")
print("=" * 65)
print()
print("[1] Fetching klines (2023-01-01 → 2024-12-31)...")

start_ts = int(BACKTEST_START.timestamp() * 1000)
end_ts = int((BACKTEST_END + pd.Timedelta(days=15)).timestamp() * 1000)  # extra for lookahead

all_klines = {}
excluded = []

for sym in TOP_SYMBOLS:
    print(f"  {sym}...", end=" ", flush=True)
    df = fetch_klines_range(sym, start_ts, end_ts)
    time.sleep(0.15)
    
    if df is None:
        print("SKIP (fetch error)")
        excluded.append(sym)
        continue
    
    # Filter to backtest window (with 15-day lookahead buffer)
    bt_rows = df[(df.index >= BACKTEST_START) & (df.index <= BACKTEST_END + pd.Timedelta(days=15))]
    
    if len(bt_rows) < 100:
        print(f"SKIP (only {len(bt_rows)} rows)")
        excluded.append(sym)
        continue
    
    all_klines[sym] = bt_rows
    print(f"OK ({len(bt_rows)} rows, {bt_rows.index.min().date()} → {bt_rows.index.max().date()})")

print(f"\n  Available: {len(all_klines)} symbols: {list(all_klines.keys())}")
print(f"  Excluded:  {excluded}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Build OI proxy from taker volume
# ─────────────────────────────────────────────────────────────────────────────
print("\n[2] Building OI-Price Divergence signals (taker-flow OI proxy)...")

"""
OI Proxy Logic:
  taker_ratio = taker_buy_vol / total_vol  (0.5 = neutral; >0.5 = buying pressure)
  
  5-day OI proxy change:
    oi_proxy_5d = rolling(5d, sum of taker_buy) / rolling(5d, sum of volume) 
                  → 5-day taker buy ratio
  
  Divergence = (oi_proxy_5d - 0.5)*2 - price_change_5d
    where (oi_proxy_5d - 0.5)*2 normalizes to [-1, +1] scale
    
  Alternative: use simple taker_ratio pct_change(5) as OI_change proxy
"""

signal_rows = []

for sym, df in all_klines.items():
    df = df.copy().sort_index()
    
    # Method: 5-day rolling taker buy ratio as OI proxy
    df['roll_buy'] = df['taker_buy_base'].rolling(5).sum()
    df['roll_vol'] = df['volume'].rolling(5).sum()
    df['oi_proxy_5d'] = df['roll_buy'] / df['roll_vol'].replace(0, np.nan)
    
    # Price 5-day change
    df['price_change_5d'] = df['close'].pct_change(5)
    
    # OI proxy change: deviation from neutral (0.5 = neutral)
    # Positive = more buying pressure than neutral
    df['oi_change_proxy'] = (df['oi_proxy_5d'] - 0.5) * 2  # normalize to ~[-1, 1]
    
    # Divergence: OI-proxy rising but price not rising
    # High divergence = takers buying aggressively but price not moving → short signal
    # Low divergence = takers not buying / selling but price rising → long signal
    df['divergence'] = df['oi_change_proxy'] - df['price_change_5d']
    
    # Filter to strict backtest window (leave lookahead buffer for exit)
    mask = (df.index >= BACKTEST_START) & (df.index <= BACKTEST_END)
    df_bt = df[mask].dropna(subset=['divergence', 'price_change_5d'])
    
    for date, row in df_bt.iterrows():
        signal_rows.append({
            'symbol': sym,
            'date': date,
            'close': row['close'],
            'oi_proxy_5d': row.get('oi_proxy_5d', np.nan),
            'oi_change_proxy': row['oi_change_proxy'],
            'price_change_5d': row['price_change_5d'],
            'divergence': row['divergence']
        })

signals_df = pd.DataFrame(signal_rows)
print(f"  Total signal rows: {len(signals_df):,}")

if len(signals_df) == 0:
    print("ERROR: No signal rows generated!")
    exit(1)

# Compute global percentile thresholds
pcts = {}
for p in [10, 20, 30, 70, 80, 90]:
    pcts[f'p{p}'] = signals_df['divergence'].quantile(p / 100)

print(f"  Divergence stats: mean={signals_df['divergence'].mean():.4f}, "
      f"std={signals_df['divergence'].std():.4f}")
print(f"  Percentiles: P10={pcts['p10']:.4f}, P20={pcts['p20']:.4f}, "
      f"P80={pcts['p80']:.4f}, P90={pcts['p90']:.4f}")

# Apply base signals (80th/20th percentile)
signals_df['signal_short'] = signals_df['divergence'] > pcts['p80']
signals_df['signal_long'] = signals_df['divergence'] < pcts['p20']

print(f"  Short signals: {signals_df['signal_short'].sum():,}")
print(f"  Long signals:  {signals_df['signal_long'].sum():,}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Backtest engine
# ─────────────────────────────────────────────────────────────────────────────
print("\n[3] Running backtests...")

def run_backtest(signals_df, all_klines, holding_days, signal_col, direction):
    """Run vectorized backtest for a given signal."""
    trades = []
    
    for sym, grp in signals_df.groupby('symbol'):
        if sym not in all_klines:
            continue
        price_series = all_klines[sym]['close']
        
        signal_dates = grp[grp[signal_col]]['date'].tolist()
        
        for entry_date in signal_dates:
            # Find entry price (close on signal date)
            if entry_date not in price_series.index:
                continue
            entry_price = price_series[entry_date]
            
            # Exit: close of holding_days trading days later
            future_dates = price_series.index[price_series.index > entry_date]
            if len(future_dates) < holding_days:
                continue
            exit_date = future_dates[holding_days - 1]
            exit_price = price_series[exit_date]
            
            # Return calculation
            price_return = (exit_price - entry_price) / entry_price
            if direction == 'short':
                trade_return = -price_return
            else:
                trade_return = price_return
            
            # Net of round-trip fees
            net_return = trade_return - 2 * TAKER_FEE
            
            row = grp[grp['date'] == entry_date].iloc[0]
            trades.append({
                'symbol': sym,
                'entry_date': entry_date,
                'exit_date': exit_date,
                'direction': direction,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'trade_return': trade_return,
                'net_return': net_return,
                'divergence': row['divergence']
            })
    
    return pd.DataFrame(trades)

def compute_metrics(trades_df, label):
    """Compute performance metrics from trade list."""
    if len(trades_df) == 0:
        return {
            'label': label, 'n_trades': 0,
            'win_rate': None, 'avg_net_return_pct': None,
            'annual_return_pct': None, 'sharpe': None, 'max_drawdown_pct': None
        }
    
    returns = trades_df['net_return'].values
    n = len(returns)
    
    win_rate = float((returns > 0).mean())
    avg_return = float(returns.mean())
    
    # Annualize: assume holding period days as trading interval
    # Number of independent periods per year for each holding period
    # 365 days / holding_days ≈ periods per year
    hold_days = (trades_df['exit_date'] - trades_df['entry_date']).dt.days.mean() if hasattr(trades_df['exit_date'], 'dt') else 7
    periods_per_year = 365 / max(hold_days, 1)
    annual_return = float((1 + avg_return) ** periods_per_year - 1)
    
    # Sharpe (per-trade annualized)
    std = float(returns.std())
    sharpe = float((avg_return / std) * np.sqrt(periods_per_year)) if std > 0 else 0.0
    
    # Max drawdown (sequential cumulative returns)
    trades_sorted = trades_df.sort_values('entry_date')
    cum = np.cumprod(1 + trades_sorted['net_return'].values)
    rolling_max = np.maximum.accumulate(cum)
    drawdowns = (cum - rolling_max) / np.where(rolling_max > 0, rolling_max, 1)
    max_dd = float(drawdowns.min())
    
    return {
        'label': label,
        'n_trades': n,
        'win_rate': round(win_rate, 4),
        'avg_net_return_pct': round(avg_return * 100, 4),
        'annual_return_pct': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 3),
        'max_drawdown_pct': round(max_dd * 100, 2)
    }

# ─────────────────────────────────────────────────────────────────────────────
# Core backtests: 3d & 7d × long & short
# ─────────────────────────────────────────────────────────────────────────────
results = {}
all_trades = {}

for hold in [3, 7]:
    for direction, sig_col in [('short', 'signal_short'), ('long', 'signal_long')]:
        label = f"{direction}_hold{hold}d"
        trades = run_backtest(signals_df, all_klines, hold, sig_col, direction)
        metrics = compute_metrics(trades, label)
        results[label] = metrics
        all_trades[label] = trades
        print(f"  {label:30s} → n={metrics['n_trades']:5d}, "
              f"Sharpe={str(metrics['sharpe']):8s}, "
              f"Ann={str(metrics['annual_return_pct']):8s}%, "
              f"MaxDD={str(metrics['max_drawdown_pct']):8s}%, "
              f"WR={str(metrics['win_rate'])}")

# ─────────────────────────────────────────────────────────────────────────────
# Long-Short combined
# ─────────────────────────────────────────────────────────────────────────────
print()
for hold in [3, 7]:
    label = f"longshort_hold{hold}d"
    t_short = all_trades[f'short_hold{hold}d'].copy()
    t_long = all_trades[f'long_hold{hold}d'].copy()
    combined = pd.concat([t_short, t_long], ignore_index=True).sort_values('entry_date')
    metrics = compute_metrics(combined, label)
    results[label] = metrics
    all_trades[label] = combined
    print(f"  {label:30s} → n={metrics['n_trades']:5d}, "
          f"Sharpe={str(metrics['sharpe']):8s}, "
          f"Ann={str(metrics['annual_return_pct']):8s}%, "
          f"MaxDD={str(metrics['max_drawdown_pct']):8s}%, "
          f"WR={str(metrics['win_rate'])}")

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Divergence strength layering (hold=7d)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[4] Divergence strength layering (hold=7d)...")

tiers = {
    'top30pct': (pcts['p70'], pcts['p30']),
    'top20pct': (pcts['p80'], pcts['p20']),
    'top10pct': (pcts['p90'], pcts['p10']),
}

layering_results = {}
for tier, (upper, lower) in tiers.items():
    for direction in ['short', 'long']:
        sigs = signals_df.copy()
        if direction == 'short':
            sigs['sig'] = sigs['divergence'] > upper
        else:
            sigs['sig'] = sigs['divergence'] < lower
        
        label = f"{direction}_{tier}_hold7d"
        trades = run_backtest(sigs, all_klines, 7, 'sig', direction)
        metrics = compute_metrics(trades, label)
        layering_results[label] = metrics
        print(f"  {label:40s} n={metrics['n_trades']:5d}, "
              f"Sharpe={str(metrics['sharpe']):8s}, "
              f"Ann={str(metrics['annual_return_pct']):8s}%, "
              f"WR={str(metrics['win_rate'])}")

results.update(layering_results)

# ─────────────────────────────────────────────────────────────────────────────
# Validation: compare taker proxy with actual OI (last 30 days)
# ─────────────────────────────────────────────────────────────────────────────
print("\n[5] OI proxy validation (recent 30-day OI vs taker proxy)...")

oi_validation = {}
for sym in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']:
    recent_oi = fetch_oi_hist_recent(sym)
    time.sleep(0.2)
    if recent_oi is None:
        continue
    
    if sym not in all_klines:
        continue
    
    recent_klines = all_klines[sym].copy()
    
    # Re-compute taker proxy on recent data
    recent_klines['roll_buy'] = recent_klines['taker_buy_base'].rolling(5).sum()
    recent_klines['roll_vol'] = recent_klines['volume'].rolling(5).sum()
    recent_klines['taker_proxy'] = recent_klines['roll_buy'] / recent_klines['roll_vol'].replace(0, np.nan)
    
    # Join with OI
    merged = recent_klines[['close', 'taker_proxy']].join(
        recent_oi[['oi']], how='inner'
    ).dropna()
    
    if len(merged) < 5:
        print(f"  {sym}: insufficient overlap")
        continue
    
    # Correlation between taker_proxy and OI change
    merged['oi_change_5d'] = merged['oi'].pct_change(5)
    merged['proxy_dev'] = (merged['taker_proxy'] - 0.5) * 2
    
    corr_data = merged[['proxy_dev', 'oi_change_5d']].dropna()
    if len(corr_data) > 3:
        corr = corr_data.corr().iloc[0, 1]
        print(f"  {sym}: correlation(proxy_dev, oi_change_5d) = {corr:.3f}  "
              f"(n={len(corr_data)} days)")
        oi_validation[sym] = round(corr, 3)
    else:
        print(f"  {sym}: not enough rows for correlation")

# ─────────────────────────────────────────────────────────────────────────────
# Save results.json
# ─────────────────────────────────────────────────────────────────────────────
print("\n[6] Saving results...")

# Per-symbol performance breakdown
symbol_perf = {}
for sym in all_klines.keys():
    sym_results = {}
    for label, trades in all_trades.items():
        if 'long' in label and 'short' not in label.split('_')[0]:
            continue
        sym_trades = trades[trades['symbol'] == sym] if len(trades) > 0 else pd.DataFrame()
        if len(sym_trades) > 0:
            sym_results[label] = {
                'n_trades': len(sym_trades),
                'avg_net_return_pct': round(sym_trades['net_return'].mean() * 100, 4),
                'win_rate': round((sym_trades['net_return'] > 0).mean(), 4)
            }
    symbol_perf[sym] = sym_results

results_out = {
    'metadata': {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'backtest_window': '2023-01-01 to 2024-12-31',
        'symbols_used': list(all_klines.keys()),
        'n_symbols': len(all_klines),
        'excluded_symbols': excluded,
        'taker_fee_bps': 4,
        'oi_data_note': (
            'Binance openInterestHist API limited to 30-day lookback. '
            'Backtest uses taker buy/sell volume ratio as OI proxy. '
            'Actual 30-day OI validation correlations shown in oi_proxy_validation.'
        ),
        'signal_method': 'taker_buy_ratio_5d_vs_price_change_5d_divergence',
        'divergence_percentiles': {f'p{p}': round(pcts[f'p{p}'], 6) for p in [10,20,30,70,80,90]},
        'oi_proxy_validation_correlations': oi_validation
    },
    'core_results': results,
    'symbol_performance_sample': {
        sym: all_trades.get('longshort_hold7d', pd.DataFrame())[
            all_trades.get('longshort_hold7d', pd.DataFrame()).get('symbol', pd.Series()) == sym
        ]['net_return'].describe().to_dict() if len(all_trades.get('longshort_hold7d', pd.DataFrame())) > 0 else {}
        for sym in list(all_klines.keys())[:5]
    }
}

output_path = '/root/.openclaw/workspace/research/strategy-alpha/oi-divergence/results.json'
with open(output_path, 'w') as f:
    json.dump(results_out, f, indent=2, default=str)

print(f"  Saved to {output_path}")
print("\n[7] Final Summary:")
print("-" * 70)
for label, m in results.items():
    if 'tier' not in label or 'hold7d' in label:
        print(f"  {label:40s} | n={str(m['n_trades']):5s} | "
              f"Sharpe={str(m.get('sharpe','N/A')):7s} | "
              f"Ann={str(m.get('annual_return_pct','N/A')):8s}% | "
              f"MaxDD={str(m.get('max_drawdown_pct','N/A')):7s}%")

print("\nDone.")
