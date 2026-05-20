#!/usr/bin/env python3
"""BTC Market Cycle Analysis: MVRV Structure Changes (Pre/Post Institutionalization)"""

import requests, time, json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import os
import hashlib
from datetime import datetime

# ─── Data Fetch ────────────────────────────────────────────────────────────────

def fetch_coinmetrics(metrics, start="2011-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {
        "assets": "btc",
        "metrics": metrics,
        "frequency": "1d",
        "start_time": start,
        "page_size": 1000
    }
    page = 0
    while True:
        try:
            j = requests.get(url, params=params, timeout=30).json()
        except Exception as e:
            print(f"Request error: {e}")
            break
        batch = j.get('data', [])
        all_data.extend(batch)
        print(f"  Page {page}: fetched {len(batch)} rows, total {len(all_data)}")
        token = j.get('next_page_token')
        if not token:
            break
        params = {
            "assets": "btc",
            "metrics": metrics,
            "frequency": "1d",
            "page_size": 1000,
            "next_page_token": token
        }
        page += 1
        time.sleep(0.1)

    df = pd.DataFrame(all_data)
    print(f"Columns: {df.columns.tolist()}")
    print(df.head(3))

    df['date'] = pd.to_datetime(df['time']).dt.tz_localize(None)
    df['price'] = pd.to_numeric(df['PriceUSD'], errors='coerce')
    df['mvrv'] = pd.to_numeric(df['CapMVRVCur'], errors='coerce')
    return df.sort_values('date').reset_index(drop=True)

# ─── Main Analysis ──────────────────────────────────────────────────────────────

print("Fetching BTC data from CoinMetrics...")
df = fetch_coinmetrics("PriceUSD,CapMVRVCur", start="2011-01-01")
df = df.dropna(subset=['price', 'mvrv'])
df = df[df['mvrv'] > 0]
print(f"Total rows: {len(df)}, date range: {df['date'].min()} to {df['date'].max()}")

# ─── Epoch Splits ──────────────────────────────────────────────────────────────
HALVINGS = {
    "H1": pd.Timestamp("2012-11-28"),
    "H2": pd.Timestamp("2016-07-09"),
    "H3": pd.Timestamp("2020-05-11"),
    "H4": pd.Timestamp("2024-04-20"),
}

IS_END = pd.Timestamp("2019-12-31")
OOS_START = pd.Timestamp("2020-01-01")

df_is = df[df['date'] <= IS_END].copy()
df_oos = df[df['date'] >= OOS_START].copy()

# ─── Part 1: MVRV Distribution Analysis ───────────────────────────────────────
print("\n=== PART 1: MVRV Statistical Properties ===")

def stats(d):
    return {
        "count": len(d),
        "mean": d.mean(),
        "median": d.median(),
        "std": d.std(),
        "skewness": d.skew(),
        "kurtosis": d.kurtosis(),
        "p25": d.quantile(0.25),
        "p50": d.quantile(0.50),
        "p75": d.quantile(0.75),
        "p80": d.quantile(0.80),
        "p90": d.quantile(0.90),
        "p95": d.quantile(0.95),
        "max": d.max(),
    }

s_is = stats(df_is['mvrv'])
s_oos = stats(df_oos['mvrv'])

print("\n2011-2019 (IS Period):")
for k, v in s_is.items():
    print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

print("\n2020-2026 (OOS Period):")
for k, v in s_oos.items():
    print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

# Bull market cycle peaks
print("\n--- Bull Cycle MVRV Peaks ---")
cycles = {
    "2013 Bull": ("2012-01-01", "2014-01-01"),
    "2017 Bull": ("2015-01-01", "2018-06-01"),
    "2021 Bull": ("2020-01-01", "2022-06-01"),
    "2024 Bull": ("2023-01-01", "2026-06-01"),
}
cycle_peaks = {}
for name, (s, e) in cycles.items():
    mask = (df['date'] >= s) & (df['date'] <= e)
    peak = df.loc[mask, 'mvrv'].max()
    peak_date = df.loc[mask & (df['mvrv'] == peak), 'date'].values[0] if peak > 0 else None
    cycle_peaks[name] = {"peak": peak, "date": str(peak_date)[:10] if peak_date else "N/A"}
    print(f"  {name}: MVRV peak = {peak:.2f} on {str(peak_date)[:10] if peak_date else 'N/A'}")

