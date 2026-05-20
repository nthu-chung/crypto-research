"""
AdaptiveTrend v3 Backtest
Improvements from Judge v2:
1. Dynamic multi allocation (BTC RV30 based: 70%/55%/40%)
2. Improved short signal: OR condition (rank decay OR universe avg Sharpe < 0)
3. Preservation mode: if no Sharpe>=1.3 but Sharpe>=0.8 AND BTC bull → 42% allocation
"""

import os, pandas as pd, numpy as np, json

WORK_DIR = '/root/.openclaw/workspace/crypto-research/adaptive-trend'
CACHE_DIR = f'{WORK_DIR}/cache'

symbols = ['BTCUSDT','ETHUSDT','XRPUSDT','BNBUSDT','LTCUSDT','BCHUSDT','ADAUSDT','LINKUSDT',
           'DOTUSDT','UNIUSDT','SOLUSDT','MATICUSDT','DOGEUSDT','AVAXUSDT','ATOMUSDT',
           'XLMUSDT','VETUSDT','TRXUSDT','ETCUSDT','FILUSDT','THETAUSDT','ALGOUSDT',
           'XMRUSDT','ZECUSDT','DASHUSDT','EOSUSDT','XTZUSDT','AAVEUSDT','COMPUSDT','SUSHIUSDT']

# ============================================================
# LOAD DATA FROM CACHE
# ============================================================
print("Loading data from cache...")
data = {}
for sym in symbols:
    cache_file = f'{CACHE_DIR}/{sym}_6h.parquet'
    if os.path.exists(cache_file):
        df = pd.read_parquet(cache_file)
        if 'quote_vol' not in df.columns:
            df['quote_vol'] = df['close'] * df['volume']
        if len(df) > 100:
            data[sym] = df
            
print(f"Loaded {len(data)} symbols from cache")

# ============================================================
# MONTHLY VOLUME UNIVERSE
# ============================================================
monthly_vol = {}
for sym, df in data.items():
    mv = df['quote_vol'].resample('ME').sum()
    monthly_vol[sym] = mv
vol_df = pd.DataFrame(monthly_vol).fillna(0)

def get_monthly_universe(month_end, top_n=20, min_daily_vol=5e7):
    if month_end not in vol_df.index:
        available = vol_df.index[vol_df.index <= month_end]
        if len(available) == 0:
            return [], pd.Series()
        month_end = available[-1]
    row = vol_df.loc[month_end]
    active = row[row > 0]
    active = active[active / 30 > min_daily_vol]
    ranked = active.nlargest(top_n)
    return ranked.index.tolist(), ranked

