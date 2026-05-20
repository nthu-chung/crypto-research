#!/usr/bin/env python3
"""
Cross-Sectional Flow Signal Analysis
Binance 1h K-line data, 2023-01-01 ~ 2024-12-31
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import json
import os
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

OUTPUT_FILE = "/root/.openclaw/workspace/research/agentA_cross_sectional.txt"
DATA_DIR = "/root/.openclaw/workspace/research/kline_cache"
os.makedirs(DATA_DIR, exist_ok=True)

STABLE_COINS = {'USDTUSDT', 'BUSDUSDT', 'USDCUSDT', 'DAIUSDT', 'TUSDUSDT', 'USDPUSDT',
                'FDUSDUSDT', 'EURUSDT', 'GBPUSDT', 'AUDUSDT', 'USDCUSDT', 'USTUSDT',
                'USTCUSDT', 'LUNAUSDT'}

def log(msg):
    print(msg, flush=True)

# ─── Step 1: Get top-50 USDT pairs by volume ──────────────────────────────────
log("=== Step 1: Fetching 24hr ticker data ===")
r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=30)
tickers = r.json()

usdt_pairs = [
    t for t in tickers
    if t['symbol'].endswith('USDT')
    and float(t['quoteVolume']) > 0
    and t['symbol'] not in STABLE_COINS
    and not any(s in t['symbol'] for s in ['USDC', 'BUSD', 'TUSD', 'USDP', 'DAI', 'FDUSD', 'UST'])
]

# Sort by quoteVolume descending, take top 50
usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
top50 = usdt_pairs[:50]
symbols = [t['symbol'] for t in top50]
log(f"Top 50 symbols by volume: {symbols}")

# ─── Step 2: Download 1h klines 2023-01-01 ~ 2024-12-31 ──────────────────────
log("\n=== Step 2: Downloading 1h klines ===")

START_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS   = int(datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)

def download_klines(symbol, interval='1h', start_ms=START_MS, end_ms=END_MS):
    cache_file = os.path.join(DATA_DIR, f"{symbol}_{interval}.parquet")
    if os.path.exists(cache_file):
        return pd.read_parquet(cache_file)
    
    all_rows = []
    cur = start_ms
    while cur < end_ms:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={symbol}&interval={interval}&startTime={cur}&endTime={end_ms}&limit=1000")
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            log(f"  Error {resp.status_code} for {symbol}")
            break
        data = resp.json()
        if not data:
            break
        all_rows.extend(data)
        last_ts = data[-1][0]
        if last_ts >= end_ms or len(data) < 1000:
            break
        cur = last_ts + 3600_000
        time.sleep(0.05)
    
    if not all_rows:
        return None
    
    cols = ['open_time','open','high','low','close','volume',
            'close_time','quote_vol','num_trades',
            'taker_buy_base','taker_buy_quote','ignore']
    df = pd.DataFrame(all_rows, columns=cols)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    for c in ['open','high','low','close','volume','taker_buy_base','taker_buy_quote','quote_vol']:
        df[c] = df[c].astype(float)
    df = df.drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
    df.to_parquet(cache_file)
    time.sleep(0.05)
    return df

symbol_data = {}
failed = []
for i, sym in enumerate(symbols):
    log(f"  [{i+1}/50] {sym}")
    df = download_klines(sym)
    if df is not None and len(df) > 1000:
        symbol_data[sym] = df
    else:
        failed.append(sym)
        log(f"    -> FAILED or insufficient data")

log(f"\nSuccessfully loaded: {len(symbol_data)} symbols")
log(f"Failed: {failed}")

valid_symbols = list(symbol_data.keys())

# ─── Step 3: Compute flow_raw and flow_z ─────────────────────────────────────
log("\n=== Step 3: Computing Flow signals ===")

flow_dfs = {}
for sym, df in symbol_data.items():
    d = df.set_index('open_time').copy()
    d['taker_sell_base'] = d['volume'] - d['taker_buy_base']
    # Avoid division by zero
    d['flow_raw'] = np.where(d['volume'] > 0,
                             (d['taker_buy_base'] - d['taker_sell_base']) / d['volume'],
                             0.0)
    # Rolling 24h (24 bars) z-score
    roll = d['flow_raw'].rolling(24, min_periods=12)
    d['flow_z'] = (d['flow_raw'] - roll.mean()) / (roll.std() + 1e-9)
    flow_dfs[sym] = d[['close', 'flow_raw', 'flow_z']]

# Build aligned panel
panel_close = pd.DataFrame({s: flow_dfs[s]['close'] for s in valid_symbols})
panel_flowz = pd.DataFrame({s: flow_dfs[s]['flow_z'] for s in valid_symbols})

# Align to common index
common_idx = panel_close.dropna(how='all').index
panel_close = panel_close.reindex(common_idx)
panel_flowz = panel_flowz.reindex(common_idx)

log(f"Panel shape: {panel_close.shape}")

# ─── Step 4: Cross-Sectional IC Analysis ─────────────────────────────────────
log("\n=== Step 4: Cross-Sectional IC Analysis ===")

# Forward 1h return
ret_1h = panel_close.pct_change(1).shift(-1)  # shift(-1) = forward return

ICs = []
for t in range(len(panel_flowz)):
    row_fz = panel_flowz.iloc[t]
    row_ret = ret_1h.iloc[t]
    mask = row_fz.notna() & row_ret.notna()
    if mask.sum() < 10:
        ICs.append(np.nan)
        continue
    ic, _ = stats.spearmanr(row_fz[mask], row_ret[mask])
    ICs.append(ic)

ic_series = pd.Series(ICs, index=panel_flowz.index).dropna()
ic_mean = ic_series.mean()
ic_std  = ic_series.std()
icir    = ic_mean / (ic_std + 1e-9)

log(f"Overall IC mean: {ic_mean:.4f}")
log(f"Overall IC std:  {ic_std:.4f}")
log(f"Overall ICIR:    {icir:.4f}")

# Per-symbol IC
sym_ics = {}
for sym in valid_symbols:
    fz_col  = panel_flowz[sym]
    ret_col = ret_1h[sym]
    mask = fz_col.notna() & ret_col.notna()
    if mask.sum() < 100:
        sym_ics[sym] = {'ic_mean': np.nan, 'ic_std': np.nan, 'icir': np.nan}
        continue
    # Rolling yearly blocks
    sym_ic_vals = []
    for t in range(len(fz_col)):
        start = max(0, t - 23)
        fz_win  = fz_col.iloc[start:t+1]
        ret_win = ret_col.iloc[start:t+1]
        m2 = fz_win.notna() & ret_win.notna()
        if m2.sum() < 8:
            sym_ic_vals.append(np.nan)
            continue
        ic_val, _ = stats.spearmanr(fz_win[m2], ret_win[m2])
        sym_ic_vals.append(ic_val)
    sym_ic_s = pd.Series(sym_ic_vals).dropna()
    sym_ics[sym] = {
        'ic_mean': sym_ic_s.mean(),
        'ic_std': sym_ic_s.std(),
        'icir': sym_ic_s.mean() / (sym_ic_s.std() + 1e-9)
    }

sym_ic_df = pd.DataFrame(sym_ics).T
sym_ic_df = sym_ic_df.sort_values('icir', ascending=False)
top10_ic = sym_ic_df.head(10)

# ─── Step 5: Cross-Sectional Long-Short Backtest ─────────────────────────────
log("\n=== Step 5: Long-Short Backtest ===")

TC = 0.001  # 0.1% per side

# Align flow_z (signal at t) with ret at t+1
signal = panel_flowz.copy()
ret_fwd = ret_1h.copy()

# Drop rows where too many NaN
min_valid = max(5, len(valid_symbols) // 5)
valid_rows = signal.notna().sum(axis=1) >= min_valid
signal = signal[valid_rows]
ret_fwd = ret_fwd[valid_rows]

# Quintile bucketing
def bucket_returns(sig_row, ret_row, n_buckets=5):
    mask = sig_row.notna() & ret_row.notna()
    if mask.sum() < n_buckets * 2:
        return [np.nan] * n_buckets
    sig_v = sig_row[mask]
    ret_v = ret_row[mask]
    qtiles = pd.qcut(sig_v, n_buckets, labels=False, duplicates='drop')
    bucket_rets = []
    for b in range(n_buckets):
        members = ret_v[qtiles == b]
        bucket_rets.append(members.mean() if len(members) > 0 else np.nan)
    return bucket_rets

bucket_matrix = []
for t in range(len(signal)):
    brets = bucket_returns(signal.iloc[t], ret_fwd.iloc[t])
    bucket_matrix.append(brets)

bucket_df = pd.DataFrame(bucket_matrix, index=signal.index,
                          columns=[f'Q{i+1}' for i in range(5)])

# Long = Q1 (lowest flow_z = most sell pressure) — per task description
# Short = Q5 (highest flow_z = most buy pressure)
long_ret  = bucket_df['Q1']
short_ret = bucket_df['Q5']

# Transaction costs: detect rebalancing (simplified: assume rebal every bar)
# For simplicity, apply TC every bar as continuous rebalancing assumption
long_net  = long_ret  - TC
short_net = (-short_ret) - TC
ls_net    = (long_net + short_net) / 2.0

def sharpe(rets, annualize=8760):
    r = rets.dropna()
    if r.std() == 0:
        return np.nan
    return r.mean() / r.std() * np.sqrt(annualize)

def ann_ret(rets, annualize=8760):
    r = rets.dropna()
    return r.mean() * annualize

def max_dd(rets):
    r = rets.dropna()
    cum = (1 + r).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max
    return dd.min()

results = {
    'Long (Q1)':   {'Sharpe': sharpe(long_net),  'AnnRet': ann_ret(long_net),  'MaxDD': max_dd(long_net)},
    'Short (Q5)':  {'Sharpe': sharpe(short_net), 'AnnRet': ann_ret(short_net), 'MaxDD': max_dd(short_net)},
    'L/S Combined': {'Sharpe': sharpe(ls_net),   'AnnRet': ann_ret(ls_net),    'MaxDD': max_dd(ls_net)},
}

# ─── Write output ─────────────────────────────────────────────────────────────
log("\n=== Writing output ===")

lines = []
lines.append("=" * 70)
lines.append("CROSS-SECTIONAL FLOW SIGNAL ANALYSIS — Binance 1h K-line")
lines.append("Period: 2023-01-01 ~ 2024-12-31")
lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
lines.append("=" * 70)

lines.append("\n─── 入選幣種清單 (Final Symbol Universe) ───")
for i, s in enumerate(valid_symbols, 1):
    lines.append(f"  {i:2d}. {s}")

lines.append(f"\n總計：{len(valid_symbols)} 個幣種")

lines.append("\n─── 截面 IC 統計 (Cross-Sectional IC) ───")
lines.append(f"  Overall IC mean : {ic_mean:.4f}")
lines.append(f"  Overall IC std  : {ic_std:.4f}")
lines.append(f"  Overall ICIR    : {icir:.4f}")

lines.append("\n─── 分幣種 IC 統計 (Per-Symbol) — 全部 ───")
lines.append(f"  {'Symbol':<15} {'IC_mean':>8} {'IC_std':>8} {'ICIR':>8}")
lines.append(f"  {'-'*43}")
for sym, row in sym_ic_df.iterrows():
    lines.append(f"  {sym:<15} {row['ic_mean']:>8.4f} {row['ic_std']:>8.4f} {row['icir']:>8.4f}")

lines.append("\n─── 表現最好前10幣種 (Top 10 by ICIR) ───")
lines.append(f"  {'Symbol':<15} {'IC_mean':>8} {'IC_std':>8} {'ICIR':>8}")
lines.append(f"  {'-'*43}")
for sym, row in top10_ic.iterrows():
    lines.append(f"  {sym:<15} {row['ic_mean']:>8.4f} {row['ic_std']:>8.4f} {row['icir']:>8.4f}")

lines.append("\n─── 多空回測結果 (Long-Short Backtest, TC=0.1%) ───")
lines.append(f"  {'Portfolio':<15} {'Sharpe':>8} {'AnnRet':>10} {'MaxDD':>8}")
lines.append(f"  {'-'*45}")
for name, m in results.items():
    lines.append(f"  {name:<15} {m['Sharpe']:>8.3f} {m['AnnRet']:>10.2%} {m['MaxDD']:>8.2%}")

lines.append("\n─── 信號說明 ───")
lines.append("  flow_raw = (taker_buy_vol - taker_sell_vol) / total_vol")
lines.append("  flow_z   = rolling 24h z-score of flow_raw")
lines.append("  Long  = Q1 (最低 flow_z，賣壓最大) → 做多（逆勢）")
lines.append("  Short = Q5 (最高 flow_z，買壓最大) → 做空（逆勢）")
lines.append("  TC = 0.1% per side, applied every bar (conservative)")
lines.append("=" * 70)

output_text = "\n".join(lines)
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(output_text)

print(output_text)
log(f"\nOutput saved to: {OUTPUT_FILE}")
