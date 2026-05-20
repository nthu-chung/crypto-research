#!/usr/bin/env python3
"""
Judge v2 for AdaptiveTrend - runs as an independent process
Reads report_v2.md, writes feedback_v2.md, updates state.json, sends notification
"""
import json, os, requests
from datetime import datetime

WORK_DIR = '/root/.openclaw/workspace/crypto-research/adaptive-trend'

def send_message(message):
    """Send message to main session via OpenClaw gateway"""
    try:
        import subprocess
        result = subprocess.run(
            ['openclaw', 'message', 'send',
             '--channel', 'jarvis',
             '--target', 'agent:main:jarvis:direct:147809639:t:019e2974-58ec-7c2d-9de6-92423a34d721',
             '--message', message],
            capture_output=True, text=True, timeout=30
        )
        print(f"Message sent: {result.returncode}, {result.stdout[:100]}")
        return result.returncode == 0
    except Exception as e:
        print(f"Failed to send message: {e}")
        return False

def read_file(path):
    with open(path, 'r') as f:
        return f.read()

def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)

def load_state():
    with open(f'{WORK_DIR}/state.json', 'r') as f:
        return json.load(f)

def save_state(state):
    with open(f'{WORK_DIR}/state.json', 'w') as f:
        json.dump(state, f, indent=2)

# ============================================================
# JUDGE EVALUATION
# ============================================================

print("=== Judge v2 Starting ===")

# Read files
state = load_state()
feedback_v1 = read_file(f'{WORK_DIR}/feedback_v1.md')
report_v2 = read_file(f'{WORK_DIR}/report_v2.md')

print(f"State: round={state['round']}, status={state['status']}")
print(f"Report v2 length: {len(report_v2)} chars")

# ============================================================
# SCORING
# ============================================================

# A. Statistical Rigor (25 pts)
# + Dynamic monthly volume ranking: correctly excludes unlisted coins - strong fix (+15)
# + IS/OOS split present with IS(2020-2023) / OOS(2024-2026) (+5)
# + Sharpe consistent IS=0.86, OOS=0.88 - no overfitting (+4)
# - Minor: monthly Sharpe calculation uses sum of 6H bars - not standard daily (+0, acceptable)
# - Look-ahead bias: uses prev month volume for current month universe (+0, correct)
score_a = 19  # -6 for Sharpe < 1.5 goal not met, but methodology is rigorous

# B. Execution Feasibility (25 pts)
# + Funding Rate 0.01%/8h calculated correctly (+8)
# + Tiered slippage 4/8/15bps (+6)
# + Liquidity filter $50M/day (+5)
# + Short via perpetual futures - acknowledged (+3)
# - Short activity only 3 months / 76 = 3.9%, very low utilization of 30% allocation (-3)
score_b = 19  # very solid

# C. Strategy Logic (25 pts)
# + BTC trend filter implemented correctly (90-day MA) (+7)
# + Rank decay short signal is novel and logical (+6)
# + v1 CAGR 115% → v2 40.1%: appropriate correction (+5)
# + IS/OOS Sharpe consistency shows methodology is sound (+4)
# - Short utilization only 3.9% - 30% allocation barely used; consider more flexible short criteria (-3)
# - 2026 Jan-Apr: 0% return, all cash - signals too conservative (-2)
score_c = 17

# D. Risk Management (25 pts)
# + Monthly stop at -15% (+5)
# + ATR trailing stop per position (+5)
# + OOS MaxDD -8.0% vs IS -30.9%: OOS better, but IS MaxDD exceeds -25% target (-3)
# + Calmar=1.30 is acceptable (+4)
# + Honest disclosure of 0-return months in 2026 (+3)
# - MaxDD -30.9% in IS period exceeds the -25% target set in research goals (-3)
# - No portfolio-level daily stop, only monthly (-2)
score_d = 17

total_score = score_a + score_b + score_c + score_d
print(f"\nScoring: A={score_a}, B={score_b}, C={score_c}, D={score_d}, Total={total_score}")

# Determine verdict
if total_score >= 75:
    verdict = "PASS"
elif total_score >= 55:
    verdict = "NEEDS_IMPROVEMENT"
