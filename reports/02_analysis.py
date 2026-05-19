#!/usr/bin/env python3
"""
Multi-Factor On-Chain Indicator Research
Available CoinMetrics community metrics:
- CapMVRVCur: MVRV Ratio ✓
- PriceUSD: BTC Price ✓  
- IssTotUSD: Daily Issuance USD (for Puell Multiple) ✓
- AdrActCnt: Active Addresses ✓
- HashRate: Hash Rate ✓
- TxTfrCnt: Transaction Transfer Count ✓
- CapMrktCurUSD: Market Cap USD ✓
- SplyCur: Current Supply ✓
- BlkCnt: Block Count ✓
- TxCnt: Transaction Count ✓

NOT available (403/400): TxTfrValAdjUSD, NVTAdj, RevUSD, CapRealUSD, SOPR, SplyAct1yr, FeeTotUSD
"""

import requests, time, json, sys
import pandas as pd
import numpy as np
from datetime import datetime

OUTPUT_FILE = "/root/.openclaw/workspace/research/multifactor_results.md"

# ─────────────────────────────────────────────
# 1. DATA FETCHING
# ─────────────────────────────────────────────

def fetch_coinmetrics(metrics_str, start="2015-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {
        "assets": "btc",
        "metrics": metrics_str,
        "frequency": "1d",
        "start_time": start,
        "page_size": 1000
    }
    page = 0
    while True:
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code != 200:
                print(f"ERR {r.status_code}: {r.text[:200]}")
                break
            j = r.json()
            batch = j.get('data', [])
            all_data.extend(batch)
            token = j.get('next_page_token')
            page += 1
            if page % 5 == 0:
                print(f"  Fetched {len(all_data)} rows...", flush=True)
            if not token:
                break
            params = {
                "assets": "btc",
                "metrics": metrics_str,
                "frequency": "1d",
                "page_size": 1000,
                "next_page_token": token
            }
            time.sleep(0.05)
        except Exception as e:
            print(f"Exception: {e}")
            break
    return all_data

print("=" * 60)
print("MULTI-FACTOR ON-CHAIN RESEARCH")
print("=" * 60)

print("\n[1/6] Fetching data from CoinMetrics community API...")
metrics = "CapMVRVCur,PriceUSD,IssTotUSD,AdrActCnt,HashRate,TxTfrCnt,CapMrktCurUSD,SplyCur,TxCnt"
data = fetch_coinmetrics(metrics, start="2015-01-01")
print(f"Total rows fetched: {len(data)}")

df = pd.DataFrame(data)
df['date'] = pd.to_datetime(df['time'])
df = df.sort_values('date').reset_index(drop=True)

# Convert numeric columns
num_cols = ['CapMVRVCur','PriceUSD','IssTotUSD','AdrActCnt','HashRate','TxTfrCnt','CapMrktCurUSD','SplyCur','TxCnt']
for col in num_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
print(f"Columns: {[c for c in num_cols if c in df.columns]}")

# ─────────────────────────────────────────────
# 2. INDICATOR CONSTRUCTION
# ─────────────────────────────────────────────
print("\n[2/6] Computing indicators...")

# A. MVRV (already available directly)
df['mvrv'] = df['CapMVRVCur']

# B. PUELL MULTIPLE
# Puell = daily IssTotUSD / 365d rolling mean(IssTotUSD)
df['puell'] = df['IssTotUSD'] / df['IssTotUSD'].rolling(365, min_periods=180).mean()
print(f"Puell Multiple - range: {df['puell'].min():.2f} to {df['puell'].max():.2f}")

# C. NVT PROXY
# True NVT needs adjusted transfer volume (403 on community API)
# We'll use: CapMrktCurUSD / (TxTfrCnt * PriceUSD * 1000) as proxy
# This represents "how much network capacity is being used per dollar of cap"
# Better proxy: use 90d smoothed transaction velocity
df['tx_volume_proxy'] = df['TxTfrCnt'] * df['PriceUSD']  # rough proxy in USD-equivalent
df['nvt_proxy'] = df['CapMrktCurUSD'] / df['tx_volume_proxy'].rolling(90, min_periods=30).mean()
# Normalize by historical distribution
nvt_median = df['nvt_proxy'].median()
print(f"NVT Proxy - median={nvt_median:.1f}, range: {df['nvt_proxy'].min():.1f} to {df['nvt_proxy'].max():.1f}")

# D. ON-CHAIN ACTIVITY RATIO (Active Addresses relative to trend)
# Captures network adoption/momentum
df['adr_ratio'] = df['AdrActCnt'] / df['AdrActCnt'].rolling(365, min_periods=90).mean()
print(f"Address Activity Ratio - median: {df['adr_ratio'].median():.2f}")

