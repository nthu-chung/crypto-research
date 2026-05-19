#!/usr/bin/env python3
"""
Initialize the research workspace and print the first Research agent task string.
Usage: python3 start_loop.py --topic "MVRV strategy" --rounds 4
"""
import json, argparse, os
from pathlib import Path
from datetime import datetime, timezone

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--asset", default="BTC")
    parser.add_argument("--data-start", default="2012-01-01")
    parser.add_argument("--fee-bps", type=int, default=4)
    args = parser.parse_args()

    workspace = Path("/root/.openclaw/workspace/research")
    workspace.mkdir(parents=True, exist_ok=True)

    state = {
        "topic": args.topic,
        "round": 1,
        "max_rounds": args.rounds,
        "status": "awaiting_research",
        "last_score": None,
        "last_verdict": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "history": [],
        "config": {
            "asset": args.asset,
            "data_start": args.data_start,
            "initial_capital": 10000,
            "fee_bps": args.fee_bps
        }
    }

    state_path = workspace / "state.json"
    state_path.write_text(json.dumps(state, indent=2))
    print(f"[OK] Initialized research workspace: {workspace}")
    print(f"[OK] Topic: {args.topic}")
    print(f"[OK] Rounds: {args.rounds}")
    print(f"[OK] state.json written to {state_path}")
    print("\n=== SPAWN FIRST RESEARCH AGENT WITH THIS TASK ===")
    print(f"""你是加密貨幣量化研究員 (crypto-research agent)。

讀取 /root/.openclaw/workspace/research/state.json 並按照 /root/.openclaw/skills/crypto-research/references/research-agent.md 的指示執行第 1 輪研究。

研究主題：{args.topic}

完成後請 spawn Judge agent，Judge agent 的指示在 /root/.openclaw/skills/crypto-research/references/judge-agent.md。
""")

if __name__ == "__main__":
    main()
