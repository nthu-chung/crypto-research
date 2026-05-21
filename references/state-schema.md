# state.json Schema

`workspace/research/state.json` is the single source of truth for the Research/Judge loop.

## Canonical Schema

```json
{
  "topic": "Strategy or reproduction topic",
  "round": 1,
  "max_rounds": 5,
  "status": "awaiting_research",
  "last_score": null,
  "last_verdict": null,
  "created_at": "2026-05-21T00:00:00Z",
  "history": [],
  "config": {
    "asset": "BTC",
    "universe": "BTC or crypto universe description",
    "data_start": "2018-01-01",
    "data_end": null,
    "initial_capital": 10000,
    "fee_bps": 4,
    "slippage_bps": 0,
    "base_currency": "USDT",
    "benchmark": "buy_and_hold"
  }
}
```

## Field Rules

- `round`: the next or current round to run.
- `max_rounds`: maximum Judge-reviewed research rounds.
- `status`: one of `awaiting_research`, `awaiting_judge`, `stopped`, `complete`.
- `last_score`: latest Judge score on a `0-100` scale.
- `last_verdict`: `PASS`, `NEEDS_IMPROVEMENT`, `REJECT`, `MAX_ROUNDS_REACHED`, or null.
- `history`: always an object list, never a string list.

## History Object

```json
{
  "round": 1,
  "report": "research/report_v1.md",
  "feedback": "research/feedback_v1.md",
  "score": 62,
  "verdict": "NEEDS_IMPROVEMENT"
}
```

During the gap after Research but before Judge, `feedback`, `score`, and `verdict` may be null.

## Status Transitions

```text
awaiting_research
  -> Research writes report_vN.md
  -> status = awaiting_judge, round = N

awaiting_judge
  -> Judge writes feedback_vN.md
  -> if score >= 80 and verdict = PASS:
       status = complete, round = N
     else if N >= max_rounds:
       status = complete, round = N, last_verdict = MAX_ROUNDS_REACHED
     else:
       status = awaiting_research, round = N + 1
```

## Stopping Conditions

The loop stops when any condition is true:

- `status == "stopped"`
- Judge sets `score >= 80` and `verdict == "PASS"`
- Judge completes `round >= max_rounds`

Research should not stop solely because `round == max_rounds`; the final round still needs a Judge review.

## File Naming

- Reports: `workspace/research/report_v{round}.md`
- Feedback: `workspace/research/feedback_v{round}.md`
- Optional final summary: `workspace/research/final_report.md`

## Flow Examples

- Round 1 Research completes:
  - `round = 1`
  - `status = "awaiting_judge"`
  - history has `report_v1.md` and null feedback fields.
- Round 1 Judge scores 62:
  - `round = 2`
  - `status = "awaiting_research"`
  - `last_score = 62`
  - `last_verdict = "NEEDS_IMPROVEMENT"`
- Final Judge scores 80 PASS:
  - `round` stays at the final reviewed round
  - `status = "complete"`
  - `last_verdict = "PASS"`
- Max rounds reached with score below 80:
  - `round` stays at the final reviewed round
  - `status = "complete"`
  - `last_verdict = "MAX_ROUNDS_REACHED"`
