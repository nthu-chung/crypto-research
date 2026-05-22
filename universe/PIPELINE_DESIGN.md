# Cross-Sectional Crypto Alpha — 完整設計流程

> 從 Universe 建立、資料取得、信號構建到回測執行的端對端說明。  
> 以 **Funding Rate Cross-Sectional** 策略為主線範例。

---

## 一、整體架構

```
┌─────────────────────────────────────────────────────────────┐
│                    Alpha Research Pipeline                   │
│                                                             │
│  Universe Builder                                           │
│  ┌──────────────────────────────────┐                       │
│  │ Binance Futures API              │                       │
│  │ → 篩選條件（volume/days/type）    │                       │
│  │ → Point-in-Time Snapshot（每4週） │                       │
│  │ → taxonomy.py（sector 分類）      │                       │
│  └──────────────────────────────────┘                       │
│            ↓                                                │
│  Data Layer                                                 │
│  ┌──────────────────────────────────┐                       │
│  │ K-bar（1d/1h）                   │                       │
│  │ Funding Rate History（8h）        │                       │
│  │ Open Interest History（1d）       │                       │
│  └──────────────────────────────────┘                       │
│            ↓                                                │
│  Signal Construction                                        │
│  ┌──────────────────────────────────┐                       │
│  │ Raw Signal                       │                       │
│  │ → BTC/ETH Beta Neutralization    │                       │
│  │ → Sector Neutralization          │                       │
│  │ → Winsorize / Vol Scaling        │                       │
│  │ → Signal Gate（門檻過濾）         │                       │
│  └──────────────────────────────────┘                       │
│            ↓                                                │
│  Portfolio Construction                                     │
│  ┌──────────────────────────────────┐                       │
│  │ Long top 20-30% / Short bottom   │                       │
│  │ Equal weight or Inv-Vol weight   │                       │
│  │ Rebalance: 1d / 7d               │                       │
│  └──────────────────────────────────┘                       │
│            ↓                                                │
│  Backtest（cyqnt-trd standard_bot）                         │
│  ┌──────────────────────────────────┐                       │
│  │ mvp_backtest → NumbaBacktestRunner│                      │
│  │ IS/OOS split or Walk-Forward     │                       │
│  │ 費用：taker 4bps + funding cost  │                       │
│  └──────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、Universe 設計

### 2.1 篩選流程

```python
# universe_builder.py 核心邏輯
def build_universe(top_n=30, min_listing_days=180, min_volume_usdt=50_000_000):

    # Step 1: 取所有 USDT perp 合約
    contracts = get_exchange_info()   # fapi.binance.com/fapi/v1/exchangeInfo

    # Step 2: 過濾條件
    filtered = [c for c in contracts if
        c['quoteAsset'] == 'USDT' and
        c['contractType'] == 'PERPETUAL' and
        c['status'] == 'TRADING' and
        c['symbol'] not in EXCLUDE_ALWAYS and      # 排除 BTC/ETH/穩定幣
        listing_days(c) > min_listing_days          # 上市 > 180 天
    ]

    # Step 3: 抓 30D 中位數交易量
    for symbol in filtered:
        vol = get_klines_30d_median_volume(symbol)  # fapi/v1/klines?interval=1d&limit=30

    # Step 4: 取 Top N by volume
    return top_n_by_volume(filtered)
```

### 2.2 Point-in-Time 快照

- 每 4 週建立一個快照（`snapshots/universe_YYYY-MM-DD.csv`）
- 回測時根據當時日期查詢最近的快照 → `get_universe_on_date("2022-01-15")`
- 共 81 個快照，覆蓋 2020-03 ~ 2026-05

### 2.3 Taxonomy 分類

```python
TAXONOMY = {
    "SOLUSDT":  {"category": "L1",   "bucket": "high_beta"},
    "ARBUSDT":  {"category": "L2",   "bucket": "high_beta"},
    "AAVEUSDT": {"category": "DeFi", "bucket": "mid_beta"},
    "DOGEUSDT": {"category": "Meme", "bucket": "meme"},
    "TAOUSDT":  {"category": "AI",   "bucket": "high_beta"},
    # ...
    "BTCUSDT":  {"category": "RF",   "bucket": "rf_btc"},  # Risk Factor
    "ETHUSDT":  {"category": "RF",   "bucket": "rf_eth"},  # Risk Factor
}
```

---

## 三、Funding Rate Cross-Sectional 策略詳解

### 3.1 核心假說

```
Funding rate 代表持有槓桿方向倉位的成本：

