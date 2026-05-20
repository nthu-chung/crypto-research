"""
MVRV Strategy v2 - Full Round 2 Backtest
Addresses all Judge feedback from v1:
1. Threshold methodology: IS (2011-2019) percentile thresholds, OOS (2020-2026) frozen
2. Stop-loss: 20% trailing stop + volatility filter (30d vol > 100% -> reduce 20%)
3. OOS decay analysis with key turning points
4. Options simplified backtest (Covered Call, IV = HistVol x 1.3)
"""

import requests
import time
import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

# ─── 1. DATA FETCH ────────────────────────────────────────────────────────────

def fetch_coinmetrics(metrics, start="2011-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {
        "assets": "btc", "metrics": metrics,
        "frequency": "1d", "start_time": start, "page_size": 1000
    }
    while True:
        try:
            j = requests.get(url, params=params, timeout=30).json()
        except Exception as e:
            print(f"  Fetch error: {e}, retrying...")
            time.sleep(2)
            continue
        all_data.extend(j.get('data', []))
        token = j.get('next_page_token')
        if not token:
            break
        params = {"assets": "btc", "metrics": metrics,
                  "frequency": "1d", "page_size": 1000, "next_page_token": token}
        time.sleep(0.05)
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['time'])
    return df.sort_values('date').reset_index(drop=True)

print("Fetching BTC price data...")
price_df = fetch_coinmetrics("PriceUSD", start="2011-01-01")
print(f"  Price rows: {len(price_df)}")

print("Fetching MVRV data...")
mvrv_df = fetch_coinmetrics("CapMVRVCur", start="2011-01-01")
print(f"  MVRV rows: {len(mvrv_df)}")

# Merge
df = pd.merge(
    price_df[['date', 'PriceUSD']],
    mvrv_df[['date', 'CapMVRVCur']],
    on='date', how='inner'
)
df['PriceUSD'] = pd.to_numeric(df['PriceUSD'], errors='coerce')
df['CapMVRVCur'] = pd.to_numeric(df['CapMVRVCur'], errors='coerce')
df = df.dropna(subset=['PriceUSD', 'CapMVRVCur']).reset_index(drop=True)
df = df[df['date'] >= '2011-01-01'].reset_index(drop=True)

print(f"Merged data: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")

# Apply MVRV data lag (T+1 delay - use previous day MVRV to avoid look-ahead bias)
df['MVRV'] = df['CapMVRVCur'].shift(1)  # 1-day lag
df = df.dropna(subset=['MVRV']).reset_index(drop=True)

# ─── 2. THRESHOLD METHODOLOGY ─────────────────────────────────────────────────

IS_END = '2019-12-31'
OOS_START = '2020-01-01'

is_data = df[df['date'] <= IS_END]
oos_data = df[df['date'] >= OOS_START]

# IS percentile-based thresholds (frozen for OOS)
p20 = np.percentile(is_data['MVRV'].dropna(), 20)
p40 = np.percentile(is_data['MVRV'].dropna(), 40)
p60 = np.percentile(is_data['MVRV'].dropna(), 60)
p80 = np.percentile(is_data['MVRV'].dropna(), 80)

print(f"\nIS Period MVRV Percentile Thresholds (2011-2019):")
print(f"  P20 = {p20:.4f}")
print(f"  P40 = {p40:.4f}")
print(f"  P60 = {p60:.4f}")
print(f"  P80 = {p80:.4f}")

# Fixed thresholds from v1
FIXED_THRESHOLDS = {'z1': 1.0, 'z2': 1.5, 'z3': 2.5, 'z4': 3.7}

def get_zone_percentile(mvrv, p20, p40, p60, p80):
    """5 zones based on percentile thresholds"""
    if mvrv <= p20:
        return 1  # Deep value
    elif mvrv <= p40:
        return 2  # Value
    elif mvrv <= p60:
        return 3  # Fair value
    elif mvrv <= p80:
        return 4  # Overvalued
    else:
        return 5  # Extreme overvalued

