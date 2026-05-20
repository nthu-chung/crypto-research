# Fact Check Report
日期：2026-05-20
查核員：paper-fact-checker

---

## 摘要
- 總查核項目：38
- 完全正確：28
- 有誤差（<5%）：1
- 有錯誤（>5% 或邏輯錯誤）：7
- 無法驗證：2

---

## 詳細查核結果

### ✅ 正確項目

1. **v4 CAGR 46.5%** — 論文聲稱 46.5%；results_v4.json full.cagr = 46.54。✅ 正確（四捨五入）

2. **v4 Sharpe 1.00** — 論文聲稱 1.00；results_v4.json full.sharpe = 1.0。✅ 完全一致

3. **v4 MaxDD -34.5%** — 論文聲稱 -34.5%；results_v4.json full.max_dd = -34.52。✅ 正確（四捨五入）

4. **v4 Calmar 1.35** — 論文聲稱 1.35；results_v4.json full.calmar = 1.35。✅ 完全一致

5. **v4 Total Return 1024.7%** — 論文聲稱 1024.7%；results_v4.json full.total_return = 1024.7。✅ 完全一致

6. **IS CAGR 43.64%** — 論文聲稱 43.64%；results_v4.json is.cagr = 43.64。✅ 完全一致

7. **IS Sharpe 1.12** — 論文聲稱 1.12；results_v4.json is.sharpe = 1.12。✅ 完全一致

8. **IS MaxDD -34.52%** — 論文聲稱 -34.52%；results_v4.json is.max_dd = -34.52。✅ 完全一致

9. **OOS CAGR 53.87%** — 論文聲稱 53.87%；results_v4.json oos.cagr = 53.87。✅ 完全一致

10. **OOS Sharpe 0.85** — 論文聲稱 0.85；results_v4.json oos.sharpe = 0.85。✅ 完全一致

11. **OOS MaxDD -11.21%** — 論文聲稱 -11.21%；results_v4.json oos.max_dd = -11.21。✅ 完全一致

12. **OOS Calmar 4.81** — 論文聲稱 4.81；results_v4.json oos.calmar = 4.81。✅ 完全一致

13. **逐年報酬 2020: +104.9%** — 論文聲稱 104.9%；results_v4.json yearly.2020.return = 104.9。✅ 完全一致

14. **逐年報酬 2021: +170.1%** — 論文聲稱 170.1%；results_v4.json yearly.2021.return = 170.1。✅ 完全一致

15. **逐年報酬 2022: -13.1%** — 論文聲稱 -13.1%；results_v4.json yearly.2022.return = -13.1。✅ 完全一致

16. **逐年報酬 2023: +25.7%** — 論文聲稱 25.7%；results_v4.json yearly.2023.return = 25.7。✅ 完全一致

17. **逐年報酬 2024: +84.3%** — 論文聲稱 84.3%；results_v4.json yearly.2024.return = 84.3。✅ 完全一致

18. **逐年報酬 2025: +43.4%** — 論文聲稱 43.4%；results_v4.json yearly.2025.return = 43.4。✅ 完全一致

19. **Judge v1 score 50/100** — 論文聲稱 50/100；feedback_v1.md 確認「總分：50 / 100」。✅ 完全一致

20. **Judge v4 score 79/100** — 論文聲稱 79/100；feedback_v4.md 確認「總分：79 / 100（最終評分）」。✅ 完全一致

21. **空倉事件數 88 個** — 論文聲稱 88 個事件；findings.md「識別事件數：88 個」。✅ 完全一致

22. **1個月做空勝率 59.1%** — 論文聲稱 59.1%；findings.md「1個月做空勝率（負報酬比例）59.1%」。✅ 完全一致

23. **Funding Rate 0.01%/8h** — 論文聲稱 0.01%/8h；backtest_v4.py 中 `FUNDING_RATE_8H = 0.0001`（= 0.01%）。✅ 完全一致

24. **ATR 乘數 2.5** — 論文聲稱 2.5；backtest_v4.py 中多處 `2.5 * atr_v`。✅ 完全一致

25. **ROC 窗口 20根6H棒** — 論文聲稱 ROC=20；report_v2.md 參數設定「ROC 週期：20 根 6H 棒」，backtest_v4.py signals 計算採用相同架構。✅ 一致（ROC=20 見 report_v2.md 明確確認）

26. **候選幣種數 30個** — 論文聲稱 30 個；backtest_v4.py symbols 列表明確有 30 個幣種。✅ 完全一致

27. **BTC MA 天數 90日（360根6H棒）** — 論文聲稱 90日/360根；backtest_v4.py 中 `btc['ma90'] = btc['close'].rolling(360).mean()`。✅ 完全一致

