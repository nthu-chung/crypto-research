#!/usr/bin/env python3
"""
MVRV + Trend Filter Backtest
4 Strategies:
1. MVRV v2 + EMA200
2. MVRV v2 + Monthly Trend
3. MVRV v2 + EMA200 + ADX
4. MVRV Z-Score (P90 threshold) + EMA200
"""

import requests, time, pandas as pd, numpy as np, json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = "/root/.openclaw/workspace/research"
MEDIA_DIR = "/root/.openclaw/workspace/openclaw-media"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)

# ─── Data Fetching ───────────────────────────────────────────────────────────

def fetch_coinmetrics(metrics, start="2012-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data, params = [], {
        "assets": "btc", "metrics": metrics, "frequency": "1d",
        "start_time": start, "page_size": 1000
    }
    while True:
        j = requests.get(url, params=params, timeout=20).json()
        all_data.extend(j.get('data', []))
        token = j.get('next_page_token')
        if not token:
            break
        params = {
            "assets": "btc", "metrics": metrics, "frequency": "1d",
            "page_size": 1000, "next_page_token": token
        }
        time.sleep(0.05)
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['time']).dt.tz_localize(None)
    for col in ['PriceUSD', 'CapMVRVCur']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('date').reset_index(drop=True)

def fetch_binance_daily(symbol="BTCUSDT", start="2012-01-01"):
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    start_ts = int(pd.Timestamp(start).timestamp() * 1000)
    end_ts = int(pd.Timestamp("2026-05-19").timestamp() * 1000)
    while start_ts < end_ts:
        r = requests.get(url, params={
            "symbol": symbol, "interval": "1d",
            "startTime": start_ts, "limit": 1000
        }, timeout=10)
        data = r.json()
        if not data or isinstance(data, dict):
            break
        all_data.extend(data)
        start_ts = data[-1][0] + 86400000
        if len(data) < 1000:
            break
        time.sleep(0.05)
    df = pd.DataFrame(all_data, columns=[
        'ts', 'open', 'high', 'low', 'close', 'vol',
        'cts', 'qvol', 'ntrades', 'tbbav', 'tbqav', 'ignore'
    ])
    df['date'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.tz_localize(None)
    for c in ['open', 'high', 'low', 'close', 'vol']:
        df[c] = df[c].astype(float)
    return df.sort_values('date').reset_index(drop=True)

# ─── Indicators ──────────────────────────────────────────────────────────────

def calc_adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    dm_plus = ((high - high.shift()) > (low.shift() - low)).astype(float) * (high - high.shift()).clip(lower=0)
    dm_minus = ((low.shift() - low) > (high - high.shift())).astype(float) * (low.shift() - low).clip(lower=0)
    atr = tr.ewm(span=period, adjust=False).mean()
    di_plus = 100 * dm_plus.ewm(span=period, adjust=False).mean() / atr
    di_minus = 100 * dm_minus.ewm(span=period, adjust=False).mean() / atr
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx

# ─── Backtest Engine ──────────────────────────────────────────────────────────

def backtest(df, position_col, fee_bps=4):
    """
    df must have 'date', 'price', position_col (0..1 allocation, T-1 signal T execution)
    Returns: equity series, metrics dict
    """
    df = df.copy().reset_index(drop=True)
    fee = fee_bps / 10000

    position = df[position_col].shift(1).fillna(0).values  # T-1 signal
    price = df['price'].values
    ret = np.zeros(len(df))

    for i in range(1, len(df)):
        price_ret = price[i] / price[i-1] - 1
        # position change: |new - old| * fee
        pos_change = abs(position[i] - position[i-1])
        ret[i] = position[i] * price_ret - pos_change * fee

    equity = (1 + ret).cumprod()
    df['equity'] = equity
    df['returns'] = ret

    # Metrics
    equity_s = pd.Series(equity)
    ann_ret = equity_s.iloc[-1] ** (365 / len(df)) - 1
    daily_std = np.std(ret[1:]) * np.sqrt(365)
    sharpe = ann_ret / daily_std if daily_std > 0 else 0

    rolling_max = equity_s.cummax()
    drawdown = (equity_s / rolling_max - 1)
    max_dd = drawdown.min()

    return df, {
        'ann_ret': ann_ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'final_equity': equity_s.iloc[-1]
    }

def period_metrics(df, start, end, label=''):
    sub = df[(df['date'] >= start) & (df['date'] < end)].copy()
    if len(sub) < 10:
        return {}
    equity = sub['equity'].values
    ret = sub['returns'].values
    ann_ret = equity[-1] ** (365 / len(sub)) - 1
    daily_std = np.std(ret[1:]) * np.sqrt(365)
    sharpe = ann_ret / daily_std if daily_std > 0 else 0
    rolling_max = pd.Series(equity).cummax()
    max_dd = (pd.Series(equity) / rolling_max - 1).min()
    return {'period': label, 'ann_ret': ann_ret, 'sharpe': sharpe, 'max_dd': max_dd}

# ─── Main ─────────────────────────────────────────────────────────────────────

print("Fetching CoinMetrics data...")
cm = fetch_coinmetrics("PriceUSD,CapMVRVCur")
print(f"CoinMetrics: {len(cm)} rows, from {cm['date'].min()} to {cm['date'].max()}")

print("Fetching Binance OHLCV data...")
bn = fetch_binance_daily()
print(f"Binance: {len(bn)} rows, from {bn['date'].min()} to {bn['date'].max()}")

# Merge datasets
bn_price = bn[['date', 'high', 'low', 'close']].copy()
bn_price['date'] = pd.to_datetime(bn_price['date']).dt.normalize()

cm['date'] = pd.to_datetime(cm['date']).dt.normalize()
df = cm[['date', 'PriceUSD', 'CapMVRVCur']].copy()

# Fill PriceUSD from Binance for dates without CM data
bn_simple = bn[['date', 'close', 'high', 'low']].copy()
bn_simple['date'] = pd.to_datetime(bn_simple['date']).dt.normalize()

df = pd.merge(df, bn_simple, on='date', how='outer')
df['PriceUSD'] = df['PriceUSD'].combine_first(df['close'])
df = df.sort_values('date').reset_index(drop=True)
df['price'] = df['PriceUSD'].fillna(method='ffill')
df = df.dropna(subset=['price'])

# Use Binance OHLC where available for ADX
df['high'] = df['high'].fillna(df['price'])
df['low'] = df['low'].fillna(df['price'])
df['close_px'] = df['close'].fillna(df['price'])

print(f"Merged: {len(df)} rows, from {df['date'].min()} to {df['date'].max()}")

# ─── MVRV Indicators ──────────────────────────────────────────────────────────

# IS period for calibration: 2012-2019
is_mask = df['date'] < '2020-01-01'

# MVRV percentile zones (IS calibrated)
mvrv = df['CapMVRVCur'].copy()
is_mvrv = mvrv[is_mask].dropna()

# v2: IS percentile zones
p20 = is_mvrv.quantile(0.20)
p40 = is_mvrv.quantile(0.40)
p60 = is_mvrv.quantile(0.60)
p80 = is_mvrv.quantile(0.80)
p90 = is_mvrv.quantile(0.90)

print(f"MVRV IS Percentiles: P20={p20:.2f}, P40={p40:.2f}, P60={p60:.2f}, P80={p80:.2f}, P90={p90:.2f}")

def mvrv_base_position(x):
    """MVRV v2 IS-calibrated position (0..1)"""
    if pd.isna(x):
        return 0.5
    if x < p20:
        return 1.0   # Extreme undervalued
    elif x < p40:
        return 0.8
    elif x < p60:
        return 0.6
    elif x < p80:
        return 0.4
    elif x < p90:
        return 0.2
    else:
        return 0.0   # Extreme overvalued

df['mvrv_pos'] = mvrv.apply(mvrv_base_position)
df['mvrv_pos'] = df['mvrv_pos'].fillna(0.5)

# MVRV Z-Score (IS calibrated)
is_mean = is_mvrv.mean()
is_std = is_mvrv.std()
df['mvrv_zscore'] = (mvrv - is_mean) / is_std

# Z-Score P85/P90/P95 thresholds (IS)
is_zscores = df.loc[is_mask, 'mvrv_zscore'].dropna()
zp85 = is_zscores.quantile(0.85)
zp90 = is_zscores.quantile(0.90)
zp95 = is_zscores.quantile(0.95)
print(f"MVRV Z-Score IS Percentiles: P85={zp85:.3f}, P90={zp90:.3f}, P95={zp95:.3f}")

def zscore_position_p90(z):
    """Z-Score based position with P90 threshold"""
    if pd.isna(z):
        return 0.5
    if z < -1.0:    # Very undervalued
        return 1.0
    elif z < -0.5:
        return 0.8
    elif z < 0.0:
        return 0.6
    elif z < zp85:
        return 0.4
    elif z < zp90:
        return 0.2
    else:
        return 0.0

df['zscore_pos_p90'] = df['mvrv_zscore'].apply(zscore_position_p90)

# ─── Trend Indicators ─────────────────────────────────────────────────────────

# EMA200
df['ema200'] = df['price'].ewm(span=200, adjust=False).mean()
df['trend_ema'] = (df['price'] > df['ema200']).astype(float)

# Monthly trend (monthly close comparison)
df_m = df.set_index('date')['price'].resample('M').last().reset_index()
df_m.columns = ['date', 'monthly_close']
df_m['date'] = df_m['date'] + pd.offsets.MonthEnd(0)
df_m['prev_close'] = df_m['monthly_close'].shift(1)
df_m['prev2_close'] = df_m['monthly_close'].shift(2)
df_m['monthly_bullish'] = (df_m['monthly_close'] > df_m['prev_close']).astype(float)
df_m['monthly_2down'] = ((df_m['monthly_close'] < df_m['prev_close']) & 
                          (df_m['prev_close'] < df_m['prev2_close'])).astype(float)

# Forward fill monthly signal to daily
df['month_key'] = df['date'].dt.to_period('M').dt.to_timestamp('M')
df = pd.merge(df, df_m[['date', 'monthly_bullish', 'monthly_2down']].rename(columns={'date': 'month_key'}), 
              on='month_key', how='left')
df['monthly_bullish'] = df['monthly_bullish'].fillna(1.0)
df['monthly_2down'] = df['monthly_2down'].fillna(0.0)

# ADX (14-day)
df_adx = df[['high', 'low', 'close_px']].copy()
df_adx.columns = ['high', 'low', 'close']
df['adx'] = calc_adx(df_adx, period=14)
df['trend_adx_bull'] = ((df['adx'] > 25) & (df['price'] > df['ema200'])).astype(float)
df['trend_adx_bear'] = ((df['adx'] > 25) & (df['price'] <= df['ema200'])).astype(float)
df['trend_adx_neutral'] = (df['adx'] <= 25).astype(float)

print("Indicators computed.")

# ─── Strategy 1: MVRV v2 + EMA200 ────────────────────────────────────────────

def strategy1(row):
    base = row['mvrv_pos']
    if row['trend_ema'] == 1:
        return base
    else:
        return base * 0.3  # Reduce heavily in downtrend

df['s1_pos'] = df.apply(strategy1, axis=1)

# ─── Strategy 2: MVRV v2 + Monthly Trend ─────────────────────────────────────

def strategy2(row):
    base = row['mvrv_pos']
    if row['monthly_2down'] == 1:
        return base * 0.3
    return base

df['s2_pos'] = df.apply(strategy2, axis=1)

# ─── Strategy 3: MVRV v2 + EMA200 + ADX ──────────────────────────────────────

def strategy3(row):
    base = row['mvrv_pos']
    if row['trend_adx_bull'] == 1:
        return base          # Full MVRV in strong uptrend
    elif row['trend_adx_bear'] == 1:
        return base * 0.2    # 20% in strong downtrend
    else:
        return base * 0.5    # 50% in ranging market

df['s3_pos'] = df.apply(strategy3, axis=1)

# ─── Strategy 4: MVRV Z-Score P90 + EMA200 ───────────────────────────────────

def strategy4(row):
    base = row['zscore_pos_p90']
    if row['trend_ema'] == 1:
        return base
    else:
        return base * 0.3

df['s4_pos'] = df.apply(strategy4, axis=1)

# ─── Run Backtests ────────────────────────────────────────────────────────────

print("Running backtests...")

df_clean = df.dropna(subset=['price', 'ema200']).copy().reset_index(drop=True)

strategies = {
    'S1_MVRV_EMA200': 's1_pos',
    'S2_MVRV_Monthly': 's2_pos',
    'S3_MVRV_EMA200_ADX': 's3_pos',
    'S4_ZScore_EMA200': 's4_pos',
}

results = {}
equities = {}

for name, col in strategies.items():
    df_r, metrics = backtest(df_clean, col)
    results[name] = metrics
    equities[name] = df_r[['date', 'equity', 'returns', col]].copy()
    equities[name].columns = ['date', 'equity', 'returns', 'position']
    print(f"{name}: Sharpe={metrics['sharpe']:.2f}, MaxDD={metrics['max_dd']:.1%}, AnnRet={metrics['ann_ret']:.1%}")

# Buy & Hold
bh_ret = df_clean['price'].pct_change().fillna(0).values
bh_eq = (1 + bh_ret).cumprod()
bh_ann = bh_eq[-1] ** (365 / len(df_clean)) - 1
bh_dd = (pd.Series(bh_eq) / pd.Series(bh_eq).cummax() - 1).min()
bh_sharpe = bh_ann / (np.std(bh_ret[1:]) * np.sqrt(365))
print(f"BuyAndHold: Sharpe={bh_sharpe:.2f}, MaxDD={bh_dd:.1%}, AnnRet={bh_ann:.1%}")
results['BuyAndHold'] = {'ann_ret': bh_ann, 'sharpe': bh_sharpe, 'max_dd': bh_dd, 'final_equity': bh_eq[-1]}

# ─── Period-Specific Analysis ─────────────────────────────────────────────────

print("\nPeriod Analysis...")
periods = [
    ('IS 2012-2019', '2012-01-01', '2020-01-01'),
    ('OOS 2020-2026', '2020-01-01', '2026-06-01'),
    ('2022 Bear', '2022-01-01', '2023-01-01'),
    ('2024 Bull', '2024-01-01', '2025-01-01'),
]

period_results = {}
for name, col in strategies.items():
    df_r = equities[name]
    df_r2 = df_r.merge(df_clean[['date', 'price']], on='date', how='left')
    period_results[name] = []
    for label, start, end in periods:
        sub = df_r2[(df_r2['date'] >= start) & (df_r2['date'] < end)].copy()
        if len(sub) < 10:
            continue
        eq = sub['equity'].values
        ret = sub['returns'].values
        eq_norm = eq / eq[0]  # Normalize to period start
        ann_ret = eq_norm[-1] ** (365 / len(sub)) - 1
        daily_std = np.std(ret[1:]) * np.sqrt(365)
        sharpe = ann_ret / daily_std if daily_std > 0 else 0
        max_dd = (pd.Series(eq_norm) / pd.Series(eq_norm).cummax() - 1).min()
        period_results[name].append({
            'period': label, 'ann_ret': ann_ret, 'sharpe': sharpe, 'max_dd': max_dd
        })
        print(f"  {name} [{label}]: Sharpe={sharpe:.2f}, MaxDD={max_dd:.1%}, AnnRet={ann_ret:.1%}")

# ─── Visualization ────────────────────────────────────────────────────────────

print("\nGenerating plots...")

# Plot 1: Equity curves
fig, axes = plt.subplots(2, 1, figsize=(14, 10))
ax1 = axes[0]

colors = {'S1_MVRV_EMA200': '#2196F3', 'S2_MVRV_Monthly': '#4CAF50',
          'S3_MVRV_EMA200_ADX': '#FF9800', 'S4_ZScore_EMA200': '#9C27B0'}

for name, eq_df in equities.items():
    eq_norm = eq_df['equity'] / eq_df['equity'].iloc[0]
    ax1.semilogy(eq_df['date'], eq_norm, label=name, alpha=0.8,
                 color=colors.get(name, 'gray'), linewidth=1.5)

bh_eq_norm = bh_eq / bh_eq[0]
ax1.semilogy(df_clean['date'], bh_eq_norm, label='BuyAndHold', color='black',
             linestyle='--', alpha=0.5, linewidth=1.2)

ax1.axvspan(pd.Timestamp('2012-01-01'), pd.Timestamp('2020-01-01'),
            alpha=0.05, color='blue', label='IS Period')
ax1.axvspan(pd.Timestamp('2020-01-01'), pd.Timestamp('2026-06-01'),
            alpha=0.05, color='green', label='OOS Period')
ax1.set_title('Strategy Equity Curves (Log Scale)', fontsize=14, fontweight='bold')
ax1.legend(loc='upper left', fontsize=9)
ax1.set_ylabel('Normalized Equity (log)')
ax1.grid(True, alpha=0.3)

# Plot 2: Price with EMA200 and position for S1
ax2 = axes[1]
ax2_twin = ax2.twinx()

s1_eq = equities['S1_MVRV_EMA200']
s1_full = s1_eq.merge(df_clean[['date', 'price', 'ema200']], on='date', how='left')

ax2.semilogy(s1_full['date'], s1_full['price'], color='gray', alpha=0.5, linewidth=1, label='BTC Price')
ax2.semilogy(s1_full['date'], s1_full['ema200'], color='blue', alpha=0.7, linewidth=1.2, label='EMA200')
ax2_twin.fill_between(s1_eq['date'], s1_eq['position'], alpha=0.3, color='#2196F3', label='S1 Position')
ax2_twin.set_ylim(0, 1.2)
ax2_twin.set_ylabel('Position Allocation', color='#2196F3')

ax2.set_title('S1: BTC Price + EMA200 + MVRV Position Allocation', fontsize=12)
ax2.legend(loc='upper left', fontsize=9)
ax2.set_ylabel('BTC Price (log)')
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(f"{MEDIA_DIR}/trend_filter_equity_curves.png", dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: {MEDIA_DIR}/trend_filter_equity_curves.png")

# Plot 3: Heatmap-style period comparison
fig, ax = plt.subplots(figsize=(12, 6))

period_labels = [p[0] for p in periods]
strat_names = list(strategies.keys())

sharpe_matrix = np.zeros((len(strat_names), len(period_labels)))
dd_matrix = np.zeros((len(strat_names), len(period_labels)))

for i, name in enumerate(strat_names):
    for j, (label, _, _) in enumerate(periods):
        p_data = [x for x in period_results[name] if x['period'] == label]
        if p_data:
            sharpe_matrix[i, j] = p_data[0]['sharpe']
            dd_matrix[i, j] = p_data[0]['max_dd'] * 100

im = ax.imshow(sharpe_matrix, cmap='RdYlGn', aspect='auto',
               vmin=-1, vmax=3)
plt.colorbar(im, ax=ax, label='Sharpe Ratio')

ax.set_xticks(range(len(period_labels)))
ax.set_xticklabels(period_labels, rotation=20, ha='right')
ax.set_yticks(range(len(strat_names)))
ax.set_yticklabels(strat_names)

for i in range(len(strat_names)):
    for j in range(len(period_labels)):
        ax.text(j, i, f'S:{sharpe_matrix[i,j]:.2f}\nDD:{dd_matrix[i,j]:.0f}%',
                ha='center', va='center', fontsize=8, fontweight='bold')

ax.set_title('Sharpe Ratio & MaxDD by Strategy & Period', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(f"{MEDIA_DIR}/trend_filter_period_heatmap.png", dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: {MEDIA_DIR}/trend_filter_period_heatmap.png")

# ─── Build Results Markdown ───────────────────────────────────────────────────

lines = []
lines.append("# MVRV + Trend Filter Backtest Results\n")
lines.append(f"*Generated: 2026-05-19*\n\n")

lines.append("## Strategy Descriptions\n")
lines.append("1. **S1: MVRV v2 + EMA200** — MVRV zone position × 0.3 when price < EMA200\n")
lines.append("2. **S2: MVRV v2 + Monthly Trend** — MVRV zone position × 0.3 when 2 consecutive down months\n")
lines.append("3. **S3: MVRV v2 + EMA200 + ADX** — ADX>25 bull=full MVRV, bear=20%, ranging=50%\n")
lines.append("4. **S4: MVRV Z-Score P90 + EMA200** — Z-Score thresholds at P85/P90 + EMA200 filter\n\n")

lines.append("## IS Calibration Parameters\n")
lines.append(f"- MVRV Percentiles (IS 2012-2019): P20={p20:.2f}, P40={p40:.2f}, P60={p60:.2f}, P80={p80:.2f}, P90={p90:.2f}\n")
lines.append(f"- Z-Score Thresholds (IS): P85={zp85:.3f}, P90={zp90:.3f}, P95={zp95:.3f}\n\n")

lines.append("## Full Period Results\n")
lines.append("| Strategy | Ann Return | Sharpe | Max DD |\n")
lines.append("|----------|-----------|--------|--------|\n")
for name in list(strategies.keys()) + ['BuyAndHold']:
    m = results[name]
    lines.append(f"| {name} | {m['ann_ret']:.1%} | {m['sharpe']:.2f} | {m['max_dd']:.1%} |\n")

lines.append("\n## Period Breakdown\n")

for label, _, _ in periods:
    lines.append(f"\n### {label}\n")
    lines.append("| Strategy | Ann Return | Sharpe | Max DD |\n")
    lines.append("|----------|-----------|--------|--------|\n")
    for name in strat_names:
        p_data = [x for x in period_results[name] if x['period'] == label]
        if p_data:
            p = p_data[0]
            lines.append(f"| {name} | {p['ann_ret']:.1%} | {p['sharpe']:.2f} | {p['max_dd']:.1%} |\n")

lines.append("\n## Key Findings\n")

# Find best strategy by Sharpe
best_sharpe = max(results.items(), key=lambda x: x[1]['sharpe'])
best_dd = max(results.items(), key=lambda x: x[1]['max_dd'])  # max_dd is negative, max = least negative

lines.append(f"- **Best Sharpe overall**: {best_sharpe[0]} (Sharpe={best_sharpe[1]['sharpe']:.2f})\n")
lines.append(f"- **Smallest Max DD**: {best_dd[0]} (MaxDD={best_dd[1]['max_dd']:.1%})\n")

# 2022 bear analysis
lines.append("\n### 2022 Bear Market Protection\n")
for name in strat_names:
    p_data = [x for x in period_results[name] if x['period'] == '2022 Bear']
    if p_data:
        p = p_data[0]
        lines.append(f"- {name}: MaxDD={p['max_dd']:.1%}, Sharpe={p['sharpe']:.2f}\n")

# 2024 bull analysis
lines.append("\n### 2024 Bull Market Participation\n")
for name in strat_names:
    p_data = [x for x in period_results[name] if x['period'] == '2024 Bull']
    if p_data:
        p = p_data[0]
        lines.append(f"- {name}: AnnReturn={p['ann_ret']:.1%}, Sharpe={p['sharpe']:.2f}\n")

# Z-Score analysis
lines.append("\n### Z-Score P90 Analysis (S4 vs S1)\n")
s1_m = results['S1_MVRV_EMA200']
s4_m = results['S4_ZScore_EMA200']
lines.append(f"- S1 (MVRV v2+EMA200): Sharpe={s1_m['sharpe']:.2f}, MaxDD={s1_m['max_dd']:.1%}\n")
lines.append(f"- S4 (Z-Score P90+EMA200): Sharpe={s4_m['sharpe']:.2f}, MaxDD={s4_m['max_dd']:.1%}\n")

if s4_m['sharpe'] > s1_m['sharpe']:
    lines.append(f"- Z-Score P90 improves Sharpe by {s4_m['sharpe']-s1_m['sharpe']:.2f} vs v2\n")
else:
    lines.append(f"- Z-Score P90 slightly underperforms v2 by Sharpe {s1_m['sharpe']-s4_m['sharpe']:.2f}\n")

lines.append("\n## Conclusion\n")

# Determine meeting criteria
meeting_criteria = []
for name in strat_names:
    m = results[name]
    if m['sharpe'] > 1.0 and m['max_dd'] > -0.20:
        meeting_criteria.append(name)

if meeting_criteria:
    lines.append(f"✅ Strategies meeting Sharpe>1 AND MaxDD<-20%: **{', '.join(meeting_criteria)}**\n\n")
else:
    partial = [name for name in strat_names if results[name]['sharpe'] > 0.8 or results[name]['max_dd'] > -0.25]
    if partial:
        lines.append(f"⚠️ No strategy fully meets Sharpe>1 AND MaxDD<-20%. Closest: **{', '.join(partial)}**\n\n")
    else:
        lines.append("⚠️ No strategy fully meets both criteria. Further tuning needed.\n\n")

for name in strat_names:
    m = results[name]
    criteria = []
    if m['sharpe'] > 1.0:
        criteria.append(f"✅ Sharpe={m['sharpe']:.2f}>1")
    else:
        criteria.append(f"❌ Sharpe={m['sharpe']:.2f}")
    if m['max_dd'] > -0.20:
        criteria.append(f"✅ MaxDD={m['max_dd']:.1%}>-20%")
    else:
        criteria.append(f"❌ MaxDD={m['max_dd']:.1%}")
    lines.append(f"- **{name}**: {' | '.join(criteria)}\n")

lines.append("\n## Charts\n")
lines.append(f"- Equity curves: `openclaw-media/trend_filter_equity_curves.png`\n")
lines.append(f"- Period heatmap: `openclaw-media/trend_filter_period_heatmap.png`\n")

result_text = ''.join(lines)
with open(f"{OUTPUT_DIR}/trend_filter_results.md", 'w') as f:
    f.write(result_text)
print(f"Results written to {OUTPUT_DIR}/trend_filter_results.md")

# ─── Summary for main session ─────────────────────────────────────────────────

# Compile a brief summary string
summary_lines = []
for name in strat_names:
    m = results[name]
    summary_lines.append(f"{name}: Sharpe={m['sharpe']:.2f}, MaxDD={m['max_dd']:.1%}, Ann={m['ann_ret']:.1%}")

best_strat = max([(n, results[n]) for n in strat_names], key=lambda x: x[1]['sharpe'])

if meeting_criteria:
    conclusion = f"✅ {len(meeting_criteria)} strategies meet Sharpe>1 AND MaxDD>-20%: {', '.join(meeting_criteria)}"
else:
    best_s = max(strat_names, key=lambda n: results[n]['sharpe'])
    conclusion = f"⚠️ No strategy meets both criteria. Best: {best_s} Sharpe={results[best_s]['sharpe']:.2f} MaxDD={results[best_s]['max_dd']:.1%}"

summary = f"""[TREND FILTER BACKTEST COMPLETE]

Strategies tested: MVRV v2 + EMA200 / Monthly Trend / EMA200+ADX | MVRV Z-Score P90 + EMA200

Results:
{chr(10).join(summary_lines)}
BuyAndHold: Sharpe={results['BuyAndHold']['sharpe']:.2f}, MaxDD={results['BuyAndHold']['max_dd']:.1%}

{conclusion}

Full results: /root/.openclaw/workspace/research/trend_filter_results.md
Charts: openclaw-media/trend_filter_equity_curves.png + trend_filter_period_heatmap.png"""

print("\n" + "="*60)
print("SUMMARY:")
print(summary)
print("="*60)

# Save summary for the main script to read
with open(f"{OUTPUT_DIR}/trend_filter_summary.txt", 'w') as f:
    f.write(summary)
