#!/usr/bin/env python3
"""
Volatility Regime-Conditional Momentum Strategy Backtest
BTC realized vol as regime filter for cross-sectional momentum on top-20 USDT perps
"""

import json
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────
START_DATE = "2021-01-01"
END_DATE   = "2024-12-31"
BASE_URL   = "https://fapi.binance.com/fapi/v1/klines"
HOLD_DAYS  = 3
FEE_BPS    = 4 / 10000  # 4 bps per leg
TOP_SYMS   = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "ADAUSDT","DOGEUSDT","AVAXUSDT","DOTUSDT","MATICUSDT",
    "LTCUSDT","LINKUSDT","UNIUSDT","ATOMUSDT","ETCUSDT",
    "XLMUSDT","ALGOUSDT","VETUSDT","FILUSDT","TRXUSDT",
]

start_ms = int(datetime.strptime(START_DATE, "%Y-%m-%d").timestamp() * 1000)
end_ms   = int(datetime.strptime(END_DATE,   "%Y-%m-%d").timestamp() * 1000)

def fetch_klines(symbol):
    rows = []
    cur_start = start_ms
    while cur_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1d",
            "startTime": cur_start,
            "endTime": end_ms,
            "limit": 1000,
        }
        try:
            r = requests.get(BASE_URL, params=params, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            break
        if not data or isinstance(data, dict):
            break
        rows.extend(data)
        last_open = data[-1][0]
        if last_open >= end_ms or len(data) < 1000:
            break
        cur_start = last_open + 86400000
        time.sleep(0.1)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"
    ])
    df["date"]  = pd.to_datetime(df["open_time"], unit="ms").dt.date
    df["close"] = df["close"].astype(float)
    df = df[["date","close"]].drop_duplicates("date").sort_values("date")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")

# ── 1. Fetch data ──────────────────────────────────────────────────────────────
print("Fetching klines for all symbols …")
price_dict = {}
for sym in TOP_SYMS:
    print(f"  {sym}")
    df = fetch_klines(sym)
    if not df.empty:
        price_dict[sym] = df["close"]
    time.sleep(0.15)

prices = pd.DataFrame(price_dict).sort_index()
# Keep dates strictly within range
prices = prices[
    (prices.index >= START_DATE) & (prices.index <= END_DATE)
]
print(f"Price matrix: {prices.shape}")

# ── 2. Daily log-returns ───────────────────────────────────────────────────────
log_ret = np.log(prices / prices.shift(1))

# ── 3. BTC realized vol (no-lookahead: use t-1 data, expanding median) ────────
btc_ret    = log_ret["BTCUSDT"].copy()
# 30d rolling std annualized – shift(1) so today's vol uses up to yesterday
btc_vol_30d = btc_ret.shift(1).rolling(30, min_periods=20).std() * np.sqrt(365)

# Expanding median: median of all vol observations up to and including t-1
# (shift already applied, so we just expand)
expanding_median = btc_vol_30d.expanding(min_periods=30).median()

vol_regime = pd.Series(
    np.where(btc_vol_30d < expanding_median, "low", "high"),
    index=btc_vol_30d.index,
)
vol_regime[btc_vol_30d.isna() | expanding_median.isna()] = np.nan

# ── 4. Momentum signal (7d rolling mean of daily return, no lookahead) ─────────
# raw_momentum[t] = mean of log_ret[t-7 .. t-1]  (shift(1) + rolling 7)
raw_mom = log_ret.shift(1).rolling(7, min_periods=5).mean()

# Combined signal:  low-vol → follow momentum, high-vol → reverse
combined = raw_mom.copy()
high_vol_mask = (vol_regime == "high")
combined[high_vol_mask] = -raw_mom[high_vol_mask]

# Baseline: unconditional momentum (always follow)
baseline = raw_mom.copy()

