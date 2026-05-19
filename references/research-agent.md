# Research Agent Task Template

Use this as the `task` parameter when spawning the Research subagent.

## Template

```
你是加密貨幣量化研究員 (crypto-research agent)。

## 第一步：讀取狀態
讀取 /root/.openclaw/workspace/research/state.json
- 取得當前 round、topic、config、以及上一輪 Judge 的 feedback 路徑

如果 round >= max_rounds 或 last_score >= 8，
  → 讀取所有歷史 report 和 feedback
  → 整理最終報告，sessions_send(label="main", message="[FINAL REPORT] ...")
  → 更新 state.json status = "complete"
  → 結束

## 第二步：讀取上一輪 Judge 意見（round > 1 時）
讀取 workspace/research/feedback_v{round-1}.md
重點關注：「優先改進建議」和「對研究員的具體指示」

## 第三步：執行研究與回測
根據 topic 和 Judge 意見進行研究：
- 用 web_search / web_fetch 找相關資料（如可用）
- 用 exec 跑 Python 回測（CoinMetrics 資料，已有 pandas/numpy/matplotlib）
- 計算 Sharpe、最大回撤、勝率、年化報酬
- 納入手續費（config.fee_bps，taker=4bps）

## 第四步：寫報告
將完整報告寫到 workspace/research/report_v{round}.md

報告格式：
# [RESEARCH REPORT v{round}]
策略名稱：
核心邏輯：
## 回測結果
（表格：Sharpe、最大回撤、年化報酬、勝率、交易次數）
## 完整交易紀錄
## 訊號條件
## 選擇權應用（如適用）
## 本輪改進（相較上一輪）
## 風險提示
## 待改進方向

## 第五步：更新 state.json
{
  "round": {round},
  "status": "awaiting_judge",
  "history": [...加入本輪 report 路徑]
}

## 第六步：通知 main
sessions_send(label="main", message="[RESEARCH v{round}] 報告完成，摘要：...")
只需 3-5 行摘要，完整報告在檔案裡。

## 第七步：spawn Judge
用 sessions_spawn 啟動 Judge agent：
- label: "crypto-judge"
- mode: "run"
- runtime: "subagent"
- task: （使用 references/judge-agent.md 的模板，填入當前 round）
```

## CoinMetrics 資料抓取（標準寫法）

```python
import requests, time, pandas as pd

def fetch_coinmetrics(metrics, start="2012-01-01"):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data, params = [], {
        "assets": "btc", "metrics": metrics,
        "frequency": "1d", "start_time": start, "page_size": 1000
    }
    while True:
        j = requests.get(url, params=params, timeout=20).json()
        all_data.extend(j.get('data', []))
        token = j.get('next_page_token')
        if not token: break
        params = {"assets": "btc", "metrics": metrics,
                  "frequency": "1d", "page_size": 1000, "next_page_token": token}
        time.sleep(0.05)
    df = pd.DataFrame(all_data)
    df['date'] = pd.to_datetime(df['time'])
    return df.sort_values('date').reset_index(drop=True)
```

## 可用 Community Metrics
- `PriceUSD` — 每日收盤價
- `CapMVRVCur` — MVRV 比率
- `CapMrktCurUSD` — 市值
