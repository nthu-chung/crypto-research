"""
AdaptiveTrend v4 - FINAL ROUND
Combines best of v2 and v3:
1. Keep v3's preservation mode (Sharpe >= 0.8, 42% alloc, BTC bull only)
2. Remove noisy Condition B short (universe avg Sharpe < 0)
3. Dynamic allocation ONLY in bear market (not bull high-vol)
4. Keep Condition A short (rank decay <=15 -> 16-20) + improved: rank drop with Sharpe < 0
"""

import os, pandas as pd, numpy as np, json

WORK_DIR = '/root/.openclaw/workspace/crypto-research/adaptive-trend'
CACHE_DIR = f'{WORK_DIR}/cache'

symbols = ['BTCUSDT','ETHUSDT','XRPUSDT','BNBUSDT','LTCUSDT','BCHUSDT','ADAUSDT','LINKUSDT',
           'DOTUSDT','UNIUSDT','SOLUSDT','MATICUSDT','DOGEUSDT','AVAXUSDT','ATOMUSDT',
           'XLMUSDT','VETUSDT','TRXUSDT','ETCUSDT','FILUSDT','THETAUSDT','ALGOUSDT',
           'XMRUSDT','ZECUSDT','DASHUSDT','EOSUSDT','XTZUSDT','AAVEUSDT','COMPUSDT','SUSHIUSDT']

# LOAD DATA
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
print(f"Loaded {len(data)} symbols")

# Monthly volume universe
monthly_vol = {}
for sym, df in data.items():
    monthly_vol[sym] = df['quote_vol'].resample('ME').sum()
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

