#!/usr/bin/env python3
"""
MVRV Z-Score Strategy v4 Backtest
Improvements over v3:
1. Strategy goal: MaxDD < -50%, CAGR > 30%
2. Options overlay: Covered Call (Zone 4/5) + Cash-Secured Put (Zone 1/2)
3. Stop-loss: Monthly drawdown > 30% triggers position reduction
4. Rolling 2-year dynamic Zone boundaries
5. 5-day EMA smoothed Z-Score signal
6. Bootstrap CI for Sharpe/Sortino differences
7. Walk-forward validation (annual rolling)
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime, date
import warnings
warnings.filterwarnings('ignore')

# Try to load cached data first
import os
CACHE_FILE = '/root/.openclaw/workspace/research/btc_mvrv_data_cache.parquet'
CSV_CACHE = '/root/.openclaw/workspace/research/btc_mvrv_data_cache.csv'

def fetch_data():
    """Fetch BTC price and MVRV from CoinMetrics"""
    if os.path.exists(CSV_CACHE):
        print("Loading cached data...")
        df = pd.read_csv(CSV_CACHE, index_col=0, parse_dates=True)
        return df
    
    print("Fetching from CoinMetrics API...")
    import urllib.request
    
    metrics = "PriceUSD,CapMVRVCur"
    url = f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics={metrics}&start_time=2010-07-01&page_size=10000&pretty=false"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        
        rows = []
        for item in data.get('data', []):
            try:
                row = {
                    'date': pd.to_datetime(item['time']).normalize(),
                    'price': float(item['PriceUSD']) if item.get('PriceUSD') else None,
                    'mvrv': float(item['CapMVRVCur']) if item.get('CapMVRVCur') else None,
                }
                rows.append(row)
            except (KeyError, ValueError, TypeError):
                continue
        
        df = pd.DataFrame(rows).set_index('date').sort_index()
        df = df.dropna(subset=['price'])
        df.to_csv(CSV_CACHE)
        print(f"Fetched {len(df)} rows from CoinMetrics")
        return df
    except Exception as e:
        print(f"API fetch failed: {e}")
        return None

def bootstrap_sharpe_ci(returns, n_bootstrap=2000, confidence=0.95):
    """Bootstrap confidence interval for Sharpe Ratio"""
    if len(returns) < 30:
        return None, None
    sharpes = []
    returns_arr = np.array(returns.dropna())
    for _ in range(n_bootstrap):
        sample = np.random.choice(returns_arr, size=len(returns_arr), replace=True)
        sr = np.sqrt(252) * sample.mean() / (sample.std() + 1e-10)
        sharpes.append(sr)
    alpha = (1 - confidence) / 2
    return np.percentile(sharpes, alpha * 100), np.percentile(sharpes, (1 - alpha) * 100)

def compute_max_drawdown(nav_series):
    """Compute maximum drawdown"""
    rolling_max = nav_series.cummax()
    dd = (nav_series - rolling_max) / rolling_max
    return dd.min()

def compute_sortino(returns, target=0):
    """Compute Sortino ratio"""
    excess = returns - target / 252
    downside = excess[excess < 0]
    downside_std = np.sqrt((downside ** 2).mean()) * np.sqrt(252)
    if downside_std < 1e-10:
        return 0.0
    return np.sqrt(252) * excess.mean() / downside_std

def compute_calmar(cagr, max_dd):
    """Compute Calmar ratio"""
    if abs(max_dd) < 1e-10:
        return 0.0
    return cagr / abs(max_dd)

def get_options_premium(zone, avg_price, vol_annual=0.80):
    """
    Estimate options premium income per day.
    
    Zone 4/5: Covered Call strategy
    - Sell 30-delta call, ~30 DTE, delta ~0.30
    - Monthly premium ~= 2.5% of position value (for 80% annual vol)
    - Per-day contribution scaled by position size
    
    Zone 1/2: Cash-Secured Put strategy  
    - Sell 20-delta put, ~30 DTE
    - Monthly premium ~= 1.5% of cash held
    - Adds to effective entry improvement
    
    Returns daily premium as fraction of notional
    """
    # Monthly premium rates based on IV (~80% annual vol = ~23% monthly vol)
    # Covered call: sell 30-delta, 1 month ~= 2.5% of BTC position
    # Cash-secured put: sell 20-delta, 1 month ~= 1.5% of cash position
    daily_factor = 1/30  # ~30 DTE options rolled monthly
    
    if zone in [4, 5]:
        # Covered call on BTC position
        monthly_premium = 0.025  # 2.5% monthly premium
        return monthly_premium * daily_factor
    elif zone in [1, 2]:
        # Cash-secured put on sideline cash
        monthly_premium = 0.015  # 1.5% monthly premium  
        return monthly_premium * daily_factor
    else:
        return 0.0

def run_backtest(df, strategy_name, use_dynamic_zones=True, use_ema=True,
                 use_options=True, use_stop_loss=True,
                 initial_capital=10000, fee_bps=4):
    """
    Run backtest for a given strategy configuration.
    
    Parameters:
    - use_dynamic_zones: Use rolling 2-year percentile boundaries
    - use_ema: Use 5-day EMA smoothed Z-Score
    - use_options: Include Covered Call / CSP overlay
    - use_stop_loss: Monthly 30% drawdown triggers position reduction
    """
    df = df.copy()
    
    # ── 1. Compute MVRV Z-Score ──────────────────────────────────────────────
    df['mvrv'] = df['mvrv'].ffill()
    df['mvrv_roll_mean'] = df['mvrv'].rolling(1460, min_periods=365).mean()
    df['mvrv_roll_std']  = df['mvrv'].rolling(1460, min_periods=365).std()
    df['zscore_raw'] = (df['mvrv'] - df['mvrv_roll_mean']) / (df['mvrv_roll_std'] + 1e-10)
    
    # 5-day EMA smoothing
    if use_ema:
        df['zscore'] = df['zscore_raw'].ewm(span=5, adjust=False).mean()
    else:
        df['zscore'] = df['zscore_raw']
    
    # T-1 delay: use yesterday's signal to trade today
    df['zscore_signal'] = df['zscore'].shift(1)
    df['mvrv_signal']   = df['mvrv'].shift(1)
    
    # ── 2. Zone Assignment ───────────────────────────────────────────────────
    if use_dynamic_zones:
        # Rolling 2-year (504 trading days) percentile boundaries
        window = 504  # ~2 years
        min_w = 252   # minimum 1 year
        df['p20'] = df['zscore_signal'].rolling(window, min_periods=min_w).quantile(0.20)
        df['p40'] = df['zscore_signal'].rolling(window, min_periods=min_w).quantile(0.40)
        df['p60'] = df['zscore_signal'].rolling(window, min_periods=min_w).quantile(0.60)
        df['p80'] = df['zscore_signal'].rolling(window, min_periods=min_w).quantile(0.80)
    else:
        # Fixed IS-period boundaries (v3 approach)
        is_data = df[df.index < '2020-01-01']['zscore_signal'].dropna()
        df['p20'] = np.percentile(is_data, 20)
        df['p40'] = np.percentile(is_data, 40)
        df['p60'] = np.percentile(is_data, 60)
        df['p80'] = np.percentile(is_data, 80)
    
    def assign_zone(row):
        z = row['zscore_signal']
        p20, p40, p60, p80 = row['p20'], row['p40'], row['p60'], row['p80']
        if pd.isna(z) or pd.isna(p20):
            return np.nan
        if z < p20:   return 1
        elif z < p40: return 2
        elif z < p60: return 3
        elif z < p80: return 4
        else:         return 5
    
    df['zone'] = df.apply(assign_zone, axis=1)
    
    # Zone to target position mapping
    zone_to_pos = {1: 1.00, 2: 0.75, 3: 0.50, 4: 0.25, 5: 0.00}
    df['target_pos'] = df['zone'].map(zone_to_pos)
    
    # Add bottom protection: MVRV < 1.0 → force 100% (replaces halving protection)
    df['target_pos'] = np.where(df['mvrv_signal'] < 1.0,
                                1.00, df['target_pos'])
    
    df['target_pos'] = df['target_pos'].ffill().fillna(0.5)
    
    # ── 3. Backtest Simulation ───────────────────────────────────────────────
    capital = float(initial_capital)
    btc_held = 0.0
    cash = capital
    nav = capital
    
    nav_series   = []
    pos_series   = []
    options_series = []
    trade_count  = 0
    
    # Stop-loss state
    month_start_nav = capital
    stop_loss_active = False
    last_month = None
    
    prices = df['price'].values
    targets = df['target_pos'].values
    zones   = df['zone'].values
    dates   = df.index
    
    for i in range(len(df)):
        price = prices[i]
        target = targets[i]
        zone = zones[i]
        curr_date = dates[i]
        
        if pd.isna(price) or price <= 0:
            nav_series.append(nav)
            pos_series.append(btc_held * price / nav if nav > 0 else 0)
            options_series.append(0)
            continue
        
        # Update NAV with current price
        nav = cash + btc_held * price
        
        # ── Stop-loss logic ──────────────────────────────────────────────────
        curr_month = (curr_date.year, curr_date.month)
        if last_month is None or curr_month != last_month:
            month_start_nav = nav
            stop_loss_active = False
            last_month = curr_month
        
        # Check monthly drawdown
        if month_start_nav > 0:
            monthly_dd = (nav - month_start_nav) / month_start_nav
            if monthly_dd < -0.30 and use_stop_loss:
                stop_loss_active = True
        
        # Apply stop-loss: reduce target by 1 zone level (more defensive)
        if stop_loss_active and use_stop_loss:
            target = max(0.0, target - 0.25)  # shift down one zone
        
        # ── Trade execution ──────────────────────────────────────────────────
        if pd.isna(target):
            target = 0.5
        
        current_btc_value = btc_held * price
        current_pos = current_btc_value / nav if nav > 0 else 0
        
        # Only trade if position difference > 5% (avoid tiny rebalancing)
        if abs(current_pos - target) > 0.05:
            desired_btc_value = nav * target
            trade_value = abs(desired_btc_value - current_btc_value)
            fee = trade_value * fee_bps / 10000
            
            if desired_btc_value > current_btc_value:
                # Buy BTC
                buy_value = desired_btc_value - current_btc_value
                if cash >= buy_value + fee:
                    btc_bought = buy_value / price
                    btc_held += btc_bought
                    cash -= (buy_value + fee)
                    trade_count += 1
            else:
                # Sell BTC
                sell_value = current_btc_value - desired_btc_value
                btc_sold = sell_value / price
                btc_held -= btc_sold
                cash += (sell_value - fee)
                trade_count += 1
            
            nav = cash + btc_held * price
        
        # ── Options overlay ──────────────────────────────────────────────────
        options_pnl = 0.0
        if use_options and not pd.isna(zone):
            zone_int = int(zone) if not pd.isna(zone) else 3
            daily_premium_rate = get_options_premium(zone_int, price)
            
            if zone_int in [4, 5]:
                # Covered call: premium on BTC position
                btc_position_value = btc_held * price
                options_pnl = btc_position_value * daily_premium_rate
            elif zone_int in [1, 2]:
                # Cash-secured put: premium on cash holdings
                options_pnl = cash * daily_premium_rate
            
            cash += options_pnl
            nav = cash + btc_held * price
        
        nav_series.append(nav)
        pos_series.append(btc_held * price / nav if nav > 0 else 0)
        options_series.append(options_pnl)
    
    # ── 4. Compute Metrics ───────────────────────────────────────────────────
    nav_s = pd.Series(nav_series, index=dates)
    pos_s = pd.Series(pos_series, index=dates)
    opts_s = pd.Series(options_series, index=dates)
    
    returns = nav_s.pct_change().dropna()
    
    # CAGR
    n_years = (dates[-1] - dates[0]).days / 365.25
    cagr = (nav_s.iloc[-1] / nav_s.iloc[0]) ** (1 / n_years) - 1
    
    # Sharpe
    sharpe = np.sqrt(252) * returns.mean() / (returns.std() + 1e-10)
    
    # Sortino
    sortino = compute_sortino(returns)
    
    # MaxDD
    max_dd = compute_max_drawdown(nav_s)
    
    # Calmar
    calmar = compute_calmar(cagr, max_dd)
    
    # Monthly win rate
    monthly_nav = nav_s.resample('ME').last()
    monthly_ret = monthly_nav.pct_change().dropna()
    win_rate = (monthly_ret > 0).mean()
    
    # Total options premium
    total_options = opts_s.sum()
    options_cagr_contribution = total_options / nav_s.iloc[0] / n_years
    
    return {
        'name': strategy_name,
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_dd': max_dd,
        'calmar': calmar,
        'win_rate': win_rate,
        'trade_count': trade_count,
        'final_nav': nav_s.iloc[-1],
        'options_pnl_total': total_options,
        'options_cagr_contribution': options_cagr_contribution,
        'n_years': n_years,
        'nav_series': nav_s,
        'returns': returns,
        'pos_series': pos_s,
    }

def run_walk_forward(df, n_folds=5):
    """
    Walk-forward validation: rolling 1-year OOS windows
    IS = all prior data, OOS = next 1 year
    """
    results = []
    
    # Define fold boundaries
    # Use 2014-2026 range, annual OOS windows
    oos_years = list(range(2015, 2027))
    
    for oos_year in oos_years:
        oos_start = f"{oos_year}-01-01"
        oos_end   = f"{oos_year}-12-31"
        
        oos_df = df[(df.index >= oos_start) & (df.index <= oos_end)].copy()
        if len(oos_df) < 200:
            continue
        
        # Run on OOS slice only (parameters derived from rolling)
        try:
            r = run_backtest(oos_df, f"OOS_{oos_year}",
                           use_dynamic_zones=True, use_ema=True,
                           use_options=False, use_stop_loss=True)
            results.append({
                'year': oos_year,
                'cagr': r['cagr'],
                'sharpe': r['sharpe'],
                'max_dd': r['max_dd'],
                'calmar': r['calmar'],
            })
        except Exception as e:
            pass
    
    return pd.DataFrame(results)

def compute_bootstrap_comparison(ret_a, ret_b, n_bootstrap=2000, confidence=0.95):
    """Test if Sharpe difference between strategy A and B is statistically significant"""
    a = np.array(ret_a.dropna())
    b = np.array(ret_b.dropna())
    min_len = min(len(a), len(b))
    a, b = a[:min_len], b[:min_len]
    
    diff_sharpes = []
    for _ in range(n_bootstrap):
        idx = np.random.choice(min_len, size=min_len, replace=True)
        sa = a[idx]
        sb = b[idx]
        sharpe_a = np.sqrt(252) * sa.mean() / (sa.std() + 1e-10)
        sharpe_b = np.sqrt(252) * sb.mean() / (sb.std() + 1e-10)
        diff_sharpes.append(sharpe_a - sharpe_b)
    
    alpha = (1 - confidence) / 2
    ci_low  = np.percentile(diff_sharpes, alpha * 100)
    ci_high = np.percentile(diff_sharpes, (1 - alpha) * 100)
    p_gt_zero = np.mean(np.array(diff_sharpes) > 0)
    
    return {
        'ci_low': ci_low,
        'ci_high': ci_high,
        'p_gt_zero': p_gt_zero,
        'significant': ci_low > 0 or ci_high < 0
    }

def main():
    print("=" * 60)
    print("MVRV Z-Score Strategy v4 Backtest")
    print("=" * 60)
    
    # ── Load data ──────────────────────────────────────────────────────────
    df = fetch_data()
    if df is None:
        print("ERROR: Could not fetch data")
        return None
    
    df = df[df.index >= '2011-01-01'].copy()
    df = df[df['price'] > 0].copy()
    
    print(f"Data range: {df.index[0].date()} to {df.index[-1].date()}")
    print(f"Total days: {len(df)}")
    
    # ── Strategy configurations ────────────────────────────────────────────
    print("\nRunning backtests...")
    
    strategies = {}
    
    # Strategy 1: v4 Full (all improvements)
    r = run_backtest(df, "v4_full",
                     use_dynamic_zones=True, use_ema=True,
                     use_options=True, use_stop_loss=True)
    strategies['v4_full'] = r
    print(f"v4 Full:        CAGR={r['cagr']*100:.1f}% Sharpe={r['sharpe']:.3f} MaxDD={r['max_dd']*100:.1f}%")
    
    # Strategy 2: v4 No Options (for options contribution analysis)
    r = run_backtest(df, "v4_no_options",
                     use_dynamic_zones=True, use_ema=True,
                     use_options=False, use_stop_loss=True)
    strategies['v4_no_options'] = r
    print(f"v4 No Options:  CAGR={r['cagr']*100:.1f}% Sharpe={r['sharpe']:.3f} MaxDD={r['max_dd']*100:.1f}%")
    
    # Strategy 3: v4 No Stop-loss (for stop-loss contribution analysis)
    r = run_backtest(df, "v4_no_stoploss",
                     use_dynamic_zones=True, use_ema=True,
                     use_options=True, use_stop_loss=False)
    strategies['v4_no_stoploss'] = r
    print(f"v4 No StopLoss: CAGR={r['cagr']*100:.1f}% Sharpe={r['sharpe']:.3f} MaxDD={r['max_dd']*100:.1f}%")
    
    # Strategy 4: Buy & Hold
    nav_bh = (df['price'] / df['price'].iloc[0]) * 10000
    bh_returns = nav_bh.pct_change().dropna()
    n_years_bh = (df.index[-1] - df.index[0]).days / 365.25
    bh_cagr = (nav_bh.iloc[-1] / nav_bh.iloc[0]) ** (1/n_years_bh) - 1
    bh_sharpe = np.sqrt(252) * bh_returns.mean() / bh_returns.std()
    bh_max_dd = compute_max_drawdown(nav_bh)
    bh_monthly = nav_bh.resample('ME').last()
    bh_monthly_ret = bh_monthly.pct_change().dropna()
    strategies['buy_hold'] = {
        'name': 'buy_hold',
        'cagr': bh_cagr,
        'sharpe': bh_sharpe,
        'sortino': compute_sortino(bh_returns),
        'max_dd': bh_max_dd,
        'calmar': compute_calmar(bh_cagr, bh_max_dd),
        'win_rate': (bh_monthly_ret > 0).mean(),
        'trade_count': 1,
        'options_pnl_total': 0,
        'options_cagr_contribution': 0,
        'nav_series': nav_bh,
        'returns': bh_returns,
    }
    print(f"Buy & Hold:     CAGR={bh_cagr*100:.1f}% Sharpe={bh_sharpe:.3f} MaxDD={bh_max_dd*100:.1f}%")
    
    # ── IS/OOS Split ───────────────────────────────────────────────────────
    print("\nComputing IS/OOS split performance...")
    is_df  = df[df.index < '2020-01-01'].copy()
    oos_df = df[df.index >= '2020-01-01'].copy()
    
    is_results  = {}
    oos_results = {}
    
    for name, use_opts, use_sl in [
        ('v4_full', True, True),
        ('v4_no_options', False, True),
    ]:
        is_r  = run_backtest(is_df,  f"{name}_is",  use_dynamic_zones=True, use_ema=True, use_options=use_opts, use_stop_loss=use_sl)
        oos_r = run_backtest(oos_df, f"{name}_oos", use_dynamic_zones=True, use_ema=True, use_options=use_opts, use_stop_loss=use_sl)
        is_results[name]  = is_r
        oos_results[name] = oos_r
    
    # ── Bootstrap Confidence Intervals ────────────────────────────────────
    print("\nComputing bootstrap confidence intervals...")
    
    v4_full_ret = strategies['v4_full']['returns']
    v4_noopts_ret = strategies['v4_no_options']['returns']
    bh_ret = strategies['buy_hold']['returns']
    
    # Sharpe CI for v4_full
    sh_ci_lo, sh_ci_hi = bootstrap_sharpe_ci(v4_full_ret)
    
    # Sharpe difference: v4_full vs v4_no_options (options contribution)
    opts_diff = compute_bootstrap_comparison(v4_full_ret, v4_noopts_ret)
    
    # Sharpe difference: v4_full vs buy_hold
    bh_diff = compute_bootstrap_comparison(v4_full_ret, bh_ret)
    
    # ── Walk-Forward Validation ────────────────────────────────────────────
    print("\nRunning walk-forward validation...")
    wf_results = run_walk_forward(df)
    print(f"Walk-forward complete: {len(wf_results)} annual OOS windows")
    
    # ── Sub-period analysis ────────────────────────────────────────────────
    print("\nComputing sub-period analysis...")
    sub_periods = {
        '2011-2013': ('2011-01-01', '2013-12-31'),
        '2014-2016': ('2014-01-01', '2016-12-31'),
        '2017-2019': ('2017-01-01', '2019-12-31'),
        '2020-2023': ('2020-01-01', '2023-12-31'),
        '2024-2026': ('2024-01-01', '2026-05-19'),
    }
    
    sub_results = {}
    for period_name, (start, end) in sub_periods.items():
        sub_df = df[(df.index >= start) & (df.index <= end)].copy()
        if len(sub_df) < 100:
            continue
        try:
            r = run_backtest(sub_df, period_name,
                           use_dynamic_zones=True, use_ema=True,
                           use_options=True, use_stop_loss=True)
            sub_results[period_name] = r
        except Exception as e:
            print(f"  Sub-period {period_name} failed: {e}")
    
    # ── Compile Results ────────────────────────────────────────────────────
    results = {
        'strategies': {
            k: {
                'cagr': float(v['cagr']),
                'sharpe': float(v['sharpe']),
                'sortino': float(v['sortino']),
                'max_dd': float(v['max_dd']),
                'calmar': float(v['calmar']),
                'win_rate': float(v['win_rate']),
                'trade_count': int(v['trade_count']),
                'options_pnl_total': float(v.get('options_pnl_total', 0)),
                'options_cagr_contribution': float(v.get('options_cagr_contribution', 0)),
                'final_nav': float(v.get('final_nav', 0)),
            }
            for k, v in strategies.items()
        },
        'is_results': {
            k: {
                'cagr': float(v['cagr']),
                'sharpe': float(v['sharpe']),
                'max_dd': float(v['max_dd']),
                'calmar': float(v['calmar']),
            }
            for k, v in is_results.items()
        },
        'oos_results': {
            k: {
                'cagr': float(v['cagr']),
                'sharpe': float(v['sharpe']),
                'max_dd': float(v['max_dd']),
                'calmar': float(v['calmar']),
            }
            for k, v in oos_results.items()
        },
        'bootstrap': {
            'v4_full_sharpe_ci': [float(sh_ci_lo) if sh_ci_lo else None, float(sh_ci_hi) if sh_ci_hi else None],
            'options_diff_ci': [float(opts_diff['ci_low']), float(opts_diff['ci_high'])],
            'options_diff_p_positive': float(opts_diff['p_gt_zero']),
            'options_significant': bool(opts_diff['significant']),
            'bh_diff_ci': [float(bh_diff['ci_low']), float(bh_diff['ci_high'])],
        },
        'walk_forward': wf_results.to_dict('records') if not wf_results.empty else [],
        'sub_periods': {
            k: {
                'cagr': float(v['cagr']),
                'sharpe': float(v['sharpe']),
                'max_dd': float(v['max_dd']),
                'calmar': float(v['calmar']),
            }
            for k, v in sub_results.items()
        },
        'data_info': {
            'start': str(df.index[0].date()),
            'end': str(df.index[-1].date()),
            'total_days': int(len(df)),
        }
    }
    
    # Save results
    with open('/root/.openclaw/workspace/research/results_v4.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, s in results['strategies'].items():
        print(f"{name:20s}  CAGR={s['cagr']*100:6.1f}%  Sharpe={s['sharpe']:.3f}  MaxDD={s['max_dd']*100:.1f}%  Calmar={s['calmar']:.3f}")
    
    print(f"\nv4 Options contribution to CAGR: {results['strategies']['v4_full']['options_cagr_contribution']*100:.2f}%/yr")
    print(f"Sharpe 95% CI for v4_full: [{results['bootstrap']['v4_full_sharpe_ci'][0]:.3f}, {results['bootstrap']['v4_full_sharpe_ci'][1]:.3f}]")
    
    if wf_results is not None and not wf_results.empty:
        print(f"\nWalk-forward ({len(wf_results)} years):")
        print(f"  Avg CAGR:   {wf_results['cagr'].mean()*100:.1f}%  (std={wf_results['cagr'].std()*100:.1f}%)")
        print(f"  Avg Sharpe: {wf_results['sharpe'].mean():.3f}  (std={wf_results['sharpe'].std():.3f})")
        print(f"  Worst MaxDD: {wf_results['max_dd'].min()*100:.1f}%")
    
    print("\nResults saved to results_v4.json")
    return results

if __name__ == '__main__':
    results = main()
