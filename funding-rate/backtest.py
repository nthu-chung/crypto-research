"""
Funding Rate Alpha — Full Strategy Backtest
Strategies simulated:
  A. Low-FR Reversal:  Enter long when FR z-score <= -1σ, hold H bars, exit
  B. Carry Trade:      Always short perp (collect positive funding), delta-neutral

Metrics: Total PnL, CAGR, Max Drawdown, Sharpe, Calmar, Trade Count, Turnover
"""
import pandas as pd
import numpy as np
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

DATA_DIR = "/root/.openclaw/workspace/research/funding_rate_alpha/data"
SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
CAPITAL  = 10_000   # USD per symbol
FEE_RT   = 0.0005   # 0.05% per side (taker, futures)

# ── helpers ──────────────────────────────────────────────────────────────────

def load(sym):
    fr = pd.read_parquet(f"{DATA_DIR}/{sym}_funding.parquet")
    kl = pd.read_parquet(f"{DATA_DIR}/{sym}_8h.parquet")
    fr = fr.rename(columns={"fundingTime": "ts"})
    kl = kl.rename(columns={"open_time": "ts"})
    df = pd.merge_asof(
        fr.sort_values("ts"),
        kl[["ts","open","high","low","close","volume"]].sort_values("ts"),
        on="ts", direction="nearest", tolerance=pd.Timedelta("30min")
    ).dropna(subset=["close"]).reset_index(drop=True)
    return df

def equity_metrics(equity: pd.Series, bars_per_year=3*365):
    """Given an equity curve (starting at 1.0), return metrics dict."""
    ret = equity.pct_change().dropna()
    total_ret = equity.iloc[-1] / equity.iloc[0] - 1
    n_bars = len(equity)
    years  = n_bars / bars_per_year
    cagr   = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0

    # drawdown
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    max_dd = dd.min()

    # sharpe (annualised, 0 risk-free)
    sharpe = (ret.mean() / ret.std() * np.sqrt(bars_per_year)) if ret.std() > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    return dict(
        total_ret=total_ret, cagr=cagr, max_dd=max_dd,
        sharpe=sharpe, calmar=calmar,
        n_bars=n_bars, years=round(years, 2)
    )


# ── Strategy A: Low-FR Reversal ───────────────────────────────────────────────

def backtest_reversal(df, hold_bars=3, z_entry=-1.0, capital=CAPITAL):
    """
    Signal: FR z-score <= z_entry  →  open long at next bar open
    Exit:   after hold_bars bars   →  close at that bar's close
    Only one position at a time (no overlapping).
    """
    fr_mean = df["fundingRate"].mean()
    fr_std  = df["fundingRate"].std()
    df = df.copy()
    df["fr_z"] = (df["fundingRate"] - fr_mean) / fr_std

    trades = []
    i = 0
    n = len(df)
    while i < n - hold_bars - 1:
        if df.at[i, "fr_z"] <= z_entry:
            entry_i   = i + 1                       # enter next bar open
            exit_i    = min(entry_i + hold_bars, n - 1)
            entry_px  = df.at[entry_i, "open"]
            exit_px   = df.at[exit_i, "close"]
            raw_ret   = exit_px / entry_px - 1
            net_ret   = raw_ret - 2 * FEE_RT        # buy + sell fee
            trades.append({
                "entry_ts":  df.at[entry_i, "ts"],
                "exit_ts":   df.at[exit_i,  "ts"],
                "entry_px":  entry_px,
                "exit_px":   exit_px,
                "fr_z":      df.at[i, "fr_z"],
                "raw_ret":   raw_ret,
                "net_ret":   net_ret,
            })
            i = exit_i + 1   # no overlapping
        else:
            i += 1

    if not trades:
        return None, pd.DataFrame()

    tdf = pd.DataFrame(trades)
    # build equity curve on trade-by-trade basis (not time-series)
    tdf["equity"] = capital * (1 + tdf["net_ret"]).cumprod()
    tdf["pnl_usd"] = tdf["net_ret"] * capital   # approximate per-trade PnL

    # time-series equity (flat between trades)
    eq_ts = pd.Series(capital, index=df["ts"])
    for _, row in tdf.iterrows():
        idx_after = df.index[df["ts"] >= row["exit_ts"]]
        if len(idx_after):
            # apply cumulative from this exit onwards
            pass
    # simpler: compute via cumulative product on trade sequence
    cum_factor = (1 + tdf["net_ret"]).cumprod()
    final_equity = capital * cum_factor.iloc[-1]

    # equity curve per bar (approximation: step at exit)
    eq_arr = np.full(n, capital, dtype=float)
    cum = capital
    for _, row in tdf.iterrows():
        exit_idx = df.index[df["ts"] == row["exit_ts"]]
        if len(exit_idx):
            cum *= (1 + row["net_ret"])
            eq_arr[exit_idx[0]:] = cum
    eq_series = pd.Series(eq_arr, index=df["ts"])

    m = equity_metrics(eq_series)

    # turnover: total notional traded / capital / years
    notional_per_trade = capital  # simplified (full capital per trade)
    total_notional = notional_per_trade * len(tdf) * 2   # entry + exit
    turnover = total_notional / capital / m["years"]

    summary = {
        "trade_count":   len(tdf),
        "win_rate":      (tdf["net_ret"] > 0).mean(),
        "avg_net_ret":   tdf["net_ret"].mean(),
        "total_pnl_usd": final_equity - capital,
        "final_equity":  final_equity,
        "turnover_x":    round(turnover, 1),
        **m
    }
    return summary, tdf, eq_series


