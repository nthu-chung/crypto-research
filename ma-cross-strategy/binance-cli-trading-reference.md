# Binance CLI 交易指令速查手冊

> **工具**：`binance-cli`（`@binance/binance-cli` npm 套件）  
> **用途**：透過 CLI 操作 Binance REST API，API Key 由 OpenClaw Gateway 安全注入，腳本無需直接處理金鑰。

---

## 目錄

1. [Spot 現貨](#-spot-現貨)
2. [Futures USDS-M 合約](#-futures-usds-m-合約)
3. [Convert 快速兌換](#-convert-快速兌換)
4. [Algo 大單分批](#-algo-大單分批)
5. [Order Type 對照表](#-order-type-對照表)
6. [策略腳本常用組合](#-策略腳本常用組合)

---

## 🟡 Spot 現貨

### 查詢

```bash
# 查餘額（排除零餘額）
binance-cli spot get-account --omit-zero-balances

# 查即時價格
binance-cli spot ticker-price --symbol BNBUSDT

# 查 24hr 漲跌統計
binance-cli spot ticker24hr --symbol BNBUSDT

# 查 K 線資料
binance-cli spot klines --symbol BNBUSDT --interval 1h --limit 100

# 查當前掛單
binance-cli spot get-open-orders --symbol BNBUSDT

# 查特定訂單狀態
binance-cli spot get-order --symbol BNBUSDT --order-id <id>

# 查歷史成交紀錄
binance-cli spot my-trades --symbol BNBUSDT
```

### 下單

```bash
# 市價買入
binance-cli spot new-order \
  --symbol BNBUSDT --side BUY --type MARKET \
  --quantity 1

# 限價買入
binance-cli spot new-order \
  --symbol BNBUSDT --side BUY --type LIMIT \
  --quantity 1 --price 580 --time-in-force GTC

# Stop Loss（止損限價）
binance-cli spot new-order \
  --symbol BNBUSDT --side SELL --type STOP_LOSS_LIMIT \
  --quantity 1 --stop-price 560 --price 559 --time-in-force GTC

# Take Profit（止盈限價）
binance-cli spot new-order \
  --symbol BNBUSDT --side SELL --type TAKE_PROFIT_LIMIT \
  --quantity 1 --stop-price 620 --price 621 --time-in-force GTC

# OCO 組合單（TP + SL 二合一，觸發一個自動取消另一個）★ 推薦
binance-cli spot order-list-oco \
  --symbol BNBUSDT --side SELL --quantity 1 \
  --above-type TAKE_PROFIT_LIMIT \
  --above-price 620 --above-stop-price 619 --above-time-in-force GTC \
  --below-type STOP_LOSS_LIMIT \
  --below-stop-price 560 --below-price 559 --below-time-in-force GTC

# 測試下單（驗證參數，不真實成交）
binance-cli spot order-test \
  --symbol BNBUSDT --side BUY --type MARKET --quantity 1
```

### 撤單

```bash
# 撤特定訂單
binance-cli spot delete-order --symbol BNBUSDT --order-id <id>

# 撤該幣對所有掛單
binance-cli spot delete-open-orders --symbol BNBUSDT

# 撤 OCO 組合單
binance-cli spot delete-order-list --symbol BNBUSDT --order-list-id <id>
```

---

## 🔵 Futures USDS-M 合約

### 查詢

```bash
# 查合約帳戶餘額
binance-cli futures-usds futures-account-balance-v3

# 查帳戶完整資訊（含 margin ratio）
binance-cli futures-usds account-information-v3

# 查當前持倉
binance-cli futures-usds position-information-v3 --symbol BNBUSDT

# 查即時標記價格
binance-cli futures-usds symbol-price-ticker --symbol BNBUSDT

# 查 Mark Price（含資金費率）
binance-cli futures-usds mark-price --symbol BNBUSDT

# 查當前掛單
binance-cli futures-usds current-all-open-orders --symbol BNBUSDT

# 查 K 線資料
binance-cli futures-usds kline-candlestick-data --symbol BNBUSDT --interval 1h --limit 100

# 查資金費率歷史
binance-cli futures-usds get-funding-rate-history --symbol BNBUSDT --limit 10

# 查多空比
binance-cli futures-usds long-short-ratio --symbol BNBUSDT --period 1h

# 查交易所規格（含 step_size / tick_size）
binance-cli futures-usds exchange-information
```

### 下單

```bash
# 市價開多
binance-cli futures-usds new-order \
  --symbol BNBUSDT --side BUY --type MARKET \
  --quantity 1

# 限價開空
binance-cli futures-usds new-order \
  --symbol BNBUSDT --side SELL --type LIMIT \
  --quantity 1 --price 590 --time-in-force GTC

# Stop Market（止損，合約常用）
binance-cli futures-usds new-order \
  --symbol BNBUSDT --side SELL --type STOP_MARKET \
  --quantity 1 --stop-price 560

# Take Profit Market（止盈，合約常用）
binance-cli futures-usds new-order \
  --symbol BNBUSDT --side SELL --type TAKE_PROFIT_MARKET \
  --quantity 1 --stop-price 620

# 平倉（reduce-only，不加倉）
binance-cli futures-usds new-order \
  --symbol BNBUSDT --side SELL --type MARKET \
  --quantity 1 --reduce-only true

# 測試下單
binance-cli futures-usds test-order \
  --symbol BNBUSDT --side BUY --type MARKET --quantity 1
```

### 帳戶設定

```bash
# 設定槓桿倍數
binance-cli futures-usds change-initial-leverage \
  --symbol BNBUSDT --leverage 5

# 切換逐倉 / 全倉保證金模式
binance-cli futures-usds change-margin-type \
  --symbol BNBUSDT --margin-type ISOLATED   # 或 CROSSED

# 切換 One-way / Hedge Mode（雙向持倉）
binance-cli futures-usds change-position-mode \
  --dual-side-position true   # true = Hedge Mode, false = One-way
```

> ⚠️ **Hedge Mode 注意**：若帳戶開啟雙向持倉模式，下單時必須額外加上 `--position-side LONG` 或 `--position-side SHORT`。

### 撤單

```bash
# 撤特定訂單
binance-cli futures-usds cancel-order --symbol BNBUSDT --order-id <id>

# 撤該幣對所有掛單（緊急平倉前清單用）
binance-cli futures-usds cancel-all-open-orders --symbol BNBUSDT
```

---

## 🔄 Convert 快速兌換

```bash
# 查可兌換交易對
binance-cli convert list-all-convert-pairs --from-asset USDT --to-asset BNB

# 取得報價（鎖定 10 秒）
binance-cli convert send-quote-request \
  --from-asset USDT --to-asset BNB --from-amount 100

# 確認兌換（需在報價有效期內）
binance-cli convert accept-quote --quote-id <id>

# 查兌換狀態
binance-cli convert order-status --quote-id <id>
```

---

## ⚡ Algo 大單分批

適合大量買賣不想影響市場深度時使用。

```bash
# TWAP 分批下單（在 duration 秒內均勻分批）
binance-cli algo new-spot-algo-order \
  --symbol BNBUSDT --side BUY \
  --quantity 10 --duration 300 \
  --algo-type TWAP

# 查 Algo 訂單狀態
binance-cli algo get-spot-algo-order --algo-id <id>

# 取消 Algo 訂單
binance-cli algo cancel-spot-algo-order --algo-id <id>
```

---

## 📋 Order Type 對照表

| `--type` 值 | 市場 | 說明 | 必要額外參數 |
|------------|------|------|------------|
| `MARKET` | Spot / Futures | 市價單，立即成交 | — |
| `LIMIT` | Spot / Futures | 限價單 | `--price` `--time-in-force GTC` |
| `STOP_LOSS_LIMIT` | Spot | 止損限價 | `--stop-price` `--price` `--time-in-force` |
| `TAKE_PROFIT_LIMIT` | Spot | 止盈限價 | `--stop-price` `--price` `--time-in-force` |
| `STOP_MARKET` | Futures | 止損市價 | `--stop-price` |
| `TAKE_PROFIT_MARKET` | Futures | 止盈市價 | `--stop-price` |
| `LIMIT_MAKER` | Spot | Post-only，不吃單 | `--price` |

**`--time-in-force` 選項**：
- `GTC`：Good Till Cancelled（掛到成交或手動撤）
- `IOC`：Immediate or Cancel（立即成交剩餘取消）
- `FOK`：Fill or Kill（全部成交或全部取消）

---

## 🧩 策略腳本常用組合

### DCA 定時定額買入

```python
import subprocess, json

def market_buy(symbol: str, quantity: float, dry_run=False):
    cmd = [
        "binance-cli", "spot", "new-order",
        "--symbol", symbol,
        "--side", "BUY",
        "--type", "MARKET",
        "--quantity", str(quantity),
    ]
    if dry_run:
        print(f"[DRY-RUN] {' '.join(cmd)}")
        return {}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)
```

### 買入後自動掛 OCO（Spot TP + SL）

```python
def place_oco(symbol: str, quantity: float, entry: float, tp_pct=0.05, sl_pct=0.02):
    tp_price     = round(entry * (1 + tp_pct), 2)
    tp_stop      = round(entry * (1 + tp_pct - 0.001), 2)
    sl_stop      = round(entry * (1 - sl_pct), 2)
    sl_price     = round(entry * (1 - sl_pct - 0.001), 2)

    cmd = [
        "binance-cli", "spot", "order-list-oco",
        "--symbol", symbol,
        "--side", "SELL",
        "--quantity", str(quantity),
        "--above-type", "TAKE_PROFIT_LIMIT",
        "--above-price", str(tp_price),
        "--above-stop-price", str(tp_stop),
        "--above-time-in-force", "GTC",
        "--below-type", "STOP_LOSS_LIMIT",
        "--below-stop-price", str(sl_stop),
        "--below-price", str(sl_price),
        "--below-time-in-force", "GTC",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)
```

### 合約進場 + 立即掛止損（Futures）

```python
def futures_entry_with_sl(symbol: str, side: str, quantity: float, sl_price: float):
    # Step 1: 市價進場
    subprocess.run([
        "binance-cli", "futures-usds", "new-order",
        "--symbol", symbol, "--side", side,
        "--type", "MARKET", "--quantity", str(quantity),
    ], capture_output=True, text=True)

    # Step 2: 掛止損（反向）
    sl_side = "SELL" if side == "BUY" else "BUY"
    subprocess.run([
        "binance-cli", "futures-usds", "new-order",
        "--symbol", symbol, "--side", sl_side,
        "--type", "STOP_MARKET",
        "--stop-price", str(sl_price),
        "--reduce-only", "true",
        "--quantity", str(quantity),
    ], capture_output=True, text=True)
```

---

## 🔒 安全注意事項

1. **API Key 不在腳本內**：透過 OpenClaw Gateway config 注入，`binance-cli` 自動讀取
2. **下單前先用 `order-test` 或 `--dry-run` 驗證**
3. **真實下單前必須確認 `get-account` 或 `futures-account-balance-v3` 有足夠餘額**
4. **Hedge Mode 帳戶記得加 `--position-side`**
5. **建議 API Key 只開交易權限，不開提幣**

---

*文件由 Binance AI Pro 自動生成 · 參考版本 `binance-cli@1.2.0`*