# ============================================================
# SIGNALS
# ============================================================
def compute_signals(df, roc_period=20, atr_period=14, atr_mult=2.5):
    df = df.copy()
    df['roc'] = df['close'].pct_change(roc_period)
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    df['tr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(atr_period).mean()
    return df

print("Computing signals...")
signals = {}
for sym, df in data.items():
    signals[sym] = compute_signals(df)

# ============================================================
# BTC TREND + RV30
# ============================================================
btc = data['BTCUSDT'].copy()
btc['ma90'] = btc['close'].rolling(360).mean()  # 90d * 4bars/6h
btc['bear_market'] = btc['close'] < btc['ma90']

# BTC RV30: 30-day realized volatility
# Use daily close returns
btc_daily = btc['close'].resample('D').last()
btc_daily_returns = btc_daily.pct_change()
btc_rv30_daily = btc_daily_returns.rolling(30).std() * np.sqrt(365)  # annualized

def get_btc_state(date):
    # Get bear/bull
    avail = btc.index[btc.index <= date]
    if len(avail) == 0:
        return False, 0.5
    bear = btc.loc[avail[-1], 'bear_market']
    
    # Get RV30
    avail_daily = btc_rv30_daily.index[btc_rv30_daily.index <= pd.Timestamp(date)]
    if len(avail_daily) == 0:
        return bear, 0.5
    rv30 = btc_rv30_daily.loc[avail_daily[-1]]
    if pd.isna(rv30):
        rv30 = 0.5
    return bear, rv30

def get_long_allocation(rv30):
    """Dynamic allocation based on BTC volatility."""
    if rv30 < 0.50:
        return 0.70
    elif rv30 < 0.80:
        return 0.55
    else:
        return 0.40

# ============================================================
# COST MODEL
# ============================================================
FUNDING_RATE_8H = 0.0001
DAILY_FUNDING = FUNDING_RATE_8H * 3

def get_fee_bps(monthly_vol_usd):
    daily_vol = monthly_vol_usd / 30
    if daily_vol > 5e8:
        return 0.0004
    elif daily_vol > 5e7:
        return 0.0008
    else:
        return 0.0015

# ============================================================
# WALK-FORWARD BACKTEST
# ============================================================
print("Running backtest v3...")

INITIAL_CAPITAL = 10000.0
MAX_LONG = 5
MAX_SHORT = 3
SHARPE_LONG_THRESHOLD = 1.3
SHARPE_PRESERVATION = 0.8
MONTHLY_STOP = -0.15

capital = INITIAL_CAPITAL
portfolio_history = []
all_months = pd.date_range('2020-01-31', '2026-04-30', freq='ME')

for i, month_end in enumerate(all_months):
    month_str = month_end.strftime('%Y-%m')
    month_start = month_end - pd.offsets.MonthBegin(1)
    
    # Get universe
    curr_result = get_monthly_universe(month_end)
    if not curr_result or len(curr_result[0]) == 0:
        portfolio_history.append({'date': month_end, 'capital': capital, 'return': 0.0, 'mode': 'no_universe'})
        continue
    current_universe, current_vol_ranked = curr_result
    
    prev_result = get_monthly_universe(all_months[i-1]) if i > 0 else ([], pd.Series())
    prev_universe, prev_vol_ranked = prev_result if prev_result else ([], pd.Series())
    
    # BTC state
    btc_bear, rv30 = get_btc_state(month_start)
    long_alloc_base = get_long_allocation(rv30)
    
    # Compute last month Sharpe for universe
    sharpe_scores = {}
    for sym in current_universe:
        if sym not in signals:
            continue
        df_sym = signals[sym]
        prev_month_start = month_start - pd.DateOffset(months=1)
        mask = (df_sym.index >= prev_month_start) & (df_sym.index < month_start)
        returns = df_sym.loc[mask, 'close'].pct_change().dropna()
        if len(returns) < 10:
            continue
        sharpe = returns.mean() / returns.std() * np.sqrt(len(returns)) if returns.std() > 0 else 0
        sharpe_scores[sym] = sharpe
    
    if not sharpe_scores:
        portfolio_history.append({'date': month_end, 'capital': capital, 'return': 0.0, 'mode': 'no_signals'})
        continue
    
    sharpe_series = pd.Series(sharpe_scores)
    universe_avg_sharpe = sharpe_series.mean()
    
    # LONG candidates
    long_candidates = sharpe_series[sharpe_series >= SHARPE_LONG_THRESHOLD].nlargest(MAX_LONG).index.tolist()
    mode = 'normal'
    
    # Preservation mode: if no primary long candidates
    if not long_candidates and not btc_bear:
        preservation_candidates = sharpe_series[sharpe_series >= SHARPE_PRESERVATION].nlargest(2).index.tolist()
        if preservation_candidates:
            long_candidates = preservation_candidates
            long_alloc_base = long_alloc_base * 0.60  # reduce to 60% of normal
            mode = 'preservation'
    
    # SHORT candidates (OR condition)
    short_candidates = []
    if btc_bear:
        # Condition A: Rank decay (<=15 to 16-20)
        if len(prev_vol_ranked) > 0:
            curr_ranked_list = current_vol_ranked.index.tolist()
            prev_ranked_list = prev_vol_ranked.index.tolist()
            for sym in curr_ranked_list[15:20]:
                if sym in prev_ranked_list[:15]:
                    short_candidates.append(sym)
        
        # Condition B: Universe avg Sharpe < 0 → short worst Sharpe symbols
        if universe_avg_sharpe < 0:
            worst_sharpe = sharpe_series.nsmallest(2).index.tolist()
            for sym in worst_sharpe:
                if sym not in short_candidates:
                    short_candidates.append(sym)
        
        short_candidates = short_candidates[:MAX_SHORT]
    
    # Compute returns
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
        exit_price = month_data['close'].iloc[-1]
        max_price = entry_price
        
        for bar in month_data.itertuples():
            max_price = max(max_price, bar.close)
            atr_val = bar.atr if not np.isnan(bar.atr) else 0
            trailing_stop = max_price - 2.5 * atr_val
            if bar.close < trailing_stop and bar.Index != month_data.index[0]:
                exit_price = bar.close
                break
        
        vol_m = vol_df.loc[month_end, sym] if sym in vol_df.columns and month_end in vol_df.index else 1e8
        fee = get_fee_bps(vol_m)
        raw_return = (exit_price - entry_price) / entry_price
        monthly_returns_long[sym] = raw_return - 2 * fee
    
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
        min_price = entry_price
        
        for bar in month_data.itertuples():
            min_price = min(min_price, bar.close)
            atr_val = bar.atr if not np.isnan(bar.atr) else 0
            trailing_stop = min_price + 2.5 * atr_val
            if bar.close > trailing_stop and bar.Index != month_data.index[0]:
                exit_price = bar.close
                break
        
        vol_m = vol_df.loc[month_end, sym] if sym in vol_df.columns and month_end in vol_df.index else 1e8
        fee = get_fee_bps(vol_m)
        days_held = (month_data.index[-1] - month_data.index[0]).days
        funding_cost = DAILY_FUNDING * days_held
        raw_return = (entry_price - exit_price) / entry_price
        monthly_returns_short[sym] = raw_return - 2 * fee - funding_cost
    
    # Portfolio return
    long_return = np.mean(list(monthly_returns_long.values())) if monthly_returns_long else 0.0
    short_return = np.mean(list(monthly_returns_short.values())) if monthly_returns_short else 0.0
    
    long_weight = long_alloc_base if long_candidates else 0
    short_weight = 0.30 if short_candidates else 0
    
    portfolio_return = long_weight * long_return + short_weight * short_return
    if portfolio_return < MONTHLY_STOP:
        portfolio_return = MONTHLY_STOP
    
    capital_new = capital * (1 + portfolio_return)
    
    portfolio_history.append({
        'date': month_end, 'capital': capital_new, 'return': portfolio_return,
        'long_symbols': long_candidates, 'short_symbols': short_candidates,
        'long_return': long_return, 'short_return': short_return,
        'btc_bear': bool(btc_bear), 'rv30': round(float(rv30), 3),
        'long_alloc': long_weight, 'mode': mode,
        'universe_avg_sharpe': round(float(universe_avg_sharpe), 3),
    })
    
    capital = capital_new

# ============================================================
# METRICS
# ============================================================
print("Computing metrics...")
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
    mean_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1)
    sharpe = (mean_ret / std_ret) * np.sqrt(12) if std_ret > 0 else 0
    cumulative = np.cumprod(1 + returns)
    rolling_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - rolling_max) / rolling_max
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    win_rate = (returns > 0).sum() / len(returns)
    
    print(f"\n{label}: Total={total_return*100:.1f}%, CAGR={cagr*100:.1f}%, "
          f"Sharpe={sharpe:.2f}, MaxDD={max_dd*100:.1f}%, Calmar={calmar:.2f}, "
          f"WinRate={win_rate*100:.1f}%")
    
    return {
        'total_return': round(total_return*100, 2),
        'cagr': round(cagr*100, 2),
        'sharpe': round(sharpe, 2),
        'max_dd': round(max_dd*100, 2),
        'calmar': round(calmar, 2),
        'win_rate': round(win_rate*100, 1),
        'n_months': n_months,
    }

