#!/usr/bin/env python3
"""
Funding Rate Cross-Sectional Alpha Strategy Research
"""

import requests
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timezone
import warnings
warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────────────────
START_DATE = "2023-01-01"
END_DATE   = "2024-12-31"
TAKER_FEE  = 0.0004   # 4bps
MIN_HISTORY_DAYS = 30
TOP_QUANTILE = 0.70   # top 30% = above 70th pct
BOT_QUANTILE = 0.30   # bottom 30% = below 30th pct

# Top-30 liquid USDT-perp symbols (by volume/OI, well-known)
SYMBOLS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "ADAUSDT","DOGEUSDT","AVAXUSDT","DOTUSDT","MATICUSDT",
    "LINKUSDT","LTCUSDT","UNIUSDT","ATOMUSDT","ETCUSDT",
    "BCHUSDT","APTUSDT","NEARUSDT","OPUSDT","ARBUSDT",
    "FILUSDT","SANDUSDT","MANAUSDT","AAVEUSDT","AXSUSDT",
    "FTMUSDT","INJUSDT","SUIUSDT","SHIBUSDT","PEPEUSDT"
]

BASE = "https://fapi.binance.com"

def ms_to_dt(ms):
    return datetime.fromtimestamp(ms/1000, tz=timezone.utc)

def dt_to_ms(dt_str):
    dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def fetch_funding_rates(symbol):
    """Fetch all funding rate records for a symbol in the date range."""
    start_ms = dt_to_ms(START_DATE)
    end_ms   = dt_to_ms(END_DATE) + 86400000  # include end date
    all_records = []
    url = f"{BASE}/fapi/v1/fundingRate"
    cur = start_ms
    while cur < end_ms:
        params = {"symbol": symbol, "startTime": cur, "endTime": end_ms, "limit": 1000}
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"  ERROR fetching funding for {symbol}: {e}")
            break
        if not data or not isinstance(data, list):
            break
        all_records.extend(data)
        if len(data) < 1000:
            break
        cur = data[-1]["fundingTime"] + 1
        time.sleep(0.05)
    return all_records

def fetch_daily_klines(symbol):
    """Fetch daily OHLCV klines for a symbol."""
    start_ms = dt_to_ms(START_DATE)
    end_ms   = dt_to_ms(END_DATE) + 86400000
    all_klines = []
    url = f"{BASE}/fapi/v1/klines"
    cur = start_ms
    while cur < end_ms:
        params = {"symbol": symbol, "interval": "1d", "startTime": cur, "endTime": end_ms, "limit": 1500}
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"  ERROR fetching klines for {symbol}: {e}")
            break
        if not data or not isinstance(data, list):
            break
        all_klines.extend(data)
        if len(data) < 1500:
            break
        cur = data[-1][0] + 86400000
        time.sleep(0.05)
    return all_klines

# ── Data Collection ─────────────────────────────────────────────────────────────
print("=" * 60)
print("Fetching data for", len(SYMBOLS), "symbols...")
print("=" * 60)

funding_data = {}
price_data = {}

for sym in SYMBOLS:
    print(f"  {sym}...", end=" ", flush=True)
    fr = fetch_funding_rates(sym)
    kl = fetch_daily_klines(sym)
    
    if not fr or not kl:
        print("SKIP (no data)")
        continue
    
    # Build funding DataFrame
    df_f = pd.DataFrame(fr)
    df_f["fundingTime"] = pd.to_datetime(df_f["fundingTime"], unit="ms", utc=True)
    df_f["fundingRate"] = df_f["fundingRate"].astype(float)
    df_f = df_f.sort_values("fundingTime").drop_duplicates("fundingTime")
    
    # Build price DataFrame
    df_p = pd.DataFrame(kl, columns=["open_time","open","high","low","close","volume",
                                      "close_time","quote_vol","trades","taker_base","taker_quote","ignore"])
    df_p["date"] = pd.to_datetime(df_p["open_time"], unit="ms", utc=True).dt.normalize()
    df_p["close"] = df_p["close"].astype(float)
    df_p = df_p[["date","close"]].drop_duplicates("date").sort_values("date").set_index("date")
    
    # Filter date range
    df_f = df_f[(df_f["fundingTime"] >= pd.Timestamp(START_DATE, tz="UTC")) &
                (df_f["fundingTime"] <= pd.Timestamp(END_DATE, tz="UTC") + pd.Timedelta(days=1))]
    
    days_covered = (df_f["fundingTime"].max() - df_f["fundingTime"].min()).days
    if days_covered < MIN_HISTORY_DAYS:
        print(f"SKIP ({days_covered} days < {MIN_HISTORY_DAYS})")
        continue
    
    funding_data[sym] = df_f.set_index("fundingTime")["fundingRate"]
    price_data[sym] = df_p["close"]
    print(f"OK ({len(df_f)} funding records, {len(df_p)} daily bars)")
    time.sleep(0.1)

