"""
Strategy A Direction 2: Cross-Sectional Funding Rate Long/Short
────────────────────────────────────────────────────────────────
每個 8h bar：
  - 計算所有幣的 funding rate z-score（rolling 120 bars window）
  - 做多 z-score 最低的幣（空頭最擁擠）
  - 做空 z-score 最高的幣（多頭最擁擠）
  - hold N bars 後平倉
  - 完全市場中性：多空名目金額相等

Metrics: PnL, CAGR, MaxDD, Sharpe, Calmar, WinRate, Turnover
"""
import pandas as pd
import numpy as np
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

DATA_DIR = "/root/.openclaw/workspace/research/funding_rate_alpha/data"
SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
CAPITAL  = 10_000   # total capital, split 50% long / 50% short
FEE_RT   = 0.0005   # 0.05% per side

# ─────────────────────────────────────────────────────────────────
# Load & align all symbols to a common timestamp index
# ─────────────────────────────────────────────────────────────────

def load_symbol(sym):
    fr = pd.read_parquet(f"{DATA_DIR}/{sym}_funding.parquet")
    kl = pd.read_parquet(f"{DATA_DIR}/{sym}_8h.parquet")
    fr = fr.rename(columns={"fundingTime": "ts"})
    kl = kl.rename(columns={"open_time": "ts"})
    df = pd.merge_asof(
        fr.sort_values("ts"),
        kl[["ts","open","close"]].sort_values("ts"),
        on="ts", direction="nearest", tolerance=pd.Timedelta("30min")
    ).dropna(subset=["close"]).set_index("ts")
    df = df.rename(columns={"fundingRate": f"{sym}_fr",
                             "open":        f"{sym}_open",
                             "close":       f"{sym}_close"})
    return df[[f"{sym}_fr", f"{sym}_open", f"{sym}_close"]]

print("Loading data...")
frames = [load_symbol(s) for s in SYMBOLS]
data = pd.concat(frames, axis=1).dropna()
print(f"Aligned rows: {len(data)}  ({data.index[0].date()} ~ {data.index[-1].date()})")

# ─────────────────────────────────────────────────────────────────
# Rolling z-score per symbol
# ─────────────────────────────────────────────────────────────────
ROLL = 120  # rolling window for z-score (120 bars ≈ 40 days)

for sym in SYMBOLS:
    col  = f"{sym}_fr"
    mu   = data[col].rolling(ROLL).mean()
    sigma = data[col].rolling(ROLL).std()
    data[f"{sym}_z"] = (data[col] - mu) / sigma.replace(0, np.nan)

data = data.dropna()
print(f"After z-score warmup: {len(data)} rows")

# ─────────────────────────────────────────────────────────────────
# Backtest engine
# ─────────────────────────────────────────────────────────────────

def backtest_cross_sectional(hold_bars=3, top_n=1, min_z_spread=0.5):
    """
    hold_bars    : bars to hold position
    top_n        : number of longs + shorts (top_n each side)
    min_z_spread : only enter if (max_z - min_z) >= this threshold
    """
    capital_per_leg = CAPITAL / 2  # 50% long, 50% short
    n = len(data)
    
    equity_curve = []
    trades = []
    
    i = 0
    total_equity = CAPITAL
    
    while i < n - hold_bars:
        row = data.iloc[i]
        
        # rank z-scores
        z_scores = {sym: row[f"{sym}_z"] for sym in SYMBOLS}
        ranked   = sorted(z_scores.items(), key=lambda x: x[1])
        
        longs  = [s for s, z in ranked[:top_n]]   # lowest z → long
        shorts = [s for s, z in ranked[-top_n:]]  # highest z → short
        
        # z-spread filter: only trade when extremes are far apart
        z_spread = ranked[-1][1] - ranked[0][1]
        if z_spread < min_z_spread:
            equity_curve.append(total_equity)
            i += 1
            continue
        
        # entry prices (next bar open)
        entry_i = i + 1
        exit_i  = min(i + 1 + hold_bars, n - 1)
        
        long_rets  = []
        short_rets = []
        
        valid = True
        for sym in longs:
            ep = data.iloc[entry_i][f"{sym}_open"]
            xp = data.iloc[exit_i][f"{sym}_close"]
            if ep == 0 or pd.isna(ep) or pd.isna(xp):
                valid = False; break
            long_rets.append(xp / ep - 1)
        
        if valid:
            for sym in shorts:
                ep = data.iloc[entry_i][f"{sym}_open"]
                xp = data.iloc[exit_i][f"{sym}_close"]
                if ep == 0 or pd.isna(ep) or pd.isna(xp):
                    valid = False; break
                short_rets.append(-(xp / ep - 1))  # short: invert return
        
        if not valid:
            equity_curve.append(total_equity)
            i += 1
            continue
        
        avg_long_ret  = np.mean(long_rets)
        avg_short_ret = np.mean(short_rets)
        
        # net return (equal weight long + short)
        gross_ret = (avg_long_ret + avg_short_ret) / 2
        fee_cost  = FEE_RT * 2 * 2  # entry+exit on both legs
        net_ret   = gross_ret - fee_cost
        
        trade_pnl = total_equity * net_ret
        total_equity += trade_pnl
        
        trades.append({
            "entry_ts":   data.index[entry_i],
            "exit_ts":    data.index[exit_i],
            "long":       longs[0] if top_n == 1 else longs,
            "short":      shorts[0] if top_n == 1 else shorts,
            "long_z":     ranked[0][1],
            "short_z":    ranked[-1][1],
            "z_spread":   z_spread,
            "long_ret":   avg_long_ret,
            "short_ret":  avg_short_ret,
            "gross_ret":  gross_ret,
            "net_ret":    net_ret,
            "pnl_usd":    trade_pnl,
            "equity":     total_equity,
        })
        
        # fill equity for held bars
        for k in range(hold_bars + 1):
            equity_curve.append(total_equity)
        
        i = exit_i + 1
    
    # fill remaining
    while len(equity_curve) < n:
        equity_curve.append(total_equity)
    
    eq = pd.Series(equity_curve[:n], index=data.index)
    tdf = pd.DataFrame(trades)
    return eq, tdf