def get_zone_fixed(mvrv, thresholds):
    if mvrv <= thresholds['z1']:
        return 1
    elif mvrv <= thresholds['z2']:
        return 2
    elif mvrv <= thresholds['z3']:
        return 3
    elif mvrv <= thresholds['z4']:
        return 4
    else:
        return 5

ZONE_ALLOC = {1: 1.0, 2: 0.75, 3: 0.50, 4: 0.25, 5: 0.0}

# ─── 3. BACKTEST ENGINE ───────────────────────────────────────────────────────

def run_backtest(df, get_zone_fn, fee_bps=4, use_trailing_stop=False, use_vol_filter=False,
                 trailing_pct=0.20, vol_threshold=1.0, vol_reduce=0.20):
    """
    Full backtest engine with optional stop-loss and vol filter.
    """
    fee = fee_bps / 10000
    capital = 10000.0
    portfolio = []
    
    # State
    btc_held = 0.0
    cash = capital
    peak_portfolio = capital
    trailing_stop_active = False
    trailing_stop_exit_alloc = None  # forced allocation when stop triggered
    
    for i, row in df.iterrows():
        price = row['PriceUSD']
        mvrv = row['MVRV']
        date = row['date']
        
        # Current portfolio value
        port_val = cash + btc_held * price
        
        # Update peak
        if port_val > peak_portfolio:
            peak_portfolio = port_val
            trailing_stop_active = False
            trailing_stop_exit_alloc = None
        
        # Check trailing stop
        drawdown_from_peak = (peak_portfolio - port_val) / peak_portfolio
        if use_trailing_stop and drawdown_from_peak >= trailing_pct and not trailing_stop_active:
            trailing_stop_active = True
            # Force allocation to 50% of current zone's upper limit
            zone = get_zone_fn(mvrv)
            zone_alloc = ZONE_ALLOC[zone]
            trailing_stop_exit_alloc = zone_alloc * 0.5
        
        # Determine target allocation
        zone = get_zone_fn(mvrv)
        target_alloc = ZONE_ALLOC[zone]
        
        # Apply trailing stop override
        if trailing_stop_active and trailing_stop_exit_alloc is not None:
            target_alloc = min(target_alloc, trailing_stop_exit_alloc)
        
        # Apply volatility filter
        if use_vol_filter and i >= 30:
            recent_prices = df.iloc[max(0, i-30):i]['PriceUSD']
            log_rets = np.log(recent_prices / recent_prices.shift(1)).dropna()
            annualized_vol = log_rets.std() * np.sqrt(365)
            if annualized_vol > vol_threshold:
                target_alloc = max(0, target_alloc - vol_reduce)
        
        # Execute rebalance
        current_alloc = (btc_held * price) / port_val if port_val > 0 else 0
        diff = target_alloc - current_alloc
        
        if abs(diff) > 0.02:  # 2% threshold to avoid micro-trades
            trade_value = abs(diff) * port_val
            fee_cost = trade_value * fee
            if diff > 0:
                # Buy BTC
                cost = diff * port_val + fee_cost
                if cost <= cash:
                    btc_bought = (diff * port_val) / price
                    btc_held += btc_bought
                    cash -= cost
            else:
                # Sell BTC
                btc_sold = abs(diff) * port_val / price
                if btc_sold > btc_held:
                    btc_sold = btc_held
                proceeds = btc_sold * price - fee_cost
                btc_held -= btc_sold
                cash += proceeds
        
        port_val_after = cash + btc_held * price
        portfolio.append({
            'date': date,
            'price': price,
            'mvrv': mvrv,
            'zone': zone,
            'portfolio_value': port_val_after,
            'btc_held': btc_held,
            'cash': cash,
            'alloc': (btc_held * price) / port_val_after if port_val_after > 0 else 0
        })
    
    return pd.DataFrame(portfolio)

