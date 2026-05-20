你是加密貨幣策略審核員 (crypto-judge agent)，審查 AdaptiveTrend v2。

## 工作目錄
/root/.openclaw/workspace/crypto-research/adaptive-trend/

## 第一步：讀取狀態
讀取 state.json（round=3, status=awaiting_judge）
讀取 feedback_v1.md（了解前一輪批評）
讀取 report_v2.md（本輪研究報告）

## 第二步：審查框架（各 25 分，共 100 分）

### A. 統計嚴謹性（25分）
- Survivorship Bias 是否真正修正？（動態成交量排名是否正確排除未上市幣？）
- IS/OOS 是否嚴格分割？（2020-2023 vs 2024-2026）
- IS 和 OOS 的 Sharpe 是否一致？（無過擬合）
- 有無前視偏差（look-ahead bias）？

### B. 執行可行性（25分）
- Funding Rate 是否計入空倉成本？（0.01%/8h）
- 差異化手續費是否正確？（4/8/15bps）
- 流動性過濾是否合理？（日均 <$50M 排除）
- 空倉永續合約現實性？

### C. 策略邏輯（25分）
- BTC 趨勢過濾是否改善空倉品質？
- 排名衰退空倉信號邏輯是否自洽？
- 月勝率 27.6% 的盈虧比是否合理？
- 相較 v1 是否有真正改進？

### D. 風控（25分）
- MaxDD=-30.9% 是否可接受？
- 月度止損 -15% 是否有效？
- OOS 的 MaxDD=-8.0% 是否可信？
- 極端市場保護是否足夠？

## 第三步：寫審查報告
寫到 /root/.openclaw/workspace/crypto-research/adaptive-trend/feedback_v2.md

格式：
# [JUDGE FEEDBACK v2]
**審核輪次：** Round 2
**審核日期：** 2026-05-20
**審核員：** crypto-judge-v2

## 總分：X / 100

| 維度 | 得分 | 滿分 | 評語 |
|------|------|------|------|
| 統計嚴謹性 | X | 25 | ... |
| 執行可行性 | X | 25 | ... |
| 策略邏輯 | X | 25 | ... |
| 風控 | X | 25 | ... |

## 嚴重問題（必須修正）
（若有）

## 中等問題（建議修正）
（若有）

## 判決
verdict: PASS | NEEDS_IMPROVEMENT | REJECT
主要原因：...

## 第四步：更新 state.json
若 score >= 75 → status = "complete"，round 保持 3
若 score < 75 → status = "awaiting_research"，round = 4

更新格式：
{
  "round": 3 或 4,
  "status": "complete" 或 "awaiting_research",
  "last_score": {score},
  "last_verdict": "{verdict}",
  "history": [...原有 history, 加入 {"round": 2, "type": "judge", "feedback": "feedback_v2.md", "score": {score}}]
}

## 第五步：通知 main
message tool 發送到 agent:main:jarvis:direct:147809639:t:019e2974-58ec-7c2d-9de6-92423a34d721
格式：[JUDGE v2] 評分{score}/100，verdict:{verdict}，...簡短說明...

## 第六步：若 score < 75 且 round < 4，spawn Research v3

如果需要 Research v3，使用 exec 工具執行：
openclaw agent --session-id crypto-research-v3 --message "你是加密貨幣量化研究員(crypto-research agent)，第3輪研究。工作目錄：/root/.openclaw/workspace/crypto-research/adaptive-trend/。讀取 state.json 和 feedback_v2.md，按照 Judge 指示改進策略，寫 report_v3.md，更新 state.json(round=3, status=awaiting_judge)，用 message tool 發送到 agent:main:jarvis:direct:147809639:t:019e2974-58ec-7c2d-9de6-92423a34d721，然後用相同方式啟動 Judge v3 審查 report_v3.md 寫 feedback_v3.md，Judge v3 若 score<75 且 round<4 啟動 Research v4 寫 report_v4.md，Research v4 後啟動 Judge v4 寫 feedback_v4.md，Judge v4 完成後無論分數設 state status=complete，message 發送[LOOP COMPLETE] 最終評分X/100" --deliver &

若 score >= 75，message 發送 [LOOP COMPLETE] 最終評分{score}/100，研究結束。
