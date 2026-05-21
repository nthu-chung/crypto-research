# AdaptiveTrend v5 No-Lookahead Audit

**研究日期：** 2026-05-20  
**接手研究員：** Codex  
**目的：** 驗證 v4 最終版是否仍含月內前視偏差，並用「交易月只使用交易月開始前已知資料」重跑。

---

## 一、接手後發現的主要問題

v4 的研究方向正確，但 `backtest_v4.py` 的時間對齊與 paper 敘述不一致。

### 1. 月度宇宙使用當月月底資料

v4 在回測每個月時使用：

```python
curr_result = get_monthly_universe(month_end)
```

接著用該 `current_universe` 交易同一個月 `month_start -> month_end`。這表示，例如 2021-01 的交易，會用 2021-01 月底才知道的成交量排名決定 2021-01 月初的持倉。

這不是 v1 那種嚴重的「用 2026 幣種倒套 2020」survivorship bias，但仍然是**月內 look-ahead bias**。

### 2. Rank-decay short 也使用當月排名

v4 的空倉條件用 `prev_vol_ranked -> current_vol_ranked` 判斷排名是否從前 15 掉到 16-20，然後在同一個月交易。實務上，當月排名衰退要到月底才確定，應該下一個月才可用。

### 3. Paper 對 ROC(20) 的描述高於程式實作

Paper 內描述 ROC(20) 是 momentum signal，但 v4 程式實際沒有用 ROC 作為入場條件；v4 主要是「上月 6H returns Sharpe 篩選 + ATR trailing stop」。這不一定是錯，但論文方法章需要改成和程式一致。

---

## 二、v5 修正方式

新增腳本：

- `backtest_v5_no_lookahead.py`

新增結果：

- `results_v5_no_lookahead.json`
- `portfolio_v5_no_lookahead.json`

v5 保留 v4 的策略規則，只修正資訊可得時間：

| 項目 | v4 | v5 no-lookahead |
|------|----|-----------------|
| 交易月宇宙 | 使用交易月月底成交量排名 | 使用上一月月底已知成交量排名 |
| Fee tier | 使用交易月成交量 | 使用上一月已知成交量 |
| Rank-decay short | 用上月 -> 當月排名後交易當月 | 用前兩月 -> 上月排名變化後交易當月 |
| BTC regime/RV30 | 月初資料 | 僅使用月初前已知 K 線 |
| 多倉 Sharpe | 上月 returns | 保留 |
| ATR stop | 當月持倉期間 trailing | 保留 |

---

## 三、v4 vs v5 結果差異

### 全期績效

| 指標 | v4 final | v5 no-lookahead | 差異 |
|------|----------|-----------------|------|
| CAGR | 46.54% | **27.36%** | -19.18 pp |
| Sharpe | 1.00 | **0.69** | -0.31 |
| MaxDD | -34.52% | **-30.52%** | +4.00 pp |
| Calmar | 1.35 | **0.90** | -0.45 |
| 月勝率 | 31.6% | **28.9%** | -2.7 pp |
| 總報酬 | +1024.7% | **+362.5%** | -662.2 pp |

### IS/OOS

| 時期 | 指標 | v4 final | v5 no-lookahead |
|------|------|----------|-----------------|
| IS 2020-2023 | CAGR | 43.64% | **21.39%** |
| IS 2020-2023 | Sharpe | 1.12 | **0.74** |
| IS 2020-2023 | MaxDD | -34.52% | **-30.52%** |
| OOS 2024-2026 | CAGR | 53.87% | **38.28%** |
| OOS 2024-2026 | Sharpe | 0.85 | **0.71** |
| OOS 2024-2026 | MaxDD | -11.21% | **-13.42%** |

### 逐年報酬

| 年份 | v4 final | v5 no-lookahead | 解讀 |
|------|----------|-----------------|------|
| 2020 | +104.9% | **+5.1%** | 早期績效大幅消失，顯示 v4 月內宇宙前視影響很大 |
| 2021 | +170.1% | **+82.2%** | 牛市仍有效，但幅度大幅下降 |
| 2022 | -13.1% | **-13.0%** | 熊市結果接近 |
| 2023 | +25.7% | **+30.3%** | v5 略好 |
| 2024 | +84.3% | **+85.7%** | OOS 第一牛市年仍強 |
| 2025 | +43.4% | **+14.7%** | v4 可能受月內排名資訊幫助 |
| 2026 | 0.0% | **0.0%** | 無有效趨勢信號 |

---

## 四、研究判斷

### 1. v4 的核心結論需要下修

v4 報告中「CAGR 46.5%、Sharpe 1.0、超越 BTC B&H」不能作為最終結論。修正月內前視後，CAGR 降至 27.36%，Sharpe 降至 0.69，已低於 BTC B&H 的粗估 CAGR 44.8%。

### 2. 策略仍有價值，但不是 v4 報告描述的強 alpha

v5 仍有 +362.5% 全期總報酬，MaxDD -30.52%，2021 與 2024 的趨勢捕捉仍有效。這表示 Sharpe 選幣 + ATR stop 的骨架不是無效，只是優勢比 v4 小很多。

### 3. Short overlay 貢獻很有限

v5 空倉只觸發 3 個月份：

| 交易月 | 已知資訊月 | 空倉標的 | 月報酬 |
|--------|------------|----------|--------|
| 2021-06 | 2021-05 | XLM, FIL | -4.54% |
| 2021-07 | 2021-06 | EOS, TRX, BCH | +1.02% |
| 2022-01 | 2021-12 | VET | -2.80% |

Rank-decay short 的事件研究可以保留，但在完整策略中因 gating 很嚴，實際貢獻不大。

### 4. OOS 沒有崩，但也沒有證明強 robustness

v5 OOS CAGR 38.28%、Sharpe 0.71，仍然可接受；但 OOS 主要由 2024 牛市貢獻，2025 明顯弱化，2026 閒置。這比較像「有牛市捕捉能力的保守趨勢策略」，不是穩定高 Sharpe alpha。

---

## 五、下一輪研究建議

1. **先建立正式 v5 baseline**  
   將 v5 no-lookahead 作為新的可信 baseline，v4 只保留為研究歷史，不再當最終版。

2. **重寫 paper 方法章**  
   修正三件事：資訊時間點、ROC 實際未使用、v4 指標需改為 v5 指標。

3. **補 BTC benchmark 同資料源重算**  
   目前 BTC B&H 數值沿用 v2 粗估，應用同一份 6H data 精準重算 full/IS/OOS。

4. **重新研究選幣信號**  
   現在最大 alpha 下降來自 universe shift 後 early bull 捕捉能力變弱。下一步可測：
   - 上月 Sharpe vs 上月 return vs ROC(20) 的比較
   - Sharpe 門檻 0.8/1.0/1.3/1.5 的 sensitivity
   - 使用前月月底宇宙，但月初延遲 1 根 6H K 才進場，模擬實務換倉

5. **重新評估 short overlay**  
   Rank-decay 的獨立事件研究有一些訊號，但完整策略觸發太少。可以改成只做風控降槓桿，不一定要開空。

---

## 六、暫定判決

```text
verdict: NEEDS_REVISION
reason: v4 final result contains monthly look-ahead bias.
new baseline: v5_no_lookahead
v5 result: CAGR 27.36%, Sharpe 0.69, MaxDD -30.52%
status: research reopened
```

v5 不是策略失敗，而是把策略從「漂亮但含前視」拉回「可信但需要再優化」。下一步應以 v5 作為新的研究起點。