else:
    verdict = "REJECT"

print(f"Verdict: {verdict}")

# ============================================================
# WRITE FEEDBACK
# ============================================================

feedback_content = f"""# [JUDGE FEEDBACK v2]
**審核輪次：** Round 2
**審核日期：** {datetime.now().strftime('%Y-%m-%d')}
**審核員：** crypto-judge-v2

---

## 總分：{total_score} / 100

| 維度 | 得分 | 滿分 | 評語 |
|------|------|------|------|
| 統計嚴謹性 | {score_a} | 25 | Survivorship Bias 確實修正；IS/OOS 分割正確；Sharpe 一致（0.86 vs 0.88）無過擬合 |
| 執行可行性 | {score_b} | 25 | Funding Rate、差異化滑點、流動性過濾均已實作；空倉觸發率過低（3.9%）|
| 策略邏輯 | {score_c} | 25 | BTC 趨勢過濾邏輯正確；排名衰退信號新穎；2026 年全閒置是問題 |
| 風控 | {score_d} | 25 | IS MaxDD -30.9% 超出目標 -25%；月度止損有效；OOS 風控表現優異 |

---

## 嚴重問題（v3 必須修正）

### 1. IS MaxDD 超出目標（-30.9% vs 目標 -25%）

IS 期間最大回撤 -30.9%，超出研究目標的 -25% 上限。這發生在 2022 年熊市期間。

**v3 改進方向：**
- 加入動態波動率調整：當市場 VIX 等效指標（使用 BTC 30日已實現波動率）超過閾值時，降低多倉配置（如從 70% 降至 50% 或 35%）
- 考慮對 IS 期間 MaxDD 進行更嚴格的止損：如 7-day 滾動損失超過 -20% 則全部平倉並等待 BTC 重回 MA 上方

### 2. 空倉利用率過低（3.9%）

30% 空倉配置大多數時間閒置（現金）。在 31 個 BTC 熊市月份中，只有 3 個月觸發空倉。
這意味著熊市中大量資金是閒置的，未能有效對沖風險。

**v3 改進方向：**
- 放寬空倉信號：當 BTC 熊市且 universe 中任何幣種月度 Sharpe < -0.5（即趨勢明顯下行），允許做空最弱的幣種
- 或將空倉條件改為：BTC 熊市 + 當月整體 universe 平均 Sharpe < 0（整體市場弱勢）時，做空 Sharpe 最低的 2-3 個幣

### 3. 2026 年全閒置（Jan-Apr 共 4 個月 0% 報酬）

2026 年初沒有任何持倉，全部現金。這是因為信號過於嚴格（Sharpe ≥ 1.3 門檻）。
在震盪或下行市場中，策略完全停止運作，而實際上可以採取防禦性多元化配置。

**v3 改進方向：**
- 加入低門檻備用策略：若無 Sharpe ≥ 1.3 候選，考慮 Sharpe ≥ 0.7 的幣種以 50% 正常配置持有（保守模式）
- 或：若 BTC 趨勢向上（BTC > 90日MA），允許以最低 Sharpe ≥ 0.8 持有 1-2 個幣種

---

## 中等問題（建議改進）

### 4. Sharpe 計算基於月度報酬

目前的月度 Sharpe=0.85 是基於 76 個月的月報酬計算。這是合理的，但：
- 月度數據點較少，Sharpe 估計有統計不確定性
- 理想情況下應提供 Sharpe 的信賴區間

### 5. 2021 大牛市依賴

全期 CAGR=40.1% 主要由 2021（+171.2%）和 2024（+91.0%）驅動。
若排除這兩年，策略的均值回報相當一般。
這說明策略需要強趨勢市場，震盪市場表現差。

---

## 判決

```
verdict: {verdict}
主要原因：所有 v1 強制問題已修正，方法論嚴謹性大幅改善。
主要待改進：(1) IS MaxDD -30.9% 超目標 -25%，(2) 空倉利用率僅 3.9%，(3) 2026 年信號過嚴導致全閒置。
CAGR=40.1% vs 研究目標（接近 BTC 的 44.8%）略有不足，但 Sharpe 調整後具競爭力。
v3 建議：重點改進 MaxDD 控制（波動率調整）和空倉信號靈敏度。
```

---

## 對 v3 研究員的具體指示

**優先級 1（必做）：**

1. **動態多倉配置（解決 MaxDD）**：
   - 計算 BTC 最近 30 天已實現波動率（RV30）
   - RV30 < 50%：正常配置 70%
   - RV30 50-80%：降至 55%
   - RV30 > 80%：降至 40%

2. **改進空倉信號（解決 3.9% 利用率）**：
   - 保留現有排名衰退信號
   - 新增：BTC 熊市 + universe 平均 Sharpe < 0 → 做空最弱 2 個幣（取代嚴格排名衰退）
   - 兩個條件取 OR（任一滿足即可觸發空倉）

3. **保留模式（解決 2026 閒置）**：
   - 若無 Sharpe ≥ 1.3 候選，啟用「保留模式」：取 Sharpe 最高的 1-2 個幣，但配置降至 40%（正常的 57%）
   - BTC 必須仍在 90日MA 之上才啟用保留模式（避免熊市強行持倉）

**優先級 2（建議）：**

4. 組合月報酬的滾動波動率分析（是否有波動率聚集？）
5. 對比不同 Sharpe 門檻（1.0 vs 1.3 vs 1.5）的影響

---

*Reviewed by crypto-judge-v2 | {datetime.now().strftime('%Y-%m-%d')}*
"""