正向 funding（多頭付空頭）→ 多頭過度擁擠 → 短期反轉風險
  信號：做空 funding 最高的幣

負向 funding（空頭付多頭）→ 空頭過度擁擠 → 短期軋空風險
  信號：做多 funding 最低（最負）的幣
```

### 3.2 資料取得

```python
# Binance Futures 公開 API，不需要 API Key

# 1. 取 funding rate 歷史（每 8 小時一筆，最多 1000 筆）
GET https://fapi.binance.com/fapi/v1/fundingRate
    ?symbol=SOLUSDT
    &startTime=1672531200000  # 2023-01-01
    &limit=1000

# 回傳格式：
[
  {
    "symbol": "SOLUSDT",
    "fundingTime": 1672560000000,   # UTC 時間戳
    "fundingRate": "0.00010000",    # 0.01%
    "markPrice": "9.876"
  },
  ...
]

# 2. 取每日 K 線（計算報酬用）
GET https://fapi.binance.com/fapi/v1/klines
    ?symbol=SOLUSDT
    &interval=1d
    &limit=730
```

### 3.3 信號構建

```python
import pandas as pd
import numpy as np

def build_funding_signal(funding_df, price_df):
    """
    funding_df: columns=[symbol, datetime, funding_rate]
    price_df:   columns=[symbol, date, close]
    """

    # Step 1: 每日最後一個 funding 結算值（16:00 UTC）
    daily_funding = (
        funding_df
        .groupby(['date', 'symbol'])['funding_rate']
        .last()
        .unstack()   # shape: [date × symbol]
    )

    # Step 2: 橫截面 z-score（每日對所有幣標準化）
    funding_mean = daily_funding.mean(axis=1)
    funding_std  = daily_funding.std(axis=1)
    z_score = daily_funding.sub(funding_mean, axis=0).div(funding_std, axis=0)

    # Step 3: 反向信號（funding 越高 → 信號越低 → 傾向做空）
    signal = -1 * z_score

    # Step 4: 信號門檻過濾（關鍵！）
    # 只在有幣的 |funding| >= 0.05% 時才交易
    max_abs_funding = daily_funding.abs().max(axis=1)
    active_days = max_abs_funding >= 0.0005  # 0.05%

    signal_filtered = signal.copy()
    signal_filtered[~active_days] = np.nan   # 無信號日設為 NaN → 不交易

    return signal_filtered
```

### 3.4 組合建構

```python
def build_portfolio(signal, top_pct=0.3):
    """
    每個交易日，根據信號排名決定倉位
    """
    positions = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)

    for date in signal.index:
        row = signal.loc[date].dropna()
        if row.isna().all():
            continue   # 無信號日，全部空倉

        n = len(row)
        n_long  = max(1, int(n * top_pct))
        n_short = max(1, int(n * top_pct))

        # 排名最高的做多，最低的做空
        ranked = row.rank(ascending=False)
        longs  = ranked[ranked <= n_long].index
        shorts = ranked[ranked > n - n_short].index

        # 等權重，美元中性
        positions.loc[date, longs]  = +1.0 / n_long
        positions.loc[date, shorts] = -1.0 / n_short

    return positions
```

### 3.5 回測邏輯

```python
def backtest(positions, price_df, fee_bps=4):
    """
    positions: [date × symbol]，值為倉位權重
    price_df:  [date × symbol]，值為收盤價
    fee_bps:   單邊 taker 費用（4 bps = 0.04%）
    """
    # 每日報酬
    returns = price_df.pct_change()

    # 策略報酬（持倉 × 次日報酬）
    strategy_returns = (positions.shift(1) * returns).sum(axis=1)

    # 交易成本（每次換倉的絕對權重變化 × fee）
    turnover = positions.diff().abs().sum(axis=1)
    cost = turnover * fee_bps / 10000

    net_returns = strategy_returns - cost

    # 績效指標
    sharpe = net_returns.mean() / net_returns.std() * np.sqrt(365)
    cagr   = (1 + net_returns).prod() ** (365 / len(net_returns)) - 1
    maxdd  = (1 + net_returns).cumprod().div(
                 (1 + net_returns).cumprod().cummax()
             ).min() - 1

    return {
        "sharpe": round(sharpe, 3),
        "cagr":   round(cagr * 100, 1),
        "maxdd":  round(maxdd * 100, 1),
        "win_rate": round((net_returns > 0).mean() * 100, 1),
        "n_trades": int(turnover.sum() * 1000),  # 估算
    }