# ── 5. Cross-sectional ranking & portfolio construction ───────────────────────
def run_backtest(signal_df, name="strategy"):
    """
    Daily long top-30% / short bottom-30% (cross-sectional).
    Hold 3 days → use non-overlapping 3-day periods (simpler) or overlapping.
    We use overlapping daily rebalance with 1/3 of portfolio refreshed each day
    (standard equal-weight momentum approach).
    """
    # Exclude BTC from traded universe (it's the regime signal, keep it neutral)
    # Actually include it as a tradeable asset per the task description
    tickers = [c for c in signal_df.columns if c in prices.columns]
    sig = signal_df[tickers].dropna(how="all")
    
    daily_pnl = []
    dates = sig.index.tolist()
    
    for i, dt in enumerate(dates):
        row = sig.loc[dt].dropna()
        if len(row) < 5:
            continue
        n = len(row)
        top_n    = max(1, int(np.ceil(n * 0.30)))
        bot_n    = max(1, int(np.ceil(n * 0.30)))
        ranked   = row.rank(ascending=True)
        longs    = ranked[ranked >= (n - top_n + 1)].index.tolist()
        shorts   = ranked[ranked <= bot_n].index.tolist()
        
        # Next 3 days forward return (already in log_ret)
        # Use hold_days-ahead return: sum of log_ret[t+1..t+hold_days]
        fut_ret = log_ret.loc[dt:].iloc[1:HOLD_DAYS+1]  # rows t+1 to t+3
        if fut_ret.empty or len(fut_ret) < 1:
            continue
        
        fut_sum = fut_ret.sum()  # total log return over hold window
        
        long_ret  = fut_sum[longs].mean()  if longs  else 0.0
        short_ret = fut_sum[shorts].mean() if shorts else 0.0
        
        gross = 0.5 * long_ret + 0.5 * (-short_ret)
        # Fees: 2 * (enter+exit) * 4bps = 4 * 4bps = 16bps per 3d period
        fees = 2 * 2 * FEE_BPS  # 2 legs × enter+exit × fee
        net  = gross - fees
        
        daily_pnl.append({"date": dt, "gross": gross, "net": net,
                           "n_long": len(longs), "n_short": len(shorts),
                           "regime": vol_regime.get(dt, np.nan)})
    
    return pd.DataFrame(daily_pnl).set_index("date")

print("Running backtest …")
strat_pnl    = run_backtest(combined,  "regime_conditional")
baseline_pnl = run_backtest(baseline,  "unconditional")

# ── 6. Performance metrics ─────────────────────────────────────────────────────
def metrics(pnl_series, label):
    s = pnl_series.dropna()
    ann_ret  = s.mean() * 365
    ann_vol  = s.std()  * np.sqrt(365)
    sharpe   = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cum      = np.exp(s.cumsum())
    drawdown = (cum / cum.cummax() - 1)
    max_dd   = drawdown.min()
    win_rate = (s > 0).mean()
    return {
        "label": label,
        "ann_return_pct": round(ann_ret * 100, 2),
        "ann_vol_pct":    round(ann_vol  * 100, 2),
        "sharpe":         round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct":   round(win_rate * 100, 2),
        "n_obs":          len(s),
    }

strat_m    = metrics(strat_pnl["net"],    "Regime-Conditional")
baseline_m = metrics(baseline_pnl["net"], "Unconditional")

# By regime
low_pnl  = strat_pnl[strat_pnl["regime"] == "low"]["net"]
high_pnl = strat_pnl[strat_pnl["regime"] == "high"]["net"]
low_m    = metrics(low_pnl,  "Regime-Conditional (Low-Vol)")
high_m   = metrics(high_pnl, "Regime-Conditional (High-Vol)")

# Also baseline by regime
bl_low  = baseline_pnl[baseline_pnl["regime"] == "low"]["net"]
bl_high = baseline_pnl[baseline_pnl["regime"] == "high"]["net"]
bl_low_m  = metrics(bl_low,  "Unconditional (Low-Vol)")
bl_high_m = metrics(bl_high, "Unconditional (High-Vol)")

print("Regime-Conditional:", strat_m)
print("Unconditional:     ", baseline_m)
print("Low-vol:           ", low_m)
print("High-vol:          ", high_m)

# ── 7. Vol threshold sensitivity ───────────────────────────────────────────────
sensitivity = {}
for pct in [30, 50, 70]:
    thresh = btc_vol_30d.expanding(min_periods=30).quantile(pct/100)
    regime_s = pd.Series(
        np.where(btc_vol_30d < thresh, "low", "high"),
        index=btc_vol_30d.index,
    )
    regime_s[btc_vol_30d.isna() | thresh.isna()] = np.nan
    
    sig_s = raw_mom.copy()
    sig_s[regime_s == "high"] = -raw_mom[regime_s == "high"]
    p = run_backtest(sig_s, f"p{pct}")
    m = metrics(p["net"], f"Threshold p{pct}")
    sensitivity[f"p{pct}"] = m

