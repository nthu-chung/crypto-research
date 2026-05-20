---
name: crypto-research
description: "Multi-agent autonomous crypto strategy research loop. Spawns a Research agent and a Judge agent that take turns improving and auditing a quantitative trading strategy using shared file-based memory. Use when the user asks to research, backtest, or evaluate a crypto trading strategy autonomously, or when phrases like research agent, judge agent, strategy loop, autonomous research, or 研究策略 appear."
---

# Crypto Research Skill

Orchestrates an autonomous research loop between two subagents:
- **Research agent** — fetches data, backtests strategies, writes reports
- **Judge agent** — audits reports for bias, feasibility, and rigor, then sends feedback

Both agents communicate via shared files in `workspace/research/`. Each is spawned fresh per round; the files are their persistent memory.

## Workspace Layout

```
workspace/research/
  state.json          ← round counter, current topic, status
  report_vN.md        ← Research output for round N
  feedback_vN.md      ← Judge feedback for round N
```

## Orchestration Flow

```
Main spawns Research (round 1)
  Research reads state.json → runs backtest → writes report_v1.md
  Research updates state.json (round=1, status=awaiting_judge)
  Research spawns Judge
    Judge reads report_v1.md → audits → writes feedback_v1.md
    Judge updates state.json (status=awaiting_research)
    Judge spawns Research (round 2)
      ...repeat until state.json round >= MAX_ROUNDS or Judge scores ≥ 8/10
  Research sends final summary to main via sessions_send(label="main")
```

## How to Start the Loop

1. Read `references/state-schema.md` for the `state.json` format.
2. Read `references/research-agent.md` for the Research agent task template.
3. Read `references/judge-agent.md` for the Judge agent task template.
4. Initialize `workspace/research/state.json` with the topic and config.
5. Spawn the first Research agent using the template in `references/research-agent.md`.

## Stopping Conditions

The loop stops when any of these is true (checked by Research at start of each round):
- `state.json` → `round >= max_rounds`
- Latest `feedback_vN.md` contains `score >= 8` and `verdict: PASS`
- `state.json` → `status == "stopped"`

When stopped, Research sends a final consolidated report to `main`.

## Key Rules

- **All inter-agent memory lives in files** — never rely on `sessions_send` for content passing.
- `sessions_send(label="main")` is for human-readable progress updates only.
- Each agent must read `state.json` first to know its round number and topic.
- Agents must update `state.json` before spawning the next agent.
- Use `--break-system-packages` for pip installs if needed, or use already-installed libs (pandas, numpy, matplotlib, scipy are available).
- CoinMetrics community API is the primary free data source for BTC on-chain metrics.

## Data Sources

See `references/data-sources.md` for available APIs, metrics, and fetch code snippets.