# Time spent by MVRV zone
def time_in_zones(d):
    zones = {
        "Zone 1 (MVRV < 1)": (d < 1).mean(),
        "Zone 2 (1-2)": ((d >= 1) & (d < 2)).mean(),
        "Zone 3 (2-3)": ((d >= 2) & (d < 3)).mean(),
        "Zone 4 (3-5)": ((d >= 3) & (d < 5)).mean(),
        "Zone 5 (5+)": (d >= 5).mean(),
    }
    return zones

print("\n--- Time Spent by Zone (IS: 2011-2019) ---")
z_is = time_in_zones(df_is['mvrv'])
for k, v in z_is.items():
    print(f"  {k}: {v*100:.1f}%")

print("\n--- Time Spent by Zone (OOS: 2020-2026) ---")
z_oos = time_in_zones(df_oos['mvrv'])
for k, v in z_oos.items():
    print(f"  {k}: {v*100:.1f}%")

# ─── Part 2: Halving Cycle Analysis ────────────────────────────────────────────
print("\n=== PART 2: Halving Cycle MVRV Analysis ===")

halving_data = {}
for name, halving_date in HALVINGS.items():
    mask = (df['date'] >= halving_date) & (df['date'] <= halving_date + pd.Timedelta(days=365))
    sub = df[mask].copy()
    sub['days_since_halving'] = (sub['date'] - halving_date).dt.days
    halving_data[name] = sub
    print(f"  {name} ({halving_date.date()}): {len(sub)} days of data")

# ─── Part 3: MVRV Z-Score ──────────────────────────────────────────────────────
print("\n=== PART 3: MVRV Z-Score ===")

# Rolling 4-year (1461 days) mean and std
ROLLING_WINDOW = 1461
df['mvrv_roll_mean'] = df['mvrv'].rolling(ROLLING_WINDOW, min_periods=100).mean()
df['mvrv_roll_std'] = df['mvrv'].rolling(ROLLING_WINDOW, min_periods=100).std()
df['mvrv_zscore'] = (df['mvrv'] - df['mvrv_roll_mean']) / df['mvrv_roll_std']

# Backtest Z-Score signal
def backtest_zscore(df, top_thresh=7.0, bot_thresh=-0.5):
    """Simple zone-based: 0% when zscore>top, 100% when zscore<bot, linear in between"""
    results = []
    position = 0.5  # start 50%
    for _, row in df.iterrows():
        z = row['mvrv_zscore']
        if pd.isna(z):
            pos = 0.5
        elif z >= top_thresh:
            pos = 0.0
        elif z <= bot_thresh:
            pos = 1.0
        else:
            pos = 1.0 - (z - bot_thresh) / (top_thresh - bot_thresh)
        results.append(pos)
    df = df.copy()
    df['zscore_position'] = results
    return df

df_bt = backtest_zscore(df)
df_bt['daily_return'] = df_bt['price'].pct_change()
df_bt['strategy_return'] = df_bt['zscore_position'].shift(1) * df_bt['daily_return']
df_bt['bh_cumret'] = (1 + df_bt['daily_return']).cumprod()
df_bt['strat_cumret'] = (1 + df_bt['strategy_return']).cumprod()

print(f"  Z-Score > 7 (top signal) dates:")
top_signals = df_bt[df_bt['mvrv_zscore'] > 7][['date', 'mvrv', 'mvrv_zscore', 'price']]
print(top_signals.to_string(index=False) if len(top_signals) > 0 else "  None found")