print("Sensitivity:", sensitivity)

# ── 8. Vol regime duration distribution ────────────────────────────────────────
regime_clean = vol_regime.dropna()
durations = {"low": [], "high": []}
current_regime = None
run_len = 0
for v in regime_clean:
    if v == current_regime:
        run_len += 1
    else:
        if current_regime is not None and run_len > 0:
            durations[current_regime].append(run_len)
        current_regime = v
        run_len = 1
if current_regime and run_len > 0:
    durations[current_regime].append(run_len)

dur_stats = {}
for regime, vals in durations.items():
    if vals:
        arr = np.array(vals)
        dur_stats[regime] = {
            "count": int(len(arr)),
            "mean_days": round(float(arr.mean()), 1),
            "median_days": round(float(np.median(arr)), 1),
            "min_days": int(arr.min()),
            "max_days": int(arr.max()),
            "p25": round(float(np.percentile(arr, 25)), 1),
            "p75": round(float(np.percentile(arr, 75)), 1),
        }

print("Duration stats:", dur_stats)

# ── 9. Regime calendar stats ───────────────────────────────────────────────────
regime_counts = regime_clean.value_counts().to_dict()
total_obs = sum(regime_counts.values())
regime_pct = {k: round(v/total_obs*100, 1) for k, v in regime_counts.items()}

# ── 10. Annual breakdown ───────────────────────────────────────────────────────
annual = {}
for yr in range(2021, 2025):
    mask = strat_pnl.index.year == yr
    yr_s = strat_pnl[mask]["net"]
    yr_b = baseline_pnl[mask]["net"]
    yr_l = strat_pnl[mask & (strat_pnl["regime"]=="low")]["net"]
    yr_h = strat_pnl[mask & (strat_pnl["regime"]=="high")]["net"]
    annual[str(yr)] = {
        "regime_conditional_ann_ret_pct": round(yr_s.sum()*100, 2),  # sum of daily log-ret * 100
        "unconditional_ann_ret_pct":      round(yr_b.sum()*100, 2),
        "low_vol_ret_pct":                round(yr_l.sum()*100, 2) if len(yr_l) > 0 else None,
        "high_vol_ret_pct":               round(yr_h.sum()*100, 2) if len(yr_h) > 0 else None,
        "low_vol_n_days":                 int((strat_pnl[mask]["regime"]=="low").sum()),
        "high_vol_n_days":                int((strat_pnl[mask]["regime"]=="high").sum()),
    }

# ── 11. Assemble results.json ──────────────────────────────────────────────────
results = {
    "metadata": {
        "strategy": "Volatility Regime-Conditional Momentum",
        "universe": TOP_SYMS,
        "start": START_DATE,
        "end":   END_DATE,
        "hold_days": HOLD_DAYS,
        "fee_bps": 4,
        "momentum_window_days": 7,
        "vol_window_days": 30,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    },
    "performance": {
        "regime_conditional": strat_m,
        "unconditional":      baseline_m,
        "low_vol_regime":     low_m,
        "high_vol_regime":    high_m,
        "unconditional_low_vol":  bl_low_m,
        "unconditional_high_vol": bl_high_m,
    },
    "annual_breakdown": annual,
    "vol_threshold_sensitivity": sensitivity,
    "regime_duration_stats": dur_stats,
    "regime_calendar": {
        "counts": regime_counts,
        "pct":    regime_pct,
        "total_obs": total_obs,
    },
    "btc_vol_stats": {
        "mean":   round(float(btc_vol_30d.mean()), 4),
        "median": round(float(btc_vol_30d.median()), 4),
        "min":    round(float(btc_vol_30d.min()), 4),
        "max":    round(float(btc_vol_30d.max()), 4),
        "p25":    round(float(btc_vol_30d.quantile(0.25)), 4),
        "p75":    round(float(btc_vol_30d.quantile(0.75)), 4),
    },
}

out_path = "/root/.openclaw/workspace/research/strategy-alpha/vol-regime/results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"Saved results to {out_path}")

# ── 12. Save daily PnL CSVs for reference ─────────────────────────────────────
strat_pnl.reset_index().to_csv(
    "/root/.openclaw/workspace/research/strategy-alpha/vol-regime/strat_pnl.csv", index=False)
baseline_pnl.reset_index().to_csv(
    "/root/.openclaw/workspace/research/strategy-alpha/vol-regime/baseline_pnl.csv", index=False)

print("Done.")
