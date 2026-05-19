#!/usr/bin/env python3
"""
Funding Rate Strategy Research
Sharpe > 1, MaxDD < -20% target
"""

import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import warnings
warnings.filterwarnings('ignore')
import time
import json
from pathlib import Path

MEDIA_DIR = Path("/root/.openclaw/workspace/openclaw-media")
RESEARCH_DIR = Path("/root/.openclaw/workspace/research")
MEDIA_DIR.mkdir(exist_ok=True)
RESEARCH_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

def fetch_funding_rate(symbol="BTCUSDT", start="2020-01-01"):
    """Binance Futures Funding Rate History"""
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    all_data = []
    start_ts = int(pd.Timestamp(start).timestamp() * 1000)
    end_ts = int(pd.Timestamp("2026-05-19").timestamp() * 1000)
    
    while start_ts < end_ts:
        r = requests.get(url, params={
            "symbol": symbol,
            "startTime": start_ts,
            "limit": 1000
        }, timeout=15)
        data = r.json()
        if not data or isinstance(data, dict):
            break
        all_data.extend(data)
        start_ts = data[-1]['fundingTime'] + 1
        if len(data) < 1000:
            break
        time.sleep(0.15)
    
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['fundingTime'], unit='ms', utc=True)
    df['funding_rate'] = df['fundingRate'].astype(float)
    df['symbol'] = df['symbol']
    return df.sort_values('date').reset_index(drop=True)


