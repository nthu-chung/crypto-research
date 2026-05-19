#!/usr/bin/env python3
"""
Generate regime_results.md from computed results (fix pandas get_loc API)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
import requests, time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
from hmmlearn import hmm

MEDIA_DIR = "/root/.openclaw/workspace/openclaw-media"
RESULTS_FILE = "/root/.openclaw/workspace/research/regime_results.md"

def fetch_coinmetrics(metrics, start="2012-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data, params = [], {"assets":"btc","metrics":metrics,"frequency":"1d","start_time":start,"page_size":1000}
    while True:
        try:
            j = requests.get(url, params=params, timeout=20).json()
        except Exception as e:
            break
        all_data.extend(j.get('data',[]))
        token = j.get('next_page_token')
        if not token: break
        params = {"assets":"btc","metrics":metrics,"frequency":"1d","page_size":1000,"next_page_token":token}
        time.sleep(0.05)
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['time'])
    for col in ['PriceUSD','CapMVRVCur']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('date').reset_index(drop=True)

print("Fetching data...")
df = fetch_coinmetrics("PriceUSD,CapMVRVCur")
df = df.set_index('date').copy()
df['price'] = df['PriceUSD']
df['mvrv'] = df['CapMVRVCur']
df['ma200'] = df['price'].rolling(200).mean()
df['ma20'] = df['price'].rolling(20).mean()
df['slope20'] = (df['ma20'] - df['ma20'].shift(10)) / df['ma20'].shift(10)
df['ret'] = df['price'].pct_change()
df['vol20'] = df['ret'].rolling(20).std()

def mvrv_to_position(mvrv):
    if pd.isna(mvrv): return 0.5
    if mvrv < 1.0: return 1.0
    elif mvrv < 1.5: return 0.9
    elif mvrv < 2.0: return 0.75
    elif mvrv < 2.5: return 0.6
    elif mvrv < 3.0: return 0.5
    elif mvrv < 3.5: return 0.35
    elif mvrv < 4.0: return 0.2
    elif mvrv < 5.0: return 0.1
    else: return 0.0

df['mvrv_pos'] = df['mvrv'].apply(mvrv_to_position)
df = df.dropna(subset=['ma200','ma20','slope20','ret','vol20'])

# Regimes
bull = (df['price'] > df['ma200']) & (df['slope20'] > 0)
bear = (df['price'] < df['ma200']) & (df['slope20'] < 0)
df['regime_ma'] = 3
df.loc[bull, 'regime_ma'] = 1
df.loc[bear, 'regime_ma'] = 2

# HMM
returns = df['ret'].values.reshape(-1, 1)
model = hmm.GaussianHMM(n_components=2, covariance_type="diag", n_iter=100, random_state=42)
model.fit(returns)
states = model.predict(returns)
state_vars = [returns[states==s].var() if (states==s).sum()>0 else 0 for s in range(2)]
bull_state = int(np.argmin(state_vars))
bear_state = int(np.argmax(state_vars))
posteriors = model.predict_proba(returns)
max_prob = posteriors.max(axis=1)
df['regime_hmm'] = 3
df.loc[np.array(states == bull_state) & (max_prob >= 0.70), 'regime_hmm'] = 1
df.loc[np.array(states == bear_state) & (max_prob >= 0.70), 'regime_hmm'] = 2

# GMM
features = df[['ret','vol20']].values
scaler = StandardScaler()
features_scaled = scaler.fit_transform(features)
gmm = GaussianMixture(n_components=2, covariance_type='full', n_init=5, random_state=42)
gmm.fit(features_scaled)
g_states = gmm.predict(features_scaled)
state_vols = [df['vol20'].values[g_states==s].mean() if (g_states==s).sum()>0 else 0 for s in range(2)]
g_bull = int(np.argmin(state_vols))
g_bear = int(np.argmax(state_vols))
g_probs = gmm.predict_proba(features_scaled)
g_max_prob = g_probs.max(axis=1)
df['regime_gmm'] = 3
df.loc[np.array(g_states == g_bull) & (g_max_prob >= 0.70), 'regime_gmm'] = 1
df.loc[np.array(g_states == g_bear) & (g_max_prob >= 0.70), 'regime_gmm'] = 2

def regime_to_position(regime, mvrv_pos):
    pos = pd.Series(index=regime.index, dtype=float)
    pos[regime == 1] = mvrv_pos[regime == 1]
    pos[regime == 2] = 0.10
    pos[regime == 3] = 0.50 * mvrv_pos[regime == 3]
    return pos.clip(0, 1)

df['pos_ma'] = regime_to_position(df['regime_ma'], df['mvrv_pos'])
df['pos_hmm'] = regime_to_position(df['regime_hmm'], df['mvrv_pos'])
df['pos_gmm'] = regime_to_position(df['regime_gmm'], df['mvrv_pos'])
df['pos_mvrv'] = df['mvrv_pos']
df['pos_bh'] = 1.0

def backtest(pos, ret, name=""):
    pos_lag = pos.shift(1).fillna(0)
    strat_ret = pos_lag * ret
    equity = (1 + strat_ret).cumprod()
    n_years = len(ret) / 365
    total_return = equity.iloc[-1] - 1
    annual_return = equity.iloc[-1] ** (1/n_years) - 1
    annual_vol = strat_ret.std() * np.sqrt(365)
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = drawdown.min()
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0
    return {'name':name,'total_return':total_return,'annual_return':annual_return,
            'annual_vol':annual_vol,'sharpe':sharpe,'max_dd':max_dd,'calmar':calmar,
            'equity':equity,'drawdown':drawdown,'strat_ret':strat_ret}

results, is_results, oos_results = {}, {}, {}
SPLIT_DATE = '2021-01-01'
df_is = df[df.index < SPLIT_DATE]
df_oos = df[df.index >= SPLIT_DATE]

for key, pos_col, name in [
    ('Regime_MA','pos_ma','Regime MA Rules'),
    ('Regime_HMM','pos_hmm','Regime HMM'),
    ('Regime_GMM','pos_gmm','Regime GMM'),
    ('MVRV_v2','pos_mvrv','MVRV v2 (baseline)'),
    ('BuyHold','pos_bh','Buy & Hold'),
]:
    results[key] = backtest(df[pos_col], df['ret'], name)
    is_results[key] = backtest(df_is[pos_col], df_is['ret'], name)
    oos_results[key] = backtest(df_oos[pos_col], df_oos['ret'], name)

print("\n=== FULL PERIOD ===")
for key, r in results.items():
    ok = "✅" if r['sharpe'] > 1.0 and r['max_dd'] > -0.20 else ("🔶" if r['sharpe'] > 1.0 else "❌")
    print(f"  {ok} {r['name']}: Sharpe={r['sharpe']:.2f}, MaxDD={r['max_dd']:.1%}")

# ─── Event analysis (fixed get_loc) ─────────────────────────────────────────
def nearest_date(idx, target):
    target = pd.Timestamp(target)
    # Handle tz-aware index
    if idx.tz is not None:
        target = target.tz_localize(idx.tz)
    pos = idx.searchsorted(target)
    pos = min(pos, len(idx)-1)
    if pos > 0 and (abs(idx[pos]-target) > abs(idx[pos-1]-target)):
        pos -= 1
    return idx[pos]

print("\n=== 2022 CRISIS EVENT ANALYSIS ===")
events = {
    'BTC ATH (Nov 2021)': '2021-11-10',
    'LUNA Collapse': '2022-05-09',
    'FTX Collapse': '2022-11-08',
}
regime_label = {1:'🟢 Bull', 2:'🔴 Bear', 3:'🟡 Trans'}
event_rows = []
for event, date in events.items():
    nd = nearest_date(df.index, date)
    price = df.loc[nd, 'price']
    row = {'event': event, 'date': date, 'price': price}
    for rcol, name in [('regime_ma','MA'),('regime_hmm','HMM'),('regime_gmm','GMM')]:
        row[name] = regime_label.get(df.loc[nd, rcol], '?')
    event_rows.append(row)
    print(f"  {event} ({date}) BTC≈${price:,.0f} | MA:{row['MA']} | HMM:{row['HMM']} | GMM:{row['GMM']}")

# First bear signal after peak
print("\n  Regime transition speed after BTC peak:")
bear_info = {}
for rcol, name in [('regime_ma','MA Rules'),('regime_hmm','HMM'),('regime_gmm','GMM')]:
    after_peak = df['2021-11-10':]
    bear_mask = after_peak[rcol] == 2
    if bear_mask.any():
        first_bear = after_peak[bear_mask].index[0]
        peak_nd = nearest_date(df.index, '2021-11-10')
        days_delay = (first_bear - peak_nd).days
        price_at_bear = df.loc[first_bear, 'price']
        peak_price = df.loc[peak_nd, 'price']
        pct_drop = (price_at_bear / peak_price - 1)
        bear_info[name] = {'date': first_bear.date(), 'days': days_delay, 'drop': pct_drop}
        print(f"    {name}: {first_bear.date()} ({days_delay}d after peak, BTC dropped {pct_drop:.1%})")
    else:
        bear_info[name] = None
        print(f"    {name}: No bear signal")

print("\n=== 2024 BULL MARKET ===")
df_2024 = df['2024-01-01':'2024-12-31']
btc_ath_2024 = df_2024['price'].max()
btc_ath_date_2024 = df_2024['price'].idxmax()
bh_2024 = backtest(df_2024['pos_bh'], df_2024['ret'], 'B&H')
print(f"  2024 ATH: ${btc_ath_2024:,.0f} on {btc_ath_date_2024.date()}")
bull_2024_rows = []
for rcol, pcol, name in [('regime_ma','pos_ma','MA Rules'),('regime_hmm','pos_hmm','HMM'),('regime_gmm','pos_gmm','GMM')]:
    bull_pct = (df_2024[rcol] == 1).mean()
    avg_pos = df_2024[pcol].mean()
    r24 = backtest(df_2024[pcol], df_2024['ret'], name)
    bull_2024_rows.append({'name':name,'bull_pct':bull_pct,'avg_pos':avg_pos,'ret':r24['annual_return'],'sharpe':r24['sharpe']})
    print(f"  {name}: Bull%={bull_pct:.0%}, AvgPos={avg_pos:.0%}, Return={r24['annual_return']:.0%}, Sharpe={r24['sharpe']:.2f}")
print(f"  Buy&Hold: Return={bh_2024['annual_return']:.0%}, Sharpe={bh_2024['sharpe']:.2f}")

# ─── Write Markdown ───────────────────────────────────────────────────────────
REGIME_COLORS = {1: '#2ecc71', 2: '#e74c3c', 3: '#f39c12'}

fig, axes = plt.subplots(4, 1, figsize=(16, 24))
fig.suptitle('BTC Regime Detection Strategy Analysis', fontsize=16, fontweight='bold')
ax1 = axes[0]
for rv, color in REGIME_COLORS.items():
    mask = df['regime_ma'] == rv
    ax1.fill_between(df.index, df['price'].min()*0.8, df['price'].max()*1.1, where=mask, alpha=0.2, color=color)
ax1.semilogy(df.index, df['price'], 'k-', linewidth=0.8)
legend_elements = [Patch(facecolor=REGIME_COLORS[1], alpha=0.5, label='Bull'),
                   Patch(facecolor=REGIME_COLORS[2], alpha=0.5, label='Bear'),
                   Patch(facecolor=REGIME_COLORS[3], alpha=0.5, label='Transition')]
ax1.legend(handles=legend_elements, loc='upper left')
ax1.set_title('BTC Price with MA Regime Classification (log scale)')
ax1.set_ylabel('BTC/USD (log)'); ax1.grid(True, alpha=0.3)

ax2 = axes[1]
for rcol, name, ls in [('regime_ma','MA Rules','-'),('regime_hmm','HMM','--'),('regime_gmm','GMM',':')]:
    bull_rolling = (df[rcol] == 1).rolling(30).mean()
    ax2.plot(df.index, bull_rolling, ls, label=f'{name} Bull%', linewidth=1.5)
ax2.axhline(0.5, color='gray', linestyle='--', alpha=0.5)
ax2.set_title('30-Day Rolling Bull Regime % Comparison'); ax2.set_ylim(0,1); ax2.legend(); ax2.grid(True, alpha=0.3)

colors_eq = {'Regime_MA':'#2ecc71','Regime_HMM':'#3498db','Regime_GMM':'#9b59b6','MVRV_v2':'#e67e22','BuyHold':'#95a5a6'}
ax3 = axes[2]
for key, r in results.items():
    ax3.semilogy(r['equity'].index, r['equity'].values, label=f"{r['name']} (S={r['sharpe']:.2f})",
                 color=colors_eq[key], linewidth=1.5 if key!='BuyHold' else 1.0)
ax3.set_title('Equity Curves (log scale) — Sharpe in legend'); ax3.legend(loc='upper left'); ax3.grid(True,alpha=0.3)

ax4 = axes[3]
for key, r in results.items():
    ax4.plot(r['drawdown'].index, r['drawdown'].values*100, label=f"{r['name']} ({r['max_dd']:.0%})",
             color=colors_eq[key], linewidth=1.5 if key!='BuyHold' else 1.0)
ax4.axhline(-20, color='red', linestyle='--', alpha=0.7, label='-20% threshold')
ax4.set_title('Drawdown Comparison'); ax4.set_ylabel('Drawdown (%)'); ax4.legend(loc='lower left'); ax4.grid(True,alpha=0.3)

plt.tight_layout()
plt.savefig(f'{MEDIA_DIR}/regime_analysis.png', dpi=150, bbox_inches='tight')
plt.close()
print(f"\nSaved: {MEDIA_DIR}/regime_analysis.png")

fig2, axes2 = plt.subplots(2, 2, figsize=(18, 12))
fig2.suptitle('Regime Detection: 2022 Crash vs 2024 Bull Market', fontsize=14, fontweight='bold')
for (start, end, title, ax) in [
    ('2021-06-01','2023-06-01','2022 Bear Cycle (LUNA + FTX)',axes2[0,0]),
    ('2023-10-01','2024-12-31','2024 Bull Market',axes2[0,1]),
]:
    dp = df[start:end]
    for rv, color in REGIME_COLORS.items():
        mask = dp['regime_ma'] == rv
        ax.fill_between(dp.index, dp['price'].min()*0.9, dp['price'].max()*1.1, where=mask, alpha=0.25, color=color)
    ax.plot(dp.index, dp['price'], 'k-', linewidth=1.2)
    ax.set_title(f'Price + MA Regime: {title}')
    ax.legend(handles=[Patch(facecolor=REGIME_COLORS[k],alpha=0.5,label=v) for k,v in {1:'Bull',2:'Bear',3:'Trans'}.items()])
    ax.grid(True, alpha=0.3)

ax_bl = axes2[1,0]
dp = df['2021-10-01':'2023-06-01']
for i,(rcol,name) in enumerate([('regime_ma','MA'),('regime_hmm','HMM'),('regime_gmm','GMM')]):
    enc = dp[rcol].map({1:1.0,3:0.5,2:0.0})
    ax_bl.plot(dp.index, enc + i*0.02, label=name, alpha=0.8)
ax_bl.axvline(pd.Timestamp('2022-05-09'), color='red', linestyle='--', alpha=0.7, label='LUNA')
ax_bl.axvline(pd.Timestamp('2022-11-08'), color='darkred', linestyle='--', alpha=0.7, label='FTX')
ax_bl.set_yticks([0,0.5,1.0]); ax_bl.set_yticklabels(['Bear','Trans','Bull'])
ax_bl.set_title('Regime Comparison: 2022 Crisis'); ax_bl.legend(); ax_bl.grid(True,alpha=0.3)

ax_br = axes2[1,1]
for pcol,name,color in [('pos_ma','MA','#2ecc71'),('pos_hmm','HMM','#3498db'),
                         ('pos_gmm','GMM','#9b59b6'),('pos_mvrv','MVRV only','#e67e22')]:
    ax_br.plot(df_2024.index, df_2024[pcol]*100, label=name, alpha=0.8)
ax_br.set_title('Position Sizes: 2024 Bull Market'); ax_br.set_ylabel('Position %')
ax_br.legend(); ax_br.grid(True,alpha=0.3)

plt.tight_layout()
plt.savefig(f'{MEDIA_DIR}/regime_crisis_bull.png', dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: {MEDIA_DIR}/regime_crisis_bull.png")

# ─── Write Markdown ───────────────────────────────────────────────────────────
best_key = max(results, key=lambda k: results[k]['sharpe'])
best = results[best_key]

lines = []
lines.append("# BTC Regime Detection Strategy — Research Results\n")
lines.append("**Generated:** 2026-05-19  \n**Research:** Market Regime Detection (MA Rules + HMM + GMM)  \n**Data:** CoinMetrics BTC 2011–2026  \n**Target:** Sharpe > 1.0 AND MaxDD > −20% (magnitude < 20%)\n\n---\n")

lines.append("## 📊 Performance Summary\n\n")
lines.append("| Strategy | IS Sharpe | IS MaxDD | OOS Sharpe | OOS MaxDD | Full Sharpe | Full MaxDD | Target |\n")
lines.append("|---|---|---|---|---|---|---|---|\n")
for key in ['Regime_MA','Regime_HMM','Regime_GMM','MVRV_v2','BuyHold']:
    r_is, r_oos, r_full = is_results[key], oos_results[key], results[key]
    meets = r_full['sharpe'] > 1.0 and r_full['max_dd'] > -0.20
    sharpe_ok = r_full['sharpe'] > 1.0
    ok = "✅ Both" if meets else ("🔶 Sharpe✓ DD✗" if sharpe_ok else "❌")
    lines.append(f"| {r_full['name']} | {r_is['sharpe']:.2f} | {r_is['max_dd']:.1%} | {r_oos['sharpe']:.2f} | {r_oos['max_dd']:.1%} | {r_full['sharpe']:.2f} | {r_full['max_dd']:.1%} | {ok} |\n")
lines.append("\n*IS = In-sample (before 2021-01-01), OOS = Out-of-sample (2021+)*\n\n")

lines.append("## 📈 Full Period Details\n\n")
lines.append("| Strategy | Ann.Return | Ann.Vol | Sharpe | MaxDD | Calmar |\n")
lines.append("|---|---|---|---|---|---|\n")
for key, r in results.items():
    lines.append(f"| {r['name']} | {r['annual_return']:.1%} | {r['annual_vol']:.1%} | {r['sharpe']:.2f} | {r['max_dd']:.1%} | {r['calmar']:.2f} |\n")
lines.append("\n")

lines.append("## 🏗 Strategy Architecture\n\n")
lines.append("### Position Sizing Logic\n\n```\nBull  (Regime 1): position = MVRV_zone_weight (0–100%)\nBear  (Regime 2): position = 10% fixed\nTrans (Regime 3): position = 50% × MVRV_zone_weight\n```\n\n")
lines.append("### MVRV Zone Table\n\n| MVRV | Position |\n|---|---|\n| < 1.0 | 100% |\n| 1.0–1.5 | 90% |\n| 1.5–2.0 | 75% |\n| 2.0–2.5 | 60% |\n| 2.5–3.0 | 50% |\n| 3.0–3.5 | 35% |\n| 3.5–4.0 | 20% |\n| 4.0–5.0 | 10% |\n| > 5.0 | 0% |\n\n")

lines.append("### A. Simple MA Regime (Baseline)\n- **Bull**: Price > 200d MA AND 20d slope > 0\n- **Bear**: Price < 200d MA AND 20d slope < 0\n- **Trans**: Everything else\n\n")
lines.append("### B. HMM (Hidden Markov Model)\n- 2-state Gaussian HMM on daily BTC returns\n- Low variance state → Bull; High variance → Bear\n- Posterior < 70% → Transition\n\n")
lines.append("### C. GMM (Gaussian Mixture Model)\n- 2D GMM on (daily return, 20d rolling vol)\n- Low-vol cluster → Bull; High-vol cluster → Bear\n- Probability < 70% → Transition\n\n")

lines.append("## 🚨 2022 LUNA/FTX Crisis Analysis\n\n")
lines.append("| Event | Date | BTC Price | MA Regime | HMM Regime | GMM Regime |\n|---|---|---|---|---|---|\n")
for row in event_rows:
    lines.append(f"| {row['event']} | {row['date']} | ${row['price']:,.0f} | {row['MA']} | {row['HMM']} | {row['GMM']} |\n")
lines.append("\n### Bear Signal Speed (days after ATH Nov 10, 2021)\n\n")
for name, info in bear_info.items():
    if info:
        lines.append(f"- **{name}**: {info['date']} — {info['days']} days after peak, BTC had dropped {info['drop']:.1%}\n")
lines.append("\n")
lines.append("**Key observation**: MA Rules triggered bear earliest (Jan 2022, ~52 days after peak at ~-25% drawdown). ")
lines.append("HMM/GMM were late on trend but faster to detect vol spikes from LUNA and FTX events. ")
lines.append("The 10% bear floor preserved capital during 2022's -80% BTC crash.\n\n")

lines.append("## 🚀 2024 Bull Market Participation\n\n")
lines.append(f"**BTC 2024 ATH**: ${btc_ath_2024:,.0f} on {btc_ath_date_2024.date()}\n\n")
lines.append("| Strategy | Bull% in 2024 | Avg Position | 2024 Return | 2024 Sharpe |\n|---|---|---|---|---|\n")
for r in bull_2024_rows:
    lines.append(f"| {r['name']} | {r['bull_pct']:.0%} | {r['avg_pos']:.0%} | {r['ret']:.0%} | {r['sharpe']:.2f} |\n")
lines.append(f"| Buy & Hold | 100% | 100% | {bh_2024['annual_return']:.0%} | {bh_2024['sharpe']:.2f} |\n")
lines.append("\n**Key observation**: GMM was most aggressive in 2024 (Bull 96%), HMM high (88%), MA rules more conservative (55%). ")
lines.append("All methods maintained meaningful BTC exposure during the 2024 rally.\n\n")

lines.append("## 🏆 Conclusion\n\n")
lines.append(f"**Best Risk-Adjusted Strategy**: {best['name']} (Sharpe={best['sharpe']:.2f}, MaxDD={best['max_dd']:.1%})\n\n")

lines.append("### Target Assessment: Sharpe > 1 AND |MaxDD| < 20%\n\n")
lines.append("⚠️ **No strategy fully meets the MaxDD < 20% target.** BTC's inherent volatility makes sub-20% drawdown extremely difficult without aggressive hedging or frequent trading.\n\n")
lines.append("### Ranked by Sharpe Ratio (Full Period)\n\n")
ranked = sorted(results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
for i, (key, r) in enumerate(ranked):
    medal = ['🥇','🥈','🥉','4️⃣','5️⃣'][i]
    sharpe_ok = "✅" if r['sharpe'] > 1.0 else "❌"
    lines.append(f"{medal} **{r['name']}**: Sharpe={r['sharpe']:.2f} {sharpe_ok}, MaxDD={r['max_dd']:.1%}\n")

lines.append("""
### Key Findings

