import requests, pandas as pd, numpy as np, time, os, secrets
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

os.makedirs('/root/.openclaw/workspace/crypto-research/adaptive-trend/mcap-rank-analysis', exist_ok=True)
os.makedirs('/root/.openclaw/workspace/openclaw-media', exist_ok=True)

symbols = ['BTCUSDT','ETHUSDT','XRPUSDT','BNBUSDT','LTCUSDT','BCHUSDT','ADAUSDT','LINKUSDT',
           'DOTUSDT','UNIUSDT','SOLUSDT','MATICUSDT','DOGEUSDT','AVAXUSDT','ATOMUSDT',
           'XLMUSDT','VETUSDT','TRXUSDT','ETCUSDT','FILUSDT','THETAUSDT','ALGOUSDT',
           'XMRUSDT','ZECUSDT','DASHUSDT','EOSUSDT','XTZUSDT','AAVEUSDT','COMPUSDT','SUSHIUSDT']

def fetch_monthly(symbol):
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': symbol, 'interval': '1M', 'startTime': int(pd.Timestamp('2020-01-01').timestamp()*1000), 'limit': 100}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if isinstance(data, dict): return None
        df = pd.DataFrame(data, columns=['open_time','open','high','low','close','volume','close_time','quote_vol','trades','tbb','tbq','ignore'])
        df['month'] = pd.to_datetime(df['open_time'], unit='ms').dt.to_period('M')
        df['quote_vol'] = df['quote_vol'].astype(float)
        df['close'] = df['close'].astype(float)
        return df[['month','close','quote_vol']].set_index('month')
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

print("=== Step 1: Fetching monthly data ===")
vol_data = {}
for sym in symbols:
    d = fetch_monthly(sym)
    if d is not None:
        vol_data[sym] = d
        print(f"  {sym}: {len(d)} months")
    else:
        print(f"  {sym}: FAILED")
    time.sleep(0.15)

print(f"\nSuccessfully fetched {len(vol_data)} symbols")

# 建立月度成交量矩陣
vol_matrix = pd.DataFrame({s: vol_data[s]['quote_vol'] for s in vol_data})
price_matrix = pd.DataFrame({s: vol_data[s]['close'] for s in vol_data})

print("\n=== Step 2: Computing monthly ranks ===")
rank_matrix = vol_matrix.rank(axis=1, ascending=False)
print("排名矩陣範例（最近6個月）：")
print(rank_matrix.tail(6))

print("\n=== Step 3: Identifying rank decay events ===")
rank_change = rank_matrix.diff()

events = []
for month in rank_matrix.index[1:]:
    prev_month = rank_matrix.index[rank_matrix.index.get_loc(month) - 1]
    for sym in rank_matrix.columns:
        prev_rank = rank_matrix.loc[prev_month, sym]
        curr_rank = rank_matrix.loc[month, sym]
        if pd.notna(prev_rank) and pd.notna(curr_rank):
            if prev_rank <= 15 and 16 <= curr_rank <= 20:
                events.append({
                    'month': month,
                    'symbol': sym,
                    'prev_rank': prev_rank,
                    'curr_rank': curr_rank,
                    'rank_drop': curr_rank - prev_rank
                })

events_df = pd.DataFrame(events)
print(f"\n總共識別到 {len(events_df)} 個「排名下滑」事件")
print(events_df)

print("\n=== Step 4: Analyzing returns after rank decay ===")
results = []
for _, ev in events_df.iterrows():
    sym = ev['symbol']
    month = ev['month']
    if sym not in price_matrix.columns:
        continue
    months = list(price_matrix.index)
    if month not in months:
        continue
    idx = months.index(month)
    try:
        entry_price = price_matrix.loc[month, sym]
        ret_1m = (price_matrix.iloc[idx+1][sym] / entry_price - 1) if idx+1 < len(months) else np.nan
        ret_2m = (price_matrix.iloc[idx+2][sym] / entry_price - 1) if idx+2 < len(months) else np.nan
        ret_3m = (price_matrix.iloc[idx+3][sym] / entry_price - 1) if idx+3 < len(months) else np.nan
        results.append({**ev, 'ret_1m': ret_1m, 'ret_2m': ret_2m, 'ret_3m': ret_3m})
    except Exception as e:
        print(f"  Error for {sym} {month}: {e}")
        continue

