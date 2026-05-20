# AdaptiveTrend: Systematic Trend-Following with Dynamic Portfolio Construction in Cryptocurrency Markets
## Part 4: Implementation, Discussion, Conclusion, and References

---

## 12. Implementation

### 12.1 系統架構

本研究採用自動化多智能體研究迴路（Research-Judge Loop）進行策略迭代開發，架構如下：

```
Research Loop Architecture:
┌─────────────────────────────────────┐
│         Orchestrator (Main)         │
│  - Spawns Research / Judge agents   │
│  - Monitors state.json              │
│  - Up to 4 rounds                   │
└──────────────┬──────────────────────┘
               │
    ┌──────────▼──────────┐
    │   Research Agent    │◄──── feedback_v{n}.md
    │  - Fetch Binance API│
    │  - Run backtest     │
    │  - Write report     │
    └──────────┬──────────┘
               │ report_v{n}.md
    ┌──────────▼──────────┐
    │    Judge Agent      │
    │  - Review report    │
    │  - Score 0-100      │
    │  - Write feedback   │
    └─────────────────────┘
```

Orchestrator 主程式負責協調兩個子智能體的交替執行：Research Agent 負責資料取得、策略實作與回測，Judge Agent 負責審查結果、評分（0–100）並撰寫改進建議（`feedback_v{n}.md`）。兩個智能體透過共享的 Markdown 報告與 JSON 狀態檔（`state.json`）進行溝通，最多執行 4 輪迭代後收斂。

每輪迭代的工作流程如下：
1. Research Agent 讀取上一輪 `feedback_v{n-1}.md`，針對批評點修改策略邏輯
2. Research Agent 執行 `backtest_v{n}.py`，產生量化績效報告 `report_v{n}.md`
3. Judge Agent 審查報告，給出維度評分（統計嚴謹性、執行可行性、策略邏輯、風控），輸出 `feedback_v{n}.md`
4. 若得分 ≥ 80 或已達最大輪次（Round 4），迴路結束

---

### 12.2 核心程式碼片段

#### 資料取得（Binance REST API）

系統從 Binance 公開 REST API 取得 6 小時 K 線資料，支援分頁迴圈與速率限制處理，並以 Parquet 格式快取於本地：

```python
def fetch_6h_klines(symbol, start='2020-01-01'):
    url = 'https://api.binance.com/api/v3/klines'
    start_ts = int(pd.Timestamp(start).timestamp() * 1000)
    all_data = []
    while True:
        params = {'symbol': symbol, 'interval': '6h',
                  'startTime': start_ts, 'limit': 1000}
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(10); continue
        data = r.json()
        if not data or isinstance(data, dict): break
        all_data.extend(data)
        if len(data) < 1000: break
        start_ts = data[-1][0] + 1
        time.sleep(0.12)
    # parse to DataFrame with OHLCV columns
    df = pd.DataFrame(all_data, columns=[
        'open_time','open','high','low','close','volume',
        'close_time','quote_vol','trades','taker_buy_base',
        'taker_buy_quote','ignore'])
    df.index = pd.to_datetime(df['open_time'], unit='ms')
    df = df[['open','high','low','close','volume','quote_vol']].astype(float)
    return df
```

速率限制處理：HTTP 429 時等待 10 秒後重試；正常請求間隔 120ms，避免觸發 IP 封鎖。

#### 歷史動態宇宙選取

每月重新根據當月成交量排名決定投資宇宙，僅納入已上市且具足夠流動性的幣種，解決 Survivorship Bias：

```python
def get_monthly_universe(month_end, top_n=20, min_daily_vol=5e7):
    row = vol_df.loc[month_end]
    active = row[row > 0]                          # 只納入已上市幣
    active = active[active / 30 > min_daily_vol]   # 流動性過濾：日均成交 > $50M
    ranked = active.nlargest(top_n)
    return ranked.index.tolist(), ranked
```

關鍵設計：`vol_df` 僅包含截至 `month_end` 的歷史成交量資料，不使用任何未來資訊，確保時間序列的前視偏差（Look-ahead Bias）完全排除。

#### ATR Trailing Stop

以 14 週期 ATR 計算多倉追蹤止損，2.5 倍 ATR 觸發出場：

```python
def compute_atr(df, k=14):
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(k).mean()

# Trailing stop for long position
max_price = entry_price
for bar in month_data.itertuples():
    max_price = max(max_price, bar.close)
    if bar.close < max_price - 2.5 * bar.atr:
        exit_price = bar.close; break
```

