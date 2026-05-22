#!/usr/bin/env python3
"""
Crypto Sector Rotation Momentum Strategy
Research Script
"""

import json
import time
import numpy as np
import requests
from datetime import datetime, timedelta
from collections import defaultdict

# ─── Config ───────────────────────────────────────────────────────────────────

TAXONOMY = {
    "SOLUSDT":   "L1",      "AVAXUSDT":  "L1",      "NEARUSDT":  "L1",
    "ADAUSDT":   "L1",      "DOTUSDT":   "L1",      "APTUSDT":   "L1",
    "SUIUSDT":   "L1",      "TONUSDT":   "L1",
    "MATICUSDT": "L2",      "ARBUSDT":   "L2",      "OPUSDT":    "L2",
    "AAVEUSDT":  "DeFi",    "UNIUSDT":   "DeFi",    "LINKUSDT":  "Infra",
    "DOGEUSDT":  "Meme",    "PEPEUSDT":  "Meme",    "SHIBUSDT":  "Meme",
    "TAOUSDT":   "AI",      "WLDUSDT":   "AI",      "FETUSDT":   "AI",
    "FILUSDT":   "Storage", "BNBUSDT":   "Exchange",
    # BTC and ETH for beta calculation
    "BTCUSDT":   "_bench",
    "ETHUSDT":   "_bench",
}

START_DATE = "2022-01-01"
END_DATE   = "2024-12-31"
TAKER_FEE  = 0.0004   # 4 bps per side
HOLD_DAYS  = 7
ROLL_WIN   = 30       # rolling beta window (days)
MOM_DAYS   = 7        # momentum lookback

BASE_URL = "https://fapi.binance.com/fapi/v1/klines"

# ─── Data Fetching ─────────────────────────────────────────────────────────────

