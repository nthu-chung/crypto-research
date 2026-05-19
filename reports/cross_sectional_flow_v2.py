#!/usr/bin/env python3
"""
Cross-Sectional Flow Signal Analysis v2 — fast vectorized
Binance 1h K-line data, 2023-01-01 ~ 2024-12-31
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import os
from scipy.stats import spearmanr
import warnings
warnings.filterwarnings('ignore')

OUTPUT_FILE = "/root/.openclaw/workspace/research/agentA_cross_sectional.txt"
DATA_DIR    = "/root/.openclaw/workspace/research/kline_cache"
os.makedirs(DATA_DIR, exist_ok=True)

STABLE_COINS = {
    'USDTUSDT','BUSDUSDT','USDCUSDT','DAIUSDT','TUSDUSDT','USDPUSDT',
    'FDUSDUSDT','EURUSDT','GBPUSDT','AUDUSDT','USTUSDT','USTCUSDT','LUNAUSDT'
}
STABLE_SUBSTRINGS = ['USDC','BUSD','TUSD','USDP','DAI','FDUSD','UST1']

def log(msg): print(msg, flush=True)

# ─── Step 1 ───────────────────────────────────────────────────────────────────
log("=== Step 1: Fetching 24hr ticker ===")
r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=30)
tickers = r.json()

usdt_pairs = [
    t for t in tickers
    if t['symbol'].endswith('USDT')
    and float(t['quoteVolume']) > 0
    and t['symbol'] not in STABLE_COINS
    and not any(s in t['symbol'] for s in STABLE_SUBSTRINGS)
]
usdt_pairs.sort(key=lambda x: float(x['quoteVolume']), reverse=True)
symbols = [t['symbol'] for t in usdt_pairs[:50]]
log(f"Top 50: {symbols}")

# ─── Step 2 ───────────────────────────────────────────────────────────────────
log("\n=== Step 2: Downloading klines (cached) ===")

START_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS   = int(datetime(2024, 12, 31, 23, 0, tzinfo=timezone.utc).timestamp() * 1000)

def download_klines(symbol):
    cache = os.path.join(DATA_DIR, f"{symbol}_1h.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    all_rows, cur = [], START_MS
    while cur < END_MS:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={symbol}&interval=1h&startTime={cur}&endTime={END_MS}&limit=1000")
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200: break
        data = resp.json()
        if not data: break
        all_rows.extend(data)
        last_ts = data[-1][0]
        if last_ts >= END_MS or len(data) < 1000: break
        cur = last_ts + 3_600_000
        time.sleep(0.05)
    if not all_rows: return None
    cols = ['open_time','open','high','low','close','volume',
            'close_time','quote_vol','num_trades',
            'taker_buy_base','taker_buy_quote','ignore']
    df = pd.DataFrame(all_rows, columns=cols)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    for c in ['open','high','low','close','volume','taker_buy_base','quote_vol']:
        df[c] = df[c].astype(float)
    df = df.drop_duplicates('open_time').sort_values('open_time').reset_index(drop=True)
    df.to_parquet(cache)
    time.sleep(0.05)
    return df

symbol_data, failed = {}, []
for i, sym in enumerate(symbols):
    log(f"  [{i+1}/50] {sym}")
    df = download_klines(sym)
    if df is not None and len(df) > 1000:
        symbol_data[sym] = df
    else:
        failed.append(sym)
        log("    -> skip")

valid_symbols = list(symbol_data.keys())
log(f"Valid: {len(valid_symbols)}  Failed: {failed}")

# ─── Step 3: Flow signals ─────────────────────────────────────────────────────
log("\n=== Step 3: Flow signals ===")

close_dict, flowz_dict = {}, {}
for sym, df in symbol_data.items():
    d = df.set_index('open_time').copy()
    d['taker_sell'] = d['volume'] - d['taker_buy_base']
    d['flow_raw'] = np.where(d['volume'] > 0,
                             (d['taker_buy_base'] - d['taker_sell']) / d['volume'], 0.0)
    roll = d['flow_raw'].rolling(24, min_periods=12)
    d['flow_z'] = (d['flow_raw'] - roll.mean()) / (roll.std() + 1e-9)
    close_dict[sym] = d['close']
    flowz_dict[sym] = d['flow_z']

panel_close = pd.DataFrame(close_dict)
panel_flowz = pd.DataFrame(flowz_dict)
common_idx  = panel_close.dropna(how='all').index
panel_close = panel_close.reindex(common_idx)
panel_flowz = panel_flowz.reindex(common_idx)
log(f"Panel: {panel_close.shape}")

# ─── Step 4: Cross-Sectional IC ──────────────────────────────────────────────
log("\n=== Step 4: Cross-Sectional IC ===")

ret_1h = panel_close.pct_change(1).shift(-1)  # forward 1h return

# Vectorized cross-sectional Spearman IC
# Rank each row (time axis) across symbols
def xsec_ic_series(signal_df, return_df):
    sig_rank = signal_df.rank(axis=1)
    ret_rank = return_df.rank(axis=1)
    # Pearson on ranks = Spearman
    n = sig_rank.notna().sum(axis=1)
    # Demean
    s_dm = sig_rank.sub(sig_rank.mean(axis=1), axis=0)
    r_dm = ret_rank.sub(ret_rank.mean(axis=1), axis=0)
    cov  = (s_dm * r_dm).sum(axis=1)
    ss   = np.sqrt((s_dm**2).sum(axis=1) * (r_dm**2).sum(axis=1))
    ic   = cov / (ss + 1e-12)
    ic[n < 10] = np.nan
    return ic

ic_series = xsec_ic_series(panel_flowz, ret_1h).dropna()
ic_mean = ic_series.mean()
ic_std  = ic_series.std()
icir    = ic_mean / (ic_std + 1e-9)
log(f"IC mean={ic_mean:.4f}  std={ic_std:.4f}  ICIR={icir:.4f}")

# Per-symbol IC: single Spearman over full period per symbol
sym_ic_rows = []
for sym in valid_symbols:
    fz  = panel_flowz[sym].dropna()
    ret = ret_1h[sym].reindex(fz.index).dropna()
    idx = fz.index.intersection(ret.index)
    if len(idx) < 100:
        sym_ic_rows.append({'symbol': sym, 'ic_mean': np.nan, 'ic_std': np.nan, 'icir': np.nan})
        continue
    # Monthly rolling IC to get distribution
    monthly_ics = []
    fz_a, ret_a = fz[idx].values, ret[idx].values
    # Stride monthly (720 bars = 30d × 24h)
    step = 720
    for start in range(0, len(fz_a) - step, step // 2):
        chunk_fz  = fz_a[start:start+step]
        chunk_ret = ret_a[start:start+step]
        mask = np.isfinite(chunk_fz) & np.isfinite(chunk_ret)
        if mask.sum() < 50: continue
        ic_val, _ = spearmanr(chunk_fz[mask], chunk_ret[mask])
        monthly_ics.append(ic_val)
    arr = np.array(monthly_ics)
    m   = arr.mean() if len(arr) else np.nan
    s   = arr.std()  if len(arr) > 1 else np.nan
    ir  = m / (s + 1e-9) if (len(arr) > 1 and not np.isnan(s)) else np.nan
    sym_ic_rows.append({'symbol': sym, 'ic_mean': m, 'ic_std': s if not np.isnan(s) else 0, 'icir': ir})

sym_ic_df = pd.DataFrame(sym_ic_rows).set_index('symbol')
sym_ic_df = sym_ic_df.sort_values('icir', ascending=False)
top10_ic = sym_ic_df.dropna().head(10)

# ─── Step 5: Long-Short Backtest ──────────────────────────────────────────────
log("\n=== Step 5: L/S Backtest ===")

TC = 0.001
min_valid = max(5, len(valid_symbols) // 5)
valid_rows = panel_flowz.notna().sum(axis=1) >= min_valid
sig = panel_flowz[valid_rows]
ret = ret_1h[valid_rows]

def quintile_rets(sig_df, ret_df, n=5):
    """Compute equal-weight bucket returns for each quintile."""
    results = {f'Q{i+1}': [] for i in range(n)}
    for t in range(len(sig_df)):
        sig_row = sig_df.iloc[t]
        ret_row = ret_df.iloc[t]
        mask = sig_row.notna() & ret_row.notna()
        if mask.sum() < n * 2:
            for q in range(n): results[f'Q{q+1}'].append(np.nan)
            continue
        try:
            labels = pd.qcut(sig_row[mask], n, labels=False, duplicates='drop')
        except Exception:
            for q in range(n): results[f'Q{q+1}'].append(np.nan)
            continue
        for q in range(n):
            members = ret_row[mask][labels == q]
            results[f'Q{q+1}'].append(members.mean() if len(members) > 0 else np.nan)
    return pd.DataFrame(results, index=sig_df.index)

bucket_df = quintile_rets(sig, ret)

long_ret  = bucket_df['Q1']                     # lowest flow_z → most sell pressure → long
short_ret = bucket_df['Q5']                     # highest flow_z → most buy pressure → short
long_net  = long_ret - TC
short_net = (-short_ret) - TC
ls_net    = (long_net + short_net) / 2.0

def sharpe(s, annualize=8760):
    r = s.dropna()
    return r.mean() / (r.std() + 1e-12) * np.sqrt(annualize)

def ann_ret(s, annualize=8760):
    return s.dropna().mean() * annualize

def max_dd(s):
    r = s.dropna()
    cum = (1 + r).cumprod()
    return ((cum - cum.cummax()) / cum.cummax()).min()

perf = {
    'Long (Q1)':   {'Sharpe': sharpe(long_net),  'AnnRet': ann_ret(long_net),  'MaxDD': max_dd(long_net)},
    'Short (Q5)':  {'Sharpe': sharpe(short_net), 'AnnRet': ann_ret(short_net), 'MaxDD': max_dd(short_net)},
    'L/S Combined':{'Sharpe': sharpe(ls_net),    'AnnRet': ann_ret(ls_net),    'MaxDD': max_dd(ls_net)},
}

# ─── Write Output ──────────────────────────────────────────────────────────────
log("\n=== Writing output ===")

lines = []
SEP = "=" * 70
lines += [SEP,
          "CROSS-SECTIONAL FLOW SIGNAL ANALYSIS — Binance 1h K-line",
          "Period: 2023-01-01 ~ 2024-12-31",
          f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
          SEP]

lines += ["\n─── 入選幣種清單 (Final Symbol Universe) ───"]
for i, s in enumerate(valid_symbols, 1):
    lines.append(f"  {i:2d}. {s}")
lines.append(f"\n總計：{len(valid_symbols)} 個幣種 (原始50，{len(failed)}個因無歷史數據排除)")
if failed:
    lines.append(f"  排除：{', '.join(failed)}")

lines += ["\n─── 截面 IC 統計 (Cross-Sectional IC — All Symbols) ───",
          f"  Overall IC mean : {ic_mean:+.4f}",
          f"  Overall IC std  : {ic_std:.4f}",
          f"  Overall ICIR    : {icir:+.4f}",
          f"  (IC < 0 → flow_z 與未來報酬負相關，逆勢信號有效性待確認)"]

lines += ["\n─── 分幣種 ICIR 排名 (Per-Symbol Monthly IC → ICIR) ───",
          f"  {'Symbol':<15} {'IC_mean':>9} {'IC_std':>8} {'ICIR':>8}",
          "  " + "-" * 44]
for sym, row in sym_ic_df.iterrows():
    ic_m = f"{row['ic_mean']:+.4f}" if not np.isnan(row['ic_mean']) else "   NaN"
    ic_s = f"{row['ic_std']:.4f}"   if not np.isnan(row['ic_std'])  else "   NaN"
    ic_r = f"{row['icir']:+.4f}"    if not np.isnan(row['icir'])    else "   NaN"
    lines.append(f"  {sym:<15} {ic_m:>9} {ic_s:>8} {ic_r:>8}")

lines += ["\n─── 表現最好前10幣種 (Top 10 by ICIR) ───",
          f"  {'Symbol':<15} {'IC_mean':>9} {'IC_std':>8} {'ICIR':>8}",
          "  " + "-" * 44]
for sym, row in top10_ic.iterrows():
    lines.append(f"  {sym:<15} {row['ic_mean']:+9.4f} {row['ic_std']:8.4f} {row['icir']:+8.4f}")

lines += ["\n─── 多空回測結果 (L/S Backtest, TC=0.1%/side/bar) ───",
          f"  {'Portfolio':<16} {'Sharpe':>8} {'AnnRet':>10} {'MaxDD':>8}",
          "  " + "-" * 46]
for name, m in perf.items():
    lines.append(f"  {name:<16} {m['Sharpe']:>8.3f} {m['AnnRet']:>10.2%} {m['MaxDD']:>8.2%}")

lines += ["\n─── 信號定義 ───",
          "  flow_raw = (taker_buy_base_vol - taker_sell_base_vol) / total_vol",
          "  flow_z   = 24h rolling z-score(flow_raw)  [min_periods=12]",
          "  Q1 = 最低 flow_z（賣壓最大）→ 做多（逆勢流量信號）",
          "  Q5 = 最高 flow_z（買壓最大）→ 做空（逆勢流量信號）",
          "  TC = 每 bar 每方向 0.1%（最保守情境）",
          "  AnnRet = mean_hourly_ret × 8760",
          SEP]

out = "\n".join(lines)
with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write(out)
print(out)
log(f"\n[DONE] Saved: {OUTPUT_FILE}")