def metrics(eq, tdf, bars_per_year=3*365):
    ret   = eq.pct_change().dropna()
    total = eq.iloc[-1] / eq.iloc[0] - 1
    years = len(eq) / bars_per_year
    cagr  = (eq.iloc[-1] / eq.iloc[0]) ** (1/years) - 1
    dd    = (eq - eq.cummax()) / eq.cummax()
    mdd   = dd.min()
    sharpe = ret.mean() / ret.std() * np.sqrt(bars_per_year) if ret.std() > 0 else 0
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    
    wr    = (tdf["net_ret"] > 0).mean() if len(tdf) else 0
    turns = len(tdf) * 2 / years  # round-trips per year
    
    return dict(total=total, cagr=cagr, mdd=mdd,
                sharpe=sharpe, calmar=calmar,
                wr=wr, n_trades=len(tdf), turns=turns,
                final_eq=eq.iloc[-1])


# ─────────────────────────────────────────────────────────────────
# Run: hold period sweep
# ─────────────────────────────────────────────────────────────────
print()
print("=" * 75)
print("CROSS-SECTIONAL STRATEGY  |  top_n=1  |  min_z_spread=0.5")
print("Long: lowest z-score coin  |  Short: highest z-score coin")
print("=" * 75)
print(f"{'Hold':>6}  {'Trades':>6}  {'Win%':>6}  {'PnL$':>8}  "
      f"{'Total%':>7}  {'CAGR%':>7}  {'MaxDD%':>8}  {'Sharpe':>7}  {'Calmar':>7}  {'Turn/yr':>8}")
print("─" * 75)

best_sharpe = -999
best_config = None
results_sweep = []

for hold in [1, 2, 3, 6, 12, 24]:
    eq, tdf = backtest_cross_sectional(hold_bars=hold, top_n=1, min_z_spread=0.5)
    if len(tdf) == 0:
        print(f"{hold:>5}h  (no trades)")
        continue
    m = metrics(eq, tdf)
    results_sweep.append({"hold_bars": hold, **m})
    print(f"{hold*8:>5}h  {m['n_trades']:>6}  {m['wr']*100:>5.1f}%  "
          f"{m['final_eq']-CAPITAL:>+8.0f}  {m['total']*100:>+6.1f}%  "
          f"{m['cagr']*100:>+6.1f}%  {m['mdd']*100:>+7.1f}%  "
          f"{m['sharpe']:>7.2f}  {m['calmar']:>7.2f}  {m['turns']:>7.1f}x")
    if m['sharpe'] > best_sharpe:
        best_sharpe = m['sharpe']
        best_config = (hold, eq, tdf, m)

# ─────────────────────────────────────────────────────────────────
# Best config: deeper dive
# ─────────────────────────────────────────────────────────────────
hold_b, eq_b, tdf_b, m_b = best_config
print(f"\n★ Best config: hold={hold_b*8}h  Sharpe={m_b['sharpe']:.2f}")

