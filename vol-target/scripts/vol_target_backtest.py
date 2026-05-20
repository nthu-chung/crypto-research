
import requests, time, pandas as pd, numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, secrets, os, sys

# ── helpers ─────────────────────────────────────────────────────────────────

def fetch_coinmetrics(metrics, start="2012-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data, params = [], {
        "assets": "btc",
        "metrics": metrics,
        "frequency": "1d",
        "start_time": start,
        "page_size": 1000
    }
    while True:
        j = requests.get(url, params=params, timeout=30).json()
        all_data.extend(j.get('data', []))
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
        time.sleep(0.05)
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['time'])
    for col in ['PriceUSD', 'CapMVRVCur']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('date').reset_index(drop=True)


def compute_stats(returns, label=""):
    ann = 365
    r = returns.dropna()
    cagr = (1 + r).prod() ** (ann / len(r)) - 1
    vol = r.std() * np.sqrt(ann)
    sharpe = (r.mean() * ann) / (r.std() * np.sqrt(ann)) if r.std() > 0 else np.nan
    neg = r[r < 0]
    sortino = (r.mean() * ann) / (neg.std() * np.sqrt(ann)) if len(neg) > 0 and neg.std() > 0 else np.nan
    cum = (1 + r).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.nan
    return {
        "label": label,
        "CAGR": round(cagr * 100, 2),
        "Vol": round(vol * 100, 2),
        "Sharpe": round(sharpe, 3),
        "Sortino": round(sortino, 3),
        "MaxDD": round(max_dd * 100, 2),
        "Calmar": round(calmar, 3),
        "Days": len(r)
    }


def compute_equity(returns):
    return (1 + returns.fillna(0)).cumprod()


# ── fetch data ───────────────────────────────────────────────────────────────

print("Fetching price + MVRV from CoinMetrics...")
df = fetch_coinmetrics("PriceUSD,CapMVRVCur", start="2012-01-01")
df = df[['date', 'PriceUSD', 'CapMVRVCur']].dropna(subset=['PriceUSD']).copy()
df = df.set_index('date').sort_index()

# BTC daily returns
df['btc_ret'] = df['PriceUSD'].pct_change()

# Rolling 20-day realized vol (annualised)
N = 20
df['rvol'] = df['btc_ret'].rolling(N).std() * np.sqrt(365)

# ── MVRV zone weights (v2 frozen percentile) ─────────────────────────────────
# Percentile computed on full history up to each date (expanding)
def mvrv_zone_weight(mvrv_series):
    """Returns a weight [0,1] based on MVRV percentile (expanding window)."""
    pct = mvrv_series.expanding().rank(pct=True)
    # Zone logic: higher percentile → lower weight (overvalued → reduce)
    # <20th pct → weight=1.0 (accumulate)
    # 20-50th → weight=0.75
    # 50-75th → weight=0.5
    # 75-90th → weight=0.25
    # >90th   → weight=0.1
    w = np.select(
        [pct < 0.20, pct < 0.50, pct < 0.75, pct < 0.90],
        [1.0, 0.75, 0.5, 0.25],
        default=0.1
    )
    return pd.Series(w, index=mvrv_series.index)

df['mvrv_w'] = mvrv_zone_weight(df['CapMVRVCur'].fillna(method='ffill'))

# MVRV Z-Score (expanding mean / std)
df['mvrv_z'] = (
    (df['CapMVRVCur'] - df['CapMVRVCur'].expanding().mean()) /
    df['CapMVRVCur'].expanding().std()
)

# ── strategy builder ──────────────────────────────────────────────────────────

FEE = 0.0004  # 4 bps one-way

def run_strategy(df, sigma_target, use_mvrv_zone=False, use_mvrv_zscore_stop=False,
                 max_lev=1.0, name=""):
    d = df.copy()
    # vol-target position size
    d['pos_vt'] = (sigma_target / d['rvol']).clip(upper=max_lev)

    if use_mvrv_zone:
        # cap by MVRV zone weight
        d['pos_raw'] = d['pos_vt'] * d['mvrv_w']
    else:
        d['pos_raw'] = d['pos_vt']

    if use_mvrv_zscore_stop:
        # force to 0.3 when Z > 2.5
        d['pos_raw'] = np.where(d['mvrv_z'] > 2.5, 0.3, d['pos_raw'])

    # T-1 signal → T execution
    d['pos'] = d['pos_raw'].shift(1).fillna(0)

    # daily P&L: position * next-day return - transaction cost
    d['delta_pos'] = d['pos'].diff().abs().fillna(0)
    d['strat_ret'] = d['pos'] * d['btc_ret'] - d['delta_pos'] * FEE

    # NaN cleanup
    d['strat_ret'] = d['strat_ret'].fillna(0)
    return d['strat_ret'], d['pos']


# ── run all 4 variants ────────────────────────────────────────────────────────

strategies = [
    dict(sigma_target=0.15, use_mvrv_zone=False, use_mvrv_zscore_stop=False,
         name="VT_15pct"),
    dict(sigma_target=0.20, use_mvrv_zone=False, use_mvrv_zscore_stop=False,
         name="VT_20pct"),
    dict(sigma_target=0.20, use_mvrv_zone=True,  use_mvrv_zscore_stop=False,
         name="MVRV_VT_20pct"),
    dict(sigma_target=0.20, use_mvrv_zone=True,  use_mvrv_zscore_stop=True,
         name="MVRV_VT_ZStop"),
]

