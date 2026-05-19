#!/usr/bin/env python3
"""
Multi-Factor On-Chain Indicator Research - Optimized Version
Reduces API calls by fetching all metrics in one request, shorter date range
"""

import requests, time, json, sys
import pandas as pd
import numpy as np
from datetime import datetime

OUTPUT_FILE = "/root/.openclaw/workspace/research/multifactor_results.md"

def fetch_coinmetrics_single(metric, start="2017-01-01"):
    """Fetch single metric with pagination."""
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {
        "assets": "btc",
        "metrics": metric,
        "frequency": "1d",
        "start_time": start,
        "page_size": 2000
    }
    while True:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            return None
        j = r.json()
        all_data.extend(j.get('data', []))
        token = j.get('next_page_token')
        if not token:
            break
        params = {"assets": "btc", "metrics": metric, "frequency": "1d", "page_size": 2000, "next_page_token": token}
        time.sleep(0.05)
    return all_data

print("Fetching metrics (one by one to avoid 403)...")

# Fetch each metric separately and merge
START = "2016-01-01"
metrics_to_fetch = {
    "CapMVRVCur": "mvrv",
    "PriceUSD": "price",
    "IssTotUSD": "issuance",
    "AdrActCnt": "active_addrs",
    "TxTfrCnt": "tx_count",
    "CapMrktCurUSD": "market_cap",
    "SplyCur": "supply",
    "HashRate": "hashrate",
    "TxCnt": "total_tx",
    "BlkCnt": "block_count",
}

dfs = {}
for metric, alias in metrics_to_fetch.items():
    print(f"  Fetching {metric}...", flush=True)
    data = fetch_coinmetrics_single(metric, start=START)
    if data:
        tmp = pd.DataFrame(data)
        tmp['date'] = pd.to_datetime(tmp['time'])
        tmp[alias] = pd.to_numeric(tmp[metric], errors='coerce')
        dfs[alias] = tmp[['date', alias]].sort_values('date')
        print(f"    OK: {len(tmp)} rows, last val: {tmp[alias].iloc[-1]:.4g}")
    else:
        print(f"    FAILED")
    time.sleep(0.3)

# Merge all
print("\nMerging dataframes...")
df = dfs['price'].copy()
for alias, tmp in dfs.items():
    if alias != 'price':
        df = df.merge(tmp, on='date', how='outer')
df = df.sort_values('date').reset_index(drop=True)
print(f"Merged dataframe: {df.shape}, date range: {df['date'].min().date()} to {df['date'].max().date()}")

# Save checkpoint
df.to_csv("/tmp/btc_onchain_data.csv", index=False)
print("Saved /tmp/btc_onchain_data.csv")

# ─────────────────────────────────────────────
# INDICATOR CONSTRUCTION
# ─────────────────────────────────────────────
print("\nBuilding indicators...")

# A. PUELL MULTIPLE: daily_issuance / 365d_MA_issuance
df['puell'] = df['issuance'] / df['issuance'].rolling(365, min_periods=180).mean()

# B. NVT PROXY (modified): using tx_count as activity proxy
# NVT_proxy = market_cap / (90d_MA_daily_tx_count * avg_tx_value_proxy)
# avg_tx_value_proxy = price * 100 (rough constant for now)
# More realistic: just use market_cap / (90d_MA tx_count * price) as velocity ratio
df['on_chain_vol_proxy'] = df['tx_count'] * df['price'] * 0.01  # scaling
df['nvt_proxy'] = df['market_cap'] / df['on_chain_vol_proxy'].rolling(90, min_periods=30).mean()

# C. ADDRESS ACTIVITY RATIO
df['adr_ratio'] = df['active_addrs'] / df['active_addrs'].rolling(365, min_periods=90).mean()

# D. HASH RIBBON proxy - hashrate momentum
df['hr_ma30'] = df['hashrate'].rolling(30, min_periods=10).mean()
df['hr_ma60'] = df['hashrate'].rolling(60, min_periods=20).mean()
df['hash_ribbon'] = (df['hr_ma30'] > df['hr_ma60']).astype(float)  # 1=bullish, 0=bearish

# E. Price MA filter
df['price_ma200'] = df['price'].rolling(200, min_periods=90).mean()

# F. Log returns
df['log_ret'] = np.log(df['price']).diff()

# ─────────────────────────────────────────────
# PERCENTILE SCORING
# ─────────────────────────────────────────────
print("Computing percentile scores...")

def rolling_pct_rank(series, window=365*4, min_periods=90):
    """Rolling percentile rank 0-100."""
    return series.rolling(window, min_periods=min_periods).rank(pct=True) * 100

# Bear scores (higher = more bearish = less position)
df['mvrv_bear'] = rolling_pct_rank(df['mvrv'])
df['puell_bear'] = rolling_pct_rank(df['puell'])
df['nvt_bear'] = rolling_pct_rank(df['nvt_proxy'])
df['adr_bear'] = 100 - rolling_pct_rank(df['adr_ratio'])  # low activity = bearish

# ─────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────
print("Computing positions...")