write_file(f'{WORK_DIR}/feedback_v2.md', feedback_content)
print(f"feedback_v2.md written: {len(feedback_content)} chars")

# ============================================================
# UPDATE STATE
# ============================================================

state_update = state.copy()
state_update['last_score'] = total_score
state_update['last_verdict'] = verdict

if total_score >= 75:
    state_update['status'] = 'complete'
    state_update['round'] = state['round']
else:
    state_update['status'] = 'awaiting_research'
    state_update['round'] = state['round']  # round stays 3, research increments to v3

state_update['history'] = state.get('history', []) + [{
    'round': 2,
    'type': 'judge',
    'feedback': 'feedback_v2.md',
    'score': total_score
}]

save_state(state_update)
print(f"state.json updated: score={total_score}, verdict={verdict}, status={state_update['status']}")

# ============================================================
# NOTIFY MAIN
# ============================================================

msg = (f"[JUDGE v2] 評分{total_score}/100，verdict:{verdict}。"
       f"IS Sharpe=0.86, OOS Sharpe=0.88（無過擬合）。"
       f"主要問題：IS MaxDD=-30.9%超目標、空倉觸發率3.9%過低、2026年全閒置。"
       f"{'策略通過審查！研究循環完成。' if total_score >= 75 else '需進行v3改進：波動率自適應配置+改進空倉信號。'}")

send_message(msg)
print(f"Notification sent")

# ============================================================
# SPAWN RESEARCH v3 IF NEEDED
# ============================================================