IS_END  = "2019-12-31"
OOS_START = "2020-01-01"

results = []
strat_rets = {}
strat_pos  = {}

for s in strategies:
    ret, pos = run_strategy(df, **{k: v for k, v in s.items() if k != 'name'}, name=s['name'])
    strat_rets[s['name']] = ret
    strat_pos[s['name']]  = pos
    # Full
    results.append(compute_stats(ret, label=s['name'] + " (ALL)"))
    # IS
    results.append(compute_stats(ret.loc[:IS_END], label=s['name'] + " (IS)"))
    # OOS
    results.append(compute_stats(ret.loc[OOS_START:], label=s['name'] + " (OOS)"))

# BTC buy-hold
btc_full = df['btc_ret']
results.append(compute_stats(btc_full, label="BTC_BuyHold (ALL)"))
results.append(compute_stats(btc_full.loc[:IS_END], label="BTC_BuyHold (IS)"))
results.append(compute_stats(btc_full.loc[OOS_START:], label="BTC_BuyHold (OOS)"))

# ── print table ───────────────────────────────────────────────────────────────

res_df = pd.DataFrame(results)
print("\n" + res_df.to_string(index=False))

# ── charts ────────────────────────────────────────────────────────────────────

epoch = int(time.time())
hex8  = secrets.token_hex(4)
out_dir = "/root/.openclaw/workspace/openclaw-media"

fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=False)

# ── Chart 1: Equity curves (log scale) ──────────────────────────────────────
ax1 = axes[0]
colors = ['#f7931a', '#2196F3', '#4CAF50', '#FF5722', '#9C27B0']
ax1.semilogy(
    compute_equity(btc_full),
    label="BTC Buy-Hold", color=colors[0], alpha=0.8, linewidth=1.5
)
for i, name in enumerate([s['name'] for s in strategies]):
    ax1.semilogy(
        compute_equity(strat_rets[name]),
        label=name, color=colors[i+1], linewidth=1.5
    )
ax1.axvline(pd.Timestamp(IS_END), color='gray', linestyle='--', alpha=0.5, label='IS/OOS split')
ax1.set_title("Equity Curves (Log Scale) — Vol Targeting Strategies vs BTC Buy-Hold")
ax1.set_ylabel("Portfolio Value ($10k → $X)")
ax1.legend(fontsize=9)
ax1.grid(True, alpha=0.3)

# ── Chart 2: Position sizing over time ───────────────────────────────────────
ax2 = axes[1]
for i, name in enumerate([s['name'] for s in strategies]):
    ax2.plot(strat_pos[name], label=name, color=colors[i+1], alpha=0.7, linewidth=0.8)
ax2.axhline(1.0, color='red', linestyle=':', alpha=0.4, label='Max leverage (1x)')
ax2.set_title("Position Sizing Over Time (Vol-Target Adjustment)")
ax2.set_ylabel("Position Size (0=flat, 1=full)")
ax2.set_xlabel("Date")
ax2.legend(fontsize=9)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
out_path = f"{out_dir}/jarvis-image-{epoch}-{hex8}.png"
plt.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\nChart saved: {out_path}")

# ── save results MD ───────────────────────────────────────────────────────────

md_rows = []
for r in results:
    md_rows.append(
        f"| {r['label']} | {r['CAGR']}% | {r['Vol']}% | {r['Sharpe']} | "
        f"{r['Sortino']} | {r['MaxDD']}% | {r['Calmar']} | {r['Days']} |"
    )

# Pick best OOS result
oos_results = [r for r in results if '(OOS)' in r['label']]
best = max(oos_results, key=lambda x: x['Sharpe'] if not np.isnan(x['Sharpe']) else -99)

md = f"""# Volatility Targeting Backtest Results
**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M UTC')}

## Summary Table

| Strategy | CAGR | Vol | Sharpe | Sortino | MaxDD | Calmar | Days |
|----------|------|-----|--------|---------|-------|--------|------|
{chr(10).join(md_rows)}

## Best OOS Strategy
**{best['label']}** — Sharpe={best['Sharpe']}, MaxDD={best['MaxDD']}%, CAGR={best['CAGR']}%

## Methodology
- Initial capital: $10,000 | Fee: 4bps per leg
- IS: 2012–2019 | OOS: 2020–2026
- Position = min(sigma_target / realized_vol_20d, 1.0)  (no leverage)
- MVRV Zone: expanding-window percentile rank → weight [0.1, 0.25, 0.5, 0.75, 1.0]
- Z-Score stop: force position to 0.3 when MVRV Z-Score > 2.5
- T-1 signal → T execution

## Chart
![Equity + Position]({out_path})
"""

res_path = "/root/.openclaw/workspace/research/vol_target_results.md"
with open(res_path, 'w') as f:
    f.write(md)

print(f"Results written: {res_path}")

# ── final summary for reporting ────────────────────────────────────────────────
print("\n=== FINAL SUMMARY ===")
for r in oos_results:
    print(f"  {r['label']}: Sharpe={r['Sharpe']}, MaxDD={r['MaxDD']}%, CAGR={r['CAGR']}%")