def score_to_position(score):
    """Composite bear score (0-100) → position (0.0-1.0)."""
    if pd.isna(score):
        return 0.0
    if score < 20:
        return 1.0
    elif score < 40:
        return 0.75
    elif score < 60:
        return 0.50
    elif score < 75:
        return 0.25
    else:
        return 0.0

def mvrv_v2_pos(mvrv):
    if pd.isna(mvrv): return 0.0
    if mvrv < 1.0: return 1.0
    elif mvrv < 2.0: return 0.75
    elif mvrv < 3.0: return 0.50
    elif mvrv < 3.7: return 0.25
    else: return 0.0

df['pos_mvrv_v2'] = df['mvrv'].apply(mvrv_v2_pos)

# Multi-factor v1: MVRV(50%) + Puell(30%) + NVT_proxy(20%)
df['composite_v1'] = (
    0.50 * df['mvrv_bear'].fillna(50) +
    0.30 * df['puell_bear'].fillna(50) +
    0.20 * df['nvt_bear'].fillna(50)
)
df['pos_mf_v1'] = df['composite_v1'].apply(score_to_position)

# Multi-factor v2: v1 + address activity refinement in zone 3
df['composite_v2'] = (
    0.45 * df['mvrv_bear'].fillna(50) +
    0.25 * df['puell_bear'].fillna(50) +
    0.15 * df['nvt_bear'].fillna(50) +
    0.15 * df['adr_bear'].fillna(50)
)
df['pos_mf_v2'] = df['composite_v2'].apply(score_to_position)

# ─────────────────────────────────────────────
# BACKTEST
# ─────────────────────────────────────────────
print("Running backtests...")

