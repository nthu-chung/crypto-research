#!/usr/bin/env python3
"""Load saved data and complete LUNA analysis + generate final report."""

import pandas as pd
import numpy as np
import json

# Load checkpoint data
print("Loading saved data...")
df = pd.read_csv("/tmp/btc_onchain_data.csv")
df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)  # strip tz

num_cols = ['price', 'mvrv', 'issuance', 'active_addrs', 'tx_count', 'market_cap', 'supply', 'hashrate', 'total_tx', 'block_count']
for c in num_cols:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce')

print(f"Data: {df.shape}, {df['date'].min().date()} to {df['date'].max().date()}")

# Rebuild indicators
df['puell'] = df['issuance'] / df['issuance'].rolling(365, min_periods=180).mean()
df['on_chain_vol_proxy'] = df['tx_count'] * df['price'] * 0.01
df['nvt_proxy'] = df['market_cap'] / df['on_chain_vol_proxy'].rolling(90, min_periods=30).mean()
df['adr_ratio'] = df['active_addrs'] / df['active_addrs'].rolling(365, min_periods=90).mean()
df['hr_ma30'] = df['hashrate'].rolling(30, min_periods=10).mean()
df['hr_ma60'] = df['hashrate'].rolling(60, min_periods=20).mean()
df['hash_ribbon'] = (df['hr_ma30'] > df['hr_ma60']).astype(float)
df['price_ma200'] = df['price'].rolling(200, min_periods=90).mean()

def rolling_pct_rank(series, window=365*4, min_periods=90):
    return series.rolling(window, min_periods=min_periods).rank(pct=True) * 100

df['mvrv_bear'] = rolling_pct_rank(df['mvrv'])
df['puell_bear'] = rolling_pct_rank(df['puell'])
df['nvt_bear'] = rolling_pct_rank(df['nvt_proxy'])
df['adr_bear'] = 100 - rolling_pct_rank(df['adr_ratio'])

df['composite_v1'] = (0.50 * df['mvrv_bear'].fillna(50) + 0.30 * df['puell_bear'].fillna(50) + 0.20 * df['nvt_bear'].fillna(50))
df['composite_v2'] = (0.45 * df['mvrv_bear'].fillna(50) + 0.25 * df['puell_bear'].fillna(50) + 0.15 * df['nvt_bear'].fillna(50) + 0.15 * df['adr_bear'].fillna(50))

def mvrv_v2_pos(m):
    if pd.isna(m): return 0.0
    if m < 1.0: return 1.0
    elif m < 2.0: return 0.75
    elif m < 3.0: return 0.50
    elif m < 3.7: return 0.25
    else: return 0.0

def score_to_pos(s):
    if pd.isna(s): return 0.0
    if s < 20: return 1.0
    elif s < 40: return 0.75
    elif s < 60: return 0.50
    elif s < 75: return 0.25
    else: return 0.0

df['pos_mvrv_v2'] = df['mvrv'].apply(mvrv_v2_pos)
df['pos_mf_v1'] = df['composite_v1'].apply(score_to_pos)
df['pos_mf_v2'] = df['composite_v2'].apply(score_to_pos)

# LUNA CRASH ANALYSIS
print("\nLUNA crash analysis...")
luna_dates = [
    ("2022-03-01", "Pre-LUNA high (BTC ~$44k)"),
    ("2022-04-15", "April warning window (BTC ~$40k)"),
    ("2022-05-05", "5 days before LUNA collapse (BTC ~$38k)"),
    ("2022-05-10", "LUNA collapse begins (BTC ~$32k)"),
    ("2022-05-18", "Post-LUNA lows (BTC ~$29k)"),
    ("2022-06-15", "3AC/Celsius crisis (BTC ~$22k)"),
    ("2022-11-10", "FTX collapse (BTC ~$18k)"),
]

luna_signals = []
for date_str, label in luna_dates:
    target_dt = pd.Timestamp(date_str)
    diff = (df['date'] - target_dt).abs()
    idx = diff.idxmin()
    row = df.iloc[idx]
    
    entry = {
        "event": label,
        "date": str(row['date'].date()),
        "price": round(float(row['price']), 0) if not pd.isna(row['price']) else None,
        "mvrv": round(float(row['mvrv']), 3) if not pd.isna(row['mvrv']) else None,
        "puell": round(float(row['puell']), 3) if not pd.isna(row['puell']) else None,
        "nvt_proxy": round(float(row['nvt_proxy']), 1) if not pd.isna(row['nvt_proxy']) else None,
        "mvrv_bear_score": round(float(row['mvrv_bear']), 0) if not pd.isna(row['mvrv_bear']) else None,
        "puell_bear_score": round(float(row['puell_bear']), 0) if not pd.isna(row['puell_bear']) else None,
        "composite_v1": round(float(row['composite_v1']), 0) if not pd.isna(row['composite_v1']) else None,
        "pos_mvrv_v2": round(float(row['pos_mvrv_v2']), 2),
        "pos_mf_v1": round(float(row['pos_mf_v1']), 2),
    }
    luna_signals.append(entry)
    print(f"  {date_str}: Price=${entry['price']:,.0f} MVRV={entry['mvrv']} Puell={entry['puell']} Composite={entry['composite_v1']} Pos_MVRV={entry['pos_mvrv_v2']:.0%} Pos_MF={entry['pos_mf_v1']:.0%}")