# Signals
def compute_signals(df):
    df = df.copy()
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    df['tr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()
    return df

print("Computing signals...")
signals = {sym: compute_signals(df) for sym, df in data.items()}

# BTC trend + RV30
btc = data['BTCUSDT'].copy()
btc['ma90'] = btc['close'].rolling(360).mean()
btc['bear_market'] = btc['close'] < btc['ma90']
btc_daily = btc['close'].resample('D').last()
btc_rv30_daily = btc_daily.pct_change().rolling(30).std() * np.sqrt(365)

def get_btc_state(date):
    avail = btc.index[btc.index <= date]
    if len(avail) == 0:
        return False, 0.5
    bear = btc.loc[avail[-1], 'bear_market']
    avail_daily = btc_rv30_daily.index[btc_rv30_daily.index <= pd.Timestamp(date)]
    rv30 = btc_rv30_daily.loc[avail_daily[-1]] if len(avail_daily) > 0 else 0.5
    if pd.isna(rv30): rv30 = 0.5
    return bool(bear), float(rv30)

def get_long_allocation(bear, rv30):
    """
    v4 KEY CHANGE: Dynamic allocation ONLY in bear market.
    In bull market: always 70% regardless of volatility.
    In bear market: reduce based on RV30.
    """
    if not bear:
        return 0.70  # Bull market: always full 70%
    # Bear market: dynamic
    if rv30 < 0.50:
        return 0.70
    elif rv30 < 0.80:
        return 0.55
    else:
        return 0.40

FUNDING_RATE_8H = 0.0001
DAILY_FUNDING = FUNDING_RATE_8H * 3

def get_fee_bps(monthly_vol_usd):
    daily_vol = monthly_vol_usd / 30
    if daily_vol > 5e8: return 0.0004
    elif daily_vol > 5e7: return 0.0008
    else: return 0.0015

# BACKTEST
print("Running v4 backtest...")
INITIAL_CAPITAL = 10000.0
MAX_LONG = 5
MAX_SHORT = 3
SHARPE_LONG = 1.3
SHARPE_PRESERVE = 0.8
MONTHLY_STOP = -0.15

capital = INITIAL_CAPITAL
portfolio_history = []
all_months = pd.date_range('2020-01-31', '2026-04-30', freq='ME')

for i, month_end in enumerate(all_months):
    month_str = month_end.strftime('%Y-%m')
    month_start = month_end - pd.offsets.MonthBegin(1)
    
    curr_result = get_monthly_universe(month_end)
    if not curr_result or len(curr_result[0]) == 0:
        portfolio_history.append({'date': month_end, 'capital': capital, 'return': 0.0, 'mode': 'no_universe'})
        continue
    current_universe, current_vol_ranked = curr_result
    
    prev_result = get_monthly_universe(all_months[i-1]) if i > 0 else ([], pd.Series())
    prev_universe, prev_vol_ranked = prev_result if prev_result else ([], pd.Series())
    
    btc_bear, rv30 = get_btc_state(month_start)
    long_alloc = get_long_allocation(btc_bear, rv30)
    
    # Compute prev month Sharpe
    sharpe_scores = {}
    for sym in current_universe:
        if sym not in signals: continue
        df_sym = signals[sym]
        prev_start = month_start - pd.DateOffset(months=1)
        mask = (df_sym.index >= prev_start) & (df_sym.index < month_start)
        returns = df_sym.loc[mask, 'close'].pct_change().dropna()
        if len(returns) < 10: continue
        sharpe = returns.mean() / returns.std() * np.sqrt(len(returns)) if returns.std() > 0 else 0
        sharpe_scores[sym] = sharpe
    
    if not sharpe_scores:
        portfolio_history.append({'date': month_end, 'capital': capital, 'return': 0.0, 'mode': 'no_signals'})
        continue
    
    sharpe_series = pd.Series(sharpe_scores)
    
    # LONG candidates
    long_candidates = sharpe_series[sharpe_series >= SHARPE_LONG].nlargest(MAX_LONG).index.tolist()
    mode = 'normal'
    
    # Preservation mode: BTC bull + no primary candidates + some above 0.8
    if not long_candidates and not btc_bear:
        preserve_cands = sharpe_series[sharpe_series >= SHARPE_PRESERVE].nlargest(2).index.tolist()
        if preserve_cands:
            long_candidates = preserve_cands
            long_alloc = long_alloc * 0.60  # 70% * 0.60 = 42%
            mode = 'preservation'
    
    # SHORT candidates: v4 = ONLY Condition A (rank decay) - no Condition B
    short_candidates = []
    if btc_bear and len(prev_vol_ranked) > 0:
        curr_list = current_vol_ranked.index.tolist()
        prev_list = prev_vol_ranked.index.tolist()
        for sym in curr_list[15:20]:  # rank 16-20
            if sym in prev_list[:15]:  # was top 15
                # Extra filter: also require negative Sharpe
                if sharpe_scores.get(sym, 0) < 0:
                    short_candidates.append(sym)
        short_candidates = short_candidates[:MAX_SHORT]
    
    # Compute monthly returns
    def get_month_return(sym, is_short=False):
        if sym not in signals: return None
        df_sym = signals[sym]
        mask = (df_sym.index >= month_start) & (df_sym.index <= month_end)
        md = df_sym.loc[mask]
        if len(md) < 2: return None
        entry = md['close'].iloc[0]
        exit_p = md['close'].iloc[-1]
        
        if not is_short:
            max_p = entry
            for bar in md.itertuples():
                max_p = max(max_p, bar.close)
                atr_v = bar.atr if not np.isnan(bar.atr) else 0
                if bar.close < max_p - 2.5 * atr_v and bar.Index != md.index[0]:
                    exit_p = bar.close; break
            raw = (exit_p - entry) / entry
        else:
            min_p = entry
            for bar in md.itertuples():
                min_p = min(min_p, bar.close)
                atr_v = bar.atr if not np.isnan(bar.atr) else 0
                if bar.close > min_p + 2.5 * atr_v and bar.Index != md.index[0]:
                    exit_p = bar.close; break
            raw = (entry - exit_p) / entry
        
        vol_m = vol_df.loc[month_end, sym] if sym in vol_df.columns and month_end in vol_df.index else 1e8
        fee = get_fee_bps(vol_m)
        
        if is_short:
            days = (md.index[-1] - md.index[0]).days
            return raw - 2 * fee - DAILY_FUNDING * days
        return raw - 2 * fee
    
    long_returns = {s: r for s in long_candidates if (r := get_month_return(s)) is not None}
    short_returns = {s: r for s in short_candidates if (r := get_month_return(s, True)) is not None}
    
    long_ret = np.mean(list(long_returns.values())) if long_returns else 0.0
    short_ret = np.mean(list(short_returns.values())) if short_returns else 0.0
    
    long_w = long_alloc if long_candidates else 0
    short_w = 0.30 if short_candidates else 0
    
    port_ret = long_w * long_ret + short_w * short_ret
    if port_ret < MONTHLY_STOP:
        port_ret = MONTHLY_STOP
    
    capital_new = capital * (1 + port_ret)
    portfolio_history.append({
        'date': month_end, 'capital': capital_new, 'return': port_ret,
        'long_symbols': long_candidates, 'short_symbols': short_candidates,
        'btc_bear': btc_bear, 'rv30': round(rv30, 3),
        'long_alloc': long_w, 'mode': mode,
    })
    capital = capital_new

# METRICS
print("Computing metrics...")
perf_df = pd.DataFrame(portfolio_history)
perf_df['date'] = pd.to_datetime(perf_df['date'])
perf_df = perf_df.set_index('date')

def compute_metrics(df, label=''):
    if len(df) < 2: return {}
    r = df['return'].values
    cap = df['capital'].values
    n = len(r)
    total = (cap[-1] / cap[0]) - 1
    cagr = (1 + total) ** (12/n) - 1
    sharpe = (np.mean(r) / np.std(r, ddof=1)) * np.sqrt(12) if np.std(r) > 0 else 0
    cum = np.cumprod(1 + r)
    maxdd = ((cum - np.maximum.accumulate(cum)) / np.maximum.accumulate(cum)).min()
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0
    winrate = (r > 0).sum() / n
    print(f"{label}: CAGR={cagr*100:.1f}%, Sharpe={sharpe:.2f}, MaxDD={maxdd*100:.1f}%, "
          f"Calmar={calmar:.2f}, WinRate={winrate*100:.1f}%")
    return {'cagr': round(cagr*100,2), 'sharpe': round(sharpe,2), 'max_dd': round(maxdd*100,2),
            'calmar': round(calmar,2), 'win_rate': round(winrate*100,1), 'n_months': n,
            'total_return': round(total*100,2)}

full = compute_metrics(perf_df, 'Full (2020-2026)')
is_m = compute_metrics(perf_df[perf_df.index.year <= 2023], 'IS (2020-2023)')
oos_m = compute_metrics(perf_df[perf_df.index.year >= 2024], 'OOS (2024-2026)')

print("\n--- Yearly ---")
yearly = {}
for yr in range(2020, 2027):
    ydf = perf_df[perf_df.index.year == yr]
    if len(ydf) == 0: continue
    yr_r = np.prod(1 + ydf['return'].values) - 1
    yr_sh = (np.mean(ydf['return'].values) / np.std(ydf['return'].values, ddof=1)) * np.sqrt(12) if np.std(ydf['return'].values) > 0 else 0
    print(f"  {yr}: {yr_r*100:.1f}%, Sharpe={yr_sh:.2f}")
    yearly[yr] = {'return': round(yr_r*100,1), 'sharpe': round(yr_sh,2)}

short_months = [p for p in portfolio_history if p.get('short_symbols')]
preserve_months = [p for p in portfolio_history if p.get('mode') == 'preservation']
print(f"\nShort: {len(short_months)}, Preservation: {len(preserve_months)}")

results = {
    'full': full, 'is': is_m, 'oos': oos_m, 'yearly': yearly,
    'short_months': len(short_months), 'preservation_months': len(preserve_months),
    'total_months': len(portfolio_history),
}
with open(f'{WORK_DIR}/results_v4.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print("\nSaved results_v4.json")
print("DONE")