# E. MINER HASH RATE GROWTH (proxy for miner confidence/selling pressure)
# High hashrate growth = miners not selling; crash in hashrate = stress
df['hr_growth_90d'] = df['HashRate'].pct_change(90)
print(f"HashRate 90d growth - range: {df['hr_growth_90d'].min():.2f} to {df['hr_growth_90d'].max():.2f}")

# F. PRICE MOMENTUM (for trend filter)
df['price_ma50'] = df['PriceUSD'].rolling(50, min_periods=20).mean()
df['price_ma200'] = df['PriceUSD'].rolling(200, min_periods=90).mean()
df['bull_filter'] = (df['PriceUSD'] > df['price_ma200']).astype(float)

# ─────────────────────────────────────────────
# 3. FACTOR SCORING (0-100)
# ─────────────────────────────────────────────
print("\n[3/6] Building factor scoring system...")

def percentile_score(series, invert=False):
    """Convert series to percentile rank 0-100. invert=True means high value = bearish."""
    # Rolling percentile over last 4 years to avoid look-ahead
    scores = series.rolling(4*365, min_periods=90).rank(pct=True) * 100
    if invert:
        scores = 100 - scores
    return scores

# MVRV Score (high MVRV = bearish, low = bullish for buying)
# Bearish score: high = overvalued
df['mvrv_bear_score'] = percentile_score(df['mvrv'])  # 100 = historically very expensive

# Puell Score: high Puell = bearish (miners selling), low = bullish
df['puell_bear_score'] = percentile_score(df['puell'])

# NVT Proxy: high NVT proxy = bearish (network underutilized relative to cap)
df['nvt_bear_score'] = percentile_score(df['nvt_proxy'])

# Address Activity: high activity = bullish (bearish score = 100 - activity)
df['adr_bear_score'] = 100 - percentile_score(df['adr_ratio'])

# ─────────────────────────────────────────────
# 4. COMPOSITE SCORE → POSITION SIZING
# ─────────────────────────────────────────────
print("\n[4/6] Composite scoring and position sizing...")

# MVRV v2 strategy (baseline) - replicated
def mvrv_v2_position(mvrv):
    """Simple MVRV v2 strategy."""
    if pd.isna(mvrv):
        return 0.0
    if mvrv < 1.0:
        return 1.0   # Zone 1: 100% - extreme undervaluation
    elif mvrv < 2.0:
        return 0.75  # Zone 2: 75%
    elif mvrv < 3.0:
        return 0.50  # Zone 3: 50%
    elif mvrv < 3.7:
        return 0.25  # Zone 4: 25%
    else:
        return 0.0   # Zone 5: exit - extreme overvaluation

df['pos_mvrv_v2'] = df['mvrv'].apply(mvrv_v2_position)

# MULTI-FACTOR v1: MVRV + Puell
def multifactor_position(row, weights=(0.5, 0.3, 0.2)):
    """Composite bear score → position."""
    w_mvrv, w_puell, w_nvt = weights
    
    mvrv_s = row.get('mvrv_bear_score', 50)
    puell_s = row.get('puell_bear_score', 50)
    nvt_s = row.get('nvt_bear_score', 50)
    
    # Handle NaN
    if pd.isna(mvrv_s):
        return 0.0
    
    if pd.isna(puell_s):
        composite = mvrv_s
    elif pd.isna(nvt_s):
        composite = 0.6 * mvrv_s + 0.4 * puell_s
    else:
        composite = w_mvrv * mvrv_s + w_puell * puell_s + w_nvt * nvt_s
    
    # Map 0-100 composite score to position 0-1 (inverse: low score = high position)
    if composite < 20:
        return 1.0
    elif composite < 40:
        return 0.75
    elif composite < 60:
        return 0.50
    elif composite < 75:
        return 0.25
    else:
        return 0.0

df['pos_multifactor'] = df.apply(multifactor_position, axis=1)

# MULTI-FACTOR v2: with address activity filter
def multifactor_v2_position(row):
    """Enhanced with activity ratio - addresses Zone 3 direction issue."""
    base_pos = multifactor_position(row)
    
    # Use address activity to add directional judgment in Zone 3 (pos=0.5)
    if abs(base_pos - 0.5) < 0.01:  # in zone 3
        adr_s = row.get('adr_bear_score', 50)
        if not pd.isna(adr_s):
            if adr_s < 30:  # high activity = networks growing = slightly more bullish
                return 0.65
            elif adr_s > 70:  # declining activity = bearish
                return 0.35
    return base_pos

df['pos_multifactor_v2'] = df.apply(multifactor_v2_position, axis=1)

# ─────────────────────────────────────────────
# 5. BACKTEST ENGINE
# ─────────────────────────────────────────────
print("\n[5/6] Running backtests...")