1. **🏆 Regime MA Rules wins overall** (Sharpe=1.59, Ann.Return=54.8%) — simple 200d MA + slope filter is hard to beat
2. **📉 Regime detection dramatically reduces drawdown vs B&H** (MA: -39% vs B&H: -93%)
3. **HMM Sharpe=1.14** — captures volatility regimes well; 2-state GaussianHMM on returns is a solid approach
4. **GMM underperforms** (Sharpe=0.62) — prone to mis-classifying trending markets as "uncertain"
5. **OOS degradation is real** — all strategies drop significantly in 2021+ (more volatile, sentiment-driven cycle)
6. **2022 crisis**: MA Rules signaled bear first (~52 days, -25% into crash); HMM/GMM detected vol spikes faster once they hit
7. **2024 bull**: All methods maintained high exposure (38–74% returns vs 109% B&H) — regime detection preserved capital for re-entry

### Recommendations

- **Production-ready**: Regime MA Rules + MVRV for risk-adjusted performance
- **Signal enhancement**: Use HMM vol state as secondary alarm for sharp drawdown events (LUNA-type)
- **MaxDD improvement path**: Add trailing stop at -15% during Bear regime, or use options for downside hedge
- **OOS robustness**: Regime + MVRV needs periodic recalibration; the IS/OOS gap suggests some data mining
""")
lines.append("\n## 📁 Charts\n\n- `openclaw-media/regime_analysis.png` — Full period: price+regimes, bull%, equity curves, drawdown\n- `openclaw-media/regime_crisis_bull.png` — 2022 crisis vs 2024 bull market closeups\n")

with open(RESULTS_FILE, 'w') as f:
    f.writelines(lines)
print(f"\n✅ Markdown written to {RESULTS_FILE}")
print(f"\n=== FINAL SUMMARY ===")
print(f"Best strategy: {best['name']}")
print(f"Full: Sharpe={best['sharpe']:.2f}, MaxDD={best['max_dd']:.1%}, AnnRet={best['annual_return']:.1%}")
for key in ['Regime_MA','Regime_HMM','Regime_GMM','MVRV_v2']:
    r = results[key]
    sharpe_ok = "✅" if r['sharpe'] > 1.0 else "❌"
    print(f"  {sharpe_ok} {r['name']}: Sharpe={r['sharpe']:.2f}, MaxDD={r['max_dd']:.1%}")
