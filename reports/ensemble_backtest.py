"""
Ensemble + Kelly Criterion BTC Strategy Backtest
4 variants:
1. Pure ensemble scoring (score/10 = position)
2. Ensemble + Kelly
3. Ensemble + Max Drawdown Protection
4. Ensemble + Kelly + Drawdown Protection (Final)
"""
import requests, time, pandas as pd, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# ─── Data Fetch ───────────────────────────────────────────────────────────────
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
    df['date'] = pd.to_datetime(df['time'])
    for col in ['PriceUSD', 'CapMVRVCur']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('date').reset_index(drop=True)

print("Fetching BTC data from CoinMetrics...")
df = fetch_coinmetrics("PriceUSD,CapMVRVCur", start="2012-01-01")
print(f"Fetched {len(df)} rows, date range: {df['date'].min()} → {df['date'].max()}")
print(df[['date', 'PriceUSD', 'CapMVRVCur']].tail(5))

# ─── Feature Engineering ──────────────────────────────────────────────────────
df = df.set_index('date').sort_index()
price = df['PriceUSD'].copy()
mvrv  = df['CapMVRVCur'].copy()

# Drop rows missing price
df = df.dropna(subset=['PriceUSD'])
price = df['PriceUSD']
mvrv  = df['CapMVRVCur']

# EMA indicators
ema50  = price.ewm(span=50,  adjust=False).mean()
ema200 = price.ewm(span=200, adjust=False).mean()

# 3-month (90d) momentum
mom90 = price.pct_change(90)

# 30-day annualized vol
daily_ret = price.pct_change()
vol30 = daily_ret.rolling(30).std() * np.sqrt(365)

# MVRV percentile ranks (rolling)
mvrv_rank = mvrv.rolling(window=4*365, min_periods=365).rank(pct=True)  # rolling percentile

# ─── Signal Scoring ───────────────────────────────────────────────────────────
score = pd.Series(0.0, index=price.index)

# Signal 1: MVRV score (0-4)
s1 = pd.Series(0.0, index=price.index)
s1[mvrv_rank < 0.20] = 4.0
s1[(mvrv_rank >= 0.20) & (mvrv_rank < 0.40)] = 3.0
s1[(mvrv_rank >= 0.40) & (mvrv_rank < 0.60)] = 2.0
s1[(mvrv_rank >= 0.60) & (mvrv_rank < 0.80)] = 1.0
s1[mvrv_rank >= 0.80] = 0.0
s1[mvrv_rank.isna()] = 2.0  # neutral when no history

# Signal 2: Trend score (0-2)
s2 = pd.Series(0.0, index=price.index)
s2[(price > ema200) & (ema50 > ema200)] = 2.0
s2[(price > ema200) & ~(ema50 > ema200)] = 1.0

# Signal 3: Momentum score (0-2)
s3 = pd.Series(0.0, index=price.index)
s3[mom90 > 0.20] = 2.0
s3[(mom90 > 0.0) & (mom90 <= 0.20)] = 1.0

# Signal 4: Volatility score (0-2)
s4 = pd.Series(0.0, index=price.index)
s4[vol30 < 0.50] = 2.0
s4[(vol30 >= 0.50) & (vol30 < 0.80)] = 1.0
s4[vol30 >= 0.80] = 0.0

total_score = s1 + s2 + s3 + s4  # max = 10
ensemble_pos = total_score / 10.0  # 0-1

print(f"\nEnsemble score stats:\n{total_score.describe()}")

# ─── Backtest Engine ──────────────────────────────────────────────────────────
FEE = 0.0004  # 4bps one-way

def backtest(target_pos: pd.Series, label: str):
    """
    target_pos: series of desired position (0-1), index=date
    Returns daily pnl series and stats dict
    """
    pos = target_pos.shift(1).fillna(0)  # T-1 signal → T execution
    ret = daily_ret.reindex(pos.index).fillna(0)
    
    # turnover and fees
    turnover = pos.diff().abs().fillna(0)
    fee_drag  = turnover * FEE
    
    strat_ret = pos * ret - fee_drag
    
    # cumulative nav
    nav = (1 + strat_ret).cumprod()
    
    # metrics
    total_days = len(strat_ret)
    years = total_days / 365
    cagr = nav.iloc[-1] ** (1/years) - 1
    ann_ret = strat_ret.mean() * 365
    ann_vol = strat_ret.std() * np.sqrt(365)
    sharpe  = ann_ret / ann_vol if ann_vol > 0 else 0
    
    running_max = nav.cummax()
    dd = (nav - running_max) / running_max
    max_dd = dd.min()
    
    return nav, strat_ret, {
        'label': label,
        'CAGR': round(cagr*100, 2),
        'Sharpe': round(sharpe, 3),
        'MaxDD': round(max_dd*100, 2),
        'AnnVol': round(ann_vol*100, 2),
    }