def calc_metrics(port_df, benchmark_df=None, start_capital=10000):
    """Calculate performance metrics"""
    pv = port_df['portfolio_value']
    dates = port_df['date']
    
    # Returns
    returns = pv.pct_change().dropna()
    total_return = (pv.iloc[-1] - pv.iloc[0]) / pv.iloc[0]
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    cagr = (pv.iloc[-1] / pv.iloc[0]) ** (1/years) - 1
    
    # Sharpe (annualized, risk-free = 0)
    sharpe = returns.mean() / returns.std() * np.sqrt(365) if returns.std() > 0 else 0
    
    # Max Drawdown
    cummax = pv.cummax()
    drawdown = (pv - cummax) / cummax
    max_dd = drawdown.min()
    
    # Win rate (positive monthly returns)
    temp_df = pd.DataFrame({'pv': pv.values, 'date': dates.values})
    temp_df = temp_df.set_index('date')
    temp_df.index = pd.to_datetime(temp_df.index).tz_localize(None)
    monthly = temp_df['pv'].resample('ME').last().pct_change().dropna()
    win_rate = (monthly > 0).mean()
    
    # Sortino
    neg_returns = returns[returns < 0]
    sortino = returns.mean() / neg_returns.std() * np.sqrt(365) if len(neg_returns) > 0 and neg_returns.std() > 0 else 0
    
    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    metrics = {
        'total_return': total_return,
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_drawdown': max_dd,
        'win_rate_monthly': win_rate,
        'calmar': calmar,
        'years': years
    }
    
    if benchmark_df is not None:
        bpv = benchmark_df['portfolio_value']
        b_total = (bpv.iloc[-1] - bpv.iloc[0]) / bpv.iloc[0]
        b_years = (benchmark_df['date'].iloc[-1] - benchmark_df['date'].iloc[0]).days / 365.25
        b_cagr = (bpv.iloc[-1] / bpv.iloc[0]) ** (1/b_years) - 1
        b_rets = bpv.pct_change().dropna()
        b_sharpe = b_rets.mean() / b_rets.std() * np.sqrt(365) if b_rets.std() > 0 else 0
        b_dd = ((bpv - bpv.cummax()) / bpv.cummax()).min()
        metrics['bh_cagr'] = b_cagr
        metrics['bh_sharpe'] = b_sharpe
        metrics['bh_max_dd'] = b_dd
    
    return metrics

# ─── 4. RUN ALL EXPERIMENTS ───────────────────────────────────────────────────

print("\n" + "="*60)
print("RUNNING BACKTESTS")
print("="*60)

# Percentile threshold functions
def zone_pct(mvrv): return get_zone_percentile(mvrv, p20, p40, p60, p80)
def zone_fix(mvrv): return get_zone_fixed(mvrv, FIXED_THRESHOLDS)

# ─── A: IS Period (2011-2019) ──────────────────────────────────────────────
df_is = df[df['date'] <= IS_END].reset_index(drop=True)
df_oos = df[df['date'] >= OOS_START].reset_index(drop=True)

# Buy and Hold benchmark
def bh_backtest(df_segment):
    pv = df_segment['PriceUSD'] / df_segment['PriceUSD'].iloc[0] * 10000
    return pd.DataFrame({'date': df_segment['date'], 'portfolio_value': pv.values})

bh_is = bh_backtest(df_is)
bh_oos = bh_backtest(df_oos)
bh_full = bh_backtest(df)

# Strategy variants on IS
print("\n[IS Period 2011-2019]")
res_is_pct = run_backtest(df_is, zone_pct)
res_is_fix = run_backtest(df_is, zone_fix)
res_is_pct_sl = run_backtest(df_is, zone_pct, use_trailing_stop=True, use_vol_filter=True)

m_is_pct = calc_metrics(res_is_pct, bh_is)
m_is_fix = calc_metrics(res_is_fix, bh_is)
m_is_pct_sl = calc_metrics(res_is_pct_sl, bh_is)