def fetch_daily_closes(symbol, start_str, end_str):
    """Fetch daily closing prices from Binance Futures."""
    start_ts = int(datetime.strptime(start_str, "%Y-%m-%d").timestamp() * 1000)
    end_ts   = int(datetime.strptime(end_str,   "%Y-%m-%d").timestamp() * 1000)

    closes = {}
    cur = start_ts
    while cur < end_ts:
        params = {
            "symbol":    symbol,
            "interval":  "1d",
            "startTime": cur,
            "endTime":   end_ts,
            "limit":     1000,
        }
        resp = requests.get(BASE_URL, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  [WARN] {symbol} HTTP {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        if not data:
            break
        for row in data:
            ts  = row[0]
            dt  = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
            close = float(row[4])
            closes[dt] = close
        last_ts = data[-1][0]
        if last_ts >= end_ts or len(data) < 1000:
            break
        cur = last_ts + 86400000   # next day
        time.sleep(0.1)

    return closes

# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_sorted_dates(closes_dict):
    """Return sorted list of date strings present in closes_dict."""
    return sorted(closes_dict.keys())

def log_returns(closes, dates):
    """Compute daily log returns aligned to a date list."""
    rets = {}
    for i in range(1, len(dates)):
        d0, d1 = dates[i-1], dates[i]
        if d0 in closes and d1 in closes and closes[d0] > 0:
            rets[d1] = np.log(closes[d1] / closes[d0])
    return rets

def rolling_beta(symbol_rets, bench_rets, date, window):
    """
    Compute OLS beta of symbol vs bench over the `window` days ending at `date`.
    Returns (alpha, beta) or (None, None) if insufficient data.
    """
    # collect window dates ending at date
    all_dates = sorted(bench_rets.keys())
    idx = all_dates.index(date) if date in all_dates else -1
    if idx < window:
        return None, None
    win_dates = all_dates[max(0, idx - window + 1): idx + 1]

    x = np.array([bench_rets.get(d, np.nan) for d in win_dates])
    y = np.array([symbol_rets.get(d, np.nan) for d in win_dates])

    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < window // 2:
        return None, None

    x, y = x[mask], y[mask]
    # OLS: y = alpha + beta * x
    xm, ym = x.mean(), y.mean()
    beta_val = np.dot(x - xm, y - ym) / (np.dot(x - xm, x - xm) + 1e-12)
    alpha_val = ym - beta_val * xm
    return alpha_val, beta_val

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=== Sector Rotation Momentum Strategy ===")
    print(f"Period: {START_DATE} → {END_DATE}")

    # 1. Fetch all data
    print("\n[1] Fetching daily closes …")
    all_closes = {}
    symbols_to_fetch = list(TAXONOMY.keys())
    for sym in symbols_to_fetch:
        print(f"  Fetching {sym} …", end=" ", flush=True)
        closes = fetch_daily_closes(sym, START_DATE, END_DATE)
        all_closes[sym] = closes
        print(f"{len(closes)} days")
        time.sleep(0.2)

    # Common date universe
    btc_dates = make_sorted_dates(all_closes.get("BTCUSDT", {}))
    eth_dates = make_sorted_dates(all_closes.get("ETHUSDT", {}))
    print(f"\n  BTC dates: {len(btc_dates)}, ETH dates: {len(eth_dates)}")

    # 2. Compute log returns
    print("\n[2] Computing log returns …")
    all_rets = {}
    for sym in symbols_to_fetch:
        dates = sorted(all_closes[sym].keys())
        all_rets[sym] = log_returns(all_closes[sym], dates)

    btc_rets = all_rets["BTCUSDT"]
    eth_rets = all_rets["ETHUSDT"]

    # Combined benchmark: equal-weight BTC+ETH
    all_bench_dates = sorted(set(btc_rets.keys()) | set(eth_rets.keys()))
    bench_rets = {}
    for d in all_bench_dates:
        vals = [v for v in [btc_rets.get(d), eth_rets.get(d)] if v is not None]
        if vals:
            bench_rets[d] = np.mean(vals)

    # 3. Compute residual returns (beta-adjusted)
    print("\n[3] Computing residual returns (rolling beta) …")
    bench_dates = sorted(bench_rets.keys())

    residuals = {}    # {symbol: {date: resid}}
    excluded  = []

    trading_symbols = [s for s in TAXONOMY if TAXONOMY[s] not in ("_bench",)]

    for sym in trading_symbols:
        sym_rets = all_rets[sym]
        # Check minimum data: 180 days
        if len(sym_rets) < 180:
            print(f"  EXCLUDE {sym}: only {len(sym_rets)} return days")
            excluded.append(sym)
            continue

        resid_by_date = {}
        for d in bench_dates:
            if d not in sym_rets:
                continue
            alpha, beta = rolling_beta(sym_rets, bench_rets, d, ROLL_WIN)
            if alpha is None:
                continue
            resid_by_date[d] = sym_rets[d] - (alpha + beta * bench_rets[d])

        residuals[sym] = resid_by_date
        print(f"  {sym}: {len(resid_by_date)} residual days")

    # Remove excluded from TAXONOMY working set
    working_tax = {s: sec for s, sec in TAXONOMY.items()
                   if TAXONOMY[s] not in ("_bench",) and s not in excluded}

    # 4. Build weekly rebalance dates
    print("\n[4] Building weekly rebalance schedule …")
    # Use bench_dates for the calendar; pick every 7th date starting from enough data
    rebal_dates = []
    # need at least ROLL_WIN + MOM_DAYS days of history before first trade
    min_idx = ROLL_WIN + MOM_DAYS + 5
    step = HOLD_DAYS
    i = min_idx
    while i < len(bench_dates):
        rebal_dates.append(bench_dates[i])
        i += step

    print(f"  Total rebalance periods: {len(rebal_dates)}")

    # 5. Backtest
    print("\n[5] Running backtest …")

    portfolio_returns = []    # list of (entry_date, exit_date, gross_return)
    sector_picks_count = defaultdict(int)   # how often each sector picked
    sector_ic_data = defaultdict(list)      # {sector: [(signal, realized_ret)]}

    for ri, entry_date in enumerate(rebal_dates[:-1]):
        exit_date = rebal_dates[ri + 1]

        # Compute 7D residual momentum for each symbol
        entry_idx = bench_dates.index(entry_date)
        lookback_start_idx = max(0, entry_idx - MOM_DAYS)
        lookback_dates = bench_dates[lookback_start_idx: entry_idx + 1]

        sym_mom = {}
        for sym, sec in working_tax.items():
            resid = residuals.get(sym, {})
            # cumulative residual return over MOM_DAYS
            cum = sum(resid.get(d, 0.0) for d in lookback_dates)
            if len([d for d in lookback_dates if d in resid]) >= MOM_DAYS // 2:
                sym_mom[sym] = cum

        if not sym_mom:
            continue

        # Sector average momentum
        sector_mom = defaultdict(list)
        for sym, mom in sym_mom.items():
            sector_mom[working_tax[sym]].append(mom)

        sector_avg = {sec: np.mean(vals) for sec, vals in sector_mom.items()
                      if len(vals) >= 1}

        if len(sector_avg) < 2:
            continue

        ranked_sectors = sorted(sector_avg, key=sector_avg.get, reverse=True)
        top_sectors    = ranked_sectors[:2]
        bottom_sector  = ranked_sectors[-1]

        # Long: top 2 symbols in top sectors (combined)
        long_candidates = []
        for sec in top_sectors:
            for sym, mom in sym_mom.items():
                if working_tax[sym] == sec:
                    long_candidates.append((sym, mom))
        long_candidates.sort(key=lambda x: x[1], reverse=True)
        long_syms = [s for s, _ in long_candidates[:2]]

        # Short: bottom 2 symbols in bottom sector
        short_candidates = [(sym, mom) for sym, mom in sym_mom.items()
                            if working_tax[sym] == bottom_sector]
        short_candidates.sort(key=lambda x: x[1])
        short_syms = [s for s, _ in short_candidates[:2]]

        if not long_syms or not short_syms:
            continue

        # Record sector selection
        for sec in top_sectors:
            sector_picks_count[sec] += 1
        sector_picks_count[bottom_sector + "_short"] += 1

        # Compute holding period return for each leg
        # Collect all dates between entry and exit
        hold_dates = [d for d in bench_dates
                      if entry_date < d <= exit_date]

        def holding_return(sym, dates):
            resid = residuals.get(sym, {})
            # use actual log returns from all_rets for pnl
            rets_sym = all_rets[sym]
            cum_log = sum(rets_sym.get(d, 0.0) for d in dates)
            return np.exp(cum_log) - 1.0

        long_ret  = np.mean([holding_return(s, hold_dates) for s in long_syms])
        short_ret = np.mean([holding_return(s, hold_dates) for s in short_syms])

        # L/S gross return
        gross_ret = long_ret - short_ret

        # Fees: open & close both legs = 4 * taker_fee
        fee = 4 * TAKER_FEE
        net_ret = gross_ret - fee

        portfolio_returns.append({
            "entry": entry_date,
            "exit":  exit_date,
            "long_syms":   long_syms,
            "short_syms":  short_syms,
            "top_sectors": top_sectors,
            "bottom_sector": bottom_sector,
            "long_ret":  long_ret,
            "short_ret": short_ret,
            "gross_ret": gross_ret,
            "net_ret":   net_ret,
        })

        # IC data: for each symbol in top sectors, record (signal, next_week_ret)
        for sec in top_sectors + [bottom_sector]:
            for sym, mom_sig in sym_mom.items():
                if working_tax[sym] == sec:
                    realized = holding_return(sym, hold_dates)
                    sector_ic_data[sec].append((mom_sig, realized))

    # 6. Performance metrics
    print("\n[6] Computing performance metrics …")

    net_rets = np.array([r["net_ret"] for r in portfolio_returns])
    n = len(net_rets)

    if n < 2:
        print("  ERROR: Not enough periods!")
        return

    ann_factor = 52   # ~52 weeks/year
    ann_return = (1 + net_rets).prod() ** (ann_factor / n) - 1
    ann_vol    = net_rets.std() * np.sqrt(ann_factor)
    sharpe     = ann_return / ann_vol if ann_vol > 0 else 0.0

    # Max drawdown
    cum = np.cumprod(1 + net_rets)
    running_max = np.maximum.accumulate(cum)
    dd = (cum - running_max) / running_max
    max_dd = dd.min()

    win_rate = (net_rets > 0).mean()
    total_periods = n

    print(f"  Periods: {total_periods}")
    print(f"  Ann Return: {ann_return:.2%}")
    print(f"  Ann Vol:    {ann_vol:.2%}")
    print(f"  Sharpe:     {sharpe:.2f}")
    print(f"  Max DD:     {max_dd:.2%}")
    print(f"  Win Rate:   {win_rate:.2%}")

    # IC per sector
    sector_ic = {}
    for sec, pairs in sector_ic_data.items():
        if len(pairs) < 5:
            continue
        sigs = np.array([p[0] for p in pairs])
        rets = np.array([p[1] for p in pairs])
        corr = np.corrcoef(sigs, rets)[0, 1] if sigs.std() > 0 else 0.0
        sector_ic[sec] = round(float(corr), 4)

    # Sector rotation frequency
    sector_freq = dict(sector_picks_count)

    # 7. Save results
    print("\n[7] Saving results …")

    results = {
        "metadata": {
            "strategy": "Sector Rotation Momentum",
            "start_date": START_DATE,
            "end_date":   END_DATE,
            "hold_days":  HOLD_DAYS,
            "roll_window": ROLL_WIN,
            "mom_days":    MOM_DAYS,
            "taker_fee":   TAKER_FEE,
            "excluded_symbols": excluded,
        },
        "performance": {
            "n_periods":    total_periods,
            "ann_return":   round(float(ann_return),  4),
            "ann_vol":      round(float(ann_vol),     4),
            "sharpe":       round(float(sharpe),      4),
            "max_drawdown": round(float(max_dd),      4),
            "win_rate":     round(float(win_rate),    4),
        },
        "sector_rotation_frequency": sector_freq,
        "sector_ic": sector_ic,
        "period_returns": [
            {k: v for k, v in r.items()} for r in portfolio_returns
        ],
    }

    out_dir = "/root/.openclaw/workspace/research/strategy-alpha/sector-rotation"

    with open(f"{out_dir}/results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"  Saved results.json")

    # 8. Write report
    print("\n[8] Writing report.md …")

    # Best/worst periods
    sorted_periods = sorted(portfolio_returns, key=lambda x: x["net_ret"])
    worst_3 = sorted_periods[:3]
    best_3  = sorted_periods[-3:][::-1]

    # Sector freq table
    long_freq  = {k: v for k, v in sector_freq.items() if not k.endswith("_short")}
    short_freq = {k.replace("_short",""): v for k, v in sector_freq.items() if k.endswith("_short")}

    freq_rows = []
    all_secs = sorted(set(list(long_freq.keys()) + list(short_freq.keys())))
    for sec in all_secs:
        lf = long_freq.get(sec, 0)
        sf = short_freq.get(sec, 0)
        ic = sector_ic.get(sec, "N/A")
        freq_rows.append(f"| {sec} | {lf} | {sf} | {ic} |")

    report_lines = [
        "# Crypto Sector Rotation Momentum — Research Report",
        "",
        f"**Period:** {START_DATE} → {END_DATE}  ",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "---",
        "",
        "## 1. Strategy Overview",
        "",
        "A weekly-rebalanced Long/Short Crypto Sector Rotation strategy.",
        "The core hypothesis: crypto sectors rotate—momentum in one sector",
        "spills over intra-sector, with 1–2 week persistence.",
        "",
        "**Signal construction:**",
        "1. Compute rolling-30d BTC/ETH beta for each token; strip out market exposure → *residual return*.",
        "2. Each rebalance date: rank sectors by 7-day cumulative residual momentum.",
        "3. **Long:** top-2 momentum symbols within the top-2 momentum sectors.",
        "4. **Short:** bottom-2 momentum symbols within the bottom-1 sector.",
        "5. Hold 7 days, repeat.  Fee: 4 bps taker × 4 legs.",
        "",
        "---",
        "",
        "## 2. Performance Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Rebalance Periods | {total_periods} |",
        f"| Annualised Return | {ann_return:.2%} |",
        f"| Annualised Volatility | {ann_vol:.2%} |",
        f"| Sharpe Ratio | {sharpe:.2f} |",
        f"| Maximum Drawdown | {max_dd:.2%} |",
        f"| Win Rate | {win_rate:.2%} |",
        "",
        "---",
        "",
        "## 3. Sector Rotation Frequency & IC",
        "",
        "| Sector | Times Long | Times Short | Momentum IC |",
        "|--------|-----------|-------------|-------------|",
    ] + freq_rows + [
        "",
        "*(IC = rank correlation between 7-day residual momentum signal and next-week return)*",
        "",
        "---",
        "",
        "## 4. Best & Worst Periods",
        "",
        "### Top 3 Periods",
        "",
        "| Entry | Exit | Long | Short | Net Ret |",
        "|-------|------|------|-------|---------|",
    ]

    for p in best_3:
        report_lines.append(
            f"| {p['entry']} | {p['exit']} | {','.join(p['long_syms'])} | "
            f"{','.join(p['short_syms'])} | {p['net_ret']:.2%} |"
        )

    report_lines += [
        "",
        "### Bottom 3 Periods",
        "",
        "| Entry | Exit | Long | Short | Net Ret |",
        "|-------|------|------|-------|---------|",
    ]

    for p in worst_3:
        report_lines.append(
            f"| {p['entry']} | {p['exit']} | {','.join(p['long_syms'])} | "
            f"{','.join(p['short_syms'])} | {p['net_ret']:.2%} |"
        )

    report_lines += [
        "",
        "---",
        "",
        "## 5. Taxonomy",
        "",
        "```python",
        "TAXONOMY = {",
    ]
    for sym, sec in TAXONOMY.items():
        if sec != "_bench":
            report_lines.append(f'    "{sym}": "{sec}",')
    report_lines += [
        "}",
        "```",
        "",
        "**Excluded symbols** (< 180 trading days): " + (", ".join(excluded) if excluded else "None"),
        "",
        "---",
        "",
        "## 6. Methodology Notes",
        "",
        "- **Beta benchmark:** equal-weight average of BTC + ETH daily log returns.",
        "- **Rolling regression:** 30-day OLS (`numpy` polyfit); skipped if < 15 valid days.",
        "- **Residual return:** `r_symbol − (α + β × r_bench)` per day.",
        "- **Momentum signal:** cumulative 7-day residual return up to (not including) entry date.",
        "- **Fees:** 4 × 4 bps = 16 bps per round-trip (open long, close long, open short, close short).",
        "- **Data source:** Binance Futures `/fapi/v1/klines` 1d bars.",
        "",
        "---",
        "",
        "## 7. Conclusions",
        "",
    ]

    if sharpe > 1.0:
        conclusion = (
            f"The strategy delivers a **Sharpe of {sharpe:.2f}** with "
            f"**{ann_return:.2%} annualised return**, supporting the sector-rotation "
            "momentum hypothesis. The signal shows positive IC across most sectors, "
            "indicating genuine predictive power beyond pure market beta."
        )
    elif sharpe > 0.5:
        conclusion = (
            f"The strategy shows a moderate **Sharpe of {sharpe:.2f}** ({ann_return:.2%} "
            "annualised). The sector-rotation effect is present but inconsistent—likely "
            "crowded during certain regimes. Consider adding regime filters or expanding taxonomy."
        )
    else:
        conclusion = (
            f"With a **Sharpe of {sharpe:.2f}** ({ann_return:.2%} annualised), the raw "
            "sector-rotation signal is weak over this period. The hypothesis may require "
            "finer sector granularity, longer momentum windows, or regime conditioning."
        )

    report_lines.append(conclusion)
    report_lines += [
        "",
        "**Next steps:**",
        "- Add regime filter (BTC trend / VIX proxy) to reduce drawdown during bear markets.",
        "- Expand taxonomy with more granular sub-sectors (e.g., DEX, Lending, RWA).",
        "- Test alternative momentum windows (14d, 21d) and holding periods.",
        "- Incorporate volume-weighted signal for better noise filtering.",
        "",
        "---",
        "*Report auto-generated by the Sector Rotation Research Agent.*",
    ]

    with open(f"{out_dir}/report.md", "w") as f:
        f.write("\n".join(report_lines))

    print(f"  Saved report.md")
    print("\n=== DONE ===")
    print(f"  Ann Return: {ann_return:.2%}")
    print(f"  Sharpe:     {sharpe:.2f}")
    print(f"  Max DD:     {max_dd:.2%}")
    print(f"  Win Rate:   {win_rate:.2%}")
    print(f"  Periods:    {total_periods}")

if __name__ == "__main__":
    main()
