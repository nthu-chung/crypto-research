"""
MVRV Z-Score Strategy Backtest v3
研究輪次: Round 3
"""

import requests, time, pandas as pd, numpy as np, json, os, secrets
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ─── 1. DATA FETCHING ───────────────────────────────────────────────────────

def fetch_coinmetrics(metrics="PriceUSD,CapMVRVCur", start="2011-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {
        "assets": "btc",
        "metrics": metrics,
        "frequency": "1d",
        "start_time": start,
        "page_size": 1000
    }
    while True:
        resp = requests.get(url, params=params, timeout=20)
        j = resp.json()
        all_data.extend(j.get('data', []))
        token = j.get('next_page_token')
        if not token:
            break
        params = {
            "assets": "btc",
            "metrics": metrics,
            "frequency": "1d",
            "page_size": 1000,
            "next_page_token": token
        }
        time.sleep(0.05)
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['time'])
    df['price'] = pd.to_numeric(df['PriceUSD'], errors='coerce')
    df['mvrv'] = pd.to_numeric(df['CapMVRVCur'], errors='coerce')
    df = df.dropna(subset=['price', 'mvrv'])
    return df.sort_values('date').reset_index(drop=True)

# ─── 2. MVRV Z-SCORE CALCULATION ─────────────────────────────────────────────

def compute_zscore(df, window=1460, min_periods=365):
    """Rolling 4-year (1460d) MVRV Z-Score, T-1 lag to avoid lookahead bias."""
    rolling_mean = df['mvrv'].rolling(window=window, min_periods=min_periods).mean()
    rolling_std  = df['mvrv'].rolling(window=window, min_periods=min_periods).std()
    df['zscore'] = (df['mvrv'] - rolling_mean) / rolling_std
    # Shift by 1: use T-1 zscore to decide T-day position
    df['zscore_lag'] = df['zscore'].shift(1)
    return df

# ─── 3. IS-PERIOD ZONE THRESHOLDS ────────────────────────────────────────────

HALVING_DATES = pd.to_datetime([
    '2012-11-28', '2016-07-09', '2020-05-11', '2024-04-20'
]).tz_localize('UTC')

def compute_is_thresholds(df, is_end='2019-12-31'):
    """Freeze IS-period Z-Score percentiles as zone boundaries."""
    is_end_ts = pd.Timestamp(is_end).tz_localize('UTC')
    is_data = df[df['date'] <= is_end_ts]['zscore_lag'].dropna()
    p20 = np.percentile(is_data, 20)
    p40 = np.percentile(is_data, 40)
    p60 = np.percentile(is_data, 60)
    p80 = np.percentile(is_data, 80)
    return {'p20': p20, 'p40': p40, 'p60': p60, 'p80': p80, 'is_data': is_data}

def zscore_to_position(z, thresholds):
    """Map Z-Score to position (0 to 1)."""
    if pd.isna(z):
        return np.nan
    p20, p40, p60, p80 = thresholds['p20'], thresholds['p40'], thresholds['p60'], thresholds['p80']
    if z < p20:
        return 1.00  # Zone 1
    elif z < p40:
        return 0.75  # Zone 2
    elif z < p60:
        return 0.50  # Zone 3
    elif z < p80:
        return 0.25  # Zone 4
    else:
        return 0.00  # Zone 5

def apply_halving_protection(df, positions, thresholds):
    """During 180 days after halving, Zone 4/5 minimum position = 30%."""
    protected = positions.copy()
    for hdate in HALVING_DATES:
        mask = (df['date'] >= hdate) & (df['date'] <= hdate + pd.Timedelta(days=180))
        protected[mask] = protected[mask].clip(lower=0.30)
    return protected

# ─── 4. ORIGINAL MVRV V2 BASELINE ────────────────────────────────────────────

def compute_mvrv_v2_position(mvrv_val, thresholds_mvrv):
    """Original MVRV (non-Z-Score) frozen IS percentile strategy."""
    if pd.isna(mvrv_val):
        return np.nan
    p20, p40, p60, p80 = thresholds_mvrv['p20'], thresholds_mvrv['p40'], thresholds_mvrv['p60'], thresholds_mvrv['p80']
    if mvrv_val < p20:
        return 1.00
    elif mvrv_val < p40:
        return 0.75
    elif mvrv_val < p60:
        return 0.50
    elif mvrv_val < p80:
        return 0.25
    else:
        return 0.00

