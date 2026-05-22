# Universe Design

## 概述

這個 Universe Builder 為 Cross-Sectional Crypto Alpha 研究建立動態幣種池，實現 Point-in-Time 快照管理，避免 Survivorship Bias。

---

## 設計原則

### 三層架構

| 層次 | 說明 | 用途 |
|------|------|------|
| **Risk Factors** | BTC、ETH | 不納入 altcoin universe，作為 beta 中性化因子 |
| **Altcoin Universe** | Top 30 流動性 USDT perp | 主要研究與交易標的 |
| **Excluded** | 穩定幣、wrapped assets、SHIB/PEPE（無 perp 資料） | 排除雜訊 |

### 篩選條件

```python
篩選邏輯（依序執行）：
1. 只保留 USDT perpetual futures（contractType=PERPETUAL）
2. 排除 BTC、ETH（作為 risk factor 使用）
3. 排除穩定幣和 wrapped assets
4. 上市天數 > 180 天（確保有足夠歷史資料）
5. 30D 中位數日交易量 > 50M USDT（確保流動性）
6. 取前 30 名（by volume）
```

---

## Point-in-Time 快照

### 為什麼需要快照？

```
❌ 錯誤做法（Survivorship Bias）：
  用 2026年5月的 universe 回測 2022年的策略
  → 你「預知」了哪些幣會活下來

✅ 正確做法（Point-in-Time）：
  2022年1月回測 → 用 2022年1月的 universe
  2023年6月回測 → 用 2023年6月的 universe
```

### 快照頻率

- **每 4 週**重建一次 universe 成員
- **2020-03 至 2026-05**，共 81 個快照
- 每個快照含：symbol、listing_date、listing_days、vol_30d_median、category、bucket

### Universe 規模演進

```
2020 初期：14 個幣（perp 市場剛起步）
2023 Q1：15 個（SOL perp 成熟）
2023 Q4：17 個（AI narrative 幣開始有量）
2024 Q3：20 個（新幣爆量 cycle）
2026 Q2：30 個（完整 Top 30）
```

---

## Taxonomy 分類表

雙分類系統：
- `category`：基本面敘事分組（L1/L2/DeFi/Meme/AI/Gaming/Infra/Storage/Privacy/Exchange）
- `bucket`：交易行為分組（high_beta/mid_beta/meme/unknown）

### 用途

1. **Sector Neutralization**：在 sector 內部排名，避免單押某個 narrative
2. **Sector Rotation**：找動能最強的 sector，在其中選最強的幣
3. **風險分析**：區分 meme 幣與基本面幣的不同風險特性

---

## 使用方式

```bash
# 安裝依賴
pip install pandas requests

# 建立當前 universe 快照
python universe_builder.py --top 30 --min-days 180

# 重建 2020~今的歷史快照（首次執行）
python universe_builder.py --top 30 --min-days 180 --rebuild-history --freq-weeks 4

# Point-in-Time 查詢：2022年1月的 universe 是什麼？
python universe_builder.py --query-date 2022-01-01
```

---

## 與 Alpha Pipeline 的銜接

```
Universe Builder
      ↓
Point-in-Time Snapshot（每4週）
      ↓
Alpha Pipeline
  ├── Step 1: 從快照取當期 universe
  ├── Step 2: 計算 returns / funding / OI / volatility
  ├── Step 3: Winsorize extreme values
  ├── Step 4: BTC/ETH beta 中性化
  ├── Step 5: Sector group neutralization（用 taxonomy）
  ├── Step 6: 計算 alpha signal
  └── Step 7: Long top 20% / Short bottom 20%
```

---

## 已知限制

| 限制 | 說明 | 影響 |
|------|------|------|
| Volume proxy | 歷史快照用現在的 30D volume 作為代理 | 早期快照（2020-2022）流動性估計可能偏高 |
| Taxonomy 靜態 | 分類表需手動更新 | 新 narrative（如 AI）剛出現時可能 Unknown |
| OI 歷史限制 | Binance OI hist API 只有 30 天 | OI 相關策略需要付費資料源 |

---

*最後更新：2026-05-21 | 快照數量：81 個（2020-03 ~ 2026-05）*
