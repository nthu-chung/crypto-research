"""
Funding Rate Alpha Analysis
Research question: When funding rate hits extreme values (±2σ),
does the next N-bar price return show statistically significant skew?

Additional analyses:
- Distribution of funding rates (histogram + percentiles)
- Autocorrelation of funding rate
- Forward returns at different extremes (1σ, 1.5σ, 2σ)
- Carry PnL simulation (delta-neutral: long spot / short perp)
"""
import pandas as pd
import numpy as np
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

DATA_DIR = "/root/.openclaw/workspace/research/funding_rate_alpha/data"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
FORWARD_BARS = [1, 3, 6, 12]  # 8h bars → 8h, 24h, 48h, 96h ahead

results = {}

def load_and_merge(sym):
    fr = pd.read_parquet(f"{DATA_DIR}/{sym}_funding.parquet")
    kl = pd.read_parquet(f"{DATA_DIR}/{sym}_8h.parquet")
    # align: merge on nearest timestamp
    fr = fr.rename(columns={"fundingTime": "ts"})
    kl = kl.rename(columns={"open_time": "ts"})
    # funding time ≈ kline open_time (they share 00:00/08:00/16:00 UTC)
    merged = pd.merge_asof(
        fr.sort_values("ts"),
        kl[["ts","open","close","high","low","volume"]].sort_values("ts"),
        on="ts", direction="nearest", tolerance=pd.Timedelta("30min")
    )
    merged = merged.dropna(subset=["close"]).reset_index(drop=True)
    # compute forward returns
    for n in FORWARD_BARS:
        merged[f"fwd_{n}"] = merged["close"].shift(-n) / merged["close"] - 1
    return merged

print("=" * 60)
print("FUNDING RATE ALPHA ANALYSIS")
print("=" * 60)

all_results = []

for sym in SYMBOLS:
    df = load_and_merge(sym)
    df = df.dropna(subset=[f"fwd_{FORWARD_BARS[-1]}"])  # drop last rows

    fr_mean = df["fundingRate"].mean()
    fr_std  = df["fundingRate"].std()

    # --- z-score ---
    df["fr_z"] = (df["fundingRate"] - fr_mean) / fr_std

    # --- define regimes ---
    df["regime"] = "neutral"
    df.loc[df["fr_z"] >= 2.0, "regime"] = "high_2s"
    df.loc[df["fr_z"] <= -2.0, "regime"] = "low_2s"
    df.loc[(df["fr_z"] >= 1.5) & (df["fr_z"] < 2.0), "regime"] = "high_1.5s"
    df.loc[(df["fr_z"] <= -1.5) & (df["fr_z"] > -2.0), "regime"] = "low_1.5s"
    df.loc[(df["fr_z"] >= 1.0) & (df["fr_z"] < 1.5), "regime"] = "high_1s"
    df.loc[(df["fr_z"] <= -1.0) & (df["fr_z"] > -1.5), "regime"] = "low_1s"

    print(f"\n{'─'*60}")
    print(f"  {sym}")
    print(f"{'─'*60}")
    print(f"  Funding rate stats:")
    print(f"    mean={fr_mean*100:.5f}%  std={fr_std*100:.5f}%")
    print(f"    min={df['fundingRate'].min()*100:.4f}%  max={df['fundingRate'].max()*100:.4f}%")
    print(f"    p1={np.percentile(df['fundingRate'],1)*100:.4f}%  p99={np.percentile(df['fundingRate'],99)*100:.4f}%")
    print(f"  Regime counts:")
    for reg in ["high_2s","high_1.5s","high_1s","neutral","low_1s","low_1.5s","low_2s"]:
        cnt = (df["regime"] == reg).sum()
        print(f"    {reg:12s}: {cnt:4d}  ({cnt/len(df)*100:.1f}%)")

    print(f"\n  Forward return analysis (fwd bar = 8h each):")
    print(f"  {'Regime':<12}  {'N':>4}  {'fwd1':>8}  {'fwd3':>8}  {'fwd6':>8}  {'fwd12':>8}  {'t-stat':>7}  {'p':>6}")

    for reg in ["high_2s","high_1.5s","high_1s","neutral","low_1s","low_1.5s","low_2s"]:
        sub = df[df["regime"] == reg]
        if len(sub) < 10:
            continue
        row = {"symbol": sym, "regime": reg, "n": len(sub)}
        means = []
        for n in FORWARD_BARS:
            m = sub[f"fwd_{n}"].mean()
            row[f"fwd{n}_mean"] = m
            means.append(m)

        # t-test: is fwd_1 mean significantly different from 0?
        t, p = stats.ttest_1samp(sub["fwd_1"].dropna(), 0)
        row["t_stat"] = t
        row["p_value"] = p
        all_results.append(row)

        fwd_vals = [f"{m*100:+.3f}%" for m in means]
        print(f"  {reg:<12}  {len(sub):4d}  {'  '.join(fwd_vals):40s}  {t:7.2f}  {p:.4f}")

    # --- carry simulation ---
    # Assumption: if you're short perp + long spot, you RECEIVE funding when rate > 0
    # Annual carry = avg_daily_rate * 365
    avg_daily_rate = fr_mean * 3  # 3 payments per day (every 8h)
    annual_carry_pct = avg_daily_rate * 365 * 100
    print(f"\n  Carry (delta-neutral, long spot + short perp):")
    print(f"    Avg funding per 8h: {fr_mean*100:.5f}%")
    print(f"    Est. annual carry: {annual_carry_pct:.2f}%  (before fees/slippage)")

# --- summary table: which regimes show significant alpha? ---
print(f"\n{'='*60}")
print("SIGNIFICANT FINDINGS (p < 0.1, |mean fwd1| > 0.1%)")
print(f"{'='*60}")
res_df = pd.DataFrame(all_results)
sig = res_df[
    (res_df["p_value"] < 0.10) &
    (res_df["fwd1_mean"].abs() > 0.001)
].sort_values("p_value")

if len(sig) > 0:
    for _, row in sig.iterrows():
        direction = "📉 REVERSAL" if (
            ("high" in row["regime"] and row["fwd1_mean"] < 0) or
            ("low" in row["regime"] and row["fwd1_mean"] > 0)
        ) else "📈 CONTINUATION"
        print(f"  {row['symbol']:8s} | {row['regime']:12s} | "
              f"n={int(row['n']):4d} | fwd1={row['fwd1_mean']*100:+.3f}% | "
              f"t={row['t_stat']:.2f} | p={row['p_value']:.4f} | {direction}")
else:
    print("  No strongly significant findings at p<0.10 threshold.")

# Save results
res_df.to_csv("/root/.openclaw/workspace/research/funding_rate_alpha/results.csv", index=False)
print(f"\n✅ Results saved to results.csv")
print(f"   Total event rows analyzed: {len(res_df)}")