# z-spread threshold sensitivity
print()
print("─" * 55)
print(f"Z-SPREAD FILTER SENSITIVITY  (hold={hold_b*8}h)")
print("─" * 55)
print(f"{'MinSpread':>10}  {'Trades':>6}  {'Win%':>6}  {'CAGR%':>7}  {'MaxDD%':>8}  {'Sharpe':>7}")
for zs in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
    eq_, tdf_ = backtest_cross_sectional(hold_bars=hold_b, top_n=1, min_z_spread=zs)
    if len(tdf_) == 0:
        print(f"{zs:>10.1f}  (no trades)")
        continue
    m_ = metrics(eq_, tdf_)
    print(f"{zs:>10.1f}  {m_['n_trades']:>6}  {m_['wr']*100:>5.1f}%  "
          f"{m_['cagr']*100:>+6.1f}%  {m_['mdd']*100:>+7.1f}%  {m_['sharpe']:>7.2f}")

# ─────────────────────────────────────────────────────────────────
# Trade breakdown: which pairs traded most?
# ─────────────────────────────────────────────────────────────────
print()
print("─" * 55)
print("PAIR BREAKDOWN (most frequent long/short combos)")
print("─" * 55)
if len(tdf_b) > 0:
    tdf_b["pair"] = tdf_b["long"].astype(str) + " vs " + tdf_b["short"].astype(str)
    pair_stats = tdf_b.groupby("pair").agg(
        count=("net_ret","count"),
        win_rate=("net_ret", lambda x: (x>0).mean()),
        avg_ret=("net_ret","mean"),
        total_pnl=("pnl_usd","sum")
    ).sort_values("count", ascending=False)
    print(f"{'Pair':<25}  {'N':>4}  {'Win%':>6}  {'AvgRet%':>8}  {'PnL$':>8}")
    for pair, row in pair_stats.iterrows():
        print(f"{pair:<25}  {int(row['count']):>4}  {row['win_rate']*100:>5.1f}%  "
              f"{row['avg_ret']*100:>+7.3f}%  {row['total_pnl']:>+8.0f}")

# ─────────────────────────────────────────────────────────────────
# Yearly breakdown
# ─────────────────────────────────────────────────────────────────
print()
print("─" * 55)
print("YEARLY BREAKDOWN (best config)")
print("─" * 55)
if len(tdf_b) > 0:
    tdf_b["year"] = pd.to_datetime(tdf_b["entry_ts"]).dt.year
    yearly = tdf_b.groupby("year").agg(
        trades=("net_ret","count"),
        win_rate=("net_ret", lambda x: (x>0).mean()),
        total_pnl=("pnl_usd","sum"),
        avg_ret=("net_ret","mean")
    )
    print(f"{'Year':>5}  {'Trades':>6}  {'Win%':>6}  {'PnL$':>8}  {'AvgRet%':>9}")
    for yr, row in yearly.iterrows():
        print(f"{yr:>5}  {int(row['trades']):>6}  {row['win_rate']*100:>5.1f}%  "
              f"{row['total_pnl']:>+8.0f}  {row['avg_ret']*100:>+8.3f}%")

# ─────────────────────────────────────────────────────────────────
# Compare: Strategy A original vs Cross-Sectional
# ─────────────────────────────────────────────────────────────────
print()
print("=" * 65)
print("COMPARISON: Strategy A (BTC only) vs Cross-Sectional L/S")
print("=" * 65)
print(f"{'Strategy':<35}  {'CAGR%':>7}  {'MaxDD%':>8}  {'Sharpe':>7}  {'Calmar':>7}")
print("─" * 65)
print(f"{'A: BTC long-only (hold 8h)':<35}  {21.0:>+6.1f}%  {-18.2:>+7.1f}%  {1.29:>7.2f}  {1.00:>7.2f}")
print(f"{'A: BTC long-only (hold 96h)':<35}  {29.6:>+6.1f}%  {-18.2:>+7.1f}%  {1.04:>7.2f}  {1.50:>7.2f}")
for r in results_sweep:
    h = r['hold_bars']
    label = f"Cross-Sectional (hold {h*8}h)"
    print(f"{label:<35}  {r['cagr']*100:>+6.1f}%  {r['mdd']*100:>+7.1f}%  "
          f"{r['sharpe']:>7.2f}  {r['calmar']:>7.2f}")

# save
tdf_b.to_csv("/root/.openclaw/workspace/research/funding_rate_alpha/cross_sectional_trades.csv", index=False)
eq_b.to_csv("/root/.openclaw/workspace/research/funding_rate_alpha/cross_sectional_equity.csv", header=["equity"])
print(f"\n✅  Trade log saved  ({len(tdf_b)} trades)")
print("Done.")