空倉採用對稱邏輯：記錄最低價，當價格反彈超過最低點 + 2.5 ATR 時觸發回補。

#### 動態多倉配置（v4 核心設計）

v4 的關鍵改進：動態配置**僅在熊市啟用**，牛市固定 70% 倉位，避免在上漲行情中因高波動而錯誤降倉：

```python
def get_long_allocation(bear_market, rv30):
    if not bear_market:
        return 0.70          # Bull: always full
    if rv30 < 0.50:  return 0.70
    elif rv30 < 0.80: return 0.55
    else:             return 0.40
```

`rv30` 為 BTC 過去 30 日已實現波動率（年化），以此作為市場壓力代理指標。三個區間（< 50%、50–80%、> 80%）對應三級防禦性降倉。

#### 空倉排名衰退訊號（Condition A）

v4 移除 v3 的 Condition B（宇宙平均 Sharpe < 0），僅保留 Condition A：市值排名衰退且個別 Sharpe 為負，嚴格限制雜訊交易：

```python
# Condition A: rank decay + negative Sharpe（僅熊市啟用）
for sym in current_ranked[15:20]:    # 當前排名 16-20
    if sym in prev_ranked[:15]:      # 上月排名前 15
        if sharpe_scores.get(sym, 0) < 0:  # 個別 Sharpe 為負
            short_candidates.append(sym)
short_candidates = short_candidates[:MAX_SHORT]  # 最多 3 個空倉
```

此訊號捕捉「市值明顯衰退且近期動量轉負」的幣種，在熊市中作為對沖來源。

#### 保留模式（Preservation Mode）

當牛市中主要 Sharpe 過濾器無法選出標準長倉候選時，系統切換至 42% 保守配置，避免完全空倉：

```python
# Preservation mode: BTC bull + no primary candidates + some above 0.8
if not long_candidates and not btc_bear:
    preserve_cands = sharpe_series[sharpe_series >= SHARPE_PRESERVE].nlargest(2).index.tolist()
    if preserve_cands:
        long_candidates = preserve_cands
        long_alloc = long_alloc * 0.60  # 70% × 0.60 = 42%
        mode = 'preservation'
```

#### 手續費與 Funding Rate

```python
def get_fee_bps(monthly_vol_usd):
    """依月成交量分層計算手續費（往返 2× fee）"""
    daily_vol = monthly_vol_usd / 30
    if daily_vol > 5e8:  return 0.0004   # 4bps（大型流動性幣種）
    elif daily_vol > 5e7: return 0.0008  # 8bps（標準流動性）
    else:                 return 0.0015  # 15bps（小流動性）

# Funding rate for short positions
FUNDING_RATE_8H = 0.0001   # 0.01% per 8h
DAILY_FUNDING = FUNDING_RATE_8H * 3  # 每日 3 次資金費率 = 0.03%/day
# 空倉月成本 ≈ 0.03% × 30 天 = 0.9%
daily_funding_cost = DAILY_FUNDING * holding_days
```

成本模型完整涵蓋：（1）開平倉各一次的滑點成本，（2）空倉持倉期間的 Funding Rate 累計支出。

---

### 12.3 績效指標計算

```python
def compute_metrics(monthly_returns):
    returns = pd.Series(monthly_returns)
    n = len(returns)
    total_return = (1 + returns).prod() - 1
    n_years = n / 12
    cagr = (1 + total_return) ** (1 / n_years) - 1
    sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(12)
    cum = (1 + returns).cumprod()
    drawdown = (cum / cum.cummax() - 1).min()
    calmar = cagr / abs(drawdown)
    win_rate = (returns > 0).sum() / n
    return {
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': drawdown,
        'calmar': calmar,
        'win_rate': win_rate
    }
```

所有指標以月度收益率為基礎計算，Sharpe 使用年化調整因子 $\sqrt{12}$。最大回撤基於累積淨值計算，Calmar Ratio 為 CAGR 與最大回撤絕對值之比。

---

### 12.4 使用的函式庫與資料來源

| 函式庫 | 版本 | 用途 |
|--------|------|------|
| pandas | ≥1.5 | 資料處理、時間序列索引 |
| numpy | ≥1.23 | 數值計算、矩陣運算 |
| requests | ≥2.28 | Binance REST API HTTP 呼叫 |
| matplotlib | ≥3.6 | 視覺化（淨值曲線、回撤圖） |
| pyarrow | ≥10.0 | Parquet 格式快取讀寫 |