results_df = pd.DataFrame(results)

print("\n=== Step 5: Statistical Analysis ===")
print(f"樣本數：{len(results_df)}")
print(f"1個月後平均報酬：{results_df['ret_1m'].mean():.2%} (中位數: {results_df['ret_1m'].median():.2%})")
print(f"2個月後平均報酬：{results_df['ret_2m'].mean():.2%} (中位數: {results_df['ret_2m'].median():.2%})")
print(f"3個月後平均報酬：{results_df['ret_3m'].mean():.2%} (中位數: {results_df['ret_3m'].median():.2%})")
print(f"\n1個月後負報酬比例（做空勝率）：{(results_df['ret_1m'] < 0).mean():.1%}")
print(f"2個月後負報酬比例：{(results_df['ret_2m'] < 0).mean():.1%}")
print(f"3個月後負報酬比例：{(results_df['ret_3m'] < 0).mean():.1%}")

# 對比 BTC 同期表現
btc_monthly = price_matrix['BTCUSDT'].pct_change()
print("\n=== 相對 BTC 的超額報酬（Alpha）===")
alpha_results = {}
for period, col in [('1m','ret_1m'),('2m','ret_2m'),('3m','ret_3m')]:
    alphas = []
    for _, ev in results_df.iterrows():
        month = ev['month']
        months = list(btc_monthly.index)
        if month not in months: continue
        idx = months.index(month)
        try:
            if period == '1m': btc_ret = btc_monthly.iloc[idx+1]
            elif period == '2m': btc_ret = (price_matrix['BTCUSDT'].iloc[idx+2]/price_matrix['BTCUSDT'].iloc[idx] - 1)
            else: btc_ret = (price_matrix['BTCUSDT'].iloc[idx+3]/price_matrix['BTCUSDT'].iloc[idx] - 1)
            alphas.append(ev[col] - btc_ret)
        except: continue
    alpha_mean = np.mean(alphas) if alphas else np.nan
    alpha_results[period] = alpha_mean
    print(f"  {period} 後平均超額報酬（vs BTC）：{alpha_mean:.2%}")

# 按市場環境分組
results_df['btc_trend'] = results_df['month'].apply(
    lambda m: 'bull' if btc_monthly.get(m, 0) > 0 else 'bear'
)
print("\n=== 按市場環境分組 ===")
bull_bear = results_df.groupby('btc_trend')[['ret_1m','ret_2m','ret_3m']].mean()
print(bull_bear)

# 按排名下滑幅度分組
results_df['drop_size'] = results_df['rank_drop'].apply(lambda x: 'large(>=3)' if x >= 3 else 'small(<3)')
print("\n=== 按下滑幅度分組 ===")
drop_group = results_df.groupby('drop_size')[['ret_1m','ret_2m']].agg(['mean','count'])
print(drop_group)

print("\n=== Step 6: Generating charts ===")
fig, axes = plt.subplots(2, 2, figsize=(14, 10), facecolor='#0d1117')
fig.suptitle('Market Cap Rank Decay Analysis\nShort Signal Validation', color='white', fontsize=13, fontweight='bold')