# ─── 5. BACKTEST ENGINE ───────────────────────────────────────────────────────

def run_backtest(df, positions, fee_bps=4, initial_capital=10000.0, name="Strategy"):
    """
    Simple fractional position backtest.
    positions: Series of target BTC fraction (0..1) aligned to df index
    fee_bps: round-trip fee in bps per trade (applied to amount traded)
    """
    capital = initial_capital
    btc_held = 0.0
    nav = []
    fee_paid = 0.0
    n_trades = 0
    current_pos = 0.0

    prices = df['price'].values
    pos_vals = positions.values

    for i in range(len(df)):
        price = prices[i]
        target = pos_vals[i]

        if pd.isna(target):
            # No signal yet: hold current position
            nav.append(capital + btc_held * price)
            continue

        # Current portfolio value
        port_val = capital + btc_held * price

        # Target BTC value
        target_btc_val = port_val * target
        current_btc_val = btc_held * price

        delta = target_btc_val - current_btc_val

        if abs(delta) > 1e-6:
            # Apply fee on traded amount
            fee = abs(delta) * (fee_bps / 10000.0)
            fee_paid += fee
            n_trades += 1

            if delta > 0:
                # Buy BTC
                cost = delta + fee
                if cost > capital:
                    cost = capital
                    delta = cost - fee
                capital -= cost
                btc_held += delta / price
            else:
                # Sell BTC
                sell_btc = abs(delta) / price
                if sell_btc > btc_held:
                    sell_btc = btc_held
                btc_held -= sell_btc
                capital += sell_btc * price - fee

            current_pos = target

        nav.append(capital + btc_held * price)

    nav_series = pd.Series(nav, index=df.index)
    return nav_series, fee_paid, n_trades

# ─── 6. METRICS ───────────────────────────────────────────────────────────────

def compute_metrics(nav, df, label=""):
    """Compute full metrics from NAV series."""
    nav = nav.dropna()
    if len(nav) < 2:
        return {}

    dates = df.loc[nav.index, 'date']
    start_date = dates.iloc[0]
    end_date = dates.iloc[-1]
    years = (end_date - start_date).days / 365.25

    daily_ret = nav.pct_change().dropna()

    # CAGR
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1

    # Sharpe (daily, annualized, rf=0)
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0

    # Sortino
    neg_ret = daily_ret[daily_ret < 0]
    sortino = (daily_ret.mean() / neg_ret.std()) * np.sqrt(252) if len(neg_ret) > 0 and neg_ret.std() > 0 else 0

    # Max Drawdown
    rolling_max = nav.cummax()
    dd = (nav - rolling_max) / rolling_max
    max_dd = dd.min()

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Monthly win rate
    nav_dated = pd.Series(nav.values, index=dates.values)
    monthly = nav_dated.resample('ME').last().pct_change().dropna()
    monthly_wr = (monthly > 0).mean()

    return {
        'label': label,
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_dd': max_dd,
        'calmar': calmar,
        'monthly_wr': monthly_wr,
        'start': str(start_date.date()),
        'end': str(end_date.date()),
        'years': years,
        'final_nav': nav.iloc[-1],
        'initial_nav': nav.iloc[0],
        'total_return': nav.iloc[-1] / nav.iloc[0] - 1
    }

def metrics_for_period(nav, df, start=None, end=None, label=""):
    """Metrics for a specific date range."""
    dates = df['date']
    mask = pd.Series(True, index=df.index)
    if start:
        ts = pd.to_datetime(start).tz_localize('UTC')
        mask &= (dates >= ts)
    if end:
        ts = pd.to_datetime(end).tz_localize('UTC')
        mask &= (dates <= ts)
    nav_slice = nav[mask]
    df_slice = df[mask]
    return compute_metrics(nav_slice, df_slice, label=label)

# ─── 7. VISUALIZATION ─────────────────────────────────────────────────────────