print(f"  Percentile threshold: Sharpe={m_is_pct['sharpe']:.3f}, CAGR={m_is_pct['cagr']:.1%}, MaxDD={m_is_pct['max_drawdown']:.1%}")
print(f"  Fixed threshold:      Sharpe={m_is_fix['sharpe']:.3f}, CAGR={m_is_fix['cagr']:.1%}, MaxDD={m_is_fix['max_drawdown']:.1%}")
print(f"  Pct + StopLoss:       Sharpe={m_is_pct_sl['sharpe']:.3f}, CAGR={m_is_pct_sl['cagr']:.1%}, MaxDD={m_is_pct_sl['max_drawdown']:.1%}")
print(f"  Buy & Hold:           Sharpe={m_is_pct['bh_sharpe']:.3f}, CAGR={m_is_pct['bh_cagr']:.1%}, MaxDD={m_is_pct['bh_max_dd']:.1%}")

# Strategy variants on OOS (frozen thresholds)
print("\n[OOS Period 2020-2026]")
res_oos_pct = run_backtest(df_oos, zone_pct)
res_oos_fix = run_backtest(df_oos, zone_fix)
res_oos_pct_sl = run_backtest(df_oos, zone_pct, use_trailing_stop=True, use_vol_filter=True)

m_oos_pct = calc_metrics(res_oos_pct, bh_oos)
m_oos_fix = calc_metrics(res_oos_fix, bh_oos)
m_oos_pct_sl = calc_metrics(res_oos_pct_sl, bh_oos)

print(f"  Percentile threshold: Sharpe={m_oos_pct['sharpe']:.3f}, CAGR={m_oos_pct['cagr']:.1%}, MaxDD={m_oos_pct['max_drawdown']:.1%}")
print(f"  Fixed threshold:      Sharpe={m_oos_fix['sharpe']:.3f}, CAGR={m_oos_fix['cagr']:.1%}, MaxDD={m_oos_fix['max_drawdown']:.1%}")
print(f"  Pct + StopLoss:       Sharpe={m_oos_pct_sl['sharpe']:.3f}, CAGR={m_oos_pct_sl['cagr']:.1%}, MaxDD={m_oos_pct_sl['max_drawdown']:.1%}")
print(f"  Buy & Hold:           Sharpe={m_oos_pct['bh_sharpe']:.3f}, CAGR={m_oos_pct['bh_cagr']:.1%}, MaxDD={m_oos_pct['bh_max_dd']:.1%}")

# Full period
print("\n[Full Period 2011-2026]")
res_full_pct = run_backtest(df, zone_pct)
res_full_pct_sl = run_backtest(df, zone_pct, use_trailing_stop=True, use_vol_filter=True)
res_full_fix = run_backtest(df, zone_fix)

m_full_pct = calc_metrics(res_full_pct, bh_full)
m_full_pct_sl = calc_metrics(res_full_pct_sl, bh_full)
m_full_fix = calc_metrics(res_full_fix, bh_full)

print(f"  Percentile threshold: Sharpe={m_full_pct['sharpe']:.3f}, CAGR={m_full_pct['cagr']:.1%}, MaxDD={m_full_pct['max_drawdown']:.1%}")
print(f"  Pct + StopLoss:       Sharpe={m_full_pct_sl['sharpe']:.3f}, CAGR={m_full_pct_sl['cagr']:.1%}, MaxDD={m_full_pct_sl['max_drawdown']:.1%}")
print(f"  Fixed threshold:      Sharpe={m_full_fix['sharpe']:.3f}, CAGR={m_full_fix['cagr']:.1%}, MaxDD={m_full_fix['max_drawdown']:.1%}")
print(f"  Buy & Hold:           Sharpe={m_full_pct['bh_sharpe']:.3f}, CAGR={m_full_pct['bh_cagr']:.1%}, MaxDD={m_full_pct['bh_max_dd']:.1%}")

# ─── 5. ANNUAL BREAKDOWN (FULL PERIOD) ────────────────────────────────────────

print("\n[Annual Returns - Full Period]")
annual_results = {}
for name, res in [('Pct_SL', res_full_pct_sl), ('Pct_NoSL', res_full_pct), ('Fixed', res_full_fix)]:
    res_c = res.copy()
    res_c['year'] = res_c['date'].dt.year
    yearly = {}
    for yr, grp in res_c.groupby('year'):
        if len(grp) > 1:
            ret = (grp['portfolio_value'].iloc[-1] / grp['portfolio_value'].iloc[0]) - 1
            yearly[yr] = ret
    annual_results[name] = yearly