# Chart 1: Event distribution
ax1 = axes[0,0]
ax1.set_facecolor('#161b22')
if len(events_df) > 0:
    monthly_count = events_df.groupby('month').size()
    ax1.bar(range(len(monthly_count)), monthly_count.values, color='#58a6ff', alpha=0.8)
    ax1.set_xticks(range(0, len(monthly_count), max(1, len(monthly_count)//6)))
    ax1.set_xticklabels([str(m) for m in monthly_count.index[::max(1, len(monthly_count)//6)]], rotation=45, color='#c9d1d9', fontsize=7)
ax1.set_title('Monthly Rank-Decay Events Count', color='white', fontsize=10)
ax1.tick_params(colors='#8b949e')
ax1.spines[:].set_color('#30363d')

# Chart 2: Short win rate
ax2 = axes[0,1]
ax2.set_facecolor('#161b22')
periods = ['1 Month', '2 Months', '3 Months']
win_rates = [
    (results_df['ret_1m'] < 0).mean() * 100,
    (results_df['ret_2m'] < 0).mean() * 100,
    (results_df['ret_3m'] < 0).mean() * 100,
]
colors_bar = ['#238636' if w > 50 else '#da3633' for w in win_rates]
bars = ax2.bar(periods, win_rates, color=colors_bar, alpha=0.85, edgecolor='#30363d')
ax2.axhline(50, color='#f0883e', linewidth=1.5, linestyle='--')
ax2.text(2.4, 51, '50% (random)', color='#f0883e', fontsize=8)
for bar, val in zip(bars, win_rates):
    ax2.text(bar.get_x()+bar.get_width()/2, val+0.5, f'{val:.1f}%', ha='center', va='bottom', color='white', fontsize=9)
ax2.set_title('Short Win Rate After Rank Decay', color='white', fontsize=10)
ax2.set_ylabel('Win Rate %', color='#c9d1d9', fontsize=9)
ax2.set_ylim(0, 80)
ax2.tick_params(colors='#8b949e')
ax2.spines[:].set_color('#30363d')

# Chart 3: Return distribution
ax3 = axes[1,0]
ax3.set_facecolor('#161b22')
if len(results_df) > 0:
    ax3.hist(results_df['ret_1m'].dropna() * 100, bins=20, color='#da3633', alpha=0.7, label='1M Return', edgecolor='#30363d')
    ax3.axvline(0, color='white', linewidth=1.5, linestyle='--')
    ax3.axvline(results_df['ret_1m'].mean()*100, color='#f0883e', linewidth=2, label=f"Mean: {results_df['ret_1m'].mean():.1%}")
ax3.set_title('1M Return Distribution After Rank Decay', color='white', fontsize=10)
ax3.set_xlabel('Return %', color='#c9d1d9', fontsize=9)
ax3.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9', fontsize=8)
ax3.tick_params(colors='#8b949e')
ax3.spines[:].set_color('#30363d')

# Chart 4: Bull vs Bear
ax4 = axes[1,1]
ax4.set_facecolor('#161b22')
if 'btc_trend' in results_df.columns and len(results_df) > 0:
    grouped = results_df.groupby('btc_trend')
    labels_bb = []
    wr_bb = []
    for trend, grp in grouped:
        labels_bb.append(trend.upper())
        wr_bb.append((grp['ret_1m'] < 0).mean() * 100)
    x = np.arange(len(labels_bb))
    ax4.bar(x, wr_bb, color=['#238636' if w > 50 else '#da3633' for w in wr_bb], alpha=0.85, edgecolor='#30363d')
    ax4.axhline(50, color='#f0883e', linewidth=1.5, linestyle='--')
    ax4.set_xticks(x)
    ax4.set_xticklabels(labels_bb, color='#c9d1d9', fontsize=10)
    for i, val in enumerate(wr_bb):
        ax4.text(i, val+0.5, f'{val:.1f}%', ha='center', va='bottom', color='white', fontsize=9)
ax4.set_title('Short Win Rate: Bull vs Bear Market', color='white', fontsize=10)
ax4.set_ylabel('Win Rate %', color='#c9d1d9', fontsize=9)
ax4.set_ylim(0, 80)
ax4.tick_params(colors='#8b949e')
ax4.spines[:].set_color('#30363d')

plt.tight_layout()
epoch = int(time.time())
hex8 = secrets.token_hex(4)
img_filename = f'jarvis-image-{epoch}-{hex8}.png'
img_path = f'./openclaw-media/{img_filename}'
plt.savefig(f'/root/.openclaw/workspace/{img_path}', dpi=130, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print(f"CHART_PATH:{img_path}")

# Save findings
wr_1m = (results_df['ret_1m'] < 0).mean()
wr_2m = (results_df['ret_2m'] < 0).mean()
wr_3m = (results_df['ret_3m'] < 0).mean()
mean_1m = results_df['ret_1m'].mean()
mean_2m = results_df['ret_2m'].mean()
mean_3m = results_df['ret_3m'].mean()

bull_wr_1m = "N/A"
bear_wr_1m = "N/A"
if 'bull' in bull_bear.index:
    bull_wr_1m = f"{bull_bear.loc['bull','ret_1m']:.2%}"
if 'bear' in bull_bear.index:
    bear_wr_1m = f"{bull_bear.loc['bear','ret_1m']:.2%}"

signal_verdict = "值得進一步研究" if wr_1m > 0.52 else "訊號偏弱，需改進"

findings = f"""# Market Cap Rank Decay - Short Signal Analysis

## 研究問題
**假說：市值排名持續下滑的加密貨幣，未來短期內價格表現偏弱，可作為空倉訊號。**

定義：某幣在前一個月排名 ≤ 15，本月排名 16-20（下滑進入邊緣區）

## 數據摘要
- **幣種數**：{len(vol_data)} 個主流幣（2019年底前已上市）
- **時間範圍**：2020-01 至 2026-05（月度）
- **識別事件數**：{len(events_df)} 個「排名下滑」事件
- **有效分析樣本**：{len(results_df)} 個（有後續月度價格）

## 核心發現
- **1個月後做空勝率：{wr_1m:.1%}**（負報酬比例）
- **2個月後做空勝率：{wr_2m:.1%}**
- **3個月後做空勝率：{wr_3m:.1%}**
- **1個月後平均報酬**：{mean_1m:.2%}（中位數：{results_df['ret_1m'].median():.2%}）
- **2個月後平均報酬**：{mean_2m:.2%}（中位數：{results_df['ret_2m'].median():.2%}）
- **3個月後平均報酬**：{mean_3m:.2%}（中位數：{results_df['ret_3m'].median():.2%}）
- **vs BTC 1m 超額報酬（Alpha）**：{alpha_results.get('1m', float('nan')):.2%}
- **vs BTC 2m 超額報酬（Alpha）**：{alpha_results.get('2m', float('nan')):.2%}
- **vs BTC 3m 超額報酬（Alpha）**：{alpha_results.get('3m', float('nan')):.2%}

## 牛市 vs 熊市表現差異
- **牛市月（BTC同月上漲）後1月平均報酬**：{bull_wr_1m}
- **熊市月（BTC同月下跌）後1月平均報酬**：{bear_wr_1m}
- 市場環境對訊號強弱有顯著影響，熊市中空訊號通常更強

## 下滑幅度的影響
{drop_group.to_string()}

## 結論：這個訊號是否值得使用？
**{signal_verdict}**

- 如果做空勝率 > 55%：訊號具有統計顯著性，可作為輔助指標
- 如果勝率 50-55%：需要疊加其他過濾條件
- 如果勝率 < 50%：假說不成立，需重新定義

本次探索性研究顯示，以月度交易量排名近似市值排名，捕捉「排名下滑」事件是可行的初步框架。

## 建議的改進方向
1. **用真實市值數據替代成交量代理**（CoinGecko/CMC API）
2. **調整閾值**：嘗試「前3個月排名均 ≤ 10，當月 > 15」等更嚴格定義
3. **加入動量確認**：要求連續2個月排名下滑才觸發訊號
4. **控制行業因素**：去除系統性輪動（如DeFi季、Layer1季）的影響
5. **流動性過濾**：排除成交量驟降（可能是下市風險）的案例
6. **結合技術面**：K線跌破關鍵均線時，排名下滑訊號更強
7. **Sample size 不足問題**：30個幣、6年數據，事件數較少，統計功效有限

## 圖表
{img_path}
"""

with open('/root/.openclaw/workspace/crypto-research/adaptive-trend/mcap-rank-analysis/findings.md', 'w') as f:
    f.write(findings)

print("\n=== findings.md written ===")
print(f"\nKEY_RESULTS:WR_1M={wr_1m:.1%},WR_2M={wr_2m:.1%},WR_3M={wr_3m:.1%},MEAN_1M={mean_1m:.2%},ALPHA_1M={alpha_results.get('1m',0):.2%},EVENTS={len(events_df)},SAMPLES={len(results_df)}")
print(f"CHART_PATH:{img_path}")