def make_chart(df, navs_dict, zscore_col, thresholds, output_path):
    """
    3-panel dark background chart:
    Top: BTC price (log) + strategy NAV curves
    Mid: MVRV Z-Score time series + zone boundaries
    Bot: Annual return bar chart
    """
    BG = '#0d1117'
    GRID = '#1c2230'
    TEXT = '#c9d1d9'
    colors = {
        'zscore_pure':      '#00d4ff',
        'zscore_halving':   '#39ff14',
        'mvrv_v2':          '#ff8c00',
        'buy_hold':         '#ff4444',
        'price':            '#8b949e',
    }

    fig = plt.figure(figsize=(16, 14), facecolor=BG)
    gs = fig.add_gridspec(3, 1, hspace=0.35, height_ratios=[2, 1.5, 1.5])
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    for ax in [ax1, ax2, ax3]:
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT, labelsize=9)
        ax.spines['bottom'].set_color(GRID)
        ax.spines['top'].set_color(GRID)
        ax.spines['left'].set_color(GRID)
        ax.spines['right'].set_color(GRID)
        ax.yaxis.label.set_color(TEXT)
        ax.xaxis.label.set_color(TEXT)
        ax.title.set_color(TEXT)
        ax.grid(True, color=GRID, linewidth=0.5, alpha=0.7)

    # ── Panel 1: Price (log) + NAV ──────────────────────────────────────────
    dates = df['date']
    ax1_twin = ax1.twinx()
    ax1_twin.set_facecolor(BG)
    ax1_twin.tick_params(colors=TEXT, labelsize=9)
    ax1_twin.spines['right'].set_color(GRID)

    ax1.semilogy(dates, df['price'], color=colors['price'], linewidth=0.8, alpha=0.5, label='BTC Price (log)')

    labels_map = {
        'zscore_pure':    'MVRV Z-Score (no halving)',
        'zscore_halving': 'MVRV Z-Score + Halving',
        'mvrv_v2':        'MVRV v2 (baseline)',
        'buy_hold':       'Buy and Hold',
    }
    for key, nav in navs_dict.items():
        ax1_twin.plot(dates, nav, color=colors[key], linewidth=1.4, label=labels_map[key], alpha=0.9)

    ax1.set_ylabel('BTC Price USD (log)', color=TEXT, fontsize=9)
    ax1_twin.set_ylabel('Portfolio NAV (USD)', color=TEXT, fontsize=9)
    ax1.set_title('MVRV Z-Score Strategy v3 - NAV vs BTC Price', color=TEXT, fontsize=12, pad=10)

    lines1, lbls1 = ax1.get_legend_handles_labels()
    lines2, lbls2 = ax1_twin.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, lbls1 + lbls2, loc='upper left', fontsize=8,
               facecolor=BG, edgecolor=GRID, labelcolor=TEXT)

    # Mark halving dates
    for hdate in HALVING_DATES:
        ax1.axvline(hdate, color='#ffd700', linewidth=0.6, alpha=0.6, linestyle='--')

    # IS/OOS boundary
    is_end = pd.Timestamp('2019-12-31', tz='UTC')
    ax1.axvline(is_end, color='#ff6b6b', linewidth=1.0, alpha=0.8, linestyle=':')
    ax1.text(is_end, ax1.get_ylim()[0] * 2 if ax1.get_ylim()[0] > 0 else 100,
             'IS/OOS', color='#ff6b6b', fontsize=7, rotation=90, va='bottom')

    # ── Panel 2: MVRV Z-Score time series ───────────────────────────────────
    valid = df[zscore_col].notna()
    ax2.plot(dates[valid], df.loc[valid, zscore_col], color='#a0c4ff', linewidth=0.8, alpha=0.9)
    ax2.fill_between(dates[valid], df.loc[valid, zscore_col], 0, alpha=0.15, color='#a0c4ff')

    th = thresholds
    zone_colors = ['#00ff7f', '#90ee90', '#ffd700', '#ff8c00', '#ff4444']
    zone_labels = ['P20 Zone1/2', 'P40 Zone2/3', 'P60 Zone3/4', 'P80 Zone4/5']
    for val, lbl, col in zip([th['p20'], th['p40'], th['p60'], th['p80']], zone_labels, zone_colors):
        ax2.axhline(val, color=col, linewidth=0.9, alpha=0.8, linestyle='--')
        ax2.text(dates.iloc[-1], val, f' {lbl}\n {val:.2f}', color=col, fontsize=7, va='center')

    ax2.axhline(0, color=GRID, linewidth=0.6)
    ax2.set_ylabel('MVRV Z-Score', color=TEXT, fontsize=9)
    ax2.set_title('MVRV Z-Score Time Series + Zone Boundaries', color=TEXT, fontsize=11)

    for hdate in HALVING_DATES:
        ax2.axvline(hdate, color='#ffd700', linewidth=0.6, alpha=0.6, linestyle='--')
    ax2.axvline(is_end, color='#ff6b6b', linewidth=1.0, alpha=0.8, linestyle=':')

    # ── Panel 3: Annual return bar chart ─────────────────────────────────────
    all_years = sorted(df['date'].dt.year.unique())
    # compute annual returns for each strategy
    bar_width = 0.2
    strategy_keys = list(navs_dict.keys())
    strategy_colors = [colors[k] for k in strategy_keys]

    annual_rets = {k: [] for k in strategy_keys}
    for yr in all_years:
        yr_mask = df['date'].dt.year == yr
        for k, nav in navs_dict.items():
            nav_yr = nav[yr_mask].dropna()
            if len(nav_yr) >= 2:
                ret = nav_yr.iloc[-1] / nav_yr.iloc[0] - 1
            else:
                ret = 0
            annual_rets[k].append(ret * 100)

    x = np.arange(len(all_years))
    for i, (k, col) in enumerate(zip(strategy_keys, strategy_colors)):
        offset = (i - len(strategy_keys) / 2 + 0.5) * bar_width
        ax3.bar(x + offset, annual_rets[k], bar_width, color=col, alpha=0.8, label=labels_map[k])

    ax3.set_xticks(x)
    ax3.set_xticklabels([str(y) for y in all_years], rotation=45, fontsize=7)
    ax3.set_ylabel('Annual Return (%)', color=TEXT, fontsize=9)
    ax3.set_title('Annual Returns by Strategy', color=TEXT, fontsize=11)
    ax3.axhline(0, color=GRID, linewidth=0.8)
    ax3.legend(loc='upper right', fontsize=7, facecolor=BG, edgecolor=GRID, labelcolor=TEXT)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=BG)
    plt.close()
    print(f"Chart saved to {output_path}")

