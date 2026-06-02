"""
run_strategy.py — backtest / paper / live 三模式統一入口
=========================================================

透過 cyqnt_trd 框架的 entrypoints 執行，不自己實作邏輯。

用法：
  # 回測
  python scripts/run_strategy.py --mode backtest

  # Paper trade
  python scripts/run_strategy.py --mode paper

  # Live trade（dry-run 先驗證）
  python scripts/run_strategy.py --mode live --dry-run

  # Live trade（真實下單）
  python scripts/run_strategy.py --mode live --max-notional 200
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _find_python() -> str:
    for candidate in ["python3.11", "python3.12", "python3"]:
        if shutil.which(candidate):
            return candidate
    return sys.executable


def _workspace() -> Path:
    """策略 workspace 根目錄（script 上層）"""
    return Path(__file__).resolve().parent.parent


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(args) -> int:
    python = _find_python()
    workspace = _workspace()

    cmd = [
        python, "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_backtest",
        "--engine",          "python",
        "--strategy",        args.strategy,
        "--strategy-module", args.strategy_module,
        "--symbol",          args.symbol,
        "--interval",        args.interval,
        "--market-type",     args.market_type,
        "--initial-capital", str(args.initial_capital),
        "--commission-bps",  str(args.fee_bps),
        "--slippage-bps",    str(args.slippage_bps),
        "--execution-model", "next_bar_open",
        "--tail-bars",       "120",
    ]

    # 資料來源：若有 --data-path 就用 --historical-dir，否則用 --allow-remote-api
    if args.data_path:
        data_path = args.data_path if Path(args.data_path).is_absolute() else str(workspace / args.data_path)
        cmd += ["--historical-dir", str(Path(data_path).parent.parent.parent)]
        cmd += ["--storage-timeframe", "1m"]
        cmd += ["--limit", str(args.limit)]
    else:
        cmd += ["--allow-remote-api", "--limit", str(args.limit)]

    env = {**os.environ, "PYTHONPATH": f"{workspace}:{os.environ.get('PYTHONPATH', '')}"}
    print(f"[run_strategy] mode=backtest")
    print(f"[run_strategy] {' '.join(cmd)}")
    return subprocess.run(cmd, env=env).returncode


# ── Paper trade ───────────────────────────────────────────────────────────────

def run_paper(args) -> int:
    python = _find_python()
    workspace = _workspace()
    state_dir = _state_dir(args)
    state_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        python, "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon",
        "--engine",          "python",
        "--strategy",        args.strategy,
        "--strategy-module", args.strategy_module,
        "--symbol",          args.symbol,
        "--interval",        args.interval,
        "--market-type",     args.market_type,
        "--state-dir",       str(state_dir),
        "--poll-interval",   str(args.poll_interval),
        "--warm-up-bars",    str(args.warm_up_bars),
        "--initial-capital", str(args.initial_capital),
        "--fee-bps",         str(args.fee_bps),
        "--slippage-bps",    str(args.slippage_bps),
    ]

    env = {**os.environ, "PYTHONPATH": f"{workspace}:{os.environ.get('PYTHONPATH', '')}"}
    print(f"[run_strategy] mode=paper")
    print(f"[run_strategy] state_dir={state_dir}")
    print(f"[run_strategy] {' '.join(cmd)}")
    return subprocess.run(cmd, env=env).returncode


# ── Live trade ────────────────────────────────────────────────────────────────

def run_live(args) -> int:
    """
    同時啟動兩個 process：
      1. Paper daemon（訊號來源，和 paper mode 完全相同）
      2. Live executor（讀 trades.jsonl → binance-cli 真實下單）
    """
    python = _find_python()
    workspace = _workspace()
    state_dir = _state_dir(args)
    state_dir.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "PYTHONPATH": f"{workspace}:{os.environ.get('PYTHONPATH', '')}"}

    # Process 1: Paper Daemon
    daemon_cmd = [
        python, "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_paper_daemon",
        "--engine",          "python",
        "--strategy",        args.strategy,
        "--strategy-module", args.strategy_module,
        "--symbol",          args.symbol,
        "--interval",        args.interval,
        "--market-type",     args.market_type,
        "--state-dir",       str(state_dir),
        "--poll-interval",   str(args.poll_interval),
        "--warm-up-bars",    str(args.warm_up_bars),
        "--initial-capital", str(args.initial_capital),
        "--fee-bps",         str(args.fee_bps),
        "--slippage-bps",    str(args.slippage_bps),
    ]

    # Process 2: Live Executor
    executor_cmd = [
        python, "-m",
        "cyqnt_trd.standard_bot.entrypoints.mvp_live_executor",
        "--state-dir",         str(state_dir),
        "--symbol",            args.symbol,
        "--max-notional",      str(args.max_notional),
        "--notional-fraction", str(args.notional_fraction),
    ]
    if args.dry_run:
        executor_cmd.append("--dry-run")

    print(f"[run_strategy] mode=live  dry_run={args.dry_run}")
    print(f"[run_strategy] state_dir={state_dir}")
    print(f"[run_strategy] daemon:   {' '.join(daemon_cmd[:6])} ...")
    print(f"[run_strategy] executor: {' '.join(executor_cmd[:6])} ...")
    if args.dry_run:
        print(f"[run_strategy] ⚠️  DRY-RUN: executor 只印指令不下單")
    else:
        print(f"[run_strategy] ⚠️  LIVE: 真實下單！max_notional={args.max_notional} USDT")
        print(f"[run_strategy] ⚠️  緊急停止: touch {state_dir}/EMERGENCY_STOP")

    daemon_proc = subprocess.Popen(daemon_cmd, env=env)
    time.sleep(3)  # 等 daemon 建立 state dir
    executor_proc = subprocess.Popen(executor_cmd, env=env)

    try:
        while True:
            if daemon_proc.poll() is not None:
                print("[run_strategy] daemon exited, stopping executor")
                executor_proc.terminate()
                break
            if executor_proc.poll() is not None:
                print("[run_strategy] executor exited, stopping daemon")
                daemon_proc.terminate()
                break
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[run_strategy] Ctrl+C — stopping both processes")
        daemon_proc.terminate()
        executor_proc.terminate()

    daemon_proc.wait()
    executor_proc.wait()
    return 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _state_dir(args) -> Path:
    if args.state_dir:
        return Path(args.state_dir)
    workspace = _workspace()
    run_id = f"{args.strategy.upper()}_{args.symbol}_{args.interval}"
    return workspace / "watcher" / run_id


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="MA cross strategy — backtest / paper / live 統一入口"
    )
    parser.add_argument("--mode", choices=["backtest", "paper", "live"], default="paper")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--strategy", default="ma_cross_v1")
    parser.add_argument("--strategy-module", default="strategies.ma_cross_v1")
    parser.add_argument("--market-type", default="futures")
    parser.add_argument("--state-dir", default=None)

    # Simulation params
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--warm-up-bars", type=int, default=80)
    parser.add_argument("--poll-interval", type=int, default=3570)

    # Backtest params
    parser.add_argument("--data-path", default=None, help="Historical parquet path")
    parser.add_argument("--limit", type=int, default=2000)

    # Live params
    parser.add_argument("--max-notional", type=float, default=200.0)
    parser.add_argument("--notional-fraction", type=float, default=0.95)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.mode == "backtest":
        return run_backtest(args)
    elif args.mode == "paper":
        return run_paper(args)
    else:
        return run_live(args)


if __name__ == "__main__":
    sys.exit(main())
