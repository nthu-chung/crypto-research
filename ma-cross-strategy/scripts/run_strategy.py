"""
run_strategy.py — backtest / paper / live 三模式統一入口
=========================================================

用法：
  # 回測（不連網路，吃本地 parquet）
  python3.11 scripts/run_strategy.py --mode backtest

  # Paper trade（連 Binance REST，假帳戶模擬成交）
  python3.11 scripts/run_strategy.py --mode paper

  # Live trade（paper daemon + signal_executor 雙 process）
  python3.11 scripts/run_strategy.py --mode live
  python3.11 scripts/run_strategy.py --mode live --dry-run   # 先驗證不真實下單

訊號一致性保證：
  三種模式都執行同一份 strategies/ma_cross_v1.py 的 make_signals()。
  差別只在 broker 層：
    backtest → 無 broker，純吃歷史 parquet
    paper    → PaperBrokerAdapter（假帳戶）
    live     → paper daemon（假帳戶）+ signal_executor（binance-cli 真實下單）
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

WORKSPACE  = Path("/root/.openclaw/workspace")
VENV_PIP   = WORKSPACE / "venv-pip"
SCRIPTS    = WORKSPACE / "scripts"
STRATEGIES = WORKSPACE / "strategies"

# paper daemon state 目錄
STATE_DIR  = WORKSPACE / "watcher" / "MA_CROSS_BTCUSDT_1h"

PYTHONPATH = f"{VENV_PIP}:{WORKSPACE}"

# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(symbol: str, interval: str, data_path: str) -> int:
    """
    mvp_backtest --engine python 跑 ma_cross_v1 回測。
    --strategy-module 在 import 時觸發 strategy.register()。
    """
    cmd = [
        "python3.11", "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_backtest",
        "--engine",          "python",
        "--strategy",        "ma_cross_v1",
        "--strategy-module", "strategies.ma_cross_v1",
        "--symbol",          symbol,
        "--interval",        interval,
        "--data-path",       data_path,
        "--fee-bps",         "4",
        "--slippage-bps",    "2",
        "--initial-capital", "10000",
    ]
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    print("[run_strategy] mode=backtest")
    print("[run_strategy]", " ".join(cmd))
    result = subprocess.run(cmd, env=env)
    return result.returncode


# ── Paper trade ───────────────────────────────────────────────────────────────

def run_paper(symbol: str, interval: str) -> int:
    """啟動 paper daemon（foreground），Ctrl+C 停止。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3.11", "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon",
        "--symbol",          symbol,
        "--interval",        interval,
        "--strategy",        "ma_cross_v1",
        "--strategy-module", "strategies.ma_cross_v1",
        "--engine",          "python",
        "--state-dir",       str(STATE_DIR),
        "--poll-interval",   "3570",
        "--warm-up-bars",    "80",
        "--initial-capital", "10000",
        "--fee-bps",         "4",
        "--slippage-bps",    "2",
        "--market-type",     "futures",
        "--jarvis-user-id",  "147809639",
        "--jarvis-thread-id","019e6e1c-5d38-7a19-9c13-2cd8c7b50163",
    ]
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}
    print("[run_strategy] mode=paper")
    print("[run_strategy]", " ".join(cmd))
    result = subprocess.run(cmd, env=env)
    return result.returncode


# ── Live trade ────────────────────────────────────────────────────────────────

def run_live(symbol: str, interval: str, max_notional: float,
             notional_fraction: float, dry_run: bool) -> int:
    """
    同時啟動兩個 process：
      1. paper daemon  — 產生訊號（與 paper/backtest 邏輯完全相同）
      2. signal_executor — 偵測 trades.jsonl → binance-cli 下單

    兩者都在前台跑，Ctrl+C 同時停止。
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": PYTHONPATH}

    # ── process 1：paper daemon ──────────────────────────────────────────────
    daemon_cmd = [
        "python3.11", "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon",
        "--symbol",          symbol,
        "--interval",        interval,
        "--strategy",        "ma_cross_v1",
        "--strategy-module", "strategies.ma_cross_v1",
        "--engine",          "python",
        "--state-dir",       str(STATE_DIR),
        "--poll-interval",   "3570",
        "--warm-up-bars",    "80",
        "--initial-capital", "10000",
        "--fee-bps",         "4",
        "--slippage-bps",    "2",
        "--market-type",     "futures",
        "--jarvis-user-id",  "147809639",
        "--jarvis-thread-id","019e6e1c-5d38-7a19-9c13-2cd8c7b50163",
    ]

    # ── process 2：signal_executor ───────────────────────────────────────────
    executor_cmd = [
        "python3.11", str(SCRIPTS / "signal_executor.py"),
        "--state-dir",        str(STATE_DIR),
        "--symbol",           symbol,
        "--notional-fraction",str(notional_fraction),
        "--max-notional",     str(max_notional),
    ]
    if dry_run:
        executor_cmd.append("--dry-run")

    print("[run_strategy] mode=live  dry_run=%s" % dry_run)
    print("[run_strategy] daemon:   ", " ".join(daemon_cmd))
    print("[run_strategy] executor: ", " ".join(executor_cmd))
    if dry_run:
        print("[run_strategy] ⚠️  DRY-RUN: executor will print orders but NOT submit to Binance")
    else:
        print("[run_strategy] ⚠️  LIVE: real orders will be placed on Binance Futures mainnet")

    daemon_proc   = subprocess.Popen(daemon_cmd,   env=env)
    executor_proc = subprocess.Popen(executor_cmd, env=env)

    try:
        # 等待任一 process 退出
        while True:
            if daemon_proc.poll() is not None:
                print("[run_strategy] daemon exited, stopping executor")
                executor_proc.terminate()
                break
            if executor_proc.poll() is not None:
                print("[run_strategy] executor exited, stopping daemon")
                daemon_proc.terminate()
                break
            import time; time.sleep(2)
    except KeyboardInterrupt:
        print("\n[run_strategy] Ctrl+C — stopping both processes")
        daemon_proc.terminate()
        executor_proc.terminate()

    daemon_proc.wait()
    executor_proc.wait()
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="MA cross strategy — backtest / paper / live 統一入口"
    )
    parser.add_argument("--mode",
        choices=["backtest", "paper", "live"], default="paper",
        help="執行模式（預設 paper）"
    )
    parser.add_argument("--symbol",   default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--data-path", default=str(WORKSPACE / "data" / "BTCUSDT_1h.parquet"),
        help="回測用本地 parquet（backtest mode 用）"
    )
    parser.add_argument("--max-notional", type=float, default=200.0,
        help="單筆最大下單 USDT（live mode 風控）"
    )
    parser.add_argument("--notional-fraction", type=float, default=0.95,
        help="下單佔可用餘額比例（live mode）"
    )
    parser.add_argument("--dry-run", action="store_true",
        help="live mode：只印出 binance-cli 指令，不真正送出"
    )
    args = parser.parse_args()

    if args.mode == "backtest":
        return run_backtest(args.symbol, args.interval, args.data_path)
    elif args.mode == "paper":
        return run_paper(args.symbol, args.interval)
    else:
        return run_live(
            symbol=args.symbol,
            interval=args.interval,
            max_notional=args.max_notional,
            notional_fraction=args.notional_fraction,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    sys.exit(main())