print(f"\nUniverse: {len(funding_data)} symbols passed filter")
valid_symbols = list(funding_data.keys())

# ── Build Cross-Sectional Signal ─────────────────────────────────────────────────
print("\nBuilding cross-sectional funding rate signals...")

# Combine funding rates into a wide panel
all_funding_times = sorted(set().union(*[s.index for s in funding_data.values()]))
funding_panel = pd.DataFrame({sym: funding_data[sym] for sym in valid_symbols})
funding_panel = funding_panel.sort_index()

# Combine prices
price_panel = pd.DataFrame({sym: price_data[sym] for sym in valid_symbols})
price_panel = price_panel.sort_index()

# Compute cross-sectional z-score at each funding timestamp
def cs_zscore(row):
    vals = row.dropna()
    if len(vals) < 3:
        return pd.Series(np.nan, index=row.index)
    mu  = vals.mean()
    std = vals.std()
    if std == 0:
        return pd.Series(0.0, index=row.index)
    return (row - mu) / std

funding_zscore = funding_panel.apply(cs_zscore, axis=1)
# Signal: negative of z-score (high funding → short; low/negative funding → long)
signal_panel = -1 * funding_zscore

print(f"Signal panel shape: {signal_panel.shape}")

# ── Backtest ──────────────────────────────────────────────────────────────────────
print("\nRunning backtest...")

# Resample signals to daily (take the last signal of each day)
# Funding times: 00:00, 08:00, 16:00 UTC → we use end-of-day signal for next day's position
signal_daily = signal_panel.resample("1D").last()
signal_daily.index = signal_daily.index.normalize()

# Align price panel to same dates
dates = sorted(set(signal_daily.index) & set(price_panel.index))
signal_daily = signal_daily.loc[dates]
price_aligned = price_panel.loc[dates]

# Daily returns (forward-looking: position entered today at close, exited tomorrow at close)
daily_returns = price_aligned.pct_change().shift(-1)  # tomorrow's return

pnl_list = []
trade_counts = []
date_range = signal_daily.index[:-1]  # exclude last day (no forward return)

for dt in date_range:
    sig  = signal_daily.loc[dt].dropna()
    rets = daily_returns.loc[dt].dropna()
    
    common = sig.index.intersection(rets.index)
    if len(common) < 6:
        continue
    
    sig_c  = sig[common]
    rets_c = rets[common]
    
    # Long top 30%, Short bottom 30%
    q_hi = sig_c.quantile(TOP_QUANTILE)
    q_lo = sig_c.quantile(BOT_QUANTILE)
    
    longs  = sig_c[sig_c >= q_hi]
    shorts = sig_c[sig_c <= q_lo]
    
    n_longs  = len(longs)
    n_shorts = len(shorts)
    
    if n_longs == 0 or n_shorts == 0:
        continue
    
    # Equal-weight
    long_ret  = rets_c[longs.index].mean()
    short_ret = rets_c[shorts.index].mean()
    
    # Long-short portfolio return (gross)
    gross_pnl = 0.5 * long_ret + 0.5 * (-short_ret)
    
    # Fee: taker in + taker out for each leg = 2 * 2 * fee (round-trip, both legs)
    # Actually: 2 legs × 2 trips × fee = 4 × fee... but standard: entry + exit per side = 2 × fee × 2 sides
    fee = 4 * TAKER_FEE  # entry+exit for long + entry+exit for short
    net_pnl = gross_pnl - fee
    
    pnl_list.append({
        "date": dt,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "long_ret": long_ret,
        "short_ret": short_ret,
        "n_longs": n_longs,
        "n_shorts": n_shorts,
        "n_assets": len(common)
    })