# EDA stats
print("\nEDA stats:")
eda = {}
for col, name in [('mvrv','MVRV'), ('puell','Puell Multiple'), ('nvt_proxy','NVT Proxy'), ('adr_ratio','Active Addr Ratio')]:
    s = df[col].dropna()
    eda[col] = {
        'name': name,
        'count': len(s),
        'mean': round(s.mean(), 3),
        'median': round(s.median(), 3),
        'std': round(s.std(), 3),
        'min': round(s.min(), 3),
        'max': round(s.max(), 3),
        'p10': round(s.quantile(0.1), 3),
        'p25': round(s.quantile(0.25), 3),
        'p75': round(s.quantile(0.75), 3),
        'p90': round(s.quantile(0.9), 3),
    }
    print(f"  {name}: count={len(s)} mean={s.mean():.2f} median={s.median():.2f} p10={s.quantile(0.1):.2f} p90={s.quantile(0.9):.2f}")

# Correlation with price
corr = df[['price','mvrv','puell','nvt_proxy','adr_ratio']].dropna().corr()
print("\nCorrelations (with price):")
for col in ['mvrv','puell','nvt_proxy','adr_ratio']:
    if col in corr.columns:
        print(f"  {col}: {corr.loc['price', col]:.3f}")

# Annual breakdown
print("\nAnnual returns:")
def backtest(df, position_col, start='2017-01-01', capital=100_000):
    sub = df[(df['date'] >= start) & df['price'].notna() & df[position_col].notna()].copy().reset_index(drop=True)
    cap = float(capital); btc = 0.0; last_rb = None; trades = 0
    rows = []
    for _, row in sub.iterrows():
        p = row['price']; tgt = row[position_col]; d = row['date']
        pv = cap + btc * p
        if last_rb is None or (d - last_rb).days >= 7:
            new_btc = pv * tgt / p
            cost = abs(new_btc - btc) * p * 0.001
            btc = new_btc; cap = pv * (1 - tgt) - cost
            if abs(new_btc) > 1e-9: trades += 1
            last_rb = d
        pv = cap + btc * p
        rows.append({'date': d, 'equity': pv, 'price': p})
    eq = pd.DataFrame(rows)
    final = eq['equity'].iloc[-1]
    days = (eq['date'].iloc[-1] - eq['date'].iloc[0]).days
    yrs = max(days/365, 0.1)
    cagr = (final/capital)**(1/yrs) - 1
    rm = eq['equity'].cummax(); dd = (eq['equity'] - rm)/rm; maxdd = dd.min()
    dr = eq['equity'].pct_change().dropna()
    sharpe = (dr.mean()/dr.std())*np.sqrt(365) if dr.std() > 0 else 0
    calmar = cagr/abs(maxdd) if maxdd != 0 else 0
    bh = (sub['price'].iloc[-1]/sub['price'].iloc[0])-1
    bh_cagr = (1+bh)**(1/yrs)-1
    return {'cagr': cagr, 'maxdd': maxdd, 'sharpe': sharpe, 'calmar': calmar,
            'total_ret': (final-capital)/capital, 'bh_cagr': bh_cagr, 'trades': trades, 'eq': eq}

r1 = backtest(df, 'pos_mvrv_v2')
r2 = backtest(df, 'pos_mf_v1')
r3 = backtest(df, 'pos_mf_v2')

annual = {}
for year in range(2017, 2026):
    d1 = r1['eq'][r1['eq']['date'].dt.year == year]
    d2 = r2['eq'][r2['eq']['date'].dt.year == year]
    d3 = r3['eq'][r3['eq']['date'].dt.year == year]
    if len(d1) > 5:
        mvrv_r = (d1['equity'].iloc[-1]/d1['equity'].iloc[0])-1
        mf1_r = (d2['equity'].iloc[-1]/d2['equity'].iloc[0])-1 if len(d2) > 5 else None
        mf2_r = (d3['equity'].iloc[-1]/d3['equity'].iloc[0])-1 if len(d3) > 5 else None
        btc_r = (d1['price'].iloc[-1]/d1['price'].iloc[0])-1
        annual[year] = {'mvrv_v2': mvrv_r, 'mf_v1': mf1_r, 'mf_v2': mf2_r, 'btc': btc_r}
        print(f"  {year}: MVRV_v2={mvrv_r:.1%} MF_v1={mf1_r:.1%} BTC={btc_r:.1%}")

# Save all for report
import pickle
with open("/tmp/final_results.pkl", "wb") as f:
    pickle.dump({
        'r1': r1, 'r2': r2, 'r3': r3,
        'luna_signals': luna_signals,
        'annual': annual,
        'eda': eda,
        'corr': corr,
        'df': df[['date','price','mvrv','puell','nvt_proxy','adr_ratio','mvrv_bear','puell_bear','composite_v1','pos_mvrv_v2','pos_mf_v1','pos_mf_v2']].to_dict()
    }, f)

print("\nFINAL_RESULTS:")
print(f"  MVRV v2:   CAGR={r1['cagr']:.1%} MaxDD={r1['maxdd']:.1%} Sharpe={r1['sharpe']:.2f} Calmar={r1['calmar']:.2f}")
print(f"  MF v1:     CAGR={r2['cagr']:.1%} MaxDD={r2['maxdd']:.1%} Sharpe={r2['sharpe']:.2f} Calmar={r2['calmar']:.2f}")
print(f"  MF v2:     CAGR={r3['cagr']:.1%} MaxDD={r3['maxdd']:.1%} Sharpe={r3['sharpe']:.2f} Calmar={r3['calmar']:.2f}")
print(f"  B&H:       CAGR={r1['bh_cagr']:.1%}")
print("DONE")
