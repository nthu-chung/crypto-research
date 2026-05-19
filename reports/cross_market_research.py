"""
Cross-Market Signal Research: TradFi × Crypto
Goal: Sharpe > 1, MaxDD < -20%
Signals: DXY, Gold, VIX, 10Y Yield (TNX), SPX
"""

import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import time
import warnings
warnings.filterwarnings('ignore')

# ─── Data Fetching ───────────────────────────────────────────────────────────

def fetch_yahoo(ticker, start="2015-01-01", end="2026-05-19"):
    """Fetch daily close from Yahoo Finance."""
    start_ts = int(pd.Timestamp(start).timestamp())
    end_ts = int(pd.Timestamp(end).timestamp())
    # Try v8 first, fall back to v7
    for api_ver in ['v8', 'v7']:
        url = f"https://query1.finance.yahoo.com/{api_ver}/finance/chart/{ticker}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            r = requests.get(url, params={
                "period1": start_ts, "period2": end_ts,
                "interval": "1d", "events": "history"
            }, headers=headers, timeout=20)
            data = r.json()
            result = data['chart']['result'][0]
            timestamps = result['timestamp']
            closes = result['indicators']['quote'][0]['close']
            df = pd.DataFrame({'date': pd.to_datetime(timestamps, unit='s', utc=True), 'close': closes})
            df = df.dropna().sort_values('date').reset_index(drop=True)
            df['close'] = df['close'].astype(float)
            print(f"  {ticker}: {len(df)} rows [{df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}]")
            return df
        except Exception as e:
            print(f"  {api_ver} failed for {ticker}: {e}")
    # If all fail, try alternative via query2
    try:
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        r = requests.get(url, params={
            "period1": start_ts, "period2": end_ts, "interval": "1d"
        }, headers=headers, timeout=20)
        data = r.json()
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        closes = result['indicators']['quote'][0]['close']
        df = pd.DataFrame({'date': pd.to_datetime(timestamps, unit='s', utc=True), 'close': closes})
        df = df.dropna().sort_values('date').reset_index(drop=True)
        df['close'] = df['close'].astype(float)
        print(f"  {ticker} (q2): {len(df)} rows")
        return df
    except Exception as e:
        print(f"  ALL methods failed for {ticker}: {e}")
        return pd.DataFrame(columns=['date','close'])

def fetch_dxy_fallback(start="2015-01-01", end="2026-05-19"):
    """Fetch DXY - try multiple sources."""
    # Try stooq
    for stooq_ticker in ['dxy.f', 'usd.index']:
        try:
            url = f"https://stooq.com/q/d/l/?s={stooq_ticker}&i=d"
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and 'Date' in r.text[:50]:
                from io import StringIO
                df = pd.read_csv(StringIO(r.text))
                df.columns = [c.lower() for c in df.columns]
                if 'date' in df.columns and 'close' in df.columns:
                    df['date'] = pd.to_datetime(df['date'], utc=True)
                    df = df[['date','close']].dropna().sort_values('date').reset_index(drop=True)
                    df['close'] = pd.to_numeric(df['close'], errors='coerce')
                    df = df.dropna()
                    start_ts = pd.Timestamp(start, tz='UTC')
                    end_ts   = pd.Timestamp(end, tz='UTC')
                    df = df[(df['date'] >= start_ts) & (df['date'] <= end_ts)].reset_index(drop=True)
                    if len(df) > 100:
                        print(f"  DXY (stooq/{stooq_ticker}): {len(df)} rows")
                        return df
        except Exception as e:
            pass
    # Try Yahoo Finance DX-Y.NYB
    for yt in ['DX-Y.NYB', 'DX=F']:
        df = fetch_yahoo(yt, start, end)
        if len(df) > 100:
            print(f"  DXY ({yt}): {len(df)} rows")
            return df
    # Synthetic DXY proxy from EURUSD (inverse)
    print("  DXY unavailable — using EURUSD inverse as proxy")
    df = fetch_yahoo('EURUSD=X', start, end)
    if len(df) > 100:
        df['close'] = 1.0 / df['close']  # invert: strong USD = high DXY
        df['close'] = df['close'] * 100   # rough scale
        return df
    return pd.DataFrame(columns=['date','close'])