def backtest(df, position_col, start_date='2017-01-01', initial_capital=100000, rebalance_freq=7):
    """Weekly rebalance backtest. Returns performance metrics."""
    sub = df[df['date'] >= start_date].copy().reset_index(drop=True)
    sub = sub.dropna(subset=['PriceUSD', position_col])
    
    capital = initial_capital
    btc_held = 0.0
    last_rebalance = None
    trades = 0
    
    equity_curve = []
    positions = []
    
    for i, row in sub.iterrows():
        price = row['PriceUSD']
        target_pos = row[position_col]
        date = row['date']
        
        # Current portfolio value
        portfolio_val = capital + btc_held * price
        
        # Rebalance on schedule or large position change
        should_rebalance = (
            last_rebalance is None or
            (date - last_rebalance).days >= rebalance_freq
        )
        
        if should_rebalance:
            target_btc_val = portfolio_val * target_pos
            new_btc = target_btc_val / price
            delta_btc = new_btc - btc_held
            cost = abs(delta_btc * price) * 0.001  # 0.1% trading fee
            
            btc_held = new_btc
            capital = portfolio_val - target_btc_val - cost
            if delta_btc != 0:
                trades += 1
            last_rebalance = date
        
        portfolio_val = capital + btc_held * price
        equity_curve.append({'date': date, 'equity': portfolio_val, 'price': price, 'pos': target_pos})
    
    eq_df = pd.DataFrame(equity_curve)
    
    # Calculate metrics
    returns = eq_df['equity'].pct_change().dropna()
    final_equity = eq_df['equity'].iloc[-1]
    total_return = (final_equity - initial_capital) / initial_capital
    
    # Annualized return
    days = (eq_df['date'].iloc[-1] - eq_df['date'].iloc[0]).days
    years = days / 365
    cagr = (final_equity / initial_capital) ** (1/years) - 1 if years > 0 else 0
    
    # Max drawdown
    rolling_max = eq_df['equity'].cummax()
    drawdown = (eq_df['equity'] - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    # Sharpe
    daily_returns = eq_df['equity'].pct_change().dropna()
    sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(365) if daily_returns.std() > 0 else 0
    
    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    # Buy & Hold comparison
    bh_return = (sub['PriceUSD'].iloc[-1] - sub['PriceUSD'].iloc[0]) / sub['PriceUSD'].iloc[0]
    bh_cagr = (1 + bh_return) ** (1/years) - 1
    
    return {
        'total_return': total_return,
        'cagr': cagr,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'calmar': calmar,
        'trades': trades,
        'final_equity': final_equity,
        'bh_return': bh_return,
        'bh_cagr': bh_cagr,
        'equity_curve': eq_df
    }

print("  Running MVRV v2...")
r_mvrv = backtest(df, 'pos_mvrv_v2')
print("  Running Multi-Factor v1...")
r_mf1 = backtest(df, 'pos_multifactor')
print("  Running Multi-Factor v2...")
r_mf2 = backtest(df, 'pos_multifactor_v2')

def fmt_results(name, r):
    print(f"\n  {name}:")
    print(f"    CAGR: {r['cagr']:.1%}  MaxDD: {r['max_drawdown']:.1%}  Sharpe: {r['sharpe']:.2f}  Calmar: {r['calmar']:.2f}")
    print(f"    Total Return: {r['total_return']:.1%}  vs B&H: {r['bh_cagr']:.1%}")
    print(f"    Trades: {r['trades']}")

fmt_results("MVRV v2", r_mvrv)
fmt_results("Multi-Factor v1 (MVRV+Puell+NVTproxy)", r_mf1)
fmt_results("Multi-Factor v2 (v1 + Addr Activity)", r_mf2)

# ─────────────────────────────────────────────
# 6. SPECIAL ANALYSIS: 2022 LUNA CRASH
# ─────────────────────────────────────────────
print("\n[6/6] LUNA crash analysis (May 2022)...")

luna_window = df[(df['date'] >= '2022-03-01') & (df['date'] <= '2022-07-01')].copy()
luna_window = luna_window.dropna(subset=['PriceUSD'])

print(f"\nLUNA crash window ({luna_window['date'].min().date()} to {luna_window['date'].max().date()}):")
print(f"BTC price range: ${luna_window['PriceUSD'].min():,.0f} to ${luna_window['PriceUSD'].max():,.0f}")

# Find peak before crash (late March - April 2022)
pre_crash = df[(df['date'] >= '2022-04-01') & (df['date'] <= '2022-05-07')]
crash_start = df[(df['date'] >= '2022-05-07') & (df['date'] <= '2022-05-20')]  # LUNA collapse

if len(pre_crash) > 0 and len(crash_start) > 0:
    # Indicator values at various points
    def get_row_indicators(date_str):
        mask = df['date'] == pd.Timestamp(date_str)
        if not mask.any():
            # Find nearest
            idx = (df['date'] - pd.Timestamp(date_str)).abs().idxmin()
            row = df.iloc[idx]
        else:
            row = df[mask].iloc[0]
        return row
    
    # Key dates
    dates_to_check = {
        "2022-04-01 (Pre-LUNA)": "2022-04-01",
        "2022-05-01 (Just before LUNA)": "2022-05-01",
        "2022-05-10 (LUNA crash begins)": "2022-05-10",
        "2022-05-20 (Post-crash)": "2022-05-20",
    }
    
    luna_analysis = {}
    for label, date_str in dates_to_check.items():
        row = get_row_indicators(date_str)
        luna_analysis[label] = {
            "date": str(row['date'].date()),
            "price": row['PriceUSD'],
            "mvrv": row['mvrv'],
            "puell": row['puell'],
            "nvt_proxy": row['nvt_proxy'],
            "mvrv_bear_score": row['mvrv_bear_score'],
            "puell_bear_score": row['puell_bear_score'],
            "pos_mvrv_v2": row['pos_mvrv_v2'],
            "pos_multifactor": row['pos_multifactor'],
        }
        print(f"\n  {label}:")
        print(f"    Price: ${row['PriceUSD']:,.0f}")
        print(f"    MVRV: {row['mvrv']:.2f} (bear_score: {row['mvrv_bear_score']:.0f})")
        print(f"    Puell: {row['puell']:.2f} (bear_score: {row['puell_bear_score']:.0f})")
        print(f"    MVRV v2 position: {row['pos_mvrv_v2']:.0%}")
        print(f"    MultiF position: {row['pos_multifactor']:.0%}")

# ─────────────────────────────────────────────
# 7. EDA SUMMARY
# ─────────────────────────────────────────────
print("\nEDA Statistics...")

eda = {}
for col in ['mvrv', 'puell', 'nvt_proxy', 'adr_ratio']:
    s = df[col].dropna()
    eda[col] = {
        'count': len(s),
        'mean': s.mean(),
        'median': s.median(),
        'std': s.std(),
        'min': s.min(),
        'max': s.max(),
        'p10': s.quantile(0.1),
        'p25': s.quantile(0.25),
        'p75': s.quantile(0.75),
        'p90': s.quantile(0.9),
    }

# Correlations
corr_df = df[['PriceUSD','mvrv','puell','nvt_proxy','adr_ratio']].dropna()
corr = corr_df.corr()
print("\nCorrelations with PriceUSD:")
for col in ['mvrv','puell','nvt_proxy','adr_ratio']:
    if col in corr.columns:
        print(f"  {col}: {corr.loc['PriceUSD', col]:.3f}")

# Annual performance breakdown
print("\nAnnual performance breakdown:")
annual_data = {}
for year in range(2017, 2026):
    year_df = r_mvrv['equity_curve'][r_mvrv['equity_curve']['date'].dt.year == year]
    mf_year = r_mf1['equity_curve'][r_mf1['equity_curve']['date'].dt.year == year]
    if len(year_df) > 1:
        mvrv_ret = (year_df['equity'].iloc[-1] / year_df['equity'].iloc[0]) - 1
        mf_ret = (mf_year['equity'].iloc[-1] / mf_year['equity'].iloc[0]) - 1 if len(mf_year) > 1 else None
        btc_ret = (year_df['price'].iloc[-1] / year_df['price'].iloc[0]) - 1
        annual_data[year] = {'mvrv_v2': mvrv_ret, 'multifactor': mf_ret, 'btc_bh': btc_ret}
        mf_str = f"{mf_ret:.1%}" if mf_ret is not None else "N/A"
        print(f"  {year}: MVRV v2={mvrv_ret:.1%}, MultiF={mf_str}, BTC B&H={btc_ret:.1%}")

# ─────────────────────────────────────────────
# 8. SAVE RESULTS
# ─────────────────────────────────────────────
print("\nSaving results...")

# Save data for reference
df.to_csv("/tmp/btc_onchain_data.csv", index=False)

# Pickle full results
import pickle
results_data = {
    'df': df,
    'r_mvrv': r_mvrv,
    'r_mf1': r_mf1,
    'r_mf2': r_mf2,
    'eda': eda,
    'corr': corr,
    'annual_data': annual_data,
    'luna_analysis': luna_analysis if 'luna_analysis' in dir() else {}
}
with open("/tmp/research_results.pkl", "wb") as f:
    pickle.dump(results_data, f)

print("Data saved to /tmp/btc_onchain_data.csv")
print("Results saved to /tmp/research_results.pkl")
print("\nDone! Now generating markdown report...")