print(f"\n  Z-Score < -0.5 (bottom signal) dates (last 10):")
bot_signals = df_bt[df_bt['mvrv_zscore'] < -0.5][['date', 'mvrv', 'mvrv_zscore', 'price']].tail(10)
print(bot_signals.to_string(index=False))

# Z-Score stats by epoch
zs_is = df_bt.loc[df_bt['date'] <= IS_END, 'mvrv_zscore'].dropna()
zs_oos = df_bt.loc[df_bt['date'] >= OOS_START, 'mvrv_zscore'].dropna()
print(f"\n  Z-Score IS max: {zs_is.max():.2f}, mean: {zs_is.mean():.2f}")
print(f"  Z-Score OOS max: {zs_oos.max():.2f}, mean: {zs_oos.mean():.2f}")

# ─── Part 4: Visualizations ────────────────────────────────────────────────────
print("\n=== PART 4: Visualizations ===")

epoch_hex = format(int(time.time()), 'x')
rand_hex = hashlib.md5(epoch_hex.encode()).hexdigest()[:8]
chart_path = f"/root/.openclaw/workspace/openclaw-media/jarvis-image-{epoch_hex}-{rand_hex}.png"

# Color zones for MVRV
def mvrv_color(v):
    if v < 1:   return '#3a7ebf'   # blue: accumulation
    elif v < 2: return '#4caf50'   # green: fair value
    elif v < 3: return '#ffc107'   # amber: elevated
    elif v < 5: return '#ff7043'   # orange: danger
    else:       return '#b71c1c'   # dark red: extreme

fig, axes = plt.subplots(4, 1, figsize=(18, 22), facecolor='#0d1117')
fig.suptitle('BTC Market Cycle Analysis: MVRV Structure Changes', 
             fontsize=18, color='white', y=0.98, fontweight='bold')

colors = {
    'bg': '#0d1117',
    'grid': '#21262d',
    'text': '#c9d1d9',
    'price': '#f0b429',
    'mvrv': '#58a6ff',
    'zscore': '#bc8cff',
    'halving': '#ff6e96',
    'accent': '#3fb950',
}

def style_ax(ax, title):
    ax.set_facecolor(colors['bg'])
    ax.tick_params(colors=colors['text'], labelsize=9)
    ax.spines['bottom'].set_color(colors['grid'])
    ax.spines['left'].set_color(colors['grid'])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.set_title(title, color=colors['text'], fontsize=11, pad=8)
    ax.yaxis.label.set_color(colors['text'])
    ax.xaxis.label.set_color(colors['text'])
    ax.grid(True, color=colors['grid'], alpha=0.5, linewidth=0.5)

def add_halvings(ax, ymin, ymax):
    for name, hdate in HALVINGS.items():
        ax.axvline(hdate, color=colors['halving'], alpha=0.7, linewidth=1.2, linestyle='--')
        ax.text(hdate, ymax * 0.92, name, color=colors['halving'], fontsize=7, rotation=90, va='top')

# ── Panel 1: BTC Price (log) + MVRV colored background ───────────────────────
ax1 = axes[0]
style_ax(ax1, 'BTC Price (log scale) + MVRV Zone Background')

# Color background by MVRV zone
zone_colors_map = {'Zone1': '#1a237e20', 'Zone2': '#1b5e2030', 'Zone3': '#f57f1730',
                   'Zone4': '#bf360c30', 'Zone5': '#7f000030'}
zone_bounds = [(0, 1, '#1a237e20'), (1, 2, '#1b5e2020'), (2, 3, '#f57f1720'),
               (3, 5, '#bf360c25'), (5, 999, '#7f000035')]

ax1.semilogy(df['date'], df['price'], color=colors['price'], linewidth=0.8, label='BTC Price')
ax1.set_ylabel('Price (USD)', color=colors['text'])
add_halvings(ax1, df['price'].min(), df['price'].max())

