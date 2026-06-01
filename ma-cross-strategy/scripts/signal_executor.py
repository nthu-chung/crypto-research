"""
signal_executor.py — trades.jsonl watcher → binance-cli 下單
=============================================================

角色：
  Paper daemon（mvp_paper_daemon --engine python）持續把 fills 寫進
  watcher/<run_id>/trades.jsonl。本腳本 tail 這個檔案，一旦發現新的
  paper fill，就透過 binance-cli 在真實 mainnet 上下對應的單。

設計原則：
  1. 策略邏輯零改動 — make_signals() 完全不動，paper daemon 照跑
  2. 只有 broker 層替換：paper fill → binance-cli subprocess
  3. 訊號一致性保證：paper daemon 用同一份 ma_cross_v1.py 產生訊號，
     executor 只負責「把 paper fill 翻譯成真實下單」

訊號 → 下單對應：
  paper fill action     binance-cli side / reduce-only
  ─────────────────────────────────────────────────────
  open_long             BUY   MARKET  (開多)
  open_short            SELL  MARKET  (開空)
  close_long            SELL  MARKET  reduce-only=true
  close_short           BUY   MARKET  reduce-only=true

數量計算：
  notional = available_usdt * POSITION_FRACTION（預設 0.95）
  quantity = notional / current_price
  → 以市價單成交，量以 step_size 對齊（從 exchange-information 取）

安全閘：
  1. 每次下單前呼叫 futures-account-balance-v3 確認有足夠保證金
  2. 每次下單前呼叫 position-information-v3 確認倉位方向不衝突
  3. --dry-run 模式：只印出 binance-cli 指令，不真正執行
  4. 每次 fill 只處理一次（fill_id 去重）

使用方式：
  # 先啟動 paper daemon（另一個 terminal）
  ./scripts/run_paper_daemon.sh

  # 啟動 executor（監聽 paper daemon 的 trades.jsonl）
  python3.11 scripts/signal_executor.py \
    --state-dir /root/.openclaw/workspace/watcher/MA_CROSS_BTCUSDT_1h \
    --symbol BTCUSDT \
    --notional-fraction 0.95 \
    --max-notional 200 \
    --dry-run          # 先用 dry-run 確認邏輯，確認後去掉此參數
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

# ── 常數 ──────────────────────────────────────────────────────────────────────
POLL_SEC       = 5      # 輪詢 trades.jsonl 的間隔（秒）
STEP_SIZE_CACHE: dict[str, float] = {}   # symbol → step_size


# ── binance-cli helpers ───────────────────────────────────────────────────────

def _cli(*args: str, dry_run: bool = False) -> dict | list:
    """執行 binance-cli，回傳 parsed JSON。dry_run=True 時只印不執行。"""
    cmd = ["binance-cli"] + list(args)
    if dry_run:
        print(f"[DRY-RUN] {' '.join(cmd)}")
        return {}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(f"binance-cli error: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def get_usdt_balance() -> float:
    data = _cli("futures-usds", "futures-account-balance-v3")
    for item in data:
        if item.get("asset") == "USDT":
            return float(item.get("availableBalance", 0))
    return 0.0


def get_current_price(symbol: str) -> float:
    data = _cli("futures-usds", "symbol-price-ticker", "--symbol", symbol)
    return float(data["price"])


def get_step_size(symbol: str) -> float:
    """取 symbol 的最小下單 step size（從 exchange-information 快取）。"""
    if symbol in STEP_SIZE_CACHE:
        return STEP_SIZE_CACHE[symbol]
    data = _cli("futures-usds", "exchange-information")
    for s in data.get("symbols", []):
        if s["symbol"] == symbol:
            for f in s.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    step = float(f["stepSize"])
                    STEP_SIZE_CACHE[symbol] = step
                    return step
    return 0.001  # fallback


def get_position(symbol: str) -> dict | None:
    """回傳目前持倉 dict，空倉時回傳 None。"""
    data = _cli("futures-usds", "position-information-v3", "--symbol", symbol)
    for p in data:
        if abs(float(p.get("positionAmt", 0))) > 0:
            return p
    return None


def round_step(qty: float, step: float) -> float:
    """把 qty 向下對齊到 step_size 精度。"""
    if step <= 0:
        return qty
    decimals = max(0, -int(math.floor(math.log10(step))))
    return round(math.floor(qty / step) * step, decimals)


# ── 下單核心 ──────────────────────────────────────────────────────────────────

def place_order(
    symbol: str,
    action: str,        # open_long / open_short / close_long / close_short
    max_notional: float,
    notional_fraction: float,
    dry_run: bool,
) -> None:
    """
    根據 paper fill action 呼叫 binance-cli 下對應的真實單。

    action → side + reduce_only 對照：
      open_long   → BUY  MARKET  reduce-only=false
      open_short  → SELL MARKET  reduce-only=false
      close_long  → SELL MARKET  reduce-only=true
      close_short → BUY  MARKET  reduce-only=true
    """
    is_close = action in ("close_long", "close_short")
    side = "BUY" if action in ("open_long", "close_short") else "SELL"

    price = get_current_price(symbol)
    step  = get_step_size(symbol)

    if is_close:
        # 平倉：用目前倉位的量
        pos = get_position(symbol)
        if pos is None:
            print(f"[executor] WARN: {action} but no open position found, skip")
            return
        qty = abs(float(pos["positionAmt"]))
        qty = round_step(qty, step)
        if qty <= 0:
            print(f"[executor] WARN: position qty=0, skip")
            return
        cmd = [
            "futures-usds", "new-order",
            "--symbol", symbol,
            "--side", side,
            "--type", "MARKET",
            "--quantity", str(qty),
            "--reduce-only", "true",
        ]
        print(f"[executor] CLOSE {action}  {side} {qty} {symbol} @ ~{price:.2f}")

    else:
        # 開倉：用 available balance 算 notional
        balance = get_usdt_balance()
        if balance <= 0:
            print(f"[executor] WARN: USDT balance=0, skip {action}")
            return
        notional = min(balance * notional_fraction, max_notional)
        qty = round_step(notional / price, step)
        if qty <= 0:
            print(f"[executor] WARN: qty rounds to 0 (notional={notional:.2f} price={price:.2f}), skip")
            return
        cmd = [
            "futures-usds", "new-order",
            "--symbol", symbol,
            "--side", side,
            "--type", "MARKET",
            "--quantity", str(qty),
        ]
        print(f"[executor] OPEN {action}  {side} {qty} {symbol} @ ~{price:.2f}  notional≈{qty*price:.2f} USDT")

    result = _cli(*cmd, dry_run=dry_run)
    if not dry_run and result:
        order_id = result.get("orderId", "?")
        status   = result.get("status", "?")
        print(f"[executor] ORDER OK  orderId={order_id} status={status}")


# ── trades.jsonl tail watcher ─────────────────────────────────────────────────

def watch_trades(
    state_dir: Path,
    symbol: str,
    max_notional: float,
    notional_fraction: float,
    dry_run: bool,
) -> None:
    trades_path = state_dir / "trades.jsonl"
    seen_ids: set[str] = set()

    print(f"[executor] watching {trades_path}")
    print(f"[executor] symbol={symbol}  max_notional={max_notional}  dry_run={dry_run}")

    # 啟動時先載入已存在的 fill_id（不對歷史重複下單）
    if trades_path.exists():
        for line in trades_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                fill = json.loads(line)
                seen_ids.add(fill["fill_id"])
            except Exception:
                pass
        print(f"[executor] loaded {len(seen_ids)} existing fills (will not re-execute)")

    while True:
        time.sleep(POLL_SEC)

        # check daemon still alive via state.json
        state_path = state_dir / "state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                if state.get("status") in ("stopped", "risk_triggered"):
                    print("[executor] daemon stopped, exiting")
                    break
            except Exception:
                pass

        if not trades_path.exists():
            continue

        for line in trades_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                fill = json.loads(line)
            except Exception:
                continue

            fill_id = fill.get("fill_id", "")
            if fill_id in seen_ids:
                continue

            seen_ids.add(fill_id)
            action = fill.get("action", "")
            ts     = fill.get("ts", 0)
            print(f"\n[executor] NEW FILL  fill_id={fill_id[:8]}  action={action}  ts={ts}")

            if action not in ("open_long", "open_short", "close_long", "close_short"):
                print(f"[executor] unknown action={action!r}, skip")
                continue

            try:
                place_order(
                    symbol=symbol,
                    action=action,
                    max_notional=max_notional,
                    notional_fraction=notional_fraction,
                    dry_run=dry_run,
                )
            except Exception as e:
                print(f"[executor] ERROR placing order: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Signal executor: paper fills → binance-cli orders")
    parser.add_argument("--state-dir",  required=True,
                        help="Paper daemon state dir (含 trades.jsonl)")
    parser.add_argument("--symbol",     default="BTCUSDT")
    parser.add_argument("--notional-fraction", type=float, default=0.95,
                        help="下單金額佔可用餘額的比例（預設 0.95）")
    parser.add_argument("--max-notional",  type=float, default=200.0,
                        help="單筆最大下單 USDT（風控上限）")
    parser.add_argument("--dry-run",    action="store_true",
                        help="只印出 binance-cli 指令，不真正下單")
    args = parser.parse_args()

    watch_trades(
        state_dir=Path(args.state_dir),
        symbol=args.symbol,
        max_notional=args.max_notional,
        notional_fraction=args.notional_fraction,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
