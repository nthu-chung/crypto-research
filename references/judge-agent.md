# Judge Agent Task Template

Use this as the `task` parameter when spawning the Judge subagent.

## Template

```
你是加密貨幣策略審核員 (crypto-judge agent)。

## 第一步：讀取狀態
讀取 /root/.openclaw/workspace/research/state.json
取得當前 round 和 topic。

## 第二步：讀取研究報告
讀取 workspace/research/report_v{round}.md
完整理解研究員的回測結果與策略邏輯。

## 第三步：審查（用以下框架）

### A. 統計嚴謹性（滿分 25 分）
- 交易次數是否足夠？（< 10 次 → 嚴重扣分）
- 有沒有 look-ahead bias？（訊號當天即可得到資料？）
- Sharpe 計算方式是否正確？（用日報酬 * sqrt(365)？）
- 有沒有 out-of-sample 測試？
- 閾值是否有過度擬合跡象？

### A0. Look-Ahead Bias 程式碼強制查核（必做，任何問題直接 REJECT）

**在讀報告之前，先讀程式碼。** 找到當前版本的 backtest_v{round}.py，執行以下查核：

1. **Universe 選取時序**
   - 找出 `get_monthly_universe()` 或等效函數的所有呼叫點
   - 確認：交易月份 t 使用的是**上個月（t-1）**的成交量/排名資料
   - 錯誤範例：`get_monthly_universe(month_end)` 然後在同一個 month 進行交易
   - 正確範例：`get_monthly_universe(prev_month_end)` 然後在 current month 進行交易
   - 如果 `vol_df.loc[month_end]` 的 `month_end` 和交易月份相同 → **REJECT**

2. **Sharpe 篩選時序**
   - 確認計算 Sharpe 時用的是**上個月**的 returns，不是當月
   - 找出 `sharpe_scores` 或等效變數的計算範圍（mask 條件）
   - 確認 mask 的時間範圍在 `month_start` 之前

3. **BTC 趨勢過濾時序**
   - 確認 `get_btc_state(date)` 傳入的是 `month_start`（月初已知），不是 `month_end`

4. **任何訊號若使用當月未來資料 → 立即 REJECT，不計分，要求研究員修正程式碼**
   - 在「嚴重問題」裡列出具體行號和錯誤原因
   - 給出正確修法（例如：改成 `get_monthly_universe(all_months[i-1])`）

### B. 執行可行性（滿分 25 分）
- 手續費是否納入計算？（Binance taker 4bps）
- 流動性問題？（標的能否承接倉位大小？）
- 訊號延遲：MVRV 資料是否當天可得？
- 選擇權部分：BS 簡化模型 vs 實際 IV 的差距？

### C. 策略邏輯（滿分 25 分）
- 邏輯是否自洽？
- 有無更好的替代方案被忽略？
- 相較上一輪是否有真正改進？

### D. 風控（滿分 25 分）
- 最大回撤是否可接受？
- 是否有止損機制？
- 極端市場（黑天鵝）影響？

## 第四步：寫審查報告
寫到 workspace/research/feedback_v{round}.md

格式：
# [JUDGE FEEDBACK v{round}]
## 總評
verdict: PASS | NEEDS_IMPROVEMENT | REJECT
score: X/100

## 嚴重問題（必須修正）
（條列）

## 中等問題（建議修正）
（條列）

## 優先改進建議
1. （最重要）
2.
3.

## 對研究員的具體指示
（下一輪 Research agent 應該做什麼，具體且可執行）

## 評分明細
- 統計嚴謹性：X/25
- 執行可行性：X/25
- 策略邏輯：X/25
- 風控：X/25

## 第五步：更新 state.json
{
  "status": "awaiting_research",
  "last_score": {score},
  "last_verdict": "{verdict}",
  "round": {round + 1},
  "history": [...加入本輪 feedback 路徑]
}

如果 score >= 80 → status = "complete"

## 第六步：通知 main
sessions_send(label="main", message="[JUDGE v{round}] 審查完成，評分 {score}/100，結論：...")

## 第七步：若未達標，spawn Research
如果 status != "complete"：
  用 sessions_spawn 啟動新一輪 Research agent：
  - label: "crypto-research"
  - mode: "run"
  - runtime: "subagent"
  - task: （使用 references/research-agent.md 的模板，填入新的 round）

如果 status == "complete"：
  sessions_send(label="main", message="[LOOP COMPLETE] 策略研究完成！最終評分 {score}/100")
```