```

### 3.6 回測結果

| 版本 | Sharpe | 年化報酬 | MaxDD | 勝率 | 有效交易天數 |
|------|--------|---------|-------|------|------------|
| 無門檻（每日交易） | -3.42 | -28.4% | -64.7% | 30.8% | 730 天 |
| **｜f｜≥ 0.05%** | **+1.58** | **+58.1%** | **-8.7%** | **51.4%** | **35 天** |

#### 為什麼無門檻版本會失敗？

```
年化交易成本計算：
  每日換倉率 ~30%（long/short 各換 ~15%）
  單邊 4bps × 2 腿 × 2（進出）= 16 bps/day
  16 bps × 252 交易日 = ~40% 年化成本

結論：策略的 gross alpha 遠低於 40%，被交易成本吃掉
```

#### 門檻效果的非線性

```
|funding| < 0.01%：純噪音，無 alpha
|funding| 0.01~0.05%：信號弱，成本 > alpha
|funding| ≥ 0.05%：極端擁擠，alpha 顯著超過成本 ✅
```

---

## 四、從回測到實際交易

### 4.1 監控流程（每 8 小時執行一次）

```python
def monitor_funding(universe_symbols):
    """
    每次 funding 結算前 5 分鐘執行
    結算時間：00:00, 08:00, 16:00 UTC
    """

    # 1. 取得所有幣最新 funding rate
    current_funding = {}
    for sym in universe_symbols:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": sym}
        )
        current_funding[sym] = float(resp.json()['lastFundingRate'])

    # 2. 檢查是否觸發門檻
    max_abs = max(abs(f) for f in current_funding.values())

    if max_abs < 0.0005:  # 0.05%
        print("No extreme funding detected, staying flat")
        return None

    # 3. 計算橫截面 z-score
    values = list(current_funding.values())
    mean_f = np.mean(values)
    std_f  = np.std(values)
    z_scores = {sym: -(f - mean_f) / std_f
                for sym, f in current_funding.items()}

    # 4. 建立倉位
    sorted_signals = sorted(z_scores.items(), key=lambda x: x[1], reverse=True)
    n = len(sorted_signals)
    n_side = max(1, int(n * 0.3))

    longs  = [s[0] for s in sorted_signals[:n_side]]
    shorts = [s[0] for s in sorted_signals[-n_side:]]

    return {"longs": longs, "shorts": shorts, "trigger": max_abs}
```

### 4.2 下單邏輯

```
進場條件：
  max(|funding_rate|) >= 0.05%
  → long 信號最低 30%（最負 funding）
  → short 信號最高 30%（最正 funding）

出場條件：
  持有 1 天後平倉（等下一個 8h 結算後）
  OR 持倉虧損 > 3% 止損
  OR funding 回歸正常（|f| < 0.02%）

倉位大小：
  每腿等權重，總倉位 = 可用資金的 X%
  建議從小倉位開始（5-10%）

費用：
  進出各 taker 4bps = 每趟 8bps × 2 腿 = 16bps round-trip
```

### 4.3 風險控制

| 風控 | 設定 |
|------|------|
| 單日最大虧損 | -2% 停止當日交易 |
| 單倉最大虧損 | -3% 立即平倉 |
| 最大同時持倉 | Long 腿 ≤ 5 個，Short 腿 ≤ 5 個 |
| Funding 二次確認 | 確認 funding 方向在過去 3 個結算週期一致 |
| 流動性過濾 | 只交易 24h volume > 100M USDT 的幣 |

---

## 五、待驗證項目

| 問題 | 重要程度 | 方法 |
|------|---------|------|
| 2020-2022 完整牛熊週期是否穩健？ | 🔴 高 | 擴展回測期間 |
| 門檻 0.05% 是否 overfitting？ | 🔴 高 | Walk-forward 驗證 |
| 加入 OI 確認是否提升信號品質？ | 🟡 中 | 結合 OI-divergence |
| 多空各自的表現分析 | 🟡 中 | 分開回測 long-only / short-only |
| 結算時間差（資料延遲）的影響 | 🟢 低 | 確認 API 回傳時間 |

---

*最後更新：2026-05-21*
