"""
Fetch funding rate history using forward pagination (startTime → now).
Target: 2023-01-01 onwards (~2.5 years)
"""
import requests
import pandas as pd
import os, time
from datetime import datetime, timezone

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
OUT_DIR = "/root/.openclaw/workspace/research/funding_rate_alpha/data"
os.makedirs(OUT_DIR, exist_ok=True)

BASE = "https://fapi.binance.com"

START_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

def fetch_funding_full(symbol):
    all_rows = []
    start = START_MS
    while True:
        params = {"symbol": symbol, "startTime": start, "limit": 1000}
        r = requests.get(f"{BASE}/fapi/v1/fundingRate", params=params, timeout=15)
        data = r.json()
        if not data or not isinstance(data, list):
            break
        all_rows.extend(data)
        if len(data) < 1000:
            break
        start = data[-1]["fundingTime"] + 1  # next page
        time.sleep(0.2)
    df = pd.DataFrame(all_rows)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.sort_values("fundingTime").drop_duplicates("fundingTime").reset_index(drop=True)
    return df

def fetch_klines_full(symbol, interval="8h"):
    all_rows = []
    start = START_MS
    while True:
        params = {"symbol": symbol, "interval": interval, "startTime": start, "limit": 1500}
        r = requests.get(f"{BASE}/fapi/v1/klines", params=params, timeout=15)
        data = r.json()
        if not data:
            break
        all_rows.extend(data)
        if len(data) < 1500:
            break
        start = data[-1][0] + 1
        time.sleep(0.2)
    cols = ["open_time","open","high","low","close","volume",
            "close_time","qv","trades","tbbv","tbqv","ignore"]
    df = pd.DataFrame(all_rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df = df.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    return df

for sym in SYMBOLS:
    print(f"\n=== {sym} ===")
    fr = fetch_funding_full(sym)
    fr.to_parquet(f"{OUT_DIR}/{sym}_funding.parquet")
    print(f"  funding : {len(fr):4d} rows | {fr['fundingTime'].min().date()} ~ {fr['fundingTime'].max().date()}")
    print(f"  rate rng: {fr['fundingRate'].min()*100:.4f}% ~ {fr['fundingRate'].max()*100:.4f}%  mean={fr['fundingRate'].mean()*100:.5f}%")

    kl = fetch_klines_full(sym, interval="8h")
    kl.to_parquet(f"{OUT_DIR}/{sym}_8h.parquet")
    print(f"  klines  : {len(kl):4d} rows | {kl['open_time'].min().date()} ~ {kl['open_time'].max().date()}")

print("\n✅ All done!")