# ── Strategy B: Carry (delta-neutral, collect funding) ────────────────────────

def backtest_carry(df, capital=CAPITAL):
    """
    Always short perp (and long spot) → collect funding rate every 8h.
    Net PnL per bar = fundingRate * capital (if positive, we earn; if negative, we pay).
    No price exposure (delta neutral assumption).
    Fee: charged on entry and exit (once at start + once at end).
    """
    df = df.copy()
    n = len(df)

    # entry fee
    entry_fee = capital * FEE_RT * 2   # perp + spot

    cumulative = capital - entry_fee
    equity = [cumulative]
    for i in range(1, n):
        fr = df.at[i, "fundingRate"]
        cumulative += cumulative * fr   # earn/pay funding
        equity.append(cumulative)

    # exit fee at end
    equity[-1] -= equity[-1] * FEE_RT * 2

    eq_series = pd.Series(equity, index=df["ts"])
    m = equity_metrics(eq_series)

    summary = {
        "trade_count":   1,    # single position held throughout
        "win_rate":      None,
        "avg_net_ret":   None,
        "total_pnl_usd": equity[-1] - capital,
        "final_equity":  equity[-1],
        "turnover_x":    round(1 / m["years"], 2),
        **m
    }
    return summary, eq_series


# ── Run all ───────────────────────────────────────────────────────────────────

print("=" * 70)
print("STRATEGY A — LOW FUNDING REVERSAL  (z ≤ -1σ, hold 3 bars = 24h)")
print("=" * 70)
print(f"{'Symbol':<10} {'Trades':>6} {'Win%':>6} {'PnL $':>9} {'Total%':>8} "
      f"{'CAGR%':>7} {'MaxDD%':>8} {'Sharpe':>7} {'Calmar':>7} {'Turn':>6}")
print("─" * 70)

all_strat_a = {}
for sym in SYMBOLS:
    df = load(sym)
    res, tdf, eq = backtest_reversal(df, hold_bars=3, z_entry=-1.0)
    if res is None:
        print(f"{sym:<10}  No trades")
        continue
    all_strat_a[sym] = (res, tdf, eq)
    print(f"{sym:<10} {res['trade_count']:>6} {res['win_rate']*100:>5.1f}% "
          f"{res['total_pnl_usd']:>+9.0f} {res['total_ret']*100:>+7.1f}% "
          f"{res['cagr']*100:>+6.1f}% {res['max_dd']*100:>+7.1f}% "
          f"{res['sharpe']:>7.2f} {res['calmar']:>7.2f} {res['turnover_x']:>5.1f}x")

print()

# Also test hold_bars = 1 and 6
for hold in [1, 6, 12]:
    print(f"\n--- hold = {hold} bars ({hold*8}h) ---")
    print(f"{'Symbol':<10} {'Trades':>6} {'Win%':>6} {'PnL $':>9} {'Total%':>8} {'CAGR%':>7} {'MaxDD%':>8} {'Sharpe':>7}")
    print("─" * 65)
    for sym in SYMBOLS:
        df = load(sym)
        res, tdf, eq = backtest_reversal(df, hold_bars=hold, z_entry=-1.0)
        if res is None:
            print(f"{sym:<10}  No trades")
            continue
        print(f"{sym:<10} {res['trade_count']:>6} {res['win_rate']*100:>5.1f}% "
              f"{res['total_pnl_usd']:>+9.0f} {res['total_ret']*100:>+7.1f}% "
              f"{res['cagr']*100:>+6.1f}% {res['max_dd']*100:>+7.1f}% "
              f"{res['sharpe']:>7.2f}")

print()
print("=" * 70)
print("STRATEGY B — CARRY TRADE  (short perp + long spot, delta-neutral)")
print("=" * 70)
print(f"{'Symbol':<10} {'PnL $':>9} {'Total%':>8} {'CAGR%':>7} {'MaxDD%':>8} {'Sharpe':>7} {'Calmar':>7}")
print("─" * 65)
for sym in SYMBOLS:
    df = load(sym)
    res, eq = backtest_carry(df)
    print(f"{sym:<10} {res['total_pnl_usd']:>+9.0f} {res['total_ret']*100:>+7.1f}% "
          f"{res['cagr']*100:>+6.1f}% {res['max_dd']*100:>+7.1f}% "
          f"{res['sharpe']:>7.2f} {res['calmar']:>7.2f}")

# ── Save trade log for BTC as example ─────────────────────────────────────────
if "BTCUSDT" in all_strat_a:
    res, tdf, eq = all_strat_a["BTCUSDT"]
    tdf.to_csv("/root/.openclaw/workspace/research/funding_rate_alpha/btc_trades.csv", index=False)
    eq.to_csv("/root/.openclaw/workspace/research/funding_rate_alpha/btc_equity.csv", header=["equity"])
    print(f"\n✅  BTC trade log saved ({len(tdf)} trades)")

print("\nDone.")
