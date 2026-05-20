"""
Alpha Signal Backtest: 6 signals × 10 symbols
Walk-Forward, TC=0.1%, Binance 1h Klines 2022-01-01 ~ 2024-12-31
"""

import os
import time
import json
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone

SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
           "DOGEUSDT","ADAUSDT","AVAXUSDT","DOTUSDT","LINKUSDT"]
SIGNAL_NAMES = ["Flow_z_Rev","VolSpike_Rev","Momentum_4h","MeanRev_24h","FundProxy","Composite"]

START_MS = int(datetime(2022,1,1,tzinfo=timezone.utc).timestamp()*1000)
END_MS   = int(datetime(2024,12,31,23,0,tzinfo=timezone.utc).timestamp()*1000)
TC = 0.001  # 0.1% one-way
MIN_TRAIN = 1000
REFIT_EVERY = 168

CACHE_DIR = "/root/.openclaw/workspace/research/kline_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_klines(symbol):
    cache_path = f"{CACHE_DIR}/{symbol}_1h.parquet"
    if os.path.exists(cache_path):
        df = pd.read_parquet(cache_path)
        print(f"  [cache] {symbol}: {len(df)} rows")
        return df

    url = "https://api.binance.com/api/v3/klines"
    rows = []
    start = START_MS
    while start < END_MS:
        params = {"symbol": symbol, "interval": "1h", "startTime": start,
                  "endTime": END_MS, "limit": 1000}
        for attempt in range(5):
            try:
                r = requests.get(url, params=params, timeout=30)
                if r.status_code == 429:
                    time.sleep(10)
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                print(f"  retry {attempt}: {e}")
                time.sleep(3)
        else:
            print(f"  FAILED {symbol}")
            break
        if not data:
            break
        rows.extend(data)
        start = data[-1][0] + 3600_000
        if len(data) < 1000:
            break
        time.sleep(0.12)

    df = pd.DataFrame(rows, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"])
    for col in ["open","high","low","close","volume","taker_buy_base"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.to_parquet(cache_path)
    print(f"  [fetch] {symbol}: {len(df)} rows")
    return df


def compute_signals(df):
    close = df["close"]
    volume = df["volume"]
    taker_buy = df["taker_buy_base"]

    ret = close.pct_change()

    # Signal 1: Flow_z reverse
    buy_sell_diff = 2 * taker_buy - volume
    bsd_roll = buy_sell_diff.rolling(168)
    flow_z = (buy_sell_diff - bsd_roll.mean()) / (bsd_roll.std() + 1e-9)

    # Signal 2: Volume Spike reverse
    vol_ma = volume.rolling(168).mean()
    vol_spike = volume / (vol_ma + 1e-9)

    # Signal 3: Momentum 4h
    mom_4h = (close / close.shift(4) - 1)

    # Signal 4: Mean Reversion 24h
    ret_24h = (close / close.shift(24) - 1)
    ret_24h_roll = ret_24h.rolling(168)
    ret_z_24h = (ret_24h - ret_24h_roll.mean()) / (ret_24h_roll.std() + 1e-9)

    # Signal 5: Taker dominance proxy
    taker_dom = (taker_buy / (volume + 1e-9)).rolling(168).mean()

    signals = pd.DataFrame({
        "flow_z": flow_z,
        "vol_spike": vol_spike,
        "mom_4h": mom_4h,
        "ret_z_24h": ret_z_24h,
        "taker_dom": taker_dom,
        "ret": ret
    })
    return signals


def generate_positions(sig_df, signal_idx):
    """Returns raw position series (-1, 0, +1) for a given signal index."""
    pos = pd.Series(0.0, index=sig_df.index)

    if signal_idx == 0:  # Flow_z reverse
        # walk-forward: use rolling threshold (cross 0 → signal)
        pos = np.where(sig_df["flow_z"] > 1.0, -1.0,
              np.where(sig_df["flow_z"] < -1.0, 1.0, 0.0))
        pos = pd.Series(pos, index=sig_df.index)

    elif signal_idx == 1:  # Vol Spike reverse
        pos = np.where(sig_df["vol_spike"] > 2.0, -1.0, 0.0)
        pos = pd.Series(pos, index=sig_df.index)

    elif signal_idx == 2:  # Momentum 4h
        # Walk-forward: use rolling median as dynamic threshold
        mom = sig_df["mom_4h"]
        roll_med = mom.rolling(MIN_TRAIN, min_periods=MIN_TRAIN).median()
        roll_std = mom.rolling(MIN_TRAIN, min_periods=MIN_TRAIN).std()
        threshold = roll_med + 0.3 * roll_std
        pos = np.where(mom > threshold, 1.0,
              np.where(mom < roll_med - 0.3 * roll_std, -1.0, 0.0))
        pos = pd.Series(pos, index=sig_df.index)

    elif signal_idx == 3:  # Mean Reversion 24h
        pos = np.where(sig_df["ret_z_24h"] > 2.0, -1.0,
              np.where(sig_df["ret_z_24h"] < -2.0, 1.0, 0.0))
        pos = pd.Series(pos, index=sig_df.index)

    elif signal_idx == 4:  # Funding rate proxy
        td = sig_df["taker_dom"]
        roll_med = td.rolling(MIN_TRAIN, min_periods=MIN_TRAIN).median()
        roll_std = td.rolling(MIN_TRAIN, min_periods=MIN_TRAIN).std()
        pos = np.where(td > roll_med + 0.5 * roll_std, -1.0,
              np.where(td < roll_med - 0.5 * roll_std, 1.0, 0.0))
        pos = pd.Series(pos, index=sig_df.index)

    elif signal_idx == 5:  # Composite
        p0 = generate_positions(sig_df, 0)
        p1 = generate_positions(sig_df, 1)
        p3 = generate_positions(sig_df, 3)
        combo = p0 + p1 + p3
        pos = np.where(combo == 3, 1.0, np.where(combo == -3, -1.0, 0.0))
        pos = pd.Series(pos, index=sig_df.index)

    return pos.shift(1).fillna(0.0)  # trade on next bar


def walk_forward_sharpe(sig_df, signal_idx, min_train=MIN_TRAIN, refit_every=REFIT_EVERY):
    """
    Walk-forward Sharpe. Refit every 168 bars.
    Positions are computed on training window ending at each refit point.
    For signal-based strategies, we use a sliding-window position generator
    but only apply positions from the test window.
    """
    n = len(sig_df)
    all_pnl = []

    # Generate full positions (uses rolling lookback, so naturally walk-forward)
    pos = generate_positions(sig_df, signal_idx)

    # Apply only from after initial train period
    ret = sig_df["ret"].fillna(0.0)

    # Walk-forward application: only trade in test windows
    wf_pnl = pd.Series(0.0, index=sig_df.index)
    test_start_indices = range(min_train, n, refit_every)

    for i, ts in enumerate(test_start_indices):
        te = min(ts + refit_every, n)
        window_pos = pos.iloc[ts:te]
        window_ret = ret.iloc[ts:te]
        # transaction cost: charge TC on position changes
        pos_change = window_pos.diff().abs()
        pos_change.iloc[0] = abs(window_pos.iloc[0])
        pnl = window_pos * window_ret - pos_change * TC
        wf_pnl.iloc[ts:te] = pnl.values

    # Compute Sharpe on test period only
    test_pnl = wf_pnl.iloc[min_train:]
    test_pnl = test_pnl.replace([np.inf, -np.inf], np.nan).dropna()

    if len(test_pnl) < 100 or test_pnl.std() < 1e-10:
        return 0.0

    sharpe = test_pnl.mean() / test_pnl.std() * np.sqrt(8760)
    return float(np.round(sharpe, 4))


def main():
    print("=== Alpha Signal Backtest ===")
    print(f"Symbols: {SYMBOLS}")
    print(f"Period: 2022-01-01 ~ 2024-12-31, 1h bars")
    print()

    results = {}  # symbol -> [sharpe_s1..s6]

    for symbol in SYMBOLS:
        print(f"Processing {symbol}...")
        try:
            df = fetch_klines(symbol)
            sig_df = compute_signals(df)
            sharpes = []
            for sig_idx in range(6):
                s = walk_forward_sharpe(sig_df, sig_idx)
                sharpes.append(s)
                print(f"  Signal{sig_idx+1} ({SIGNAL_NAMES[sig_idx]}): Sharpe={s:.4f}")
            results[symbol] = sharpes
        except Exception as e:
            print(f"  ERROR {symbol}: {e}")
            import traceback; traceback.print_exc()
            results[symbol] = [0.0]*6

    # Build matrix
    sym_labels = [s.replace("USDT","") for s in SYMBOLS]
    matrix = pd.DataFrame(results, index=SIGNAL_NAMES).T
    matrix.index = sym_labels

    # Overall Sharpe per signal (mean across coins)
    signal_mean = matrix.mean(axis=0)

    # Best combos (Sharpe > 0)
    best_combos = []
    for sym in matrix.index:
        for sig in matrix.columns:
            val = matrix.loc[sym, sig]
            if val > 0:
                best_combos.append((sym, sig, val))
    best_combos.sort(key=lambda x: -x[2])

    # Write output
    out_path = "/root/.openclaw/workspace/research/agentB_signals.txt"
    with open(out_path, "w") as f:
        f.write("=" * 70 + "\n")
        f.write("ALPHA SIGNAL BACKTEST RESULTS\n")
        f.write("6 Signals × 10 Crypto Symbols\n")
        f.write("Period: 2022-01-01 ~ 2024-12-31 | Interval: 1h | TC=0.1%\n")
        f.write("Walk-Forward: min_train=1000h, refit_every=168h\n")
        f.write("=" * 70 + "\n\n")

        f.write("## 1. 各信號整體 Sharpe（10幣平均）\n\n")
        for sig, val in signal_mean.items():
            f.write(f"  {sig:<20}: {val:>8.4f}\n")
        f.write("\n")

        f.write("## 2. Sharpe 熱力圖數據（10×6 矩陣）\n\n")
        # header
        header = f"{'Symbol':<8}" + "".join(f"{s:<22}" for s in SIGNAL_NAMES)
        f.write(header + "\n")
        f.write("-" * (8 + 22*6) + "\n")
        for sym in matrix.index:
            row = f"{sym:<8}"
            for sig in SIGNAL_NAMES:
                val = matrix.loc[sym, sig]
                row += f"{val:<22.4f}"
            f.write(row + "\n")
        f.write("\n")

        f.write("## 3. 最佳信號×幣別組合（Sharpe > 0）\n\n")
        f.write(f"{'Symbol':<8} {'Signal':<22} {'Sharpe':>8}\n")
        f.write("-" * 42 + "\n")
        for sym, sig, val in best_combos:
            f.write(f"{sym:<8} {sig:<22} {val:>8.4f}\n")
        f.write(f"\n共 {len(best_combos)} 個有效組合\n\n")

        f.write("## 4. 結論\n\n")
        best_sig = signal_mean.idxmax()
        best_val = signal_mean.max()
        worst_sig = signal_mean.idxmin()
        worst_val = signal_mean.min()
        f.write(f"最強信號：{best_sig}（平均 Sharpe={best_val:.4f}）\n")
        f.write(f"最弱信號：{worst_sig}（平均 Sharpe={worst_val:.4f}）\n\n")

        f.write("詳細分析：\n")
        for sig in SIGNAL_NAMES:
            mv = signal_mean[sig]
            pos_count = sum(1 for sym in matrix.index if matrix.loc[sym, sig] > 0)
            f.write(f"  {sig}: 平均={mv:.4f}, {pos_count}/10 個幣 Sharpe>0\n")
        f.write("\n")

        rank = signal_mean.sort_values(ascending=False)
        f.write("信號排名（高到低）：\n")
        for i, (sig, val) in enumerate(rank.items(), 1):
            f.write(f"  {i}. {sig}: {val:.4f}\n")
        f.write("\n")

        f.write("=" * 70 + "\n")
        f.write(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    print(f"\nResults saved to {out_path}")
    print("\nSignal Mean Sharpe:")
    print(signal_mean.to_string())
    print("\nMatrix:")
    print(matrix.to_string())


if __name__ == "__main__":
    main()
