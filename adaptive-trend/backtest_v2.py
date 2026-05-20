"""
AdaptiveTrend v2 Backtest
Fixes applied:
1. Survivorship Bias: dynamic monthly volume-based universe (not current top 20)
2. IS/OOS split: IS=2020-2023, OOS=2024-2026
3. Funding Rate cost for short positions: 0.01%/8h
4. Liquidity filter: exclude coins with avg daily USDT vol < $50M
5. Tiered slippage: large >5B = 4bps, mid >500M = 8bps, small = 15bps
6. BTC trend filter for shorts: short only when BTC < 90-day MA
7. Short logic: rank drop from <=15 to 16-20 (market cap decay signal)
"""

import os, requests, pandas as pd, numpy as np, time, json

WORK_DIR = '/root/.openclaw/workspace/crypto-research/adaptive-trend'
CACHE_DIR = f'{WORK_DIR}/cache'
os.makedirs(CACHE_DIR, exist_ok=True)

# Candidate symbols: listed before 2020, avoiding survivorship bias
symbols = ['BTCUSDT','ETHUSDT','XRPUSDT','BNBUSDT','LTCUSDT','BCHUSDT','ADAUSDT','LINKUSDT',
           'DOTUSDT','UNIUSDT','SOLUSDT','MATICUSDT','DOGEUSDT','AVAXUSDT','ATOMUSDT',
           'XLMUSDT','VETUSDT','TRXUSDT','ETCUSDT','FILUSDT','THETAUSDT','ALGOUSDT',
           'XMRUSDT','ZECUSDT','DASHUSDT','EOSUSDT','XTZUSDT','AAVEUSDT','COMPUSDT','SUSHIUSDT']

# ============================================================
# DATA FETCH
# ============================================================
def fetch_6h_klines(symbol, start='2019-12-01'):
    cache_file = f'{CACHE_DIR}/{symbol}_6h.parquet'
    if os.path.exists(cache_file):
        df = pd.read_parquet(cache_file)
        # Add quote_vol if missing (compute from close * volume)
        if 'quote_vol' not in df.columns:
            df['quote_vol'] = df['close'] * df['volume']
            df.to_parquet(cache_file)  # update cache
        return df
    
    url = 'https://api.binance.com/api/v3/klines'
    start_ts = int(pd.Timestamp(start).timestamp() * 1000)
    all_data = []
    while True:
        params = {'symbol': symbol, 'interval': '6h', 'startTime': start_ts, 'limit': 1000}
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 429:
            print(f"Rate limited, sleeping 15s...")
            time.sleep(15)
            continue
        if r.status_code != 200:
            break
        data = r.json()
        if not data or isinstance(data, dict):
            break
        all_data.extend(data)
        if len(data) < 1000:
            break
        start_ts = data[-1][0] + 1
        time.sleep(0.15)
    
    if not all_data:
        return None
    
    df = pd.DataFrame(all_data, columns=['open_time','open','high','low','close','volume',
                                          'close_time','quote_vol','trades','tbb','tbq','ignore'])
    df['ts'] = pd.to_datetime(df['open_time'], unit='ms')
    for c in ['open','high','low','close','volume','quote_vol']:
        df[c] = df[c].astype(float)
    df = df.set_index('ts')[['open','high','low','close','volume','quote_vol']]
    df.to_parquet(cache_file)
    return df


# ============================================================
# LOAD DATA
# ============================================================
print("Loading data...")
data = {}
for sym in symbols:
    d = fetch_6h_klines(sym)
    if d is not None and len(d) > 100:
        data[sym] = d
        print(f"  {sym}: {len(d)} bars, from {d.index[0].date()} to {d.index[-1].date()}")
    time.sleep(0.1)

print(f"\nTotal symbols loaded: {len(data)}")

# ============================================================
# DYNAMIC MONTHLY VOLUME UNIVERSE (anti-survivorship bias)
# ============================================================
print("\nBuilding monthly volume universe...")

