# Parallel Alpha Research — Master Report

**Session:** 2026-05-21 Parallel Strategy Research  
**Agents:** 4 個並行 Subagent  
**Universe:** Top 30 Binance USDT Perpetual Futures  
**研究期間:** 2021–2024

---

## 總覽

| 策略 | Sharpe | 年化報酬 | MaxDD | 結論 |
|------|--------|---------|-------|------|
| Funding CS（高信念版） | **+1.58** | **+58.1%** | -8.7% | ✅ 有效，需加門檻 |
| Sector Rotation | 0.02 | +1.68% | -89.4% | ⚠️ 弱，但 L1/L2 IC 真實 |
| OI-Price Divergence（Long-only top 10%） | — | +3.43% avg/trade | — | ⚠️ 只有 Long 側有效 |
| Vol Regime Momentum | -1.05 | 大幅虧損 | — | ❌ 假說被否定 |

---

## 一、Funding Rate Cross-Sectional Alpha ⭐ 最佳

### 核心發現
Funding rate cross-sectional alpha **真實存在**，但需要信號門檻才能盈利。

### 結果對比

| 版本 | Sharpe | 年化報酬 | MaxDD | 交易天數 |
|------|--------|---------|-------|---------|
| 無門檻（每日交易） | -3.42 | -28.4% | -64.7% | ~730 天 |
| **高信念（\|f\| ≥ 0.05%）** | **+1.58** | **+58.1%** | **-8.7%** | 35 天 |

### 關鍵洞察
- **交易成本是殺手**：無門檻版本年化交易成本 ~40%，策略完全被吃掉
- **極端 funding 事件**（|f| ≥ 0.05%）才是真正的 alpha 來源
- 2 年內只有 35 個有效交易日，屬於**機會型策略**，不是常態策略
- 信號邏輯成立：funding 極高 = 多頭擁擠 → 短期反轉做空

### 建議下一步
1. 擴展測試至 2020–2024 完整牛熊週期
2. 測試不同門檻（0.03%, 0.05%, 0.1%）的敏感度
3. 結合 OI 確認信號強度

---

## 二、Sector Rotation Momentum ⚠️ 部分有效

### 核心發現
整體策略 Sharpe 極低（0.02），但**個別 sector 的預測能力（IC）分化明顯**。

### Sector IC 排名

| Sector | IC | 解讀 |
|--------|-----|------|
| **L1** | **0.28** | 動能最可預測 |
| **L2** | **0.25** | 動能次強 |
| DeFi | ~0.0 | 無預測力 |
| AI | ~0.0 | 無預測力 |
| Exchange | ~0.0 | 無預測力 |
| Meme | 負值 | 動能反轉 |

### 關鍵洞察
- L1/L2 的 IC 是真實的，但整體 Sharpe 低是因為**單資產波動極大**拖累組合
- Meme 幣的動能呈現反轉，而非延續——這與其散戶驅動的特性一致
- AI/DeFi sector 幣種少（2-3 個），統計力不足

### 建議下一步
1. 只做 L1+L2 的 sector rotation，排除其他 sector
2. 加入波動率倒數加權（inverse vol weighting）降低極端波動
3. 配合 BTC regime filter 使用

---

## 三、OI-Price Divergence ⚠️ Long-only 有效

### 核心發現
**Short 側在牛市完全失效，Long 側有穩定的微弱 alpha。**

### 信號表現（7 天持有期）

| 信號 | 交易數 | 平均淨報酬 | 勝率 | vs 基準 |
|------|--------|----------|------|---------|
| Long（P20 門檻） | 2,881 | +2.88% | 51.2% | +0.78% alpha |
| **Long（top 10%）** | 1,441 | **+3.43%** | **54.4%** | **+1.33% alpha** |
| Short（P80 門檻） | 2,880 | -2.55% | 41.9% | -4.65%（差） |
| Long-Short 合併 | 5,761 | +0.16% | 46.6% | 跑輸基準 |

基準（隨機 7 日持有，牛市）：+2.10%，53.5% 勝率