bh_annual = {}
df['year'] = df['date'].dt.year
for yr, grp in df.groupby('year'):
    if len(grp) > 1:
        ret = (grp['PriceUSD'].iloc[-1] / grp['PriceUSD'].iloc[0]) - 1
        bh_annual[yr] = ret

all_years = sorted(set(list(annual_results['Pct_SL'].keys()) + list(bh_annual.keys())))
print(f"  {'Year':<6} {'Pct+SL':>10} {'Pct':>10} {'Fixed':>10} {'BH':>10}")
for yr in all_years:
    ps = annual_results['Pct_SL'].get(yr, float('nan'))
    pn = annual_results['Pct_NoSL'].get(yr, float('nan'))
    fx = annual_results['Fixed'].get(yr, float('nan'))
    bh = bh_annual.get(yr, float('nan'))
    print(f"  {yr:<6} {ps:>10.1%} {pn:>10.1%} {fx:>10.1%} {bh:>10.1%}")

# ─── 6. OOS DECAY ANALYSIS (2022-2026) ────────────────────────────────────────

print("\n[OOS Key Turning Points 2022-2026]")
oos_22_26 = df[(df['date'] >= '2022-01-01') & (df['date'] <= '2026-12-31')].reset_index(drop=True)
res_22_26 = res_full_pct_sl[res_full_pct_sl['date'] >= '2022-01-01'].reset_index(drop=True)

# Find key dates
key_events = [
    ('2022-01-01', 'Start 2022 Bear'),
    ('2022-05-09', 'LUNA Crash'),
    ('2022-06-18', 'BTC $17.7K Low'),
    ('2022-11-08', 'FTX Collapse'),
    ('2022-11-21', 'Post-FTX Low'),
    ('2023-01-01', 'Start 2023'),
    ('2023-03-10', 'Silicon Valley Bank'),
    ('2024-01-11', 'ETF Approval'),
    ('2024-04-19', 'Halving'),
    ('2024-11-07', 'Post-Election ATH'),
    ('2025-01-20', '2025 Start'),
    ('2025-04-01', 'Q2 2025'),
    ('2026-01-01', 'Start 2026 (if data)'),
]

print(f"  {'Date':<14} {'Event':<30} {'BTC Price':>12} {'MVRV':>8} {'Zone':>6} {'Alloc':>8}")
for date_str, event in key_events:
    target_date = pd.to_datetime(date_str).tz_localize('UTC')
    row = res_full_pct_sl[res_full_pct_sl['date'] >= target_date]
    if len(row) == 0:
        continue
    row = row.iloc[0]
    price_row = df[df['date'] >= target_date]
    if len(price_row) == 0:
        continue
    price_row = price_row.iloc[0]
    print(f"  {str(row['date'].date()):<14} {event:<30} ${price_row['PriceUSD']:>10,.0f} {price_row['MVRV']:>8.2f} {int(row['zone']):>6} {row['alloc']:>8.1%}")

# ─── 7. STOP-LOSS IMPACT ANALYSIS ─────────────────────────────────────────────

print("\n[Stop-Loss Impact: OOS Period]")
res_oos_no_sl = run_backtest(df_oos, zone_pct)
res_oos_sl_only = run_backtest(df_oos, zone_pct, use_trailing_stop=True, use_vol_filter=False)
res_oos_vol_only = run_backtest(df_oos, zone_pct, use_trailing_stop=False, use_vol_filter=True)
res_oos_both = run_backtest(df_oos, zone_pct, use_trailing_stop=True, use_vol_filter=True)

for name, res in [('No StopLoss', res_oos_no_sl), ('Trailing Stop Only', res_oos_sl_only),
                  ('Vol Filter Only', res_oos_vol_only), ('Both', res_oos_both)]:
    m = calc_metrics(res, bh_oos)
    print(f"  {name:<25} Sharpe={m['sharpe']:.3f} CAGR={m['cagr']:.1%} MaxDD={m['max_drawdown']:.1%}")