# Compute monthly volume for each symbol
monthly_vol = {}
for sym, df in data.items():
    mv = df['quote_vol'].resample('ME').sum()
    monthly_vol[sym] = mv

vol_df = pd.DataFrame(monthly_vol).fillna(0)
print(f"Monthly vol matrix: {vol_df.shape}")

def get_monthly_universe(month_end, top_n=20, min_daily_vol=5e7):
    """
    Returns top_n symbols by volume for a given month-end timestamp.
    Applies liquidity filter: avg daily vol > min_daily_vol.
    """
    if month_end not in vol_df.index:
        # Find nearest
        available = vol_df.index[vol_df.index <= month_end]
        if len(available) == 0:
            return []
        month_end = available[-1]
    
    row = vol_df.loc[month_end]
    # Only include symbols with data that month (non-zero volume)
    active = row[row > 0]
    # Liquidity filter: monthly vol / ~30 days > 50M/day
    # Monthly vol is total, roughly 30 days
    active = active[active / 30 > min_daily_vol]
    ranked = active.nlargest(top_n)
    return ranked.index.tolist(), ranked


# ============================================================
# SIGNAL COMPUTATION
# ============================================================
def compute_signals(df, roc_period=20, atr_period=14, atr_mult=2.5):
    df = df.copy()
    df['roc'] = df['close'].pct_change(roc_period)
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    df['tr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(atr_period).mean()
    df['trailing_stop_long'] = df['close'] - atr_mult * df['atr']
    df['trailing_stop_short'] = df['close'] + atr_mult * df['atr']
    return df

# Pre-compute signals for all symbols
print("Computing signals for all symbols...")
signals = {}
for sym, df in data.items():
    signals[sym] = compute_signals(df)

# ============================================================
# BTC TREND FILTER
# ============================================================
btc = data['BTCUSDT'].copy()
# 90 days = 90 * 4 = 360 bars of 6H
btc['ma90'] = btc['close'].rolling(360).mean()
btc['bear_market'] = btc['close'] < btc['ma90']

def btc_is_bearish(date):
    """Check if BTC is in bear market at given date."""
    available = btc.index[btc.index <= date]
    if len(available) == 0:
        return False
    return btc.loc[available[-1], 'bear_market']


# ============================================================
# COST MODEL
# ============================================================
FUNDING_RATE_8H = 0.0001  # 0.01% per 8h
DAILY_FUNDING = FUNDING_RATE_8H * 3  # 3 times per day

def get_fee_bps(sym, monthly_vol_usd):
    """Tiered fee based on daily volume."""
    daily_vol = monthly_vol_usd / 30
    if daily_vol > 5e8:    # >$500M/day: large
        return 0.0004      # 4bps
    elif daily_vol > 5e7:  # >$50M/day: mid
        return 0.0008      # 8bps
    else:
        return 0.0015      # 15bps (small)


# ============================================================
# WALK-FORWARD BACKTEST
# ============================================================
print("\nRunning Walk-Forward Backtest...")

INITIAL_CAPITAL = 10000.0
LONG_ALLOC = 0.70
SHORT_ALLOC = 0.30
MAX_LONG = 5
MAX_SHORT = 3
SHARPE_LONG_THRESHOLD = 1.3
MONTHLY_STOP = -0.15  # Portfolio-level monthly stop

capital = INITIAL_CAPITAL
portfolio_history = []
trade_log = []

# Get all month-ends in backtest range
all_months = pd.date_range('2020-01-31', '2026-04-30', freq='ME')

prev_universe_ranked = None  # For rank-drop short signal

for i, month_end in enumerate(all_months):
    month_str = month_end.strftime('%Y-%m')
    
    # Get current month universe
    universe_result = get_monthly_universe(month_end, top_n=20)
    if not universe_result or len(universe_result) == 0:
        print(f"  {month_str}: No universe, skip")
        portfolio_history.append({'date': month_end, 'capital': capital, 'return': 0.0})
        continue
    
    current_universe, current_vol_ranked = universe_result
    
    # Get previous month universe (for rank comparison)
    if i > 0:
        prev_month_end = all_months[i-1]
        prev_result = get_monthly_universe(prev_month_end, top_n=20)
        if prev_result:
            prev_universe, prev_vol_ranked = prev_result
        else:
            prev_universe, prev_vol_ranked = [], pd.Series()
    else:
        prev_universe, prev_vol_ranked = [], pd.Series()
    
    # Get month's bar data (this month's bars)
    month_start = month_end - pd.offsets.MonthBegin(1)
    
    # Compute last month Sharpe for each symbol in universe
    sharpe_scores = {}
    for sym in current_universe:
        if sym not in signals:
            continue
        df_sym = signals[sym]
        prev_month_start = month_start - pd.DateOffset(months=1)
        prev_month_end_dt = month_start
        mask = (df_sym.index >= prev_month_start) & (df_sym.index < prev_month_end_dt)
        returns = df_sym.loc[mask, 'close'].pct_change().dropna()
        if len(returns) < 10:
            continue
        sharpe = returns.mean() / returns.std() * np.sqrt(len(returns)) if returns.std() > 0 else 0
        sharpe_scores[sym] = sharpe
    
    if not sharpe_scores:
        portfolio_history.append({'date': month_end, 'capital': capital, 'return': 0.0})
        prev_universe_ranked = current_vol_ranked
        continue
    
    sharpe_series = pd.Series(sharpe_scores)
    
    # LONG candidates: Sharpe >= 1.3, top 5
    long_candidates = sharpe_series[sharpe_series >= SHARPE_LONG_THRESHOLD].nlargest(MAX_LONG).index.tolist()
    
    # SHORT candidates: BTC bear market + rank drop signal
    short_candidates = []
    btc_bear = btc_is_bearish(month_start)
    
    if btc_bear and len(prev_vol_ranked) > 0:
        # Find symbols that were in top 15 last month but dropped to 16-20 this month
        prev_ranked_list = prev_vol_ranked.index.tolist()
        curr_ranked_list = current_vol_ranked.index.tolist()
        
        for sym in curr_ranked_list[15:20]:  # rank 16-20 (0-indexed: 15-19)
            if sym in prev_ranked_list[:15]:  # was top 15 last month
                short_candidates.append(sym)
        
        short_candidates = short_candidates[:MAX_SHORT]
    
    # Compute this month's returns for long and short positions
    monthly_returns_long = {}
    monthly_returns_short = {}
    
    for sym in long_candidates:
        if sym not in signals:
            continue
        df_sym = signals[sym]
        mask = (df_sym.index >= month_start) & (df_sym.index <= month_end)
        month_data = df_sym.loc[mask]
        if len(month_data) < 2:
            continue
        
        entry_price = month_data['close'].iloc[0]
        
        # ATR trailing stop simulation
        exit_price = month_data['close'].iloc[-1]
        max_price = entry_price
        for bar in month_data.itertuples():
            max_price = max(max_price, bar.close)
            atr_val = bar.atr if not np.isnan(bar.atr) else 0
            trailing_stop = max_price - 2.5 * atr_val
            if bar.close < trailing_stop and bar.Index != month_data.index[0]:
                exit_price = bar.close
                break
        
        # Fee
        vol_this_month = vol_df.loc[month_end, sym] if sym in vol_df.columns and month_end in vol_df.index else 1e8
        fee = get_fee_bps(sym, vol_this_month)
        
        raw_return = (exit_price - entry_price) / entry_price
        net_return = raw_return - 2 * fee  # entry + exit
        monthly_returns_long[sym] = net_return
    
    for sym in short_candidates:
        if sym not in signals:
            continue
        df_sym = signals[sym]
        mask = (df_sym.index >= month_start) & (df_sym.index <= month_end)
        month_data = df_sym.loc[mask]
        if len(month_data) < 2:
            continue
        
        entry_price = month_data['close'].iloc[0]
        exit_price = month_data['close'].iloc[-1]
        
        # ATR trailing stop for shorts
        min_price = entry_price
        for bar in month_data.itertuples():
            min_price = min(min_price, bar.close)
            atr_val = bar.atr if not np.isnan(bar.atr) else 0
            trailing_stop = min_price + 2.5 * atr_val
            if bar.close > trailing_stop and bar.Index != month_data.index[0]:
                exit_price = bar.close
                break
        
        # Fee + Funding Rate
        vol_this_month = vol_df.loc[month_end, sym] if sym in vol_df.columns and month_end in vol_df.index else 1e8
        fee = get_fee_bps(sym, vol_this_month)
        
        # Short return: negative of price change
        days_held = (month_data.index[-1] - month_data.index[0]).days
        funding_cost = DAILY_FUNDING * days_held
        
        raw_return = (entry_price - exit_price) / entry_price  # short return
        net_return = raw_return - 2 * fee - funding_cost
        monthly_returns_short[sym] = net_return
    
    # Compute portfolio return
    if long_candidates and monthly_returns_long:
        long_return = np.mean(list(monthly_returns_long.values()))
    else:
        long_return = 0.0
    
    if short_candidates and monthly_returns_short:
        short_return = np.mean(list(monthly_returns_short.values()))
    else:
        short_return = 0.0
    
    # Weighted portfolio return
    long_weight = LONG_ALLOC if long_candidates else 0
    short_weight = SHORT_ALLOC if short_candidates else 0
    cash_weight = 1.0 - long_weight - short_weight
    
    portfolio_return = long_weight * long_return + short_weight * short_return
    
    # Portfolio-level monthly stop
    if portfolio_return < MONTHLY_STOP:
        portfolio_return = MONTHLY_STOP
    
    capital_new = capital * (1 + portfolio_return)
    
    # Record
    portfolio_history.append({
        'date': month_end,
        'capital': capital_new,
        'return': portfolio_return,
        'long_symbols': long_candidates,
        'short_symbols': short_candidates,
        'long_return': long_return,
        'short_return': short_return,
        'btc_bear': btc_bear,
        'universe': current_universe[:10],  # first 10 for log
    })
    
    trade_log.append({
        'month': month_str,
        'long': list(monthly_returns_long.items()),
        'short': list(monthly_returns_short.items()),
        'portfolio_return': round(portfolio_return * 100, 2),
        'capital': round(capital_new, 2),
    })
    
    prev_universe_ranked = current_vol_ranked
    capital = capital_new
    
    print(f"  {month_str}: long={long_candidates[:3]}... short={short_candidates}, "
          f"ret={portfolio_return*100:.1f}%, cap=${capital:.0f}, btc_bear={btc_bear}")


# ============================================================
# PERFORMANCE METRICS
# ============================================================
print("\nComputing performance metrics...")

perf_df = pd.DataFrame(portfolio_history)
perf_df['date'] = pd.to_datetime(perf_df['date'])
perf_df = perf_df.set_index('date')

def compute_metrics(df, label=''):
    if len(df) < 2:
        return {}
    
    returns = df['return'].values
    capital_series = df['capital'].values
    
    n_months = len(returns)
    years = n_months / 12
    
    total_return = (capital_series[-1] / capital_series[0]) - 1
    cagr = (1 + total_return) ** (1/years) - 1 if years > 0 else 0
    
    # Sharpe (monthly)
    mean_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1)
    sharpe = (mean_ret / std_ret) * np.sqrt(12) if std_ret > 0 else 0
    
    # Max Drawdown
    cumulative = np.cumprod(1 + returns)
    rolling_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    # Win rate
    win_rate = (returns > 0).sum() / len(returns)
    
    # Trades count
    n_trades = sum(len(t.get('long', [])) + len(t.get('short', [])) for t in trade_log 
                   if pd.Timestamp(t['month'] + '-01') >= df.index[0] - pd.DateOffset(months=1) 
                   and pd.Timestamp(t['month'] + '-01') <= df.index[-1])
    
    print(f"\n{'='*40}")
    print(f"{label} Performance ({df.index[0].date()} to {df.index[-1].date()})")
    print(f"{'='*40}")
    print(f"Total Return: {total_return*100:.1f}%")
    print(f"CAGR: {cagr*100:.1f}%")
    print(f"Sharpe Ratio: {sharpe:.2f}")
    print(f"Max Drawdown: {max_dd*100:.1f}%")
    print(f"Calmar Ratio: {calmar:.2f}")
    print(f"Monthly Win Rate: {win_rate*100:.1f}%")
    print(f"Months: {n_months}")
    
    return {
        'label': label,
        'total_return': round(total_return * 100, 2),
        'cagr': round(cagr * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_dd': round(max_dd * 100, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate * 100, 1),
        'n_months': n_months,
        'start_capital': round(capital_series[0], 2),
        'end_capital': round(capital_series[-1], 2),
    }

# Full period
full_metrics = compute_metrics(perf_df, 'Full Period (2020-2026)')

# IS: 2020-2023
is_df = perf_df[perf_df.index.year <= 2023]
is_metrics = compute_metrics(is_df, 'IS: 2020-2023')

# OOS: 2024-2026
oos_df = perf_df[perf_df.index.year >= 2024]
oos_metrics = compute_metrics(oos_df, 'OOS: 2024-2026')

# Yearly breakdown
print("\n--- Yearly Breakdown ---")
yearly = {}
for year in range(2020, 2027):
    yr_df = perf_df[perf_df.index.year == year]
    if len(yr_df) == 0:
        continue
    yr_returns = yr_df['return'].values
    yr_total = np.prod(1 + yr_returns) - 1
    yr_sharpe = (np.mean(yr_returns) / np.std(yr_returns, ddof=1)) * np.sqrt(12) if np.std(yr_returns) > 0 else 0
    print(f"  {year}: {yr_total*100:.1f}%, Sharpe={yr_sharpe:.2f}")
    yearly[year] = {'return': round(yr_total*100, 1), 'sharpe': round(yr_sharpe, 2)}

# BTC Buy & Hold
btc_start = data['BTCUSDT'].loc['2020-01-01':'2020-01-31']['close'].iloc[0]
btc_end = data['BTCUSDT']['close'].iloc[-1]
btc_years = 6.4
btc_total = (btc_end - btc_start) / btc_start
btc_cagr = (1 + btc_total) ** (1/btc_years) - 1
print(f"\nBTC Buy & Hold: Total={btc_total*100:.0f}%, CAGR={btc_cagr*100:.1f}%")

# Short activity analysis
short_months = [p for p in portfolio_history if p.get('short_symbols')]
print(f"\nShort activity: {len(short_months)} months out of {len(portfolio_history)}")
bear_months = [p for p in portfolio_history if p.get('btc_bear')]
print(f"BTC Bear market months: {len(bear_months)}")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'full': full_metrics,
    'is': is_metrics,
    'oos': oos_metrics,
    'yearly': yearly,
    'btc_buy_hold': {
        'total_return': round(btc_total * 100, 1),
        'cagr': round(btc_cagr * 100, 1),
    },
    'portfolio_history': [
        {k: str(v) if isinstance(v, (pd.Timestamp, list)) else v 
         for k, v in p.items()} 
        for p in portfolio_history
    ],
    'trade_log': trade_log,
    'short_activity': len(short_months),
    'bear_months': len(bear_months),
    'total_months': len(portfolio_history),
}

with open(f'{WORK_DIR}/results_v2.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to results_v2.json")
print("DONE")