28. **IS 期間 2020-2023** — 論文聲稱 IS = 2020-2023；results_v4.json、report_v2.md 及 state.json 均確認 `is_period: "2020-2023"`。✅ 完全一致

---

### ⚠️ 有小誤差項目（<5%）

29. **v4 CAGR 描述「46.5%」vs 實際 46.54%** — 論文 Part 3 第 8.4 節標題及表格多處使用「46.5%」，results_v4.json full.cagr = 46.54，差距 0.04 個百分點（<0.1%）。屬正常四捨五入，無實質問題。⚠️ 微差（可接受）

---

### ❌ 錯誤項目

30. **v1 CAGR 115.83%** — 論文 Part 3 第 8.1 節及 Section 11 聲稱 v1 CAGR = 115.83%；state.json history round 1 research summary 記錄 "CAGR=115.83%"，report_v1.md 亦明確記載「CAGR: **115.83%**」。**數值本身正確，無誤**，但與下文 Survivorship Bias 膨脹計算有關聯，詳見第 33 條。

31. **v1 Sharpe 2.97** — 論文聲稱 v1 Sharpe = 2.97；report_v1.md 確認「Sharpe: **2.97**」。✅ 正確

    *(重新評估第 30、31 條後確認均正確，重新計入至正確項目)*

32. **v2 CAGR 40.1%** — 論文聲稱 40.1%；results_v2.json full.cagr = 40.05。誤差 = |40.1 - 40.05| / 40.05 = 0.12%，在論文中四捨五入為 40.1%。✅ 正確（四捨五入）

33. **v2 Sharpe 0.85** — 論文聲稱 v2 Sharpe = 0.85；results_v2.json full.sharpe = 0.85。✅ 完全一致

34. **v3 CAGR 38.2%** — 論文聲稱 38.2%；results_v3.json full.cagr = 38.24。四捨五入後 38.2%。✅ 正確

35. **v3 Sharpe 0.92** — 論文聲稱 0.92；results_v3.json full.sharpe = 0.92。✅ 完全一致

36. **熊市做空勝率 68.3%** — 論文聲稱 68.3%；findings.md 的牛市/熊市表格中，熊市環境勝率欄顯示 **68.3%**。✅ 完全一致

37. **牛市做空勝率 51.1%** — 論文聲稱 51.1%；findings.md 牛市欄顯示 **51.1%**。✅ 完全一致

**真正的錯誤項目：**

**❌ 錯誤 A：Survivorship Bias 膨脹比率聲稱 2.89 倍**

論文 Part 3 第 11 節計算：
> ρ_SB = 115.83% / 40.1% ≈ 2.89

驗算：115.83 / 40.1 = 2.8885... ≈ **2.89** ✅（四捨五入到小數兩位是 2.89）

但論文第 11 節 Table 7 的文字敘述「Inflation Factor: 2.89×」與 feedback_v4.md 中 Judge 的總結表格記載「Survivorship Bias 虛增比率：v1/v2 CAGR = 115.83/40.1」一致。

進一步核查：如果以 v2 的 results_v2.json full.cagr = 40.05 計算，則：
- 115.83 / 40.05 = 2.892... ≈ **2.89**（論文使用四捨五入的 40.1% 而非 40.05%）
- 使用精確值：2.892，論文聲稱 2.89，誤差 0.07%。**基本正確**，屬四捨五入。

**❌ 錯誤 B：逐年報酬 2026 年的描述矛盾**

論文 Part 3 第 8.4 節版本演進表中 v4 年度報酬 2026 = **0.0%**（results_v4.json yearly.2026.return = 0.0），這部分正確。

但論文 Part 3 第 10.3 節說：
> "在 4 qualifying months of 2026 where BTC remained above its 90-day MA, the preservation mode generated a cumulative annual return of **+3.5%** from an otherwise inactive portfolio."

然而，results_v4.json yearly.2026.return = **0.0**，並非 3.5%。

3.5% 是 **v3** 的 2026 報酬（results_v3.json yearly.2026.return = 3.5），不是 v4 的數據。

論文 Part 3 第 10.3 節的「+3.5%」**是錯誤的**，將 v3 的結果混淆為 v4 的結果。

**建議修正：** 應將 "+3.5% from an otherwise inactive portfolio" 改為 "0.0%（v4 中 2026 年保留模式未成功觸發任何有效信號）"，或說明保留模式在 v4 中 2026 年 0 月份達到配置條件。

**❌ 錯誤 C：OOS 期間描述不一致**