pnl_df = pd.DataFrame(pnl_list).set_index("date")
print(f"Backtest days: {len(pnl_df)}")

# ── Performance Metrics ───────────────────────────────────────────────────────────
def calc_sharpe(returns, annual_factor=252):
    if returns.std() == 0:
        return 0
    return returns.mean() / returns.std() * np.sqrt(annual_factor)

def calc_max_dd(returns):
    cum = (1 + returns).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max
    return dd.min()

def calc_annual_return(returns, annual_factor=252):
    n = len(returns)
    if n == 0:
        return 0
    total = (1 + returns).prod()
    return total ** (annual_factor / n) - 1

net_returns = pnl_df["net_pnl"]

sharpe      = calc_sharpe(net_returns)
ann_ret     = calc_annual_return(net_returns)
max_dd      = calc_max_dd(net_returns)
win_rate    = (net_returns > 0).mean()
n_trades    = len(net_returns) * (pnl_df["n_longs"].mean() + pnl_df["n_shorts"].mean())
total_ret   = (1 + net_returns).prod() - 1

print(f"\n{'='*60}")
print(f"PERFORMANCE SUMMARY")
print(f"{'='*60}")
print(f"Sharpe Ratio:      {sharpe:.3f}")
print(f"Annual Return:     {ann_ret*100:.2f}%")
print(f"Total Return:      {total_ret*100:.2f}%")
print(f"Max Drawdown:      {max_dd*100:.2f}%")
print(f"Win Rate:          {win_rate*100:.2f}%")
print(f"Avg daily trades:  {pnl_df['n_longs'].mean() + pnl_df['n_shorts'].mean():.1f}")

# ── Signal Strength Analysis ───────────────────────────────────────────────────
print("\nSignal Strength Analysis (by |funding| threshold)...")

thresholds = [0.0001, 0.0005, 0.001]  # 0.01%, 0.05%, 0.1%
strength_results = {}

for thr in thresholds:
    sub_pnl = []
    for dt in date_range:
        sig  = signal_daily.loc[dt].dropna()
        rets = daily_returns.loc[dt].dropna()
        common = sig.index.intersection(rets.index)
        if len(common) < 6:
            continue
        
        # Only use assets where |funding| > threshold
        raw_funding = funding_panel.loc[dt] if dt in funding_panel.index else pd.Series()
        if raw_funding.empty:
            # find nearest
            candidates = funding_panel.index[funding_panel.index <= dt]
            if len(candidates) == 0:
                continue
            raw_funding = funding_panel.iloc[funding_panel.index.get_loc(candidates[-1])]
        
        high_abs = raw_funding[raw_funding.abs() >= thr].index
        filtered = common.intersection(high_abs)
        
        if len(filtered) < 4:
            continue
        
        sig_f  = sig[filtered]
        rets_f = rets[filtered]
        
        q_hi = sig_f.quantile(TOP_QUANTILE)
        q_lo = sig_f.quantile(BOT_QUANTILE)
        longs  = sig_f[sig_f >= q_hi]
        shorts = sig_f[sig_f <= q_lo]
        
        if len(longs) == 0 or len(shorts) == 0:
            continue
        
        gross = 0.5 * rets_f[longs.index].mean() + 0.5 * (-rets_f[shorts.index].mean())
        net   = gross - 4 * TAKER_FEE
        sub_pnl.append(net)
    
    if sub_pnl:
        sp = pd.Series(sub_pnl)
        strength_results[f"|f|>={thr*100:.2f}%"] = {
            "sharpe": calc_sharpe(sp),
            "ann_ret": calc_annual_return(sp) * 100,
            "max_dd": calc_max_dd(sp) * 100,
            "win_rate": (sp > 0).mean() * 100,
            "n_days": len(sp)
        }
        print(f"  {thr*100:.2f}%: Sharpe={strength_results[f'|f|>={thr*100:.2f}%']['sharpe']:.3f}, AnnRet={strength_results[f'|f|>={thr*100:.2f}%']['ann_ret']:.2f}%")

# ── Regime Analysis ───────────────────────────────────────────────────────────────
print("\nRegime Analysis...")

