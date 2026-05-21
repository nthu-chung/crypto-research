---
name: crypto-research
description: "General-purpose multi-agent crypto strategy research loop for OpenClaw. Spawns Research and Judge subagents that iteratively build, backtest, audit, and improve crypto trading strategies with shared file-based memory. Use when the user asks to research, reproduce, backtest, evaluate, or audit a crypto trading strategy autonomously."
---

# Crypto Research Skill

This skill orchestrates an OpenClaw subagent loop for crypto strategy research:

- **Research agent** — collects data, implements or reproduces a strategy, runs backtests, compares baselines, and writes a report.
- **Judge agent** — audits the report for statistical rigor, bias, execution feasibility, and risk, then writes feedback for the next round.

All durable memory lives in files under `workspace/research/`. `sessions_send(label="main", ...)` is only for short progress updates.

## Workspace Layout

```
workspace/research/
  state.json          # single source of truth for topic, round, status, config
  report_vN.md        # Research output for round N
  feedback_vN.md      # Judge feedback for round N
  artifacts/          # optional charts, result JSON, notebooks, downloaded data notes
```

## Recommended Workflow

1. Read `references/state-schema.md`.
2. Read `references/research-agent.md` and `references/judge-agent.md`.
3. Initialize `workspace/research/state.json` from `references/state.json`.
4. Fill in the topic, strategy universe, data range, fee assumptions, and max rounds.
5. Spawn the first Research agent with the template from `references/research-agent.md`.
6. Let Research and Judge self-cycle until the state becomes `complete` or `stopped`.
7. Read the final report and feedback files before summarizing to the user.

## State Rules

- `round` means the next or current research round.
- Research completing round N sets `status = "awaiting_judge"` and keeps `round = N`.
- Judge completing round N with more work needed sets `status = "awaiting_research"` and `round = N + 1`.
- Judge completing round N with `score >= 80` and `verdict = "PASS"` sets `status = "complete"`.
- Judge reaching `max_rounds` without passing sets `status = "complete"` and `last_verdict = "MAX_ROUNDS_REACHED"`.
- Scores are always `0-100`.

## Required Research Quality

Every research report must include:

- Reproducible commands or code paths.
- Data source and timestamp assumptions.
- Transaction costs, at least using `config.fee_bps`.
- Baselines relevant to the strategy, such as buy-and-hold, equal-weight, or simple momentum.
- IS/OOS split or walk-forward evaluation.
- Risk metrics: CAGR or annualized return, Sharpe, max drawdown, win rate, trade count, and turnover when applicable.
- Bias checks: no-lookahead timing, survivorship risk, universe construction, overfitting risk, and missing-data handling.

## Key Rules

- Update `state.json` before spawning the next subagent.
- Do not pass full reports through `sessions_send`; write them to files.
- If web access or a paid data source is unavailable, document the substitute data source and how it changes the interpretation.
- Prefer public, reproducible data first. Use `references/data-sources.md` for standard API options.