def backtest(df, position_col, start_date='2017-01-01', initial_capital=100_000, fee=0.001):
    sub = df[(df['date'] >= start_date) & df['price'].notna() & df[position_col].notna()].copy()
    sub = sub.reset_index(drop=True)
    
    capital = float(initial_capital)
    btc = 0.0
    last_rebal = None
    trades = 0
    equity_rows = []
    
    for _, row in sub.iterrows():
        price = row['price']
        target = row[position_col]
        date = row['date']
        
        pv = capital + btc * price
        
        rebal = last_rebal is None or (date - last_rebal).days >= 7
        
        if rebal:
            target_btc_val = pv * target
            new_btc = target_btc_val / price
            cost = abs(new_btc - btc) * price * fee
            btc = new_btc
            capital = pv - target_btc_val - cost
            if abs(new_btc - (target_btc_val - cost) / price) > 1e-9:
                trades += 1
            last_rebal = date
        
        pv = capital + btc * price
        equity_rows.append({'date': date, 'equity': pv, 'price': price, 'pos': target})
    
    eq = pd.DataFrame(equity_rows)
    final = eq['equity'].iloc[-1]
    total_ret = (final - initial_capital) / initial_capital
    days = (eq['date'].iloc[-1] - eq['date'].iloc[0]).days
    years = max(days / 365, 0.1)
    cagr = (final / initial_capital) ** (1 / years) - 1
    
    rolling_max = eq['equity'].cummax()
    drawdown = (eq['equity'] - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    dr = eq['equity'].pct_change().dropna()
    sharpe = (dr.mean() / dr.std()) * np.sqrt(365) if dr.std() > 0 else 0
    sortino_neg = dr[dr < 0].std()
    sortino = (dr.mean() / sortino_neg) * np.sqrt(365) if sortino_neg > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    bh_ret = (sub['price'].iloc[-1] / sub['price'].iloc[0]) - 1
    bh_cagr = (1 + bh_ret) ** (1 / years) - 1
    
    return {
        'cagr': cagr, 'total_return': total_ret, 'max_drawdown': max_dd,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'trades': trades, 'final_equity': final,
        'bh_cagr': bh_cagr, 'bh_return': bh_ret,
        'equity_curve': eq
    }

r_mvrv = backtest(df, 'pos_mvrv_v2')
r_mf1 = backtest(df, 'pos_mf_v1')
r_mf2 = backtest(df, 'pos_mf_v2')

print(f"\nMVRV v2:           CAGR={r_mvrv['cagr']:.1%} MaxDD={r_mvrv['max_drawdown']:.1%} Sharpe={r_mvrv['sharpe']:.2f} Calmar={r_mvrv['calmar']:.2f}")
print(f"MultiF v1 (3-fac): CAGR={r_mf1['cagr']:.1%} MaxDD={r_mf1['max_drawdown']:.1%} Sharpe={r_mf1['sharpe']:.2f} Calmar={r_mf1['calmar']:.2f}")
print(f"MultiF v2 (4-fac): CAGR={r_mf2['cagr']:.1%} MaxDD={r_mf2['max_drawdown']:.1%} Sharpe={r_mf2['sharpe']:.2f} Calmar={r_mf2['calmar']:.2f}")
print(f"Buy & Hold:        CAGR={r_mvrv['bh_cagr']:.1%}")

# ─────────────────────────────────────────────
# SPECIAL ANALYSIS: LUNA CRASH
# ─────────────────────────────────────────────
print("\nLUNA crash analysis...")

luna_dates = {
    "2022-03-01": "Pre-LUNA (March high ~$44k)",
    "2022-04-15": "April warning window (~$40k)",
    "2022-05-05": "5 days before LUNA collapse (~$38k)",
    "2022-05-10": "LUNA collapse begins (~$32k)",
    "2022-05-18": "Post-LUNA (~$29k)",
    "2022-06-15": "3AC/Celsius crisis (~$22k)",
}

luna_signals = {}
for date_str, label in luna_dates.items():
    idx = (df['date'] - pd.Timestamp(date_str)).abs().idxmin()
    row = df.iloc[idx]
    luna_signals[date_str] = {
        "label": label,
        "date": str(row['date'].date()),
        "price": round(row['price'], 0),
        "mvrv": round(row['mvrv'], 3) if not pd.isna(row['mvrv']) else None,
        "puell": round(row['puell'], 3) if not pd.isna(row['puell']) else None,
        "nvt_proxy": round(row['nvt_proxy'], 1) if not pd.isna(row['nvt_proxy']) else None,
        "mvrv_bear": round(row['mvrv_bear'], 1) if not pd.isna(row['mvrv_bear']) else None,
        "puell_bear": round(row['puell_bear'], 1) if not pd.isna(row['puell_bear']) else None,
        "composite_v1": round(row['composite_v1'], 1) if not pd.isna(row['composite_v1']) else None,
        "pos_mvrv_v2": row['pos_mvrv_v2'],
        "pos_mf_v1": row['pos_mf_v1'],
        "pos_mf_v2": row['pos_mf_v2'],
    }
    print(f"  {date_str} ({label}):")
    print(f"    Price=${row['price']:,.0f}, MVRV={row['mvrv']:.2f}, Puell={row['puell']:.2f}")
    print(f"    MVRV_bear={row['mvrv_bear']:.0f}, Puell_bear={row['puell_bear']:.0f}, Composite={row['composite_v1']:.0f}")
    print(f"    Position: MVRV_v2={row['pos_mvrv_v2']:.0%}, MF_v1={row['pos_mf_v1']:.0%}")

# Annual returns
print("\nAnnual breakdown:")
annual_data = {}
for year in range(2017, 2026):
    yr_mvrv = r_mvrv['equity_curve'][r_mvrv['equity_curve']['date'].dt.year == year]
    yr_mf1 = r_mf1['equity_curve'][r_mf1['equity_curve']['date'].dt.year == year]
    yr_mf2 = r_mf2['equity_curve'][r_mf2['equity_curve']['date'].dt.year == year]
    if len(yr_mvrv) > 1:
        mvrv_ret = (yr_mvrv['equity'].iloc[-1] / yr_mvrv['equity'].iloc[0]) - 1
        mf1_ret = (yr_mf1['equity'].iloc[-1] / yr_mf1['equity'].iloc[0]) - 1 if len(yr_mf1) > 1 else None
        mf2_ret = (yr_mf2['equity'].iloc[-1] / yr_mf2['equity'].iloc[0]) - 1 if len(yr_mf2) > 1 else None
        btc_ret = (yr_mvrv['price'].iloc[-1] / yr_mvrv['price'].iloc[0]) - 1
        annual_data[year] = {'mvrv_v2': mvrv_ret, 'multifactor_v1': mf1_ret, 'multifactor_v2': mf2_ret, 'btc_bh': btc_ret}
        print(f"  {year}: MVRV_v2={mvrv_ret:.1%} MF_v1={mf1_ret:.1%} MF_v2={mf2_ret:.1%} BTC={btc_ret:.1%}")

# EDA stats
print("\nEDA statistics:")
eda_stats = {}
for col, alias in [('mvrv','MVRV'), ('puell','Puell'), ('nvt_proxy','NVT Proxy'), ('adr_ratio','Addr Ratio')]:
    s = df[col].dropna()
    eda_stats[col] = {
        'mean': s.mean(), 'median': s.median(), 'std': s.std(),
        'p10': s.quantile(0.1), 'p25': s.quantile(0.25),
        'p75': s.quantile(0.75), 'p90': s.quantile(0.9),
        'min': s.min(), 'max': s.max(), 'count': len(s)
    }
    print(f"  {alias}: mean={s.mean():.2f} median={s.median():.2f} p10={s.quantile(0.1):.2f} p90={s.quantile(0.9):.2f}")

# Correlation
corr = df[['price','mvrv','puell','nvt_proxy','adr_ratio']].corr()

# Save all results for report generation
import pickle
results = {
    'df': df,
    'r_mvrv': r_mvrv,
    'r_mf1': r_mf1,
    'r_mf2': r_mf2,
    'luna_signals': luna_signals,
    'annual_data': annual_data,
    'eda_stats': eda_stats,
    'corr': corr,
}
with open("/tmp/research_results.pkl", "wb") as f:
    pickle.dump(results, f)

print("\nAll results saved to /tmp/research_results.pkl")
print("ANALYSIS_COMPLETE")