# ─── 8. MAIN ──────────────────────────────────────────────────────────────────

def main():
    print("Fetching BTC data from CoinMetrics...")
    df = fetch_coinmetrics(start="2011-01-01")
    print(f"  Loaded {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")

    # Compute Z-Score (with T-1 lag)
    df = compute_zscore(df)
    print(f"  Z-Score computed, {df['zscore_lag'].notna().sum()} valid rows")

    # IS period thresholds for Z-Score
    is_thresh_z = compute_is_thresholds(df, is_end='2019-12-31')
    print(f"  Z-Score thresholds: P20={is_thresh_z['p20']:.3f}, P40={is_thresh_z['p40']:.3f}, "
          f"P60={is_thresh_z['p60']:.3f}, P80={is_thresh_z['p80']:.3f}")

    # IS period thresholds for original MVRV
    df['mvrv_lag'] = df['mvrv'].shift(1)
    is_end_ts = pd.Timestamp('2019-12-31', tz='UTC')
    is_mvrv = df[(df['date'] <= is_end_ts)]['mvrv_lag'].dropna()
    mvrv_p20 = np.percentile(is_mvrv, 20)
    mvrv_p40 = np.percentile(is_mvrv, 40)
    mvrv_p60 = np.percentile(is_mvrv, 60)
    mvrv_p80 = np.percentile(is_mvrv, 80)
    is_thresh_mvrv = {'p20': mvrv_p20, 'p40': mvrv_p40, 'p60': mvrv_p60, 'p80': mvrv_p80}
    print(f"  MVRV v2 thresholds: P20={mvrv_p20:.3f}, P40={mvrv_p40:.3f}, "
          f"P60={mvrv_p60:.3f}, P80={mvrv_p80:.3f}")

    # --- Strategy 1: Z-Score Pure (no halving protection) ---
    pos_z_pure = df['zscore_lag'].apply(lambda z: zscore_to_position(z, is_thresh_z))
    # Only use rows with valid zscore
    pos_z_pure_valid = pos_z_pure.where(df['zscore_lag'].notna())

    # --- Strategy 2: Z-Score + Halving Protection ---
    pos_z_halving = apply_halving_protection(df, pos_z_pure_valid.copy(), is_thresh_z)

    # --- Strategy 3: MVRV v2 baseline ---
    pos_mvrv_v2 = df['mvrv_lag'].apply(lambda m: compute_mvrv_v2_position(m, is_thresh_mvrv))
    pos_mvrv_v2_valid = pos_mvrv_v2.where(df['mvrv_lag'].notna())

    # --- Strategy 4: Buy & Hold ---
    pos_bnh = pd.Series(1.0, index=df.index)

    print("\nRunning backtests...")
    nav_z_pure,    fee1, n1 = run_backtest(df, pos_z_pure_valid,   name="MVRV Z-Score Pure")
    nav_z_halving, fee2, n2 = run_backtest(df, pos_z_halving,      name="MVRV Z-Score + Halving")
    nav_mvrv_v2,   fee3, n3 = run_backtest(df, pos_mvrv_v2_valid,  name="MVRV v2 Baseline")
    nav_bnh,       fee4, n4 = run_backtest(df, pos_bnh,             name="Buy & Hold")

    print(f"  Z-Score Pure: {n1} trades, fees ${fee1:.2f}")
    print(f"  Z-Score + Halving: {n2} trades, fees ${fee2:.2f}")
    print(f"  MVRV v2: {n3} trades, fees ${fee3:.2f}")
    print(f"  Buy & Hold: {n4} trades, fees ${fee4:.2f}")

    navs = {
        'zscore_pure':    nav_z_pure,
        'zscore_halving': nav_z_halving,
        'mvrv_v2':        nav_mvrv_v2,
        'buy_hold':       nav_bnh,
    }

    # ── Full period metrics
    all_metrics = {}
    for key, nav in navs.items():
        all_metrics[key] = {
            'full':  metrics_for_period(nav, df, label=key),
            'is':    metrics_for_period(nav, df, end='2019-12-31', label=f"{key}_IS"),
            'oos':   metrics_for_period(nav, df, start='2020-01-01', label=f"{key}_OOS"),
            'y2024': metrics_for_period(nav, df, start='2024-01-01', end='2024-12-31', label=f"{key}_2024"),
        }

    # Print summary
    def fmt(m):
        if not m:
            return "N/A"
        return (f"CAGR={m.get('cagr',0)*100:.1f}% Sharpe={m.get('sharpe',0):.3f} "
                f"MaxDD={m.get('max_dd',0)*100:.1f}% Calmar={m.get('calmar',0):.2f} "
                f"WinRate={m.get('monthly_wr',0)*100:.1f}%")

    print("\n=== FULL PERIOD METRICS ===")
    for k in navs:
        print(f"  {k:20s}: {fmt(all_metrics[k]['full'])}")

    print("\n=== IS PERIOD (2011-2019) ===")
    for k in navs:
        print(f"  {k:20s}: {fmt(all_metrics[k]['is'])}")

    print("\n=== OOS PERIOD (2020-2026) ===")
    for k in navs:
        print(f"  {k:20s}: {fmt(all_metrics[k]['oos'])}")

    print("\n=== 2024 (Post-ETF) ===")
    for k in navs:
        print(f"  {k:20s}: {fmt(all_metrics[k]['y2024'])}")

    # ── Generate chart
    epoch = int(time.time())
    hex8 = secrets.token_hex(4)
    chart_path = f"/root/.openclaw/workspace/openclaw-media/jarvis-image-{epoch}-{hex8}.png"
    make_chart(df, navs, 'zscore_lag', is_thresh_z, chart_path)

    # ── Save results JSON
    def clean_metrics(m):
        r = {}
        for k, v in m.items():
            if k == 'is_data':
                continue
            if isinstance(v, (np.float64, np.float32, float)):
                r[k] = round(float(v), 6)
            elif isinstance(v, (np.int64, np.int32, int)):
                r[k] = int(v)
            else:
                r[k] = v
        return r

    results = {
        'strategies': {k: {period: clean_metrics(m) for period, m in v.items()} for k, v in all_metrics.items()},
        'thresholds': {
            'zscore': {k: float(v) for k, v in is_thresh_z.items() if k != 'is_data'},
            'mvrv_v2': {k: float(v) for k, v in is_thresh_mvrv.items()},
        },
        'trades': {
            'zscore_pure': n1,
            'zscore_halving': n2,
            'mvrv_v2': n3,
            'buy_hold': n4,
        },
        'chart': chart_path,
    }

    results_path = "/root/.openclaw/workspace/research/results_v3.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    return results, df, navs, all_metrics, is_thresh_z, chart_path

if __name__ == '__main__':
    results, df, navs, all_metrics, is_thresh_z, chart_path = main()
    print("\nDone.")