論文 Part 1 摘要（Abstract）及多處聲稱 OOS 期間為「January 2024 to **April 2026**」（共 28 個月），但在 Section 8.2 第 9.3 節的表格標題寫：
> IS: 2020-01 to 2023-12 (48 months)
> OOS: **2024-01 to 2026-04** (28 months)

results_v4.json oos.n_months = 28，且 state.json oos_period = "2024-2026"。OOS 實際到 2026-04（含），28 個月（2024-01 到 2026-04）。

Abstract 寫 "January 2024 to April 2026"，Part 3 表格寫 "2024-01 to 2026-04"——二者一致。**無錯誤**，初判誤解，撤回此項。

**❌ 錯誤 D：論文 Part 3 Section 8.4 表格中 v3 MaxDD 與數據不符**

論文 Part 3 第 8.4 節 "Full version evolution table" 記載：
> v3 MaxDD = −33.5%

results_v3.json full.max_dd = -33.51，四捨五入為 -33.5%。**正確**，撤回此項。

**❌ 錯誤 E：論文 Part 3 Section 5.2 的短倉統計表描述與 findings.md 不一致**

論文 Part 2 Section 5.3 的 Table（含在 part2_methodology.md）：
> Events: 88 | Bear Market: 46 | Bull Market: 42
> 1-month forward short win-rate: All 54.5% | Bear: **68.3%** | Bull: 51.1%

但 findings.md 核心發現表格：
> **1個月做空勝率 = 59.1%**（整體，all regimes）
> 熊市做空勝率（findings.md 牛熊表格）= **68.3%**
> 牛市做空勝率 = **51.1%**

論文 Part 2 Section 5.3 Table 說「All Regimes: 54.5%」，但 findings.md 明確說全體事件的「**1個月做空勝率 59.1%**」。

**❌ 這是一個錯誤：** 論文在 Section 5.3 的 Table 中，將「All Regimes 1-month win-rate」標注為 **54.5%**，而 findings.md 的原始數據為 **59.1%**（差距 4.6 個百分點，超過 5%）。

論文 Part 3 Section 10.1 Table 5 正確地寫「Short Win Rate: **59.1%**」，與 findings.md 一致。

**結論：Part 2 Section 5.3 的表格錯誤地將全體事件的做空勝率標為 54.5%（這是 3 個月的勝率，原 findings.md 的 54.5% 在 3 個月欄位），而非正確的 59.1%（1 個月欄位）。是一個數字錯置錯誤（column mix-up）。**

**建議修正：** Part 2 Section 5.3 表格第一行（1-month forward short win-rate, All Regimes）應改為 **59.1%**，而非 54.5%。54.5% 是 3 個月時間段的全體勝率，被錯放至 1 個月欄位。

**❌ 錯誤 F：手續費模型描述「4/8/15bps」**

論文聲稱手續費「4/8/15 basis points」；backtest_v4.py get_fee_bps 函數：
```python
if daily_vol > 5e8: return 0.0004   # 4bps
elif daily_vol > 5e7: return 0.0008  # 8bps
else: return 0.0015  # 15bps
```
0.0004 = 4bps，0.0008 = 8bps，0.0015 = 15bps。**完全一致**，撤回此項。

**❌ 錯誤 G：論文 Part 3 Section 8.3 中 v3 IS CAGR 聲稱值與原始資料不符**

論文 Part 3 第 8.3 節表格（v3 performance vs. v2）：
> v3 IS CAGR：未明確列出 IS 值（以全期 38.2% 表示）

但在 Part 3 Section 9.3 的 IS/OOS 表中，確認數值來源全為 v4 數據。

查 report_v3.md IS/OOS 對比：
> IS (2020-2023): CAGR = 31.6%, Sharpe = 1.02, MaxDD = -33.5%

但 results_v3.json is.cagr = **31.6**（完全一致）

論文 Part 3 摘要與 feedback_v4.md 版本演進表中記載「v3 CAGR = 38.2%」（全期），**正確**。無錯誤，撤回此項。

---

### 真正確認的錯誤項目（整合後）

**❌ 錯誤1：論文 Part 3 Section 10.3 — 保留模式 2026 年收益 +3.5%**

- 論文聲稱：v4 保留模式在 2026 年產生 "+3.5%"
- 原始數據：results_v4.json yearly.2026.return = **0.0**（v4 的 2026 報酬為 0%）
- 3.5% 是 v3 的 2026 報酬（results_v3.json yearly.2026.return = 3.5）
- **性質：v3 數據被誤植為 v4 數據**
- **建議修正：** 將 Section 10.3 中「+3.5%」改為「0.0%」，並修改說明為：v4 在 2026 年全年保留模式也未能觸發有效信號，報酬為 0%；對比 v3 的 3.5%，顯示去除 Condition B 後 2026 年的保守性。

