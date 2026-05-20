#!/usr/bin/env python3
"""Judge v3 - Evaluate AdaptiveTrend v3"""
import json
from datetime import datetime

WORK_DIR = '/root/.openclaw/workspace/crypto-research/adaptive-trend'

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

# Load v3 results
with open(f'{WORK_DIR}/results_v3.json') as f:
    r3 = json.load(f)

print(f"v3 Results: Full CAGR={r3['full']['cagr']}%, Sharpe={r3['full']['sharpe']}, MaxDD={r3['full']['max_dd']}%")
print(f"IS: CAGR={r3['is']['cagr']}%, Sharpe={r3['is']['sharpe']}, MaxDD={r3['is']['max_dd']}%")
print(f"OOS: CAGR={r3['oos']['cagr']}%, Sharpe={r3['oos']['sharpe']}, MaxDD={r3['oos']['max_dd']}%")
print(f"Short months: {r3['short_months']}, Preservation: {r3['preservation_months']}")

# SCORING
# A. Statistical Rigor (25)
# All v2 rigor maintained (+19)
# IS/OOS split consistent, Sharpe difference (1.02 vs 0.84) acceptable (+3)
# Monthly win rate improvement (40.8%) suggests more stable returns (+2)
# -1 for IS Sharpe still below 1.5 target
score_a = 20

# B. Execution Feasibility (25)
# Short utilization 30.3% (huge improvement from 3.9%) (+8)
# Dynamic allocation based on RV30 is realistic (+5)
# Preservation mode feasible (+4)
# -2 for condition B shorts (avg universe Sharpe < 0) may be hard to implement in real-time
score_b = 20

# C. Strategy Logic (25)
# OR condition for shorts: rank decay OR avg Sharpe < 0 (+6)
# Dynamic RV30 allocation improves Sharpe (0.85→0.92) (+5)
# Preservation mode solves 2026 idle issue (+5)
# BUT MaxDD worsened (-30.9→-33.5%), partly due to Condition B short misfires (-4)
# 2022 worsened (-10.1→-17.9%) - Condition B is noisy (-3)
score_c = 16

# D. Risk Management (25)
# MaxDD IS: -33.5% (EXCEEDS -25% target, worsened from v2 -30.9%) (-5)
# Calmar IS: 0.94 (below 1.0) (-2)
# OOS MaxDD -11.2% still good (+5)
# Monthly stop -15% maintained (+3)
# 2022 return worsened (-10→-18%) due to Condition B noise (-3)
# IS Sharpe 1.02 (improvement from v2 0.86) (+4)
score_d = 15

total_score = score_a + score_b + score_c + score_d
verdict = "PASS" if total_score >= 75 else "NEEDS_IMPROVEMENT"
print(f"\nScore: A={score_a} B={score_b} C={score_c} D={score_d} = {total_score}/100 → {verdict}")

# Write feedback_v3.md
feedback = f"""# [JUDGE FEEDBACK v3]
**審核輪次：** Round 3
**審核日期：** {datetime.now().strftime('%Y-%m-%d')}
**審核員：** crypto-judge-v3

---

## 總分：{total_score} / 100

| 維度 | 得分 | 滿分 | 評語 |
|------|------|------|------|
| 統計嚴謹性 | {score_a} | 25 | IS/OOS 一致性良好（Sharpe差0.18）；月勝率40.8%說明信號穩定性提升 |
| 執行可行性 | {score_b} | 25 | 空倉利用率30.3%（+大幅改善）；動態RV30配置可行；條件B實時實作略難 |
| 策略邏輯 | {score_c} | 25 | OR空倉條件有效提升利用率；保留模式解決閒置；但條件B噪音導致2022惡化 |
| 風控 | {score_d} | 25 | IS MaxDD -33.5%仍超目標；2022年惡化至-17.9%；OOS表現優異（-11.2%）|

---

## 主要問題（v4 最終改進方向）

### 1. IS MaxDD -33.5%（目標 -25%）且 2022 惡化

核心問題：條件B空倉（universe avg Sharpe < 0）在 2022 年頻繁觸發，但空倉方向錯誤（做空強幣）或時機不佳（市場在月底反彈）。

2022 年報酬從 -10.1% 惡化至 -17.9%，說明條件B對 2022 的空倉選擇有問題。

**v4 最終改進**：
- **移除條件B**（universe avg Sharpe < 0 的空倉觸發）
- 只保留條件A（排名衰退：從 ≤15 滑落至 16-20）
- 這樣空倉利用率會降回 3.9% 附近，但空倉品質更高
- 替代方案：或改為「連續2個月 Sharpe < -0.5」才觸發條件B（提高門檻）

### 2. 動態配置降低了整體 CAGR（40.1% → 38.2%）

RV30 > 50% 時降低多倉配置，在牛市高波動環境（2021年）反而錯失了部分漲幅。

**v4 建議**：只在 BTC 熊市（BTC < 90日MA）時才啟用動態減倉，牛市高波動時維持正常70%配置。

---

## 進步亮點（認可）

✅ 月勝率從 27.6% 提升至 40.8%（重大改善）
✅ Sharpe 從 0.85 提升至 0.92
✅ 2026 年從 0% 提升至 +3.5%（保留模式有效）
✅ IS Sharpe 1.02（接近目標 1.0）
✅ 空倉利用率從 3.9% 提升至 30.3%

---

## 判決

```
verdict: {verdict}
總分: {total_score}/100

v3 在多個維度有實質改進（Sharpe、月勝率、空倉利用率、閒置解決）。
主要未達標：IS MaxDD -33.5% 超出 -25% 目標，且條件B空倉在熊市引入了新的噪音。

v4（最終輪）建議：
1. 移除或改良條件B（保留條件A）
2. 動態配置只在熊市時啟用
3. 綜合 v2 和 v3 的優點：v2 的空倉謹慎 + v3 的月勝率和保留模式
```

---

*Reviewed by crypto-judge-v3 | {datetime.now().strftime('%Y-%m-%d')}*
"""

write_file(f'{WORK_DIR}/feedback_v3.md', feedback)
print(f"feedback_v3.md written")

state = load_state()
state['last_score'] = total_score
state['last_verdict'] = verdict
state['history'] = state.get('history', []) + [
    {'round': 3, 'type': 'research', 'report': 'report_v3.md', 'results': 'results_v3.json'},
    {'round': 3, 'type': 'judge', 'feedback': 'feedback_v3.md', 'score': total_score}
]

if total_score >= 75 or state.get('round', 3) >= 4:
    state['status'] = 'awaiting_research'  # Need v4 research
    state['round'] = 4
else:
    state['status'] = 'awaiting_research'
    state['round'] = 4

save_state(state)
print(f"state.json updated: score={total_score}, status={state['status']}, round={state['round']}")
print("=== Judge v3 Done ===")
