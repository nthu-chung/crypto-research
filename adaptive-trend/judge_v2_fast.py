#!/usr/bin/env python3
"""
Judge v2 - FAST version: evaluate, write feedback, update state, notify
No spawning - just evaluation and file writes
"""
import json, os
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

print("=== Judge v2 Fast Evaluation ===")

state = load_state()
print(f"State: round={state['round']}, status={state['status']}")

# SCORING
score_a = 19  # Statistical rigor: survivorship bias fixed, IS/OOS split, no overfitting
score_b = 19  # Feasibility: funding rate, tiered fees, liquidity filter - but short underutilized
score_c = 17  # Strategy logic: BTC trend filter good, rank decay novel - but 2026 all idle
score_d = 17  # Risk: monthly stop works, OOS DD great, but IS MaxDD -30.9% exceeds -25% target

total_score = score_a + score_b + score_c + score_d
verdict = "NEEDS_IMPROVEMENT" if total_score < 75 else "PASS"

print(f"Score: A={score_a} B={score_b} C={score_c} D={score_d} = {total_score}/100 → {verdict}")

# Write feedback
feedback = f"""# [JUDGE FEEDBACK v2]
**審核輪次：** Round 2
**審核日期：** {datetime.now().strftime('%Y-%m-%d')}
**審核員：** crypto-judge-v2

---

## 總分：{total_score} / 100

| 維度 | 得分 | 滿分 | 評語 |
|------|------|------|------|
| 統計嚴謹性 | {score_a} | 25 | Survivorship Bias 確實修正；IS/OOS 分割正確；Sharpe 一致（IS=0.86 vs OOS=0.88）無過擬合跡象 |
| 執行可行性 | {score_b} | 25 | Funding Rate(0.01%/8h)、差異化滑點(4/8/15bps)、流動性過濾均已實作；空倉觸發率僅3.9%，30%配置大多閒置 |
| 策略邏輯 | {score_c} | 25 | BTC趨勢過濾邏輯正確；排名衰退做空信號新穎合理；2026年Jan-Apr全閒置說明信號門檻過嚴 |
| 風控 | {score_d} | 25 | IS MaxDD=-30.9%超出-25%目標；月度止損-15%有效；OOS MaxDD=-8.0%優異；Calmar IS=1.05/OOS=7.07 |

---

## 嚴重問題（v3 必須修正）

### 1. IS MaxDD -30.9% 超出研究目標（目標：< -25%）

2022熊市中，策略最大回撤達-30.9%。主要因為多倉配置為固定70%，市場高波動時未自動減倉。

**v3 修正方案（動態配置）：**
- 計算 BTC 最近30天已實現波動率（RV30 = 30日日報酬標準差 × √365）
- RV30 < 50%：多倉配置 70%（正常）
- RV30 50-80%：多倉配置 55%（減倉）
- RV30 > 80%：多倉配置 40%（最低）

### 2. 空倉利用率過低（3.9%，76個月中只有3個月）

在31個BTC熊市月份中，只有3個月觸發空倉。排名衰退（≤15→16-20）是罕見事件，導致空倉配置大多閒置。

**v3 修正方案（放寬空倉條件，取 OR）：**
- 條件A（保留）：BTC熊市 + 幣種從≤15排名跌至16-20
- 條件B（新增）：BTC熊市 + universe平均月度Sharpe < 0（整體市場弱勢時，做空Sharpe最低的1-2個幣）

### 3. 2026年信號過嚴（Jan-Apr共4個月全閒置）

Sharpe ≥ 1.3 門檻在震盪市場中無候選，導致大量閒置資金。

**v3 修正方案（保留模式）：**
- 若無Sharpe ≥ 1.3候選，但有Sharpe ≥ 0.8的幣種且BTC > 90日MA：
- 啟用「保留模式」：取Sharpe最高2個幣，但配置降至正常的60%（即 0.7 × 0.6 = 42%）

---

## 中等問題（建議改進）

### 4. 策略在無趨勢年份（2022、2020）表現差

2022年：-10.1%（應是空倉受益的年份，但空倉觸發不足）
2020年：-1.2%（宇宙較小，早期幣種動量弱）

### 5. OOS表現好（+183.9%）可能部分因運氣

2024年BTC ETF效應和2025年市場強勁，使OOS的多倉幾乎無懸念獲利。
v3應明確說明：若OOS期間是熊市，策略是否仍能表現良好？

---

## 判決

```
verdict: {verdict}
總分: {total_score}/100

主要成就（v2相對v1的改進）：
- CAGR從虛構的115.83%降至真實的40.1%，與Judge預測一致
- Survivorship Bias徹底修正，動態月度宇宙完全正確
- IS/OOS無過擬合（Sharpe差異僅0.02）
- Funding Rate和差異化滑點均已實作

主要待改進：
- IS MaxDD -30.9%超出-25%目標（需動態配置修正）
- 空倉利用率3.9%過低（需放寬OR條件）
- 2026信號過嚴（需保留模式）

預期v3修正後：MaxDD應改善至-20%至-25%，空倉利用率應提升至15-25%
```

---

## 評分說明

v2的核心方法論已達標，問題主要在參數優化層面：
- 動態波動率調整是標準的風控技術，v3可直接實作
- 空倉信號放寬是合理的，整體市場Sharpe < 0 是可靠的空倉指標
- 保留模式降低Sharpe門檻是務實的改進，避免過度閒置

---

*Reviewed by crypto-judge-v2 | {datetime.now().strftime('%Y-%m-%d')}*
"""

write_file(f'{WORK_DIR}/feedback_v2.md', feedback)
print(f"feedback_v2.md written ({len(feedback)} chars)")

# Update state
state['last_score'] = total_score
state['last_verdict'] = verdict
state['history'] = state.get('history', []) + [{
    'round': 2,
    'type': 'judge',
    'feedback': 'feedback_v2.md',
    'score': total_score
}]

if total_score >= 75:
    state['status'] = 'complete'
else:
    state['status'] = 'awaiting_research'
    state['round'] = 3  # Research v3 will be round 3

save_state(state)
print(f"state.json updated: score={total_score}, status={state['status']}, round={state['round']}")

print("=== Judge v2 Done ===")
