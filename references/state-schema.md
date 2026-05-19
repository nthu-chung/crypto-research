# state.json Schema

The `state.json` file lives at `workspace/research/state.json` and is the single source of truth for the research loop.

## Schema

```json
{
  "topic": "string — research topic / strategy name",
  "round": 1,
  "max_rounds": 5,
  "status": "awaiting_research | awaiting_judge | stopped | complete",
  "last_score": null,
  "last_verdict": null,
  "history": [
    {
      "round": 1,
      "report": "research/report_v1.md",
      "feedback": "research/feedback_v1.md",
      "score": 6,
      "verdict": "NEEDS_IMPROVEMENT"
    }
  ],
  "config": {
    "asset": "BTC",
    "data_start": "2012-01-01",
    "initial_capital": 10000,
    "fee_bps": 4
  }
}
```

## Status Transitions

```
awaiting_research → (Research writes report) → awaiting_judge
awaiting_judge    → (Judge writes feedback)  → awaiting_research (or complete/stopped)
```

## Stopping Conditions

Research checks at the start of each round:
- `round >= max_rounds` → set status=complete, send final report to main
- `last_score >= 8 AND last_verdict == "PASS"` → set status=complete, send final report to main

## File Naming

- Reports: `workspace/research/report_v{round}.md`
- Feedback: `workspace/research/feedback_v{round}.md`