# Add MVRV zone background shading
ax1_twin = ax1.twinx()
ax1_twin.set_facecolor(colors['bg'])
ax1_twin.fill_between(df['date'], df['mvrv'], 0, where=(df['mvrv'] < 1),
                       color='#1a237e', alpha=0.3, label='MVRV<1 (Accumulate)')
ax1_twin.fill_between(df['date'], df['mvrv'], 0, where=((df['mvrv'] >= 1) & (df['mvrv'] < 2)),
                       color='#1b5e20', alpha=0.3, label='MVRV 1-2 (Fair)')
ax1_twin.fill_between(df['date'], df['mvrv'], 0, where=((df['mvrv'] >= 2) & (df['mvrv'] < 3)),
                       color='#f57f17', alpha=0.3, label='MVRV 2-3 (Elevated)')
ax1_twin.fill_between(df['date'], df['mvrv'], 0, where=((df['mvrv'] >= 3) & (df['mvrv'] < 5)),
                       color='#bf360c', alpha=0.3, label='MVRV 3-5 (Danger)')
ax1_twin.fill_between(df['date'], df['mvrv'], 0, where=(df['mvrv'] >= 5),
                       color='#7f0000', alpha=0.4, label='MVRV 5+ (Extreme)')
ax1_twin.set_ylabel('MVRV', color=colors['mvrv'])
ax1_twin.tick_params(colors=colors['mvrv'], labelsize=8)
ax1_twin.spines['top'].set_visible(False)
ax1_twin.spines['right'].set_color(colors['grid'])
ax1_twin.set_ylim(0, 16)

# Add IS/OOS epoch demarcation
ax1.axvline(IS_END, color='cyan', alpha=0.8, linewidth=1.5, linestyle=':')
ax1.text(IS_END, 1000, 'IS→OOS\n2020', color='cyan', fontsize=7, ha='center')

# ── Panel 2: MVRV with statistical annotations ────────────────────────────────
ax2 = axes[1]
style_ax(ax2, 'MVRV Ratio: IS Period (2011-2019) vs OOS Period (2020-2026)')

ax2.plot(df_is['date'], df_is['mvrv'], color='#58a6ff', linewidth=0.8, label='IS MVRV (2011-2019)')
ax2.plot(df_oos['date'], df_oos['mvrv'], color='#3fb950', linewidth=0.8, label='OOS MVRV (2020-2026)')

# Add horizontal reference lines
for thresh, label, col in [(s_is['p80'], f'IS P80={s_is["p80"]:.2f}', '#58a6ff'),
                             (s_oos['p80'], f'OOS P80={s_oos["p80"]:.2f}', '#3fb950'),
                             (2.5, 'OOS peak zone ~2.4-2.8', '#ffc107')]:
    ax2.axhline(thresh, color=col, alpha=0.5, linewidth=1, linestyle='--')
    ax2.text(df['date'].iloc[-200], thresh + 0.05, label, color=col, fontsize=7)

# Mark cycle peaks
for name, data in cycle_peaks.items():
    if data['peak'] > 0 and data['date'] != 'N/A':
        try:
            peak_date = pd.Timestamp(data['date'])
            ax2.annotate(f"{name}\n{data['peak']:.1f}x",
                        xy=(peak_date, data['peak']),
                        xytext=(0, 15), textcoords='offset points',
                        fontsize=7, color='white',
                        arrowprops=dict(arrowstyle='->', color='white', lw=0.8),
                        ha='center')
        except:
            pass

add_halvings(ax2, 0, df['mvrv'].max())
ax2.set_ylabel('MVRV Ratio', color=colors['text'])
ax2.legend(fontsize=8, facecolor=colors['bg'], labelcolor=colors['text'], loc='upper left')
ax2.axvline(IS_END, color='cyan', alpha=0.8, linewidth=1.5, linestyle=':')

# ── Panel 3: Halving cycle MVRV overlay ───────────────────────────────────────
ax3 = axes[2]
style_ax(ax3, 'MVRV Post-Halving: 365-Day Window per Halving Cycle')

