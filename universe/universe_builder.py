"""
Universe Builder
================
從 Binance Futures 公開 API 抓所有 USDT perp 資訊，
篩選出符合條件的 Top N 幣種，並建立 Point-in-Time snapshots。

用法：
  python universe_builder.py --top 30 --min-days 180
  python universe_builder.py --top 30 --min-days 180 --rebuild-history
"""

import os
import json
import time
import argparse
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
from taxonomy import TAXONOMY, RISK_FACTORS, EXCLUDE_ALWAYS, STABLE_AND_WRAPPED, get_category, get_bucket

BASE_URL = "https://fapi.binance.com"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
DATA_DIR     = Path(__file__).parent / "data"
SNAPSHOT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────

def get_exchange_info():
    """取得所有 USDT perp 合約資訊（含上市時間）"""
    resp = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=15)
    resp.raise_for_status()
    symbols = resp.json()["symbols"]
    return [s for s in symbols
            if s["quoteAsset"] == "USDT"
            and s["contractType"] == "PERPETUAL"
            and s["status"] == "TRADING"]


def get_24h_tickers():
    """取得所有 symbol 的 24h 統計"""
    resp = requests.get(f"{BASE_URL}/fapi/v1/ticker/24hr", timeout=15)
    resp.raise_for_status()
    return {t["symbol"]: t for t in resp.json()}


def get_funding_rate(symbol: str):
    """取得最新 funding rate"""
    try:
        resp = requests.get(
            f"{BASE_URL}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=10
        )
        resp.raise_for_status()
        return float(resp.json()["lastFundingRate"])
    except Exception:
        return None


def get_open_interest(symbol: str):
    """取得目前 OI"""
    try:
        resp = requests.get(
            f"{BASE_URL}/fapi/v1/openInterest",
            params={"symbol": symbol},
            timeout=10
        )
        resp.raise_for_status()
        return float(resp.json()["openInterest"])
    except Exception:
        return None