full = compute_metrics(perf_df, 'Full (2020-2026)')
is_m = compute_metrics(perf_df[perf_df.index.year <= 2023], 'IS (2020-2023)')
oos_m = compute_metrics(perf_df[perf_df.index.year >= 2024], 'OOS (2024-2026)')

print("\n--- Yearly ---")
yearly = {}
for year in range(2020, 2027):
    yr_df = perf_df[perf_df.index.year == year]
    if len(yr_df) == 0:
        continue
    yr_r = np.prod(1 + yr_df['return'].values) - 1
    yr_sh = (np.mean(yr_df['return'].values) / np.std(yr_df['return'].values, ddof=1)) * np.sqrt(12) if np.std(yr_df['return'].values) > 0 else 0
    print(f"  {year}: {yr_r*100:.1f}%, Sharpe={yr_sh:.2f}")
    yearly[year] = {'return': round(yr_r*100,1), 'sharpe': round(yr_sh,2)}

# Short and preservation analysis
short_months = [p for p in portfolio_history if p.get('short_symbols')]
preservation_months = [p for p in portfolio_history if p.get('mode') == 'preservation']
print(f"\nShort months: {len(short_months)}/76 ({len(short_months)/76*100:.1f}%)")
print(f"Preservation months: {len(preservation_months)}")

# Save results
results = {
    'full': full, 'is': is_m, 'oos': oos_m, 'yearly': yearly,
    'short_months': len(short_months),
    'preservation_months': len(preservation_months),
    'total_months': len(portfolio_history),
}
with open(f'{WORK_DIR}/results_v3.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print("\nResults saved to results_v3.json")
print("DONE")