halving_colors = ['#58a6ff', '#3fb950', '#ffc107', '#ff6e96']
for (name, sub), col in zip(halving_data.items(), halving_colors):
    if len(sub) > 10:
        ax3.plot(sub['days_since_halving'], sub['mvrv'], color=col, linewidth=1.2,
                label=f'{name} ({sub["date"].iloc[0].year})', alpha=0.9)

ax3.axhline(2.5, color='#ffc107', alpha=0.5, linewidth=1, linestyle='--', label='2.5 threshold')
ax3.axhline(5.0, color='#ff6e96', alpha=0.5, linewidth=1, linestyle='--', label='5.0 threshold (old)')
ax3.axvspan(0, 180, alpha=0.08, color='#ffc107', label='First 180 days post-halving')
ax3.set_xlabel('Days Since Halving', color=colors['text'])
ax3.set_ylabel('MVRV Ratio', color=colors['text'])
ax3.legend(fontsize=8, facecolor=colors['bg'], labelcolor=colors['text'])

# ── Panel 4: MVRV Z-Score ─────────────────────────────────────────────────────
ax4 = axes[3]
style_ax(ax4, 'MVRV Z-Score (Rolling 4-Year Window) — Glassnode-style')

df_zs = df_bt.dropna(subset=['mvrv_zscore'])
ax4.plot(df_zs['date'], df_zs['mvrv_zscore'], color=colors['zscore'], linewidth=0.8, label='MVRV Z-Score')
ax4.fill_between(df_zs['date'], df_zs['mvrv_zscore'], 0,
                  where=(df_zs['mvrv_zscore'] > 0), color=colors['zscore'], alpha=0.15)
ax4.fill_between(df_zs['date'], df_zs['mvrv_zscore'], 0,
                  where=(df_zs['mvrv_zscore'] < 0), color='#58a6ff', alpha=0.2)

ax4.axhline(7, color='#b71c1c', alpha=0.8, linewidth=1.2, linestyle='--', label='Top: Z=7')
ax4.axhline(-0.5, color='#1b5e20', alpha=0.8, linewidth=1.2, linestyle='--', label='Bot: Z=-0.5')
ax4.axhline(0, color=colors['grid'], linewidth=0.8)

add_halvings(ax4, df_zs['mvrv_zscore'].min(), df_zs['mvrv_zscore'].max())
ax4.axvline(IS_END, color='cyan', alpha=0.8, linewidth=1.5, linestyle=':')
ax4.set_ylabel('Z-Score', color=colors['text'])
ax4.legend(fontsize=8, facecolor=colors['bg'], labelcolor=colors['text'])

plt.tight_layout(rect=[0, 0, 1, 0.97])
plt.savefig(chart_path, dpi=150, bbox_inches='tight', facecolor=colors['bg'])
plt.close()
print(f"Chart saved to: {chart_path}")

# ─── Save Analysis Data ─────────────────────────────────────────────────────────
analysis_data = {
    "is_stats": {k: float(v) if isinstance(v, (float, np.floating)) else int(v) for k, v in s_is.items()},
    "oos_stats": {k: float(v) if isinstance(v, (float, np.floating)) else int(v) for k, v in s_oos.items()},
    "cycle_peaks": {k: {"peak": float(v["peak"]), "date": v["date"]} for k, v in cycle_peaks.items()},
    "zone_is": {k: float(v) for k, v in z_is.items()},
    "zone_oos": {k: float(v) for k, v in z_oos.items()},
    "zscore_is_max": float(zs_is.max()),
    "zscore_oos_max": float(zs_oos.max()),
    "chart_path": chart_path,
}

with open("/root/.openclaw/workspace/research/btc_analysis_data.json", 'w') as f:
    json.dump(analysis_data, f, indent=2)

print("\nAnalysis complete! Data saved.")
print(json.dumps(analysis_data, indent=2))