# ─── Kelly Fraction ───────────────────────────────────────────────────────────
def rolling_kelly(ret_series, window=252):
    """Half-kelly fraction based on rolling win statistics.
    Uses min_periods=window//4 so rolling values populate even when ~45% are NaN.
    """
    min_p = max(window // 4, 30)
    
    win_rate  = ret_series.rolling(window, min_periods=min_p).apply(
        lambda x: (x > 0).mean(), raw=True
    )
    loss_rate = 1 - win_rate
    
    # avg_win: mean of positive returns; avg_loss: mean of |negative returns|
    avg_win  = ret_series.where(ret_series > 0).rolling(window, min_periods=min_p).mean()
    avg_loss = ret_series.where(ret_series < 0).abs().rolling(window, min_periods=min_p).mean()
    
    # fallback to global means for the very first period
    global_win_mean  = ret_series[ret_series > 0].mean()
    global_loss_mean = ret_series[ret_series < 0].abs().mean()
    avg_win  = avg_win.fillna(global_win_mean)
    avg_loss = avg_loss.fillna(global_loss_mean)
    
    # Kelly = p - q * (L/W)
    kelly = win_rate - loss_rate * (avg_loss / avg_win.replace(0, np.nan))
    half_kelly = (kelly / 2).clip(0, 1).fillna(0)
    return half_kelly

# compute kelly on B&H daily returns
bh_daily = daily_ret.fillna(0)
kelly_frac = rolling_kelly(bh_daily, window=252)

# ─── Drawdown Protection ──────────────────────────────────────────────────────
def apply_dd_protection(pos: pd.Series, dd_trigger=-0.15, reduced_pos=0.20):
    """
    Reduce position to reduced_pos when drawdown from peak > dd_trigger.
    Use the strategy's own running NAV to detect drawdown.
    We apply it iteratively (slightly simplified: use price drawdown as proxy).
    """
    price_dd = (price - price.cummax()) / price.cummax()
    protected = pos.copy()
    protected[price_dd < dd_trigger] = np.minimum(protected[price_dd < dd_trigger], reduced_pos)
    return protected

# ─── Build 4 Strategies ───────────────────────────────────────────────────────

# V1: Pure ensemble
pos_v1 = ensemble_pos.clip(0, 1)

# V2: Ensemble + Kelly  
pos_v2 = np.minimum(kelly_frac * ensemble_pos / ensemble_pos.where(ensemble_pos > 0, np.nan).fillna(1),
                    ensemble_pos)
pos_v2 = (kelly_frac * ensemble_pos).clip(0, 1)

# V3: Ensemble + DD Protection
pos_v3 = apply_dd_protection(pos_v1)

# V4: Ensemble + Kelly + DD Protection
pos_v4 = apply_dd_protection(pos_v2)

# Buy & Hold baseline
bh_pos = pd.Series(1.0, index=price.index)

# Run backtests
nav_v1, ret_v1, s_v1 = backtest(pos_v1, "V1: Pure Ensemble")
nav_v2, ret_v2, s_v2 = backtest(pos_v2, "V2: Ensemble+Kelly")
nav_v3, ret_v3, s_v3 = backtest(pos_v3, "V3: Ensemble+DD")
nav_v4, ret_v4, s_v4 = backtest(pos_v4, "V4: Ensemble+Kelly+DD")
nav_bh, ret_bh, s_bh = backtest(bh_pos, "Buy & Hold")

# ─── Yearly Returns ───────────────────────────────────────────────────────────
def yearly_rets(ret_series):
    return ret_series.groupby(ret_series.index.year).apply(
        lambda x: (1 + x).prod() - 1
    ) * 100

yr_v1 = yearly_rets(ret_v1)
yr_v2 = yearly_rets(ret_v2)
yr_v3 = yearly_rets(ret_v3)
yr_v4 = yearly_rets(ret_v4)
yr_bh = yearly_rets(ret_bh)

# ─── Print Results ────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("OVERALL METRICS")
print("="*70)
for s in [s_v1, s_v2, s_v3, s_v4, s_bh]:
    print(f"{s['label']:30s} | CAGR={s['CAGR']:7.2f}% | Sharpe={s['Sharpe']:.3f} | MaxDD={s['MaxDD']:.2f}% | Vol={s['AnnVol']:.2f}%")

# Segment stats
def seg_stats(ret_s, label, start, end):
    seg = ret_s[start:end]
    if len(seg) == 0:
        return {}
    nav = (1 + seg).cumprod()
    years = len(seg) / 365
    cagr = nav.iloc[-1] ** (1/years) - 1 if years > 0 else 0
    ann_vol = seg.std() * np.sqrt(365)
    sharpe = (seg.mean() * 365) / ann_vol if ann_vol > 0 else 0
    dd = ((nav - nav.cummax()) / nav.cummax()).min()
    return {
        'label': label, 'start': start, 'end': end,
        'CAGR': round(cagr*100, 2), 'Sharpe': round(sharpe, 3),
        'MaxDD': round(dd*100, 2)
    }

print("\n" + "="*70)
print("IN-SAMPLE (2012-2019)")
print("="*70)
for r, lbl in [(ret_v1, s_v1['label']), (ret_v2, s_v2['label']), 
               (ret_v3, s_v3['label']), (ret_v4, s_v4['label']), (ret_bh, 'Buy & Hold')]:
    ss = seg_stats(r, lbl, '2012-01-01', '2019-12-31')
    print(f"{ss['label']:30s} | CAGR={ss['CAGR']:7.2f}% | Sharpe={ss['Sharpe']:.3f} | MaxDD={ss['MaxDD']:.2f}%")

print("\n" + "="*70)
print("OUT-OF-SAMPLE (2020-2026)")
print("="*70)
for r, lbl in [(ret_v1, s_v1['label']), (ret_v2, s_v2['label']),
               (ret_v3, s_v3['label']), (ret_v4, s_v4['label']), (ret_bh, 'Buy & Hold')]:
    ss = seg_stats(r, lbl, '2020-01-01', '2026-12-31')
    print(f"{ss['label']:30s} | CAGR={ss['CAGR']:7.2f}% | Sharpe={ss['Sharpe']:.3f} | MaxDD={ss['MaxDD']:.2f}%")

print("\n" + "="*70)
print("2024 ALONE")
print("="*70)
for r, lbl in [(ret_v1, s_v1['label']), (ret_v2, s_v2['label']),
               (ret_v3, s_v3['label']), (ret_v4, s_v4['label']), (ret_bh, 'Buy & Hold')]:
    ss = seg_stats(r, lbl, '2024-01-01', '2024-12-31')
    if ss:
        print(f"{ss['label']:30s} | CAGR={ss['CAGR']:7.2f}% | Sharpe={ss['Sharpe']:.3f} | MaxDD={ss['MaxDD']:.2f}%")

print("\nYearly Returns (%):")
yr_df = pd.DataFrame({
    'BH': yr_bh, 'V1': yr_v1, 'V2': yr_v2, 'V3': yr_v3, 'V4': yr_v4
}).round(1)
print(yr_df.to_string())

# ─── Plots ────────────────────────────────────────────────────────────────────
media_dir = "/root/.openclaw/workspace/openclaw-media"
fig, axes = plt.subplots(2, 1, figsize=(14, 10))

# NAV curves
ax = axes[0]
ax.semilogy(nav_bh.index, nav_bh, color='gray', alpha=0.5, linewidth=1, label='Buy & Hold')
ax.semilogy(nav_v1.index, nav_v1, color='steelblue',   linewidth=1.5, label=s_v1['label'])
ax.semilogy(nav_v2.index, nav_v2, color='darkorange',  linewidth=1.5, label=s_v2['label'])
ax.semilogy(nav_v3.index, nav_v3, color='green',       linewidth=1.5, label=s_v3['label'])
ax.semilogy(nav_v4.index, nav_v4, color='red',         linewidth=2.0, label=s_v4['label'])
ax.axvline(pd.Timestamp('2020-01-01'), color='black', linestyle='--', alpha=0.5, label='IS/OOS split')
ax.set_title('BTC Ensemble + Kelly Strategy — NAV (log scale)', fontsize=13)
ax.legend(fontsize=9); ax.grid(True, alpha=0.3)
ax.set_ylabel('Portfolio Value (starting $1)')

# Ensemble score over time
ax2 = axes[1]
ax2.fill_between(total_score.index, total_score, alpha=0.3, color='steelblue', label='Total Score')
ax2.plot(total_score.index, total_score.rolling(30).mean(), color='darkblue', linewidth=1.5, label='30d MA')
ax2.axhline(5, color='orange', linestyle='--', alpha=0.7, label='Neutral (5)')
ax2.axhline(7, color='green',  linestyle='--', alpha=0.7, label='Strong Bull (7)')
ax2.axhline(3, color='red',    linestyle='--', alpha=0.7, label='Bear (3)')
ax2.set_title('Ensemble Signal Score Over Time (0-10)', fontsize=13)
ax2.legend(fontsize=9); ax2.grid(True, alpha=0.3)
ax2.set_ylabel('Score')
ax2.set_ylim(0, 10.5)

plt.tight_layout()
fig.savefig(f"{media_dir}/ensemble_btc_strategy.png", dpi=150, bbox_inches='tight')
print(f"\nChart saved to {media_dir}/ensemble_btc_strategy.png")

# ─── Collect results for output ───────────────────────────────────────────────
results = {
    'overall': [s_v1, s_v2, s_v3, s_v4, s_bh],
    'yr_df': yr_df,
    's_v1': s_v1, 's_v2': s_v2, 's_v3': s_v3, 's_v4': s_v4, 's_bh': s_bh,
    'is': {}, 'oos': {}, 'y2024': {}
}
for r, key in [(ret_v1,'v1'),(ret_v2,'v2'),(ret_v3,'v3'),(ret_v4,'v4'),(ret_bh,'bh')]:
    results['is'][key]    = seg_stats(r, key, '2012-01-01', '2019-12-31')
    results['oos'][key]   = seg_stats(r, key, '2020-01-01', '2026-12-31')
    results['y2024'][key] = seg_stats(r, key, '2024-01-01', '2024-12-31')

# Save results to a pickle for further use
import pickle
with open('/tmp/ensemble_results.pkl', 'wb') as f:
    pickle.dump(results, f)
print("Results saved to /tmp/ensemble_results.pkl")
print("\nDONE.")
