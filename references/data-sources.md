# Data Sources

## CoinMetrics Community API（免費，無需 API Key）

Base URL: `https://community-api.coinmetrics.io/v4`

### 可用 BTC Metrics

| Metric | 說明 |
|--------|------|
| `PriceUSD` | 每日收盤價 |
| `CapMVRVCur` | MVRV 比率（Market Cap / Realized Cap）|
| `CapMrktCurUSD` | 市值（USD）|

### 注意事項
- 降序分頁，需用 `next_page_token` 取完所有頁面後再 sort ascending
- Rate limit 寬鬆，每頁 sleep 0.05s 即可
- `CapRealUSD`（Realized Cap）需付費帳號，community 無法使用

---

## Binance eAPI（選擇權，免費公開）

Base URL: `https://eapi.binance.com`

| Endpoint | 用途 |
|----------|------|
| `GET /eapi/v1/mark` | 所有 BTC 選擇權 Mark IV 和 Mark Price |
| `GET /eapi/v1/depth` | 盤口深度（bid/ask）|
| `GET /eapi/v1/index?underlying=BTCUSDT` | BTC 現貨指數價格 |

---

## Binance Spot API（免費公開）

Base URL: `https://api.binance.com`

| Endpoint | 用途 |
|----------|------|
| `GET /api/v3/klines?symbol=BTCUSDT&interval=1d` | K 線資料 |
| `GET /api/v3/ticker/price?symbol=BTCUSDT` | 即時價格 |

---

## 已安裝的 Python 套件

- `pandas`, `numpy`, `scipy`, `matplotlib` — 回測與視覺化
- `requests` — HTTP 請求
- `python-binance` — Binance API（需 API key 做交易）