# ─── 8. OPTIONS BACKTEST (COVERED CALL - SIMPLIFIED) ─────────────────────────

print("\n[Options: Covered Call OOS Period]")
# When in Zone 3 (MVRV P40-P60, fair value), sell monthly covered calls
# Assumption: IV = HistVol_30d * 1.3, sell 10% OTM call, collect ~2-3% monthly premium
# Delta ~0.2-0.3 at 10% OTM

# Compute 30-day historical vol for OOS
df_oos_opt = df_oos.copy()
df_oos_opt['log_ret'] = np.log(df_oos_opt['PriceUSD'] / df_oos_opt['PriceUSD'].shift(1))
df_oos_opt['hist_vol_30'] = df_oos_opt['log_ret'].rolling(30).std() * np.sqrt(365)

# Black-Scholes approximation for 10% OTM call premium
# Using simplified: call_prem ≈ S * IV * sqrt(T/365) * N(d1) where T=30 days
# For 10% OTM, use simplified ATM vol * sqrt(T) * 0.4 (rough delta-adjusted)
from math import log, sqrt, exp
from scipy.stats import norm

def bs_call_price(S, K, T, sigma, r=0):
    """Black-Scholes call price"""
    if sigma <= 0 or T <= 0:
        return 0
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    return S * norm.cdf(d1) - K * exp(-r*T) * norm.cdf(d2)

# Monthly covered call P&L
monthly_cc_pnl = []
df_oos_opt['zone'] = df_oos_opt['MVRV'].apply(zone_pct)

# Sample monthly (end of each month)
months = df_oos_opt.groupby(df_oos_opt['date'].dt.to_period('M'))
for period, grp in months:
    if len(grp) < 5:
        continue
    # Check zone at start of month
    first_row = grp.iloc[0]
    zone = first_row['zone']
    if zone != 3:  # Only sell CC in Zone 3 (fair value)
        continue
    
    S = first_row['PriceUSD']
    hist_vol = first_row.get('hist_vol_30', 0.8)
    if pd.isna(hist_vol) or hist_vol <= 0:
        hist_vol = 0.8
    
    implied_vol = hist_vol * 1.3  # IV premium assumption
    K = S * 1.10  # 10% OTM call
    T = 30/365
    
    premium = bs_call_price(S, K, T, implied_vol)
    premium_pct = premium / S  # as % of spot
    
    # End of month price
    last_price = grp.iloc[-1]['PriceUSD']
    
    # P&L: collect premium, offset by assignment if BTC > K
    if last_price > K:
        # Called away at K, lose upside (last_price - K)
        net_pnl_pct = (K - S) / S + premium_pct  # sell at K + premium
    else:
        net_pnl_pct = premium_pct  # keep full premium
    
    monthly_cc_pnl.append({
        'month': str(period),
        'S': S, 'K': K, 'IV': implied_vol, 'hist_vol': hist_vol,
        'premium': premium, 'premium_pct': premium_pct,
        'end_price': last_price, 'net_pnl_pct': net_pnl_pct
    })

cc_df = pd.DataFrame(monthly_cc_pnl)
if len(cc_df) > 0:
    print(f"  Covered Call months (Zone 3 only): {len(cc_df)}")
    print(f"  Average monthly premium: {cc_df['premium_pct'].mean():.2%}")
    print(f"  Average net P&L per month: {cc_df['net_pnl_pct'].mean():.2%}")
    print(f"  Total OOS CC P&L contribution: {cc_df['net_pnl_pct'].sum():.2%}")
    print(f"  Win rate (positive P&L months): {(cc_df['net_pnl_pct'] > 0).mean():.1%}")
    print(f"\n  Sample months:")
    for _, r in cc_df.head(8).iterrows():
        print(f"    {r['month']}: S=${r['S']:,.0f} K=${r['K']:,.0f} IV={r['IV']:.1%} "
              f"Prem={r['premium_pct']:.2%} NetPnL={r['net_pnl_pct']:.2%}")