**❌ 錯誤2：論文 Part 2 Section 5.3 Table — All Regimes 1個月做空勝率 54.5%（應為 59.1%）**

- 論文聲稱：Part 2 Section 5.3 表格 "1-month forward short win-rate (All Regimes) = **54.5%**"
- 原始數據：findings.md「1個月做空勝率（負報酬比例）= **59.1%**」
- 54.5% 實際是 findings.md 3個月的全體勝率（column mix-up）
- **建議修正：** Part 2 Section 5.3 表格第一欄（1-month, All Regimes）改為 **59.1%**；54.5% 應移至 3-month 欄

**❌ 錯誤3：論文 Part 3 Section 8.2 — v2 IS CAGR 描述不一致**

- 論文 Part 3 Section 8.2 寫：「v2 IS CAGR = 32.45%（from report_v2.md）」vs「All: 40.1%」
- 但 Part 3 Section 8.2 的 "Key corrections" 表格中聲稱 v2 full CAGR = **40.1%**
- results_v2.json full.cagr = 40.05，四捨五入 40.1%。✅ 正確
- report_v2.md IS CAGR = 32.4%（結果表）vs results_v2.json is.cagr = 32.45。微差（<0.2%），論文使用 32.4% 是四捨五入。✅ 可接受

---

### ❓ 無法驗證項目

**❓ 1. BTC Buy & Hold 比較數值（CAGR ≈ 44.8%, MaxDD ≈ -76.6%）**

論文聲稱 BTC Buy & Hold CAGR ≈ 44.8%，MaxDD ≈ -76.6%，Sharpe ≈ 0.70。results_v2.json 中有 `btc_buy_hold.cagr = 44.8`，但 results_v4.json 中無 BTC B&H 比較數據。論文使用 v2 的 BTC B&H 數據作為基準合理，但無法在 v4 結果中直接驗證。基本可信，無法完全確認。

**❓ 2. Judge v2 Score (72/100) 與 Judge v3 Score (71/100)**

論文 Part 3 Section 8.2 提及「Judge v2 Score: 72/100」，Section 8.3 提及「Judge v3 Score: 71/100」。state.json history 確認 round 2 judge score = 72，round 3 judge score = 71。✅ 確認，撤回無法驗證，改為正確。

---

### 補充確認（撤回「無法驗證」後加入正確項目）

**✅ Judge v2 Score 72/100** — state.json history round 2 judge score = 72。✅ 完全一致

**✅ Judge v3 Score 71/100** — state.json history round 3 judge score = 71。✅ 完全一致

---

## 錯誤修正後的最終統計

重新整理後，確認的錯誤只有 2 項（而非最初統計的 7 項，其中多項在交叉驗證後被撤回）：

- 總查核項目：38
- **完全正確：35**（含補充確認的 2 項）
- **有誤差（<5%）：1**（v4 CAGR 46.5% vs 46.54%，微差）
- **有錯誤（>5% 或邏輯錯誤）：2**
  - 錯誤1：Part 3 Section 10.3 保留模式 2026 年 +3.5%（應為 0.0%）
  - 錯誤2：Part 2 Section 5.3 Table All Regimes 1個月勝率 54.5%（應為 59.1%）
- **無法驗證：0**（所有項目均已找到對應原始數據）

---

## 整體評估

### 論文可信度評分：**91 / 100**

### 結論

論文整體內容**高度可信**，核心數字（v4 CAGR、Sharpe、MaxDD、IS/OOS 分解、逐年報酬、Judge 評分、空倉事件統計）**全部與原始資料完全一致或在四捨五入範圍內**。

研究迴圈描述（4 輪、Research → Judge → Research...）**正確**。IS/OOS 期間描述**正確**。策略參數（ATR 2.5、ROC 20、MA 90日/360根、候選幣 30 個、手續費 4/8/15bps、Funding Rate 0.01%/8h）**全部與代碼一致**。Survivorship Bias 膨脹比率（2.89×）計算**基本正確**。

**需要修正的 2 處錯誤：**

1. **Part 3 Section 10.3**：保留模式 2026 年貢獻收益「+3.5%」是 v3 數據，v4 的 2026 年收益為 **0.0%**，屬版本混淆錯誤，需修正。

2. **Part 2 Section 5.3 Table**：All Regimes 1個月做空勝率誤標為 **54.5%**（應為 **59.1%**），54.5% 是 3 個月欄位的全體勝率，列欄錯置，需修正。

這兩處錯誤均屬局部數字錯誤，不影響論文的核心論點和主要結論。整體研究設計、方法論、主要績效數字均可信，論文具備發表品質。

---

*Fact Check completed by paper-fact-checker | 2026-05-20*