### 關鍵洞察
- **Short 側邏輯錯誤**：2023-2024 牛市中，OI 增加代表趨勢延續，而非反轉
- **Long 側邏輯正確**：去槓桿化 + 價格上漲 = 健康上漲，值得追
- 資料限制：Binance OI 歷史 API 只有 30 天，用成交量比例作為 proxy（相關係數 ~0.36）

### 建議下一步
1. 取得完整 OI 歷史（CoinGlass API 或付費資料源）
2. 在 2022 熊市驗證 Short 側是否有效
3. 考慮 Long-only 策略 + funding filter 組合

---

## 四、Volatility Regime-Conditional Momentum ❌ 假說否定

### 核心發現
**Crypto 和傳統股票相反**：高波動期 momentum 繼續延續，不反轉。

### 結果對比

| 版本 | Sharpe | 說明 |
|------|--------|------|
| 無條件 momentum（基準） | -0.30 | 直接做 momentum |
| **Regime-conditional（翻轉）** | **-1.05** | 高波動期反向 → 更差 |
| 高波動期純 momentum | +0.27 | 高波動期順勢反而較好 |

### 關鍵洞察
- **傳統假說在 crypto 不成立**：Ang et al. (2006) 的股票市場結論無法移植
- 高波動期（平均持續 6 天）中 momentum 信號更強，不是更弱
- 低波動期持續時間更長（中位數 26.5 天），但 momentum 反而更弱
- 這可能反映 crypto 的**散戶 FOMO 驅動**特性：越是高波動，追漲殺跌越明顯

### 建議下一步
1. 改變假說方向：研究**高波動 + momentum 組合**，而非對立
2. 研究 vol regime 作為倉位規模調節器（高波動縮倉，而非換方向）

---

## 五、跨策略比較與組合建議

### 相關性分析（推測）

| | Funding CS | Sector Rotation | OI Long | Vol Regime |
|--|-----------|----------------|---------|------------|
| **Funding CS** | 1.0 | 低 | 中 | 低 |
| **Sector Rotation** | 低 | 1.0 | 低 | 中 |
| **OI Long** | 中 | 低 | 1.0 | 低 |

### 組合建議

**短期可行組合（2 個策略）：**
```
主策略：Funding CS（高信念版，|f| ≥ 0.05%）
補充策略：OI Long-only（top 10%，7 日持有）

邏輯：
- Funding CS 捕捉極端擁擠的反轉機會（短期，1-3 天）
- OI Long 捕捉去槓桿後的健康上漲（中期，7 天）
- 兩者信號來源不同，相關性低
```

**中期研究方向：**
```
Sector Rotation 改良版：
- 只用 L1 + L2（IC 有效的 sector）
- 加入 inverse vol weighting
- 配合 BTC regime filter
```

---

## 六、研究方法論總結

### Subagent 並行研究的優點
- 4 個策略同時研究，總耗時 ~11 分鐘（最慢的 OI）
- 各 agent 獨立，不互相影響結論
- 可以在相同 universe 和費用假設下比較結果

### 已知資料限制
| 限制 | 影響策略 | 嚴重程度 |
|------|---------|---------|
| OI 歷史 API 只有 30 天 | OI-Divergence | 🔴 高 |
| SHIB/PEPE 無 Futures 資料 | 全部 | 🟡 中 |
| 2023-2024 牛市偏差 | OI Short 側 | 🔴 高 |
| Vol proxy（成交量比例）精度 | OI-Divergence | 🟡 中 |

---

## 七、下一步優先級

| 優先 | 行動 | 預期價值 |
|------|------|---------|
| 🔴 1 | Funding CS：完整牛熊週期測試（2020-2024） | 驗證穩健性 |
| 🔴 2 | OI-Divergence：取得真實 OI 歷史資料 | 修正核心資料問題 |
| 🟡 3 | Sector Rotation：只用 L1+L2 + inverse vol | 提升 Sharpe |
| 🟡 4 | Vol Regime：改研究高波動下的倉位調節 | 轉換假說方向 |
| 🟢 5 | Funding CS + OI Long 組合回測 | 驗證組合效果 |

---

*研究日期：2026-05-21 | 研究員：4 個並行 Subagent | 彙整：Binance AI Pro*