else:
    print("  No Zone 3 months found in OOS period")

# ─── 9. QUARTERLY OOS PERFORMANCE ─────────────────────────────────────────────

print("\n[Quarterly OOS Performance - Percentile+StopLoss]")
res_oos_q = res_full_pct_sl[res_full_pct_sl['date'] >= pd.to_datetime('2022-01-01').tz_localize('UTC')].copy()
res_oos_q['quarter'] = res_oos_q['date'].dt.to_period('Q')
bh_oos_q = df[df['date'] >= pd.to_datetime('2022-01-01').tz_localize('UTC')].copy()
bh_oos_q['quarter'] = bh_oos_q['date'].dt.to_period('Q')

print(f"  {'Quarter':<10} {'Strategy':>12} {'BH':>12} {'Alpha':>12}")
for q in res_oos_q['quarter'].unique():
    s_grp = res_oos_q[res_oos_q['quarter'] == q]
    b_grp = bh_oos_q[bh_oos_q['quarter'] == q]
    if len(s_grp) < 2 or len(b_grp) < 2:
        continue
    s_ret = (s_grp['portfolio_value'].iloc[-1] / s_grp['portfolio_value'].iloc[0]) - 1
    b_ret = (b_grp['PriceUSD'].iloc[-1] / b_grp['PriceUSD'].iloc[0]) - 1
    alpha = s_ret - b_ret
    print(f"  {str(q):<10} {s_ret:>12.1%} {b_ret:>12.1%} {alpha:>12.1%}")

# ─── 10. SAVE RESULTS ─────────────────────────────────────────────────────────

results_summary = {
    'thresholds': {
        'method': 'IS 2011-2019 historical percentiles (frozen for OOS)',
        'p20': float(p20), 'p40': float(p40), 'p60': float(p60), 'p80': float(p80),
        'fixed_v1': FIXED_THRESHOLDS
    },
    'is_period': {
        'pct_threshold': {k: float(v) for k, v in m_is_pct.items()},
        'fixed_threshold': {k: float(v) for k, v in m_is_fix.items()},
        'pct_with_sl': {k: float(v) for k, v in m_is_pct_sl.items()},
    },
    'oos_period': {
        'pct_threshold': {k: float(v) for k, v in m_oos_pct.items()},
        'fixed_threshold': {k: float(v) for k, v in m_oos_fix.items()},
        'pct_with_sl': {k: float(v) for k, v in m_oos_pct_sl.items()},
    },
    'full_period': {
        'pct_threshold': {k: float(v) for k, v in m_full_pct.items()},
        'pct_with_sl': {k: float(v) for k, v in m_full_pct_sl.items()},
        'fixed_threshold': {k: float(v) for k, v in m_full_fix.items()},
    },
    'annual': {
        'pct_sl': {str(k): float(v) for k, v in annual_results['Pct_SL'].items()},
        'pct_no_sl': {str(k): float(v) for k, v in annual_results['Pct_NoSL'].items()},
        'fixed': {str(k): float(v) for k, v in annual_results['Fixed'].items()},
        'bh': {str(k): float(v) for k, v in bh_annual.items()}
    },
    'options': {
        'total_months': len(cc_df),
        'avg_premium_pct': float(cc_df['premium_pct'].mean()) if len(cc_df) > 0 else 0,
        'avg_net_pnl_pct': float(cc_df['net_pnl_pct'].mean()) if len(cc_df) > 0 else 0,
        'total_pnl_pct': float(cc_df['net_pnl_pct'].sum()) if len(cc_df) > 0 else 0,
        'win_rate': float((cc_df['net_pnl_pct'] > 0).mean()) if len(cc_df) > 0 else 0
    }
}

with open('/root/.openclaw/workspace/research/results_v2.json', 'w') as f:
    json.dump(results_summary, f, indent=2)

print("\nResults saved to results_v2.json")
print("\n" + "="*60)
print("BACKTEST COMPLETE")
print("="*60)