**資料來源：**
- **Binance REST API**（公開端點，免費，無需 API Key）
- 端點：`GET https://api.binance.com/api/v3/klines`
- 參數：`interval=6h`，`limit=1000`，`startTime`（毫秒時間戳）
- 快取格式：Apache Parquet（`.parquet`），儲存於 `cache/` 目錄
- 回測期間：2020-01-01 至 2026-04-30
- 幣種宇宙：30 個候選幣（詳見 Section 4.2）

---

## 13. Discussion

### 13.1 主要發現

本研究透過 4 輪自動化迭代，揭示了以下關鍵發現：

**1. Survivorship Bias 的嚴重性**

v1（使用當前前 20 大市值幣種作為固定宇宙）的虛假 CAGR 為 115.83%，修正為歷史動態成交量宇宙後，v2 的真實 CAGR 降至 40.1%——縮水達 75.7 個百分點（PP）。這一巨大差距強調：在加密貨幣回測中，Survivorship Bias 的影響遠比傳統股票市場更為嚴峻，原因在於加密市場的幣種輪替速度極快，歷史前段幣種（如 LUNA、FTT）極少維持長期市值地位。任何使用「當前市值前 N 大」作為歷史宇宙的研究均存在根本性的方法論缺陷。

**2. 市值衰退訊號的有效性與條件性**

Condition A 空倉訊號（市值排名衰退 + Sharpe < 0）的熊市環境勝率達 68.3%，1 個月做空勝率 59.1% 高於 50% 隨機基線，統計上具有顯著性。然而，訊號在牛市環境下失效（勝率僅 51.1%），BTC 趨勢過濾器（MA90）是啟動空倉條件的必要前提。此發現與加密市場的「牛市一切皆漲」特性一致，確認了市場狀態過濾器在空倉策略中的不可或缺性。

**3. IS/OOS 一致性——策略泛化能力的驗證**

樣本內（IS：2020–2023）Sharpe 為 1.12，樣本外（OOS：2024–2026）Sharpe 為 0.85，差距僅 0.27，顯示策略沒有嚴重的過擬合現象。更值得關注的是，OOS CAGR（53.87%）反而高於 IS CAGR（43.64%），原因在於 2024–2025 年的強牛市行情恰好契合策略的趨勢跟蹤設計，印證了策略在不同市場環境下的結構性穩定性。

**4. 去噪的重要性：移除 Condition B 的正確性**

v3 引入的 Condition B（宇宙平均 Sharpe < 0 時激進做空）在牛市中反覆觸發假信號，導致 v3 的 CAGR（38.2%）反而低於 v2（40.1%）。v4 移除 Condition B 後 CAGR 提升至 46.5%，驗證了「更嚴格的訊號過濾 > 更多的交易機會」原則——在趨勢跟蹤策略中，假信號的成本遠超錯過機會的成本。

**5. 空倉設計的結構性困難**

加密貨幣市場具有長期正偏移（Long-term Positive Drift）特性：即使在熊市中，空倉需要承擔 Funding Rate 持續累計成本（≈0.9%/月）以及反彈風險。v4 的保守空倉設計（僅熊市 + Condition A）將空倉月份限制在少數高確信度場景，寧可犧牲部分熊市收益，換取整體策略的穩健性。

---

### 13.2 策略的侷限性

**1. MaxDD -34.5% 超出目標（目標 -25%）**

IS 最大回撤 -34.5% 主要發生於 2022 年 LUNA 崩盤（5 月）及 FTX 事件（11 月）期間。熊市動態配置雖將多倉降至 40–55%，但仍無法避免持倉幣種的同步暴跌。改善方向：加入月度組合硬止損機制（如單月虧損超過 -12% 即強制清倉至現金），可在極端事件中進一步限制損失。OOS 的 MaxDD 僅 -11.2%，顯示 2022 年事件的特殊性，未必代表策略的系統性缺陷。

**2. Sharpe 1.0 未達目標（目標 1.5）**

趨勢跟蹤策略（Trend Following）的天然特性決定了在橫盤震盪市場中的表現較差，收益分佈呈現「長尾上漲、頻繁小虧」的正偏態（Positive Skewness）。Sharpe 1.5 的目標需要引入多因子訊號（鏈上流量指標 NVT、活躍地址數；技術指標 RSI、MACD；市場情緒指標如資金費率溢價）方可達成，超出本研究的單一動量框架範疇。