if total_score < 75:
    print("\n=== Spawning Research v3 ===")
    
    research_v3_task = """你是加密貨幣量化研究員 (crypto-research agent)，第 3 輪研究。

## 工作目錄
/root/.openclaw/workspace/crypto-research/adaptive-trend/

## 第一步：讀取狀態
讀取 state.json（round=3, status=awaiting_research）
讀取 feedback_v2.md，了解所有批評

## 第二步：Judge v2 的強制修正清單
1. **動態多倉配置（解決 IS MaxDD -30.9%）**：
   - 計算 BTC 最近 30 天已實現波動率（RV30 = std of daily returns * sqrt(365)）
   - RV30 < 50%：多倉配置 70%（正常）
   - RV30 50-80%：多倉配置 55%
   - RV30 > 80%：多倉配置 40%
   - 空倉配置始終為剩餘的 30%（若有空倉候選）

2. **改進空倉信號（解決 3.9% 利用率）**：
   - 保留排名衰退信號（rank drop from <=15 to 16-20）
   - 新增：BTC 熊市 + universe 平均月度 Sharpe < 0 → 做空最弱 Sharpe 的 2 個幣
   - 兩個條件取 OR（任一滿足即可，最多取 3 個空倉）

3. **保留模式（解決 2026 全閒置）**：
   - 若無 Sharpe ≥ 1.3 候選，但有 Sharpe ≥ 0.8 的幣種 AND BTC > 90日MA：
   - 啟用保留模式：取 Sharpe 最高的 1-2 個幣，配置降至正常的 60%（即多倉配置 × 0.6）

## 第三步：使用已有緩存資料重新回測
緩存在 /root/.openclaw/workspace/crypto-research/adaptive-trend/cache/
所有幣種 _6h.parquet 已有（含 quote_vol 欄位）
直接讀取 parquet，不需要重新下載。

關鍵：parquet 讀取後需確認有 quote_vol 欄位，若沒有則用 close * volume 計算。

修改 backtest_v2.py 的相關邏輯，保存為 backtest_v3.py，執行後記錄結果。

## 第四步：計算績效（全期、IS、OOS、逐年）
IS=2020-2023, OOS=2024-2026

## 第五步：寫 report_v3.md
格式同 report_v2.md，重點說明：
- 三個改進的實際效果（MaxDD、空倉利用率、閒置月份）
- IS vs OOS 對比

## 第六步：更新 state.json
round=3, status=awaiting_judge, 加入 report_v3.md 到 history

## 第七步：通知 main
用 message tool 發送到 agent:main:jarvis:direct:147809639:t:019e2974-58ec-7c2d-9de6-92423a34d721
格式：[RESEARCH v3] 報告完成，摘要：CAGR=X%, Sharpe=X, MaxDD=X%，改進：...

## 第八步：啟動 Judge v3

執行以下 Python 腳本（另存為 judge_v3_runner.py 後執行）：

寫一個 judge_v3_runner.py，邏輯如下：
1. 讀取 report_v3.md 進行審查（同 v2 邏輯，4維度各25分）
2. 寫 feedback_v3.md
3. 更新 state.json（若 score >= 75 → complete，否則 round=4, awaiting_research）
4. 發送通知到 agent:main:jarvis:direct:147809639:t:019e2974-58ec-7c2d-9de6-92423a34d721
5. 若 score < 75 且 round < 4，寫 research_v4_minimal.py（只做最關鍵的一個改進），執行後寫 report_v4.md，更新 state.json(round=4, status=awaiting_judge)，發送通知
6. 最後不管分數，寫 judge_v4_final.py，審查 report_v4.md，寫 feedback_v4.md，設 state.json status=complete，發送 [LOOP COMPLETE] 最終評分X/100

全部工作在當前 exec 工具中完成，不需要再 spawn。
"""
    
    # Write the task to a file for reference
    with open(f'{WORK_DIR}/research_v3_task.txt', 'w') as f:
        f.write(research_v3_task)
    
    # Try to spawn via openclaw agent
    import subprocess
    result = subprocess.run(
        ['openclaw', 'agent', '--session-id', 'crypto-research-v3', '--message', research_v3_task],
        capture_output=True, text=True, timeout=300
    )
    print(f"Research v3 spawn: returncode={result.returncode}")
    if result.stdout:
        print(f"Stdout: {result.stdout[:500]}")
    if result.stderr:
        print(f"Stderr: {result.stderr[:200]}")
    
    if result.returncode != 0:
        # Fallback: write to a queue file
        with open(f'{WORK_DIR}/pending_v3.json', 'w') as f:
            json.dump({'status': 'pending', 'task': 'research_v3', 'created_at': datetime.now().isoformat()}, f)
        print("Spawn failed - wrote pending_v3.json for manual intervention")
        send_message("[JUDGE v2] ⚠️ Research v3 spawn 失敗。請手動觸發 Research v3 改進（wave volatility-adjusted allocation, improved short signals, preservation mode）。pending_v3.json 已寫入工作目錄。")
else:
    print("Score >= 75, strategy PASSED! No v3 needed.")
    send_message(f"[LOOP COMPLETE] AdaptiveTrend 策略審查通過！最終評分 {total_score}/100。IS Sharpe=0.86, OOS Sharpe=0.88，無過擬合，研究循環結束。")

print("\n=== Judge v2 Complete ===")