def fetch_binance_btc(start="2015-01-01", end="2026-05-19"):
    url = "https://api.binance.com/api/v3/klines"
    all_data = []
    start_ts = int(pd.Timestamp(start).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end).timestamp() * 1000)
    while start_ts < end_ts:
        try:
            r = requests.get(url, params={
                "symbol": "BTCUSDT", "interval": "1d",
                "startTime": start_ts, "limit": 1000
            }, timeout=15)
            data = r.json()
            if not data or isinstance(data, dict):
                break
            all_data.extend(data)
            start_ts = data[-1][0] + 86400000
            if len(data) < 1000:
                break
            time.sleep(0.1)
        except Exception as e:
            print(f"  Binance fetch error: {e}")
            break
    cols = ['ts','open','high','low','close','vol','cts','qvol','n','tbbav','tbqav','x']
    df = pd.DataFrame(all_data, columns=cols)
    df['date'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df['close'] = df['close'].astype(float)
    df = df[['date','close']].sort_values('date').reset_index(drop=True)
    print(f"  BTCUSDT: {len(df)} rows [{df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}]")
    return df

# ─── Fetch All Data ───────────────────────────────────────────────────────────

print("=== Fetching Data ===")
btc  = fetch_binance_btc("2015-01-01")
dxy  = fetch_yahoo("^DXY",  "2015-01-01")
if len(dxy) < 100:
    print("  Falling back to stooq for DXY...")
    dxy = fetch_dxy_fallback("2015-01-01")
gold = fetch_yahoo("GC=F",  "2015-01-01")
vix  = fetch_yahoo("^VIX",  "2015-01-01")
tnx  = fetch_yahoo("^TNX",  "2015-01-01")
spx  = fetch_yahoo("^GSPC", "2015-01-01")

# ─── Align to Common Date Index ──────────────────────────────────────────────

def to_series(df, name):
    s = df.set_index('date')['close']
    # Ensure UTC timezone aware
    if hasattr(s.index, 'tz') and s.index.tz is None:
        s.index = s.index.tz_localize('UTC')
    # Normalize to date-only
    if hasattr(s.index, 'normalize'):
        s.index = s.index.normalize()
    else:
        s.index = pd.DatetimeIndex(s.index).normalize()
    return s.rename(name)

btc_s  = to_series(btc,  'BTC')
dxy_s  = to_series(dxy,  'DXY')
gold_s = to_series(gold, 'Gold')
vix_s  = to_series(vix,  'VIX')
tnx_s  = to_series(tnx,  'TNX')
spx_s  = to_series(spx,  'SPX')

master = pd.concat([btc_s, dxy_s, gold_s, vix_s, tnx_s, spx_s], axis=1)
master = master.ffill().dropna()
master = master[master.index >= pd.Timestamp("2016-01-01", tz='UTC')]
print(f"\nMaster dataset: {len(master)} rows [{master.index[0].date()} → {master.index[-1].date()}]")

# Compute daily returns
ret = master.pct_change().dropna()

# ─── Step 1: Correlation Analysis ────────────────────────────────────────────

print("\n=== Step 1: Correlation Analysis ===")

# Full-period
full_corr = ret.corr()['BTC'].drop('BTC')
print("Full-period correlation with BTC:")
for col, v in full_corr.items():
    print(f"  {col}: {v:.3f}")

# Pre/Post 2020
pre  = ret[ret.index < pd.Timestamp("2020-01-01", tz='UTC')]
post = ret[ret.index >= pd.Timestamp("2020-01-01", tz='UTC')]
print("\nPre-2020 vs Post-2020 correlation with BTC:")
for col in ['DXY','Gold','VIX','TNX','SPX']:
    pre_c  = pre['BTC'].corr(pre[col])
    post_c = post['BTC'].corr(post[col])
    print(f"  {col}: pre={pre_c:.3f}  post={post_c:.3f}")

# Rolling 90d correlation
roll90 = ret[['BTC','DXY','VIX','SPX']].rolling(90).corr()['BTC'].unstack(level=1).drop(columns='BTC', errors='ignore')

# ─── Helper Functions ─────────────────────────────────────────────────────────

def mvrv_proxy(btc_price, window=365):
    """
    Proxy MVRV zone using price vs rolling 1-year MA.
    ratio > 2.4 → overheated (zone 3)  → 30% base pos
    ratio 1.2-2.4 → normal (zone 2)    → 70% base pos
    ratio < 1.2 → undervalued (zone 1) → 100% base pos
    """
    ma = btc_price.rolling(window).mean()
    ratio = btc_price / ma
    pos = pd.Series(index=btc_price.index, dtype=float)
    pos[ratio > 2.4] = 0.30
    pos[(ratio >= 1.2) & (ratio <= 2.4)] = 0.70
    pos[ratio < 1.2] = 1.00
    return pos.ffill().fillna(1.0)

def backtest(positions, btc_ret, fee=0.0004, name="Strategy"):
    """
    positions: daily float [0,1] aligned with btc_ret
    fee: one-way transaction cost (4bps = 0.0004)
    """
    pos = positions.reindex(btc_ret.index).ffill().fillna(0)
    daily_ret = pos.shift(1) * btc_ret  # enter next day
    # Apply fees on position changes
    turnover = pos.diff().abs().fillna(0)
    fee_drag  = turnover * fee
    net_ret   = daily_ret - fee_drag

    cumret  = (1 + net_ret).cumprod()
    ann_ret = cumret.iloc[-1] ** (252 / len(cumret)) - 1
    ann_vol = net_ret.std() * np.sqrt(252)
    sharpe  = ann_ret / ann_vol if ann_vol > 0 else 0

    roll_max = cumret.cummax()
    drawdown = cumret / roll_max - 1
    max_dd   = drawdown.min()

    return {
        'name': name, 'cumret': cumret, 'net_ret': net_ret,
        'ann_ret': ann_ret, 'ann_vol': ann_vol, 'sharpe': sharpe,
        'max_dd': max_dd, 'drawdown': drawdown
    }

def print_stats(res):
    print(f"  {res['name']:<35} AnnRet={res['ann_ret']*100:+.1f}%  "
          f"Vol={res['ann_vol']*100:.1f}%  "
          f"Sharpe={res['sharpe']:.2f}  "
          f"MaxDD={res['max_dd']*100:.1f}%")

# ─── Prepare Signal Data ─────────────────────────────────────────────────────

btc_px = master['BTC']
dxy_px = master['DXY']
vix_px = master['VIX']
spx_px = master['SPX']

# MVRV proxy
mvrv_pos = mvrv_proxy(btc_px)

# DXY 20d slope (normalised)
dxy_ma20  = dxy_px.rolling(20).mean()
dxy_slope = dxy_ma20.diff(5)  # 5-day change in 20d MA

# VIX levels
# SPX EMA200
spx_ema200 = spx_px.ewm(span=200).mean()

# Rolling BTC-SPX 60d corr (to detect high-correlation regime)
btc_spx_roll = ret['BTC'].rolling(60).corr(ret['SPX'])

# ─── Define IS / OOS Splits ──────────────────────────────────────────────────
IS_END  = pd.Timestamp("2020-12-31", tz='UTC')
OOS_START = pd.Timestamp("2021-01-01", tz='UTC')

def split(series):
    return series[series.index <= IS_END], series[series.index >= OOS_START]

btc_ret_full = ret['BTC']

# ─── BTC Buy-and-Hold Benchmark ──────────────────────────────────────────────

bnh_pos = pd.Series(1.0, index=btc_ret_full.index)
bnh = backtest(bnh_pos, btc_ret_full, fee=0.0004, name="BTC Buy-and-Hold")

# ─── Strategy A: DXY Inverse Signal ─────────────────────────────────────────

pos_A = mvrv_pos.copy()
# DXY slope > 0 → reduce position × 0.5
pos_A[dxy_slope > 0] = mvrv_pos[dxy_slope > 0] * 0.5
pos_A = pos_A.clip(0, 1)
strat_A = backtest(pos_A, btc_ret_full, fee=0.0004, name="A: DXY Inverse + MVRV")

# ─── Strategy B: VIX Panic Protection ────────────────────────────────────────

pos_B = mvrv_pos.copy()
# VIX > 30 and rising (5d avg above prior 5d avg) → 20%
vix_rise = (vix_px.rolling(5).mean() > vix_px.rolling(5).mean().shift(5)) & (vix_px > 30)
vix_caution = (vix_px >= 20) & (vix_px <= 30)

pos_B[vix_rise]    = 0.20
pos_B[vix_caution] = mvrv_pos[vix_caution] * 0.7
pos_B = pos_B.clip(0, 1)
strat_B = backtest(pos_B, btc_ret_full, fee=0.0004, name="B: VIX Panic + MVRV")

# ─── Strategy C: SPX Trend (2020+) + MVRV ───────────────────────────────────

pos_C = mvrv_pos.copy()
spx_below_ema200 = spx_px < spx_ema200
# Only apply SPX filter from 2020 onwards
post2020_idx = pos_C.index >= pd.Timestamp("2020-01-01", tz='UTC')
pos_C[post2020_idx & spx_below_ema200] = (
    mvrv_pos[post2020_idx & spx_below_ema200].clip(0, 0.40)
)
pos_C = pos_C.clip(0, 1)
strat_C = backtest(pos_C, btc_ret_full, fee=0.0004, name="C: SPX Trend (2020+) + MVRV")

# ─── Strategy D: Multi-Signal Macro Score × MVRV ────────────────────────────

# Macro score: sum of signals (each -1 to +1 normalized)
# DXY signal: -1 if slope > 0 (bearish), +1 if slope < 0
dxy_sig = np.where(dxy_slope > 0, -1.0, 1.0)
# VIX signal: -1 if >30, -0.3 if 20-30, +1 if <20
vix_sig = np.where(vix_px > 30, -1.0, np.where(vix_px > 20, -0.3, 1.0))
# SPX signal: +1 if > EMA200, -1 if < (only post-2020)
spx_sig_arr = np.where(spx_px > spx_ema200, 1.0, -1.0)
spx_sig = pd.Series(spx_sig_arr, index=spx_px.index)
# Pre-2020: SPX signal is neutral (0)
spx_sig[spx_sig.index < pd.Timestamp("2020-01-01", tz='UTC')] = 0.0

dxy_sig_s = pd.Series(dxy_sig, index=dxy_slope.index)
vix_sig_s = pd.Series(vix_sig, index=vix_px.index)

# Macro score: average of active signals, normalized 0-1
macro_score_raw = (dxy_sig_s + vix_sig_s + spx_sig) / 3  # -1 to +1
macro_score_01  = (macro_score_raw + 1) / 2               # 0 to 1

# Final position = macro_score_01 × mvrv_pos
pos_D = (macro_score_01 * mvrv_pos).clip(0, 1)
strat_D = backtest(pos_D, btc_ret_full, fee=0.0004, name="D: Multi-Signal Macro × MVRV")

# ─── Strategy E: Hybrid (best of A + B + VIX floor) ─────────────────────────

pos_E = pd.concat([pos_A, pos_B], axis=1).min(axis=1)  # more conservative
strat_E = backtest(pos_E, btc_ret_full, fee=0.0004, name="E: Conservative (A∩B)")

# ─── Print Results ────────────────────────────────────────────────────────────

print("\n=== Full Period (2016-2026) ===")
for r in [bnh, strat_A, strat_B, strat_C, strat_D, strat_E]:
    print_stats(r)

# IS / OOS breakdown
print("\n=== In-Sample (2016-2020) ===")
for strat in [bnh, strat_A, strat_B, strat_C, strat_D, strat_E]:
    pos_is, _ = split(
        pd.Series(1.0, index=btc_ret_full.index) if strat['name'] == "BTC Buy-and-Hold"
        else (pos_A if "A:" in strat['name'] else
              pos_B if "B:" in strat['name'] else
              pos_C if "C:" in strat['name'] else
              pos_D if "D:" in strat['name'] else pos_E)
    )
    btc_is, _ = split(btc_ret_full)
    r = backtest(pos_is, btc_is, fee=0.0004, name=strat['name'])
    print_stats(r)

print("\n=== Out-of-Sample (2021-2026) ===")
for strat_pos, name in [(bnh_pos, "BTC Buy-and-Hold"), (pos_A, "A: DXY Inverse + MVRV"),
                         (pos_B, "B: VIX Panic + MVRV"), (pos_C, "C: SPX Trend (2020+) + MVRV"),
                         (pos_D, "D: Multi-Signal Macro × MVRV"), (pos_E, "E: Conservative (A∩B)")]:
    _, pos_oos = split(strat_pos)
    _, btc_oos = split(btc_ret_full)
    r = backtest(pos_oos, btc_oos, fee=0.0004, name=name)
    print_stats(r)

# ─── Collect results for report ──────────────────────────────────────────────

all_strategies = [
    (bnh_pos, "BTC Buy-and-Hold"),
    (pos_A, "A: DXY Inverse + MVRV"),
    (pos_B, "B: VIX Panic + MVRV"),
    (pos_C, "C: SPX Trend (2020+) + MVRV"),
    (pos_D, "D: Multi-Signal Macro × MVRV"),
    (pos_E, "E: Conservative (A∩B)"),
]

full_results = {}
is_results   = {}
oos_results  = {}
for pos, name in all_strategies:
    full_results[name] = backtest(pos, btc_ret_full, fee=0.0004, name=name)
    pos_is, pos_oos = split(pos)
    btc_is, btc_oos = split(btc_ret_full)
    is_results[name]  = backtest(pos_is,  btc_is,  fee=0.0004, name=name)
    oos_results[name] = backtest(pos_oos, btc_oos, fee=0.0004, name=name)

# ─── Visualization 1: BTC + DXY + VIX Triple Axis ────────────────────────────

print("\n=== Generating Charts ===")

fig, ax1 = plt.subplots(figsize=(16, 7))
fig.suptitle("BTC Price vs DXY vs VIX (2016–2026)", fontsize=14, fontweight='bold')

color_btc = '#F0B90B'  # Binance yellow
ax1.semilogy(master.index, master['BTC'], color=color_btc, linewidth=1.5, label='BTC (log scale)')
ax1.set_ylabel('BTC Price (USD, log)', color=color_btc)
ax1.tick_params(axis='y', labelcolor=color_btc)

ax2 = ax1.twinx()
ax2.plot(master.index, master['DXY'], color='#2196F3', linewidth=1.2, alpha=0.8, label='DXY')
ax2.set_ylabel('DXY', color='#2196F3')
ax2.tick_params(axis='y', labelcolor='#2196F3')

ax3 = ax1.twinx()
ax3.spines['right'].set_position(('outward', 60))
ax3.plot(master.index, master['VIX'], color='#E53935', linewidth=0.9, alpha=0.7, label='VIX')
ax3.axhline(30, color='#E53935', linestyle='--', alpha=0.4, linewidth=0.8, label='VIX=30')
ax3.axhline(20, color='orange', linestyle='--', alpha=0.4, linewidth=0.8, label='VIX=20')
ax3.set_ylabel('VIX', color='#E53935')
ax3.tick_params(axis='y', labelcolor='#E53935')

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
lines3, labels3 = ax3.get_legend_handles_labels()
ax1.legend(lines1+lines2+lines3, labels1+labels2+labels3, loc='upper left', fontsize=9)
ax1.set_xlabel('Date')
ax1.grid(True, alpha=0.2)
plt.tight_layout()
plt.savefig('/root/.openclaw/workspace/openclaw-media/btc_dxy_vix_chart.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved btc_dxy_vix_chart.png")

# ─── Visualization 2: Strategy Equity Curves ─────────────────────────────────

fig, axes = plt.subplots(2, 1, figsize=(16, 12))

ax = axes[0]
ax.set_title("Strategy Equity Curves — Full Period (2016–2026)", fontsize=13, fontweight='bold')
colors = ['#999999', '#F0B90B', '#2196F3', '#4CAF50', '#E91E63', '#9C27B0']
for (pos, name), c in zip(all_strategies, colors):
    r = full_results[name]
    sharpe = r['sharpe']
    maxdd  = r['max_dd'] * 100
    ax.plot(r['cumret'].index, r['cumret'], label=f"{name} (S={sharpe:.2f}, DD={maxdd:.0f}%)", linewidth=1.4, color=c)
ax.set_ylabel('Cumulative Return')
ax.legend(fontsize=8)
ax.grid(True, alpha=0.2)
ax.set_yscale('log')

# Drawdown chart
ax2 = axes[1]
ax2.set_title("Drawdown Comparison", fontsize=13, fontweight='bold')
for (pos, name), c in zip(all_strategies, colors):
    r = full_results[name]
    ax2.plot(r['drawdown'].index, r['drawdown'] * 100, label=name, linewidth=1.0, color=c, alpha=0.8)
ax2.axhline(-20, color='red', linestyle='--', alpha=0.5, linewidth=1, label='-20% threshold')
ax2.set_ylabel('Drawdown (%)')
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.2)
ax2.fill_between(full_results["BTC Buy-and-Hold"]['drawdown'].index,
                  full_results["BTC Buy-and-Hold"]['drawdown'] * 100, 0, alpha=0.08, color='#999999')

plt.tight_layout()
plt.savefig('/root/.openclaw/workspace/openclaw-media/strategy_equity_curves.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved strategy_equity_curves.png")

# ─── Visualization 3: Rolling Correlation BTC vs SPX/DXY/VIX ─────────────────

fig, axes = plt.subplots(3, 1, figsize=(16, 10), sharex=True)
fig.suptitle("Rolling 90-Day Correlation: BTC vs TradFi Signals", fontsize=13, fontweight='bold')

for ax_i, (col, color, title) in enumerate(zip(
    ['DXY', 'VIX', 'SPX'],
    ['#2196F3', '#E53935', '#4CAF50'],
    ['BTC vs DXY (expect negative)', 'BTC vs VIX (expect negative)', 'BTC vs SPX (expect positive post-2020)']
)):
    roll_corr = ret['BTC'].rolling(90).corr(ret[col])
    axes[ax_i].plot(roll_corr.index, roll_corr, color=color, linewidth=1.2)
    axes[ax_i].axhline(0, color='black', linestyle='-', linewidth=0.8, alpha=0.5)
    axes[ax_i].axhline(0.5, color='green', linestyle='--', linewidth=0.8, alpha=0.5)
    axes[ax_i].axhline(-0.5, color='red', linestyle='--', linewidth=0.8, alpha=0.5)
    axes[ax_i].axvline(pd.Timestamp("2020-01-01", tz='UTC'), color='orange', linestyle='--', linewidth=1.0, alpha=0.7)
    axes[ax_i].fill_between(roll_corr.index, roll_corr, 0, alpha=0.15, color=color)
    axes[ax_i].set_ylabel('Correlation')
    axes[ax_i].set_title(title, fontsize=10)
    axes[ax_i].grid(True, alpha=0.2)
    axes[ax_i].set_ylim(-1, 1)

axes[-1].set_xlabel('Date')
plt.tight_layout()
plt.savefig('/root/.openclaw/workspace/openclaw-media/rolling_correlation.png', dpi=150, bbox_inches='tight')
plt.close()
print("  Saved rolling_correlation.png")

# ─── Special Analysis: 2022 / 2024 ───────────────────────────────────────────

print("\n=== Special Period Analysis ===")

# 2022: Fed rate hike cycle (DXY surge)
y2022_pos_D = pos_D[(pos_D.index >= pd.Timestamp("2022-01-01", tz='UTC')) &
                    (pos_D.index <= pd.Timestamp("2022-12-31", tz='UTC'))]
y2022_btc   = btc_ret_full[(btc_ret_full.index >= pd.Timestamp("2022-01-01", tz='UTC')) &
                            (btc_ret_full.index <= pd.Timestamp("2022-12-31", tz='UTC'))]
r2022_D = backtest(y2022_pos_D, y2022_btc, fee=0.0004, name="D: 2022 Fed Hike")
r2022_bnh = backtest(pd.Series(1.0, index=y2022_btc.index), y2022_btc, fee=0.0004, name="BnH: 2022")
print(f"  2022 (Fed hike, DXY surge):")
print_stats(r2022_bnh)
print_stats(r2022_D)

# 2024: Rate cut expectations + Bitcoin ETF approval
y2024_start = pd.Timestamp("2024-01-01", tz='UTC')
y2024_end   = pd.Timestamp("2024-12-31", tz='UTC')
y2024_pos_D = pos_D[(pos_D.index >= y2024_start) & (pos_D.index <= y2024_end)]
y2024_btc   = btc_ret_full[(btc_ret_full.index >= y2024_start) & (btc_ret_full.index <= y2024_end)]
r2024_D   = backtest(y2024_pos_D, y2024_btc, fee=0.0004, name="D: 2024 ETF+Cuts")
r2024_bnh = backtest(pd.Series(1.0, index=y2024_btc.index), y2024_btc, fee=0.0004, name="BnH: 2024")
print(f"\n  2024 (ETF approval, rate cut expectations):")
print_stats(r2024_bnh)
print_stats(r2024_D)

# Average macro score during 2022 vs 2024
score_2022 = macro_score_01[(macro_score_01.index.year == 2022)].mean()
score_2024 = macro_score_01[(macro_score_01.index.year == 2024)].mean()
print(f"\n  Avg Macro Score 2022: {score_2022:.3f}  (0=bearish, 1=bullish)")
print(f"  Avg Macro Score 2024: {score_2024:.3f}")

# ─── Write Summary Data ───────────────────────────────────────────────────────

print("\n=== Summary Table ===")
print(f"{'Strategy':<40} {'Full_S':>7} {'Full_DD':>8} {'IS_S':>7} {'IS_DD':>8} {'OOS_S':>7} {'OOS_DD':>8}")
print("-" * 90)
for name in [n for _, n in all_strategies]:
    fr = full_results[name]
    ir = is_results[name]
    or_ = oos_results[name]
    print(f"{name:<40} {fr['sharpe']:>7.2f} {fr['max_dd']*100:>7.1f}% {ir['sharpe']:>7.2f} {ir['max_dd']*100:>7.1f}% {or_['sharpe']:>7.2f} {or_['max_dd']*100:>7.1f}%")

# ─── Pickle results for report generation ─────────────────────────────────────
import json

summary = {}
for name in [n for _, n in all_strategies]:
    fr = full_results[name]
    ir = is_results[name]
    or_ = oos_results[name]
    summary[name] = {
        'full': {'sharpe': round(fr['sharpe'],3), 'max_dd': round(fr['max_dd']*100,2), 'ann_ret': round(fr['ann_ret']*100,2), 'ann_vol': round(fr['ann_vol']*100,2)},
        'is':   {'sharpe': round(ir['sharpe'],3), 'max_dd': round(ir['max_dd']*100,2), 'ann_ret': round(ir['ann_ret']*100,2)},
        'oos':  {'sharpe': round(or_['sharpe'],3), 'max_dd': round(or_['max_dd']*100,2), 'ann_ret': round(or_['ann_ret']*100,2)},
    }

with open('/root/.openclaw/workspace/research/cross_market_summary.json', 'w') as f:
    json.dump({
        'summary': summary,
        'full_corr': {k: round(v,4) for k, v in full_corr.items()},
        'pre2020_corr': {col: round(pre['BTC'].corr(pre[col]),4) for col in ['DXY','Gold','VIX','TNX','SPX']},
        'post2020_corr': {col: round(post['BTC'].corr(post[col]),4) for col in ['DXY','Gold','VIX','TNX','SPX']},
        'macro_score_2022': round(float(score_2022),4),
        'macro_score_2024': round(float(score_2024),4),
        'special_2022': {
            'bnh': {'ann_ret': round(r2022_bnh['ann_ret']*100,2), 'max_dd': round(r2022_bnh['max_dd']*100,2)},
            'strat_D': {'ann_ret': round(r2022_D['ann_ret']*100,2), 'max_dd': round(r2022_D['max_dd']*100,2)},
        },
        'special_2024': {
            'bnh': {'ann_ret': round(r2024_bnh['ann_ret']*100,2), 'max_dd': round(r2024_bnh['max_dd']*100,2)},
            'strat_D': {'ann_ret': round(r2024_D['ann_ret']*100,2), 'max_dd': round(r2024_D['max_dd']*100,2)},
        },
    }, f, indent=2)

print("\n=== DONE — results saved to cross_market_summary.json ===")