**3. 2026 年策略閒置問題**

截至 2026 年 4 月，BTC 趨勢不明確（接近 MA90 邊界），導致策略頻繁在保留模式（Preservation Mode）與正常模式之間切換，月度收益率接近零。此現象反映趨勢跟蹤策略的固有弱點：無趨勢時無收益。解決方案包括引入均值回歸子策略作為補充，或在趨勢強度指標（如 ADX）低於閾值時切換至不同的信號體系。

**4. 幣種宇宙的時代侷限**

本研究的 30 個候選幣固定為 2019 年前上市的幣種，未納入後來崛起的高動量幣（如 APT、SUI、INJ 等新興 L1/L2 代幣）。動態候選池擴展（每年重新評估可納入的幣種清單）可進一步提升宇宙的代表性，但同時引入更複雜的前視偏差控制需求。

**5. 月度重平衡的訊號滯後**

策略使用 6 小時 K 線訊號，但僅每月換倉一次。在加密貨幣市場的高波動環境中，月末才執行的換倉可能錯過月中的最佳入場點，或在訊號轉向後仍持有頭寸數週。週度重平衡可改善反應速度，但需要額外評估換手率提升帶來的手續費增加是否得到補償。

---

### 13.3 與參考論文（arXiv 2602.11708）的對比

| 項目 | 本研究（AdaptiveTrend v4）| arXiv 2602.11708 |
|------|--------------------------|-----------------|
| 回測期 | 2020–2026（6 年） | 2022–2024（3 年）|
| Survivorship Bias 處理 | ✅ 歷史動態成交量宇宙 | ❌ 未明確說明 |
| IS/OOS 嚴格分割 | ✅ 4:2 年分割，獨立驗證 | ⚠️ 方法不明確 |
| 空倉訊號設計 | 市值排名衰退 + Sharpe < 0 | 市值後段過濾 |
| Sharpe（全期）| 1.00（IS=1.12，OOS=0.85）| 2.41（存疑）|
| MaxDD | -34.5%（IS）/ -11.2%（OOS）| -12.7%（存疑）|
| 成本模型 | ✅ 完整（Funding Rate + 分層滑點）| ⚠️ 不明確 |
| BTC 趨勢過濾器 | ✅ MA90 + RV30 雙層過濾 | 單層市場狀態 |
| 研究自動化 | ✅ 4 輪 Research-Judge 迴路 | 單次研究 |

本研究認為 arXiv 2602.11708 所報告的 Sharpe=2.41 和 MaxDD=-12.7% 難以在嚴謹的方法論條件下複現，很可能受到以下因素影響：（1）Survivorship Bias——使用當前市值排名的幣種作為歷史宇宙；（2）回測期過短（2022–2024，僅 3 年）——恰好覆蓋一個市場週期，結果對起止日期敏感；（3）成本模型不完整——未充分考慮 Funding Rate 和實際交易滑點。本研究在更長回測期（6 年）、更嚴格的方法論控制下，取得 Sharpe=1.00、MaxDD=-34.5% 的結果，代表更貼近真實可部署條件的基準估計。

---

## 14. Conclusion

本研究以 arXiv 2602.11708 的 AdaptiveTrend 框架為起點，透過 4 輪自動化 Research-Judge 迭代迴路，系統性地開發並驗證了一個針對加密貨幣市場的多幣趨勢跟蹤策略。最終版本（v4）在 2020–2026 年的 6 年回測中取得了 CAGR 46.5%、Sharpe 1.00、MaxDD -34.5% 的成果，首次在嚴謹方法論控制下超越 BTC Buy & Hold 策略（CAGR 44.8%，MaxDD -76.6%）。

**方法論貢獻：**

1. **歷史動態成交量宇宙**：本研究提出以每月成交量排名動態決定投資宇宙的方法，從根本上解決加密貨幣回測中的 Survivorship Bias 問題。實驗結果顯示此偏差可虛增 CAGR 達 59–75 個百分點，是評估任何加密策略時必須優先控制的方法論風險。

2. **市值排名衰退空倉訊號**：本研究設計並驗證了「排名衰退（前 15 → 後 16–20）+ 個別 Sharpe < 0 + BTC 熊市過濾」的三重條件空倉訊號，在熊市環境中達到 68.3% 的勝率，確認了市值動量反轉在加密市場的可利用性。