# Use BTC as market proxy
btc_prices = price_panel.get("BTCUSDT")
if btc_prices is not None:
    btc_ma200 = btc_prices.rolling(200).mean()
    bull_dates = btc_prices.index[btc_prices > btc_ma200]
    bear_dates = btc_prices.index[btc_prices <= btc_ma200]
    
    bull_ret = net_returns[net_returns.index.isin(bull_dates)]
    bear_ret = net_returns[net_returns.index.isin(bear_dates)]
    
    regime_results = {
        "bull": {
            "sharpe": calc_sharpe(bull_ret) if len(bull_ret) > 10 else None,
            "ann_ret": calc_annual_return(bull_ret) * 100 if len(bull_ret) > 10 else None,
            "win_rate": (bull_ret > 0).mean() * 100 if len(bull_ret) > 0 else None,
            "n_days": len(bull_ret)
        },
        "bear": {
            "sharpe": calc_sharpe(bear_ret) if len(bear_ret) > 10 else None,
            "ann_ret": calc_annual_return(bear_ret) * 100 if len(bear_ret) > 10 else None,
            "win_rate": (bear_ret > 0).mean() * 100 if len(bear_ret) > 0 else None,
            "n_days": len(bear_ret)
        }
    }
    print(f"  Bull market days: {len(bull_ret)}, Bear market days: {len(bear_ret)}")
    if len(bull_ret) > 10:
        print(f"  Bull Sharpe: {regime_results['bull']['sharpe']:.3f}, AnnRet: {regime_results['bull']['ann_ret']:.2f}%")
    if len(bear_ret) > 10:
        print(f"  Bear Sharpe: {regime_results['bear']['sharpe']:.3f}, AnnRet: {regime_results['bear']['ann_ret']:.2f}%")
else:
    regime_results = {}
    print("  BTC data not available for regime analysis")

# ── Monthly Returns ───────────────────────────────────────────────────────────────
monthly_ret = net_returns.resample("ME").apply(lambda x: (1+x).prod()-1)

# ── Save Results ──────────────────────────────────────────────────────────────────
results = {
    "meta": {
        "strategy": "Funding Rate Cross-Sectional Alpha",
        "universe": valid_symbols,
        "n_symbols": len(valid_symbols),
        "start_date": START_DATE,
        "end_date": END_DATE,
        "taker_fee_bps": TAKER_FEE * 10000,
        "long_quantile_threshold": f"top {(1-TOP_QUANTILE)*100:.0f}%",
        "short_quantile_threshold": f"bottom {BOT_QUANTILE*100:.0f}%"
    },
    "performance": {
        "sharpe_ratio": round(sharpe, 4),
        "annual_return_pct": round(ann_ret * 100, 4),
        "total_return_pct": round(total_ret * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "win_rate_pct": round(win_rate * 100, 4),
        "total_backtest_days": len(net_returns),
        "avg_daily_positions": round(float(pnl_df["n_longs"].mean() + pnl_df["n_shorts"].mean()), 2)
    },
    "monthly_returns": {str(k.date()): round(v*100, 4) for k, v in monthly_ret.items()},
    "signal_strength_analysis": strength_results,
    "regime_analysis": regime_results,
    "daily_pnl_sample": pnl_df.head(20).reset_index().to_dict(orient="records") if len(pnl_df) > 0 else []
}

# Convert dates in daily_pnl_sample
for row in results["daily_pnl_sample"]:
    row["date"] = str(row["date"])

out_path = "/root/.openclaw/workspace/research/strategy-alpha/funding-cs/results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")

# Store results in a variable for report generation
print("\nAll computations complete.")
print(f"FINAL: Sharpe={sharpe:.3f}, AnnRet={ann_ret*100:.2f}%, MaxDD={max_dd*100:.2f}%, WinRate={win_rate*100:.2f}%")
print(f"REGIMES: {json.dumps({k: {kk: round(vv,3) if isinstance(vv, float) else vv for kk,vv in v.items()} for k,v in regime_results.items()}, default=str)}")
print(f"STRENGTH: {json.dumps({k: {kk: round(vv,3) if isinstance(vv, float) else vv for kk,vv in v.items()} for k,v in strength_results.items()}, default=str)}")
print(f"SYMBOLS: {valid_symbols}")
print(f"MONTHLY_SAMPLE: {list(monthly_ret.items())[:6]}")