def get_klines_30d_volume(symbol: str) -> float:
    """
    抓近 30 天日線，計算 median 日成交量（USDT）
    用 daily kline，limit=30
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1d", "limit": 30},
            timeout=15
        )
        resp.raise_for_status()
        klines = resp.json()
        # kline[7] = quoteAssetVolume
        volumes = [float(k[7]) for k in klines]
        if not volumes:
            return 0.0
        volumes.sort()
        mid = len(volumes) // 2
        return volumes[mid]
    except Exception:
        return 0.0


# ─────────────────────────────────────────
# Universe building
# ─────────────────────────────────────────

def build_universe(
    top_n: int = 30,
    min_listing_days: int = 180,
    min_volume_usdt: float = 50_000_000,   # 30D median daily vol > 50M USDT
    as_of: datetime = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    核心篩選邏輯：
    1. 只留 USDT perp，排除 stable/wrapped/BTC/ETH
    2. 上市天數 > min_listing_days
    3. 30D median daily volume > min_volume_usdt
    4. 取 top_n by volume
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    if verbose:
        print(f"\n[Universe Builder] as_of = {as_of.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  top_n={top_n}  min_days={min_listing_days}  min_vol={min_volume_usdt/1e6:.0f}M USDT")

    # Step 1: 取合約清單
    if verbose: print("  Fetching exchange info...")
    contracts = get_exchange_info()

    # Step 2: 取 24h ticker（含 volume）
    if verbose: print("  Fetching 24h tickers...")
    tickers = get_24h_tickers()

    rows = []
    exclude_set = EXCLUDE_ALWAYS | STABLE_AND_WRAPPED

    for c in contracts:
        sym = c["symbol"]
        if sym in exclude_set:
            continue

        # 上市時間（onboardDate 單位：ms）
        onboard_ms = c.get("onboardDate", 0)
        if onboard_ms == 0:
            continue
        listing_dt = datetime.fromtimestamp(onboard_ms / 1000, tz=timezone.utc)
        listing_days = (as_of - listing_dt).days

        if listing_days < min_listing_days:
            continue

        rows.append({
            "symbol":       sym,
            "listing_date": listing_dt.strftime("%Y-%m-%d"),
            "listing_days": listing_days,
        })

    if verbose:
        print(f"  Passed listing-age filter: {len(rows)} symbols")

    # Step 3: 拉 30D median volume（限流：批次處理）
    if verbose:
        print(f"  Fetching 30D median volume for {len(rows)} symbols...")

    for i, row in enumerate(rows):
        row["vol_30d_median_usdt"] = get_klines_30d_volume(row["symbol"])
        if verbose and (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(rows)} done...")
        time.sleep(0.05)   # 避免打太快

    df = pd.DataFrame(rows)
    if df.empty:
        print("  ERROR: No symbols passed filters.")
        return df

    # Step 4: volume 篩選
    df = df[df["vol_30d_median_usdt"] >= min_volume_usdt].copy()

    # Step 5: 取 Top N
    df = df.nlargest(top_n, "vol_30d_median_usdt").reset_index(drop=True)

    # Step 6: 加 taxonomy
    df["category"] = df["symbol"].map(get_category)
    df["bucket"]   = df["symbol"].map(get_bucket)

    # Step 7: 加 rank
    df.insert(0, "rank", range(1, len(df) + 1))

    if verbose:
        print(f"\n  ✅ Universe built: {len(df)} symbols")
        print(df[["rank", "symbol", "category", "bucket",
                   "listing_date", "listing_days",
                   "vol_30d_median_usdt"]].to_string(index=False))

    return df


# ─────────────────────────────────────────
# Snapshot management
# ─────────────────────────────────────────

def save_snapshot(df: pd.DataFrame, as_of: datetime):
    """存 Point-in-Time snapshot（JSON + CSV）"""
    date_str = as_of.strftime("%Y-%m-%d")
    csv_path  = SNAPSHOT_DIR / f"universe_{date_str}.csv"
    json_path = SNAPSHOT_DIR / f"universe_{date_str}.json"

    df.to_csv(csv_path, index=False)

    meta = {
        "as_of":        date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count":        len(df),
        "symbols":      df["symbol"].tolist(),
    }
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n  💾 Snapshot saved: {csv_path}")
    return csv_path


def load_snapshot(date_str: str) -> pd.DataFrame:
    """讀取指定日期的 snapshot"""
    path = SNAPSHOT_DIR / f"universe_{date_str}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Snapshot not found: {path}")
    return pd.read_csv(path)


def get_universe_on_date(date_str: str) -> pd.DataFrame:
    """Point-in-Time 查詢：給定日期，返回當時的 universe"""
    snapshots = sorted(SNAPSHOT_DIR.glob("universe_*.csv"))
    if not snapshots:
        raise RuntimeError("No snapshots found. Run universe_builder.py first.")

    target = datetime.strptime(date_str, "%Y-%m-%d")
    best = None
    for snap in snapshots:
        snap_date_str = snap.stem.replace("universe_", "")
        snap_date = datetime.strptime(snap_date_str, "%Y-%m-%d")
        if snap_date <= target:
            best = snap
        else:
            break

    if best is None:
        raise RuntimeError(f"No snapshot available on or before {date_str}")

    print(f"[PIT Query] Using snapshot: {best.name}")
    return pd.read_csv(best)


# ─────────────────────────────────────────
# Historical rebuild
# ─────────────────────────────────────────

def rebuild_history(
    top_n: int = 30,
    min_listing_days: int = 180,
    min_volume_usdt: float = 50_000_000,
    frequency_weeks: int = 4,   # 每幾週一個快照
):
    """
    回溯建立 2020~今 的 universe 快照。
    注意：因為 Binance API 只能查「現在」的合約清單與上市時間，
    我們用 Point-in-Time 近似法：
    - 對每個歷史時間點，根據「listing_date <= snapshot_date」篩出當時存在的幣
    - 用現在的 30D volume 作為流動性的 proxy（近似，已知限制）
    - 這是 bootstrap 用的歷史基礎，正式回測會用每日 bar 重算
    """
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end   = datetime.now(timezone.utc)
    delta = timedelta(weeks=frequency_weeks)

    print(f"\n[Historical Rebuild] {start.date()} → {end.date()}, every {frequency_weeks} weeks")

    # 先拉一次完整合約清單（含 listing_date）
    print("  Fetching all contracts once...")
    contracts = get_exchange_info()
    exclude_set = EXCLUDE_ALWAYS | STABLE_AND_WRAPPED

    # 建立每個 symbol 的 listing_date lookup
    symbol_info = {}
    for c in contracts:
        sym = c["symbol"]
        if sym in exclude_set:
            continue
        onboard_ms = c.get("onboardDate", 0)
        if onboard_ms == 0:
            continue
        listing_dt = datetime.fromtimestamp(onboard_ms / 1000, tz=timezone.utc)
        symbol_info[sym] = listing_dt

    # 拉一次 30D volume（用作全期代理）
    print(f"  Fetching 30D volume for {len(symbol_info)} symbols (once, used as proxy)...")
    vol_map = {}
    syms = list(symbol_info.keys())
    for i, sym in enumerate(syms):
        vol_map[sym] = get_klines_30d_volume(sym)
        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(syms)} done...")
        time.sleep(0.05)

    # 逐個時間點建立 snapshot
    current = start
    snapshot_count = 0
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        snap_path = SNAPSHOT_DIR / f"universe_{date_str}.csv"

        if snap_path.exists():
            print(f"  [SKIP] {date_str} (already exists)")
            current += delta
            continue

        rows = []
        for sym, listing_dt in symbol_info.items():
            listing_days = (current - listing_dt).days
            if listing_days < min_listing_days:
                continue
            vol = vol_map.get(sym, 0.0)
            rows.append({
                "symbol":              sym,
                "listing_date":        listing_dt.strftime("%Y-%m-%d"),
                "listing_days":        listing_days,
                "vol_30d_median_usdt": vol,
            })

        df = pd.DataFrame(rows)
        if df.empty:
            print(f"  [{date_str}] No symbols passed filter, skipping.")
            current += delta
            continue

        df = df[df["vol_30d_median_usdt"] >= min_volume_usdt]
        df = df.nlargest(top_n, "vol_30d_median_usdt").reset_index(drop=True)
        df["category"] = df["symbol"].map(get_category)
        df["bucket"]   = df["symbol"].map(get_bucket)
        df.insert(0, "rank", range(1, len(df) + 1))

        save_snapshot(df, current)
        snapshot_count += 1
        print(f"  [{date_str}] {len(df)} symbols")

        current += delta

    print(f"\n✅ Rebuild complete. {snapshot_count} new snapshots saved.")


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Universe Builder")
    parser.add_argument("--top",          type=int,   default=30,            help="Top N symbols (default: 30)")
    parser.add_argument("--min-days",     type=int,   default=180,           help="Min listing days (default: 180)")
    parser.add_argument("--min-vol",      type=float, default=50_000_000,    help="Min 30D median daily vol USDT (default: 50M)")
    parser.add_argument("--rebuild-history", action="store_true",            help="Rebuild historical snapshots 2020~today")
    parser.add_argument("--freq-weeks",   type=int,   default=4,             help="Snapshot frequency in weeks (default: 4)")
    parser.add_argument("--query-date",   type=str,   default=None,          help="Query PIT universe on date YYYY-MM-DD")
    args = parser.parse_args()

    if args.query_date:
        df = get_universe_on_date(args.query_date)
        print(df.to_string(index=False))

    elif args.rebuild_history:
        rebuild_history(
            top_n=args.top,
            min_listing_days=args.min_days,
            min_volume_usdt=args.min_vol,
            frequency_weeks=args.freq_weeks,
        )

    else:
        df = build_universe(
            top_n=args.top,
            min_listing_days=args.min_days,
            min_volume_usdt=args.min_vol,
        )
        if not df.empty:
            now = datetime.now(timezone.utc)
            save_snapshot(df, now)