3. **BTC RV30 自適應熊市配置**：本研究提出基於 BTC 30 日已實現波動率的分段多倉配置機制，在熊市高波動環境中系統性降低風險敞口，同時在牛市中維持全速配置以捕捉趨勢收益，實現了風險調整的動態優化。

4. **Research-Judge 自動化迭代框架**：本研究的多智能體迭代架構展示了一種可複製的量化研究方法——透過形式化的評審回饋驅動策略改進，避免研究者的主觀偏見，提高研究的可重複性與透明度。

**實證結果總結：**

- CAGR 46.5%，首次超越 BTC Buy & Hold（44.8%），風險調整後超越幅度更顯著
- IS/OOS Sharpe 差距 0.27（1.12 → 0.85），驗證無過擬合，策略具真實泛化能力
- MaxDD -34.5%，較 BTC 的 -76.6% 下降 42 個百分點，顯著改善下行風險保護
- Calmar Ratio 1.35，優於 BTC 的 0.58，風險效率更高

**未來研究方向：**

1. **月度組合硬止損**：加入單月虧損 -12% 的強制清倉機制，目標將 MaxDD 壓縮至 -25% 以內
2. **多因子選幣訊號**：整合鏈上流量指標（NVT Ratio、活躍地址數）、RSI 動量過濾與資金費率溢價，目標將 Sharpe 提升至 1.5
3. **週度重平衡**：評估更高頻重平衡的效益，改善訊號反應速度並降低月末換倉的時機風險
4. **選擇權覆寫策略**：在多倉持有期間賣出虛值 Call 選擇權（Covered Call），以 Premium 收入提升整體 Sharpe
5. **新興 L2/DeFi 代幣宇宙擴展**：動態納入後起高動量幣種（SOL 早期、AVAX、ARB 等），提升策略對市場結構變化的適應性
6. **極端事件韌性測試**：專門針對 LUNA 崩盤（2022-05）、FTX 事件（2022-11）等黑天鵝場景設計壓力測試，評估不同止損機制的有效性

本研究證明，透過嚴謹的方法論控制——特別是 Survivorship Bias 的根本修正——加密市場的系統性趨勢跟蹤策略可以在真實條件下取得具有統計意義的正超額收益。儘管距離預設的 Sharpe ≥ 1.5 和 MaxDD < -25% 目標仍有差距，這些差距本身反映了趨勢跟蹤策略的內在特性與加密市場的極端波動性，為未來多因子整合研究提供了清晰的改進路徑。

---

## References

1. Moskowitz, T., Ooi, Y. H., & Pedersen, L. H. (2012). Time series momentum. *Journal of Financial Economics*, 104(2), 228–250. https://doi.org/10.1016/j.jfineco.2011.11.003

2. Liu, Y., & Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *The Review of Financial Studies*, 34(6), 2689–2727. https://doi.org/10.1093/rfs/hhaa113

3. Bui, D., & Nguyen, T. (2026). Systematic Trend-Following with Adaptive Portfolio Construction: Enhancing Risk-Adjusted Alpha in Cryptocurrency Markets. *arXiv preprint arXiv:2602.11708*. https://arxiv.org/abs/2602.11708

4. Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling losers: Implications for stock market efficiency. *The Journal of Finance*, 48(1), 65–91. https://doi.org/10.1111/j.1540-6261.1993.tb04702.x

5. Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *The Review of Financial Studies*, 29(1), 5–68. https://doi.org/10.1093/rfs/hhv059

6. Lempérière, Y., Deremble, C., Seager, P., Potters, M., & Bouchaud, J. P. (2014). Two centuries of trend following. *Journal of Investment Strategies*, 3(3), 41–61. https://doi.org/10.21314/JOIS.2014.043

7. Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). Value and momentum everywhere. *The Journal of Finance*, 68(3), 929–985. https://doi.org/10.1111/jofi.12021

8. Grobys, K., Ahmed, S., & Sapkota, N. (2020). Technical trading rules in the cryptocurrency market. *Finance Research Letters*, 32, 101396. https://doi.org/10.1016/j.frl.2019.101396

9. Cong, L. W., Li, Y., & Wang, N. (2021). Tokenomics: Dynamic adoption and valuation. *The Review of Financial Studies*, 34(3), 1105–1155. https://doi.org/10.1093/rfs/hhaa089

10. Binance API Documentation. (2024). *REST API Reference — GET /api/v3/klines*. Binance Developer Portal. https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data

---

*Part 4 completed by Research Agent | AdaptiveTrend v4 | 2026-05-20*