def fetch_binance_daily(symbol="BTCUSDT", start="2020-01-01"):
    url = "https://api.binance.com/api/v3/klines"
    all_data, start_ts = [], int(pd.Timestamp(start).timestamp()*1000)
    end_ts = int(pd.Timestamp("2026-05-19").timestamp()*1000)
    while start_ts < end_ts:
        r = requests.get(url, params={"symbol": symbol, "interval": "1d",
                                       "startTime": start_ts, "limit": 1000}, timeout=15)
        data = r.json()
        if not data or isinstance(data, dict):
            break
        all_data.extend(data)
        start_ts = data[-1][0] + 86400000
        if len(data) < 1000:
            break
        time.sleep(0.15)
    df = pd.DataFrame(all_data, columns=['ts','open','high','low','close','vol','cts','qvol','n','tbbav','tbqav','x'])
    df['date'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    for c in ['open','high','low','close']:
        df[c] = df[c].astype(float)
    return df[['date','open','high','low','close']].sort_values('date').reset_index(drop=True)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def compute_metrics(returns, label=""):
    """Compute Sharpe, MaxDD, CAGR from daily returns Series."""
    # CAGR
    n_years = len(returns) / 252
    total = (1 + returns).prod()
    cagr = total ** (1 / n_years) - 1 if n_years > 0 else 0
    
    # Sharpe (daily risk-free ≈ 0)
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    
    # Max Drawdown
    cumulative = (1 + returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    # Win rate
    win_rate = (returns > 0).mean()
    
    print(f"[{label}] CAGR={cagr:.1%}, Sharpe={sharpe:.2f}, MaxDD={max_dd:.1%}, WinRate={win_rate:.1%}")
    return {
        "label": label,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "total_return": total - 1,
        "n_years": n_years,
        "equity": cumulative
    }


def split_is_oos(df, oos_start="2023-01-01"):
    """Split DataFrame into IS and OOS periods."""
    oos_ts = pd.Timestamp(oos_start, tz='UTC')
    is_mask = df.index < oos_ts if isinstance(df.index, pd.DatetimeIndex) else df['date'] < oos_ts
    return df[is_mask], df[~is_mask]


# ─────────────────────────────────────────────
# MAIN RESEARCH
# ─────────────────────────────────────────────

print("=" * 60)
print("FUNDING RATE STRATEGY RESEARCH")
print("=" * 60)

# 1. Fetch data
print("\n[1] Fetching data...")
symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

fr_data = {}
price_data = {}

for sym in symbols:
    print(f"  Fetching funding rate: {sym}")
    fr_data[sym] = fetch_funding_rate(sym, "2020-01-01")
    print(f"  Fetching price: {sym}")
    price_data[sym] = fetch_binance_daily(sym, "2020-01-01")
    print(f"  {sym}: {len(fr_data[sym])} FR records, {len(price_data[sym])} price days")

# 2. Build daily FR series
print("\n[2] Building daily FR signals...")

def build_daily_fr(fr_df):
    """Aggregate 3x/day funding rate to daily."""
    fr_df = fr_df.copy()
    fr_df['day'] = fr_df['date'].dt.normalize()
    daily = fr_df.groupby('day')['funding_rate'].sum()  # sum of 3 periods = daily cost
    daily.index = pd.DatetimeIndex(daily.index, tz='UTC')
    return daily

daily_fr = {sym: build_daily_fr(fr_data[sym]) for sym in symbols}

# BTC daily price
btc_price = price_data["BTCUSDT"].set_index('date')['close']
btc_price.index = pd.DatetimeIndex(btc_price.index, tz='UTC')
btc_returns = btc_price.pct_change().dropna()

# ─────────────────────────────────────────────
# EDA
# ─────────────────────────────────────────────
print("\n[3] EDA: Funding Rate Analysis")

btc_fr = daily_fr["BTCUSDT"].copy()
eth_fr = daily_fr["ETHUSDT"].copy()

# Align
common_idx = btc_fr.index.intersection(btc_price.index)
btc_fr_aligned = btc_fr.reindex(common_idx)
btc_price_aligned = btc_price.reindex(common_idx)
btc_ret_aligned = btc_price_aligned.pct_change()

# Z-score signal
fr_90d_mean = btc_fr_aligned.rolling(90, min_periods=30).mean()
fr_90d_std = btc_fr_aligned.rolling(90, min_periods=30).std()
fr_z = (btc_fr_aligned - fr_90d_mean) / fr_90d_std.replace(0, np.nan)

# Percentiles
p5 = btc_fr_aligned.quantile(0.05)
p95 = btc_fr_aligned.quantile(0.95)
print(f"  BTC FR stats: mean={btc_fr_aligned.mean():.4%}, std={btc_fr_aligned.std():.4%}")
print(f"  p5={p5:.4%}, p95={p95:.4%}")
print(f"  Daily FR avg (annualized): {btc_fr_aligned.mean() * 365:.1%}")

# Forward returns after extreme FR
results_eda = {}
for horizon in [1, 3, 7, 14]:
    fwd_ret = btc_ret_aligned.rolling(horizon).sum().shift(-horizon)
    
    high_fr_mask = fr_z > 2.0
    low_fr_mask = fr_z < -1.5
    
    results_eda[f"high_fr_{horizon}d"] = fwd_ret[high_fr_mask].mean()
    results_eda[f"low_fr_{horizon}d"] = fwd_ret[low_fr_mask].mean()
    
    print(f"  After extreme HIGH FR (z>2): {horizon}d fwd return = {fwd_ret[high_fr_mask].mean():.2%}")
    print(f"  After extreme LOW  FR (z<-1.5): {horizon}d fwd return = {fwd_ret[low_fr_mask].mean():.2%}")

# Special analysis: key historical events
print("\n  Key Historical Events:")
# 2021-05 crash
mask_2021_04 = (btc_fr_aligned.index >= '2021-03-01') & (btc_fr_aligned.index <= '2021-05-20')
print(f"  2021-04 peak FR: {btc_fr_aligned[mask_2021_04].max():.4%} (daily)")

# 2022-06 bottom
mask_2022_06 = (btc_fr_aligned.index >= '2022-05-01') & (btc_fr_aligned.index <= '2022-07-31')
print(f"  2022-06 bottom FR: {btc_fr_aligned[mask_2022_06].min():.4%} (daily)")

# 2024-03 ATH
mask_2024_03 = (btc_fr_aligned.index >= '2024-02-01') & (btc_fr_aligned.index <= '2024-04-30')
print(f"  2024-03 ATH FR peak: {btc_fr_aligned[mask_2024_03].max():.4%} (daily)")

# ─────────────────────────────────────────────
# STRATEGY BUILDING
# ─────────────────────────────────────────────

# Align all series to common date index
common_dates = btc_fr_aligned.index.intersection(btc_ret_aligned.dropna().index)
fr_z_s = fr_z.reindex(common_dates).ffill()
btc_ret_s = btc_ret_aligned.reindex(common_dates).fillna(0)
btc_price_s = btc_price_aligned.reindex(common_dates)

print(f"\n  Data range: {common_dates[0].date()} to {common_dates[-1].date()} ({len(common_dates)} days)")

IS_end = pd.Timestamp("2022-12-31", tz='UTC')
OOS_start = pd.Timestamp("2023-01-01", tz='UTC')


# ─────────────────────────────────────────────
# STRATEGY A: Pure Funding Rate Timing
# ─────────────────────────────────────────────
print("\n[4] Strategy A: Pure FR Timing")

def strategy_a(fr_z_series, price_returns, fee=0.0004):
    """
    fr_z > 2.0  → 20% position
    fr_z > 1.0  → 50% position
    -1.0 < fr_z < 1.0 → 100% position
    fr_z < -1.5 → 100% position (no leverage)
    """
    position = pd.Series(1.0, index=fr_z_series.index)
    position[fr_z_series > 2.0] = 0.20
    position[(fr_z_series > 1.0) & (fr_z_series <= 2.0)] = 0.50
    position[fr_z_series < -1.5] = 1.0  # max 100% no leverage
    
    # Calculate turnover and fees
    pos_change = position.diff().abs().fillna(0)
    
    # Strategy returns: position * next day return - fees on position changes
    strat_returns = position.shift(1).fillna(1.0) * price_returns - pos_change * fee
    return strat_returns, position

strat_a_ret, strat_a_pos = strategy_a(fr_z_s, btc_ret_s)

# BTC Buy & Hold
bnh_ret = btc_ret_s.copy()

print("  IS (2020-2022):")
is_mask = common_dates <= IS_end
m_a_is = compute_metrics(strat_a_ret[is_mask], "Strat A IS")
m_bnh_is = compute_metrics(bnh_ret[is_mask], "BnH IS")

print("  OOS (2023-2026):")
oos_mask = common_dates >= OOS_start
m_a_oos = compute_metrics(strat_a_ret[oos_mask], "Strat A OOS")
m_bnh_oos = compute_metrics(bnh_ret[oos_mask], "BnH OOS")

print("  Full period:")
m_a_full = compute_metrics(strat_a_ret, "Strat A Full")
m_bnh_full = compute_metrics(bnh_ret, "BnH Full")


# ─────────────────────────────────────────────
# STRATEGY B: FR + MVRV Combo (approx MVRV via long-term MA)
# ─────────────────────────────────────────────
print("\n[5] Strategy B: FR + MVRV Combo (MA proxy)")

def compute_mvrv_proxy(price_series, lookback=365):
    """
    Proxy MVRV using 365-day MA ratio (price vs. realized value proxy).
    When price >> 365d MA, overvalued; when price << 365d MA, undervalued.
    """
    ma = price_series.rolling(lookback, min_periods=lookback//2).mean()
    mvrv_proxy = price_series / ma
    return mvrv_proxy

mvrv_proxy = compute_mvrv_proxy(btc_price_s)

# MVRV-based base position (percentile-based)
mvrv_roll_pct = mvrv_proxy.rolling(365, min_periods=90).rank(pct=True)

def strategy_b(fr_z_series, mvrv_pct, price_returns, fee=0.0004):
    """
    MVRV percentile → base position
    FR z-score → multiplier
    """
    # Base position from MVRV
    base = pd.Series(1.0, index=mvrv_pct.index)
    base[mvrv_pct > 0.85] = 0.30
    base[(mvrv_pct > 0.70) & (mvrv_pct <= 0.85)] = 0.60
    base[(mvrv_pct > 0.40) & (mvrv_pct <= 0.70)] = 1.0
    base[mvrv_pct <= 0.40] = 1.0
    
    # FR multiplier
    fr_mult = pd.Series(1.0, index=fr_z_series.index)
    fr_mult[fr_z_series > 2.0] = 0.3
    fr_mult[(fr_z_series > 1.0) & (fr_z_series <= 2.0)] = 0.7
    fr_mult[fr_z_series < -1.5] = 1.2
    
    position = (base * fr_mult).clip(0, 1.0)  # no leverage for spot
    pos_change = position.diff().abs().fillna(0)
    strat_returns = position.shift(1).fillna(1.0) * price_returns - pos_change * fee
    return strat_returns, position

strat_b_ret, strat_b_pos = strategy_b(fr_z_s, mvrv_roll_pct.reindex(common_dates).ffill(), btc_ret_s)

print("  IS (2020-2022):")
m_b_is = compute_metrics(strat_b_ret[is_mask], "Strat B IS")

print("  OOS (2023-2026):")
m_b_oos = compute_metrics(strat_b_ret[oos_mask], "Strat B OOS")

print("  Full:")
m_b_full = compute_metrics(strat_b_ret, "Strat B Full")


# ─────────────────────────────────────────────
# STRATEGY C: Spot-Futures Funding Rate Arb
# ─────────────────────────────────────────────
print("\n[6] Strategy C: Funding Rate Arb (Spot Long / Futures Short)")

def strategy_c(btc_fr_daily, eth_fr_daily, btc_price_ret, eth_price_ret, threshold=0.0003, fee=0.0002):
    """
    When BTC FR > threshold AND ETH FR > threshold:
      → Long spot (delta neutral: price return cancels), collect FR
    P&L = FR collected - fees
    When FR < threshold: sit in stablecoin (0 return)
    
    Simplified: both legs cancel on price, net = FR - fees
    We assume perfect hedge so price return is 0 when active
    """
    common = btc_fr_daily.index.intersection(eth_fr_daily.index)
    btc_fr = btc_fr_daily.reindex(common)
    eth_fr = eth_fr_daily.reindex(common)
    
    # Average FR across BTC and ETH (equal weight)
    avg_fr = (btc_fr + eth_fr) / 2
    
    active = (btc_fr > threshold) & (eth_fr > threshold)
    
    # Net return when active = avg FR collected - fee (small)
    strat_ret = pd.Series(0.0, index=common)
    # When active: collect avg FR (positive), but pay trading fee on entry/exit
    position_change = active.astype(float).diff().abs().fillna(0)
    strat_ret[active] = avg_fr[active] - fee * position_change[active]
    strat_ret[~active] = 0  # In stablecoin, 0 return
    
    return strat_ret, active

btc_fr_d = daily_fr["BTCUSDT"].copy()
eth_fr_d = daily_fr["ETHUSDT"].copy()
btc_fr_d.index = pd.DatetimeIndex(btc_fr_d.index, tz='UTC')
eth_fr_d.index = pd.DatetimeIndex(eth_fr_d.index, tz='UTC')

strat_c_ret, strat_c_active = strategy_c(btc_fr_d, eth_fr_d, btc_ret_s, btc_ret_s)

# Align to common dates
strat_c_ret = strat_c_ret.reindex(common_dates).fillna(0)
strat_c_active_aligned = strat_c_active.reindex(common_dates).fillna(False)

print(f"  Active days: {strat_c_active_aligned.sum()} / {len(strat_c_active_aligned)} ({strat_c_active_aligned.mean():.1%})")
print(f"  Avg FR collected when active: {btc_fr_d[strat_c_active_aligned.reindex(btc_fr_d.index).fillna(False)].mean():.4%}/day")

print("  IS:")
m_c_is = compute_metrics(strat_c_ret[is_mask], "Strat C IS")
print("  OOS:")
m_c_oos = compute_metrics(strat_c_ret[oos_mask], "Strat C OOS")
print("  Full:")
m_c_full = compute_metrics(strat_c_ret, "Strat C Full")


# ─────────────────────────────────────────────
# STRATEGY D: Multi-Coin FR Rotation
# ─────────────────────────────────────────────
print("\n[7] Strategy D: Multi-Coin FR Rotation")

def strategy_d(fr_daily_dict, price_dict, symbols, fee=0.0004):
    """
    Each week: rank coins by FR (ascending = most negative = highest opportunity)
    Allocate more to lowest FR coins.
    """
    # Build daily FR and price DataFrame
    fr_df = pd.DataFrame({s: fr_daily_dict[s] for s in symbols})
    
    # Weekly resampling for signal
    fr_weekly = fr_df.resample('W').mean()
    
    # Build price returns
    ret_df = pd.DataFrame({
        s: price_dict[s].set_index('date')['close'].astype(float).pct_change()
        for s in symbols
    })
    ret_df.index = pd.DatetimeIndex(ret_df.index, tz='UTC')
    
    # Align
    common = fr_df.index.intersection(ret_df.index)
    fr_df = fr_df.reindex(common).ffill()
    ret_df = ret_df.reindex(common).ffill().fillna(0)
    
    # Weekly FR signal → daily weights
    # Lower FR → higher weight
    # Use negative FR rank as weight (rank 1 = lowest FR = highest weight)
    weights = pd.DataFrame(index=common, columns=symbols, dtype=float)
    
    for i, date in enumerate(common):
        # Use last 7-day avg FR
        if i < 7:
            w = pd.Series(0.25, index=symbols)
        else:
            fr_week = fr_df.iloc[i-7:i].mean()
            # Rank: lowest FR = highest rank
            rank = fr_week.rank(ascending=True)  # rank 1 = most negative
            # Weight proportional to rank (inverse FR)
            w = rank / rank.sum()
        weights.iloc[i] = w.values
    
    # Calculate strategy returns (rebalanced weekly, position shift 1 day)
    port_ret = (weights.shift(1) * ret_df).sum(axis=1)
    
    # Approximate turnover cost
    turnover = weights.diff().abs().sum(axis=1).fillna(0)
    port_ret = port_ret - turnover * fee
    
    return port_ret, weights

strat_d_ret, strat_d_weights = strategy_d(daily_fr, price_data, symbols)
strat_d_ret = strat_d_ret.reindex(common_dates).fillna(0)

print("  IS:")
m_d_is = compute_metrics(strat_d_ret[is_mask], "Strat D IS")
print("  OOS:")
m_d_oos = compute_metrics(strat_d_ret[oos_mask], "Strat D OOS")
print("  Full:")
m_d_full = compute_metrics(strat_d_ret, "Strat D Full")


# ─────────────────────────────────────────────
# VISUALIZATIONS
# ─────────────────────────────────────────────
print("\n[8] Generating visualizations...")

# ── Plot 1: BTC Price + Funding Rate + Signal
fig, axes = plt.subplots(4, 1, figsize=(14, 16), sharex=True)
fig.suptitle('BTC Price vs Funding Rate Signal Analysis', fontsize=14, fontweight='bold')

ax1 = axes[0]
ax1.semilogy(btc_price_s.index, btc_price_s.values, color='#F3BA2F', linewidth=1.5, label='BTC Price')
ax1.set_ylabel('BTC Price (USD)', fontsize=10)
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)

ax2 = axes[1]
ax2.bar(btc_fr_aligned.index, btc_fr_aligned.values * 100, color='steelblue', alpha=0.6, label='Daily FR (%)', width=1)
ax2.axhline(0, color='black', linewidth=0.5)
ax2.axhline(btc_fr_aligned.quantile(0.95) * 100, color='red', linewidth=1, linestyle='--', label=f'p95={btc_fr_aligned.quantile(0.95)*100:.3f}%')
ax2.axhline(btc_fr_aligned.quantile(0.05) * 100, color='green', linewidth=1, linestyle='--', label=f'p5={btc_fr_aligned.quantile(0.05)*100:.3f}%')
ax2.set_ylabel('Daily Funding Rate (%)', fontsize=10)
ax2.legend(loc='upper left', fontsize=8)
ax2.grid(True, alpha=0.3)

ax3 = axes[2]
ax3.plot(fr_z_s.index, fr_z_s.values, color='purple', linewidth=1, label='FR Z-Score (90d)')
ax3.axhline(2.0, color='red', linewidth=1.5, linestyle='--', label='z=+2 (Over-heated)')
ax3.axhline(-1.5, color='green', linewidth=1.5, linestyle='--', label='z=-1.5 (Panic)')
ax3.axhline(0, color='gray', linewidth=0.5)
ax3.fill_between(fr_z_s.index, 2.0, fr_z_s.values, where=fr_z_s.values > 2.0, color='red', alpha=0.3)
ax3.fill_between(fr_z_s.index, -1.5, fr_z_s.values, where=fr_z_s.values < -1.5, color='green', alpha=0.3)
ax3.set_ylabel('FR Z-Score', fontsize=10)
ax3.legend(loc='upper left', fontsize=8)
ax3.grid(True, alpha=0.3)

ax4 = axes[3]
ax4.plot(strat_a_pos.index, strat_a_pos.values * 100, color='orange', linewidth=1, label='Strat A Position %')
ax4.set_ylabel('Position Size (%)', fontsize=10)
ax4.set_ylim(0, 120)
ax4.legend(loc='upper left')
ax4.grid(True, alpha=0.3)
ax4.set_xlabel('Date')

# Add key event annotations
for ax in axes:
    ax.axvline(pd.Timestamp('2021-05-19', tz='UTC'), color='red', linewidth=1, alpha=0.5, linestyle=':')
    ax.axvline(pd.Timestamp('2022-06-18', tz='UTC'), color='green', linewidth=1, alpha=0.5, linestyle=':')
    ax.axvline(pd.Timestamp('2024-03-14', tz='UTC'), color='gold', linewidth=1, alpha=0.5, linestyle=':')

axes[0].text(pd.Timestamp('2021-05-19', tz='UTC'), btc_price_s.max() * 0.5, '2021 Crash', fontsize=7, rotation=90, color='red')
axes[0].text(pd.Timestamp('2022-06-18', tz='UTC'), btc_price_s.max() * 0.5, '2022 Bottom', fontsize=7, rotation=90, color='green')
axes[0].text(pd.Timestamp('2024-03-14', tz='UTC'), btc_price_s.max() * 0.5, '2024 ATH', fontsize=7, rotation=90, color='goldenrod')

plt.tight_layout()
plt.savefig(MEDIA_DIR / 'fr_analysis.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: fr_analysis.png")


# ── Plot 2: Strategy Equity Curves
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('Strategy Equity Curves (2020-2026)', fontsize=14, fontweight='bold')

strategies = [
    (strat_a_ret, 'Strategy A\nPure FR Timing', axes[0, 0], '#E67E22'),
    (strat_b_ret, 'Strategy B\nFR + MVRV Proxy', axes[0, 1], '#27AE60'),
    (strat_c_ret, 'Strategy C\nFunding Rate Arb', axes[1, 0], '#3498DB'),
    (strat_d_ret, 'Strategy D\nMulti-Coin Rotation', axes[1, 1], '#9B59B6'),
]

for (ret, title, ax, color) in strategies:
    bnh_eq = (1 + bnh_ret).cumprod()
    strat_eq = (1 + ret).cumprod()
    
    ax.plot(bnh_eq.index, bnh_eq.values, color='gray', linewidth=1, alpha=0.5, label='BTC B&H')
    ax.plot(strat_eq.index, strat_eq.values, color=color, linewidth=2, label=title.split('\n')[0])
    
    # IS/OOS divider
    ax.axvline(pd.Timestamp('2023-01-01', tz='UTC'), color='black', linewidth=1.5, linestyle='--', alpha=0.7)
    ax.text(pd.Timestamp('2021-06-01', tz='UTC'), strat_eq.max() * 0.9, 'IS', fontsize=10, color='black')
    ax.text(pd.Timestamp('2024-01-01', tz='UTC'), strat_eq.max() * 0.9, 'OOS', fontsize=10, color='black')
    
    m = compute_metrics(ret, title.replace('\n', ' '))
    info = f"Sharpe={m['sharpe']:.2f}\nMaxDD={m['max_dd']:.1%}\nCAGR={m['cagr']:.1%}"
    ax.text(0.02, 0.02, info, transform=ax.transAxes, fontsize=8,
            verticalalignment='bottom', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.set_ylabel('Portfolio Value (starting=1)')

plt.tight_layout()
plt.savefig(MEDIA_DIR / 'strategy_equity_curves.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: strategy_equity_curves.png")


# ── Plot 3: FR Distribution
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
fig.suptitle('Funding Rate Distribution Analysis', fontsize=13, fontweight='bold')

ax1 = axes[0]
btc_fr_vals = btc_fr_aligned.values * 100
ax1.hist(btc_fr_vals, bins=100, color='steelblue', alpha=0.7, edgecolor='navy', linewidth=0.3)
ax1.axvline(np.percentile(btc_fr_vals, 5), color='green', linewidth=2, linestyle='--', label=f'p5={np.percentile(btc_fr_vals,5):.3f}%')
ax1.axvline(np.percentile(btc_fr_vals, 95), color='red', linewidth=2, linestyle='--', label=f'p95={np.percentile(btc_fr_vals,95):.3f}%')
ax1.axvline(btc_fr_vals.mean(), color='orange', linewidth=2, linestyle='-', label=f'mean={btc_fr_vals.mean():.3f}%')
ax1.set_xlabel('Daily Funding Rate (%)')
ax1.set_ylabel('Frequency')
ax1.set_title('BTC Daily Funding Rate Distribution')
ax1.legend()
ax1.grid(True, alpha=0.3)

ax2 = axes[1]
# Compare strategies' monthly returns
def monthly_returns(ret):
    return (1 + ret).resample('ME').prod() - 1

for (ret, label, color) in [
    (strat_a_ret, 'Strat A', '#E67E22'),
    (strat_b_ret, 'Strat B', '#27AE60'),
    (strat_c_ret, 'Strat C', '#3498DB'),
    (strat_d_ret, 'Strat D', '#9B59B6'),
    (bnh_ret, 'BTC B&H', 'gray'),
]:
    mret = monthly_returns(ret)
    ax2.plot(mret.index, (1 + mret).cumprod(), linewidth=1.5, label=label, color=color)

ax2.axvline(pd.Timestamp('2023-01-01', tz='UTC'), color='black', linewidth=1.5, linestyle='--', alpha=0.7, label='IS/OOS Split')
ax2.set_title('All Strategies Comparison')
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.3)
ax2.set_ylabel('Cumulative Return (monthly resampled)')

plt.tight_layout()
plt.savefig(MEDIA_DIR / 'fr_distribution_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: fr_distribution_comparison.png")


# ─────────────────────────────────────────────
# SUMMARY TABLE
# ─────────────────────────────────────────────
print("\n[9] Summary Table")

all_metrics = []
for (ret, label, period) in [
    (strat_a_ret[is_mask], "A: Pure FR Timing", "IS"),
    (strat_a_ret[oos_mask], "A: Pure FR Timing", "OOS"),
    (strat_a_ret, "A: Pure FR Timing", "Full"),
    (strat_b_ret[is_mask], "B: FR+MVRV Proxy", "IS"),
    (strat_b_ret[oos_mask], "B: FR+MVRV Proxy", "OOS"),
    (strat_b_ret, "B: FR+MVRV Proxy", "Full"),
    (strat_c_ret[is_mask], "C: FR Arb", "IS"),
    (strat_c_ret[oos_mask], "C: FR Arb", "OOS"),
    (strat_c_ret, "C: FR Arb", "Full"),
    (strat_d_ret[is_mask], "D: Multi-Coin Rotation", "IS"),
    (strat_d_ret[oos_mask], "D: Multi-Coin Rotation", "OOS"),
    (strat_d_ret, "D: Multi-Coin Rotation", "Full"),
    (bnh_ret[is_mask], "BTC Buy & Hold", "IS"),
    (bnh_ret[oos_mask], "BTC Buy & Hold", "OOS"),
    (bnh_ret, "BTC Buy & Hold", "Full"),
]:
    m = compute_metrics(ret, f"{label} {period}")
    all_metrics.append({
        "Strategy": label,
        "Period": period,
        "CAGR": f"{m['cagr']:.1%}",
        "Sharpe": f"{m['sharpe']:.2f}",
        "MaxDD": f"{m['max_dd']:.1%}",
        "WinRate": f"{m['win_rate']:.1%}",
        "TotalReturn": f"{m['total_return']:.1%}",
    })

summary_df = pd.DataFrame(all_metrics)
print(summary_df.to_string(index=False))

# Save results as JSON
results = {
    "summary": all_metrics,
    "eda": {k: float(v) for k, v in results_eda.items()},
    "fr_stats": {
        "btc_daily_mean": float(btc_fr_aligned.mean()),
        "btc_daily_std": float(btc_fr_aligned.std()),
        "btc_p5": float(p5),
        "btc_p95": float(p95),
        "btc_annualized_avg": float(btc_fr_aligned.mean() * 365),
    }
}

with open(RESEARCH_DIR / 'funding_rate_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\nResults saved to funding_rate_results.json")
print("Done!")
