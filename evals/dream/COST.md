# Estimated cost of the dream eval batches

Recorded before any paid run. Copy this estimate into the story that tracks the work.

## The runs

3 scenarios x 3 arms = 9 `dream-run --now` invocations, one run each. Arms `skill` and `baseline` run both
stages on the default eval model (`claude-opus-5-5`, the first entry of `fixtures.json` `models`). Arm
`skill-sonnet` is the comparison arm for the cheaper extract model: the extract stage on `sonnet`
and the reviewer on the default eval model. Each invocation is one extract call plus one reviewer call per
`checks.json` item. The first-run reorganization is switched off in every run (the seeded state is marked
reorganized), so there is no third call.

## Per-call cap

`run.py` pins `budget_extract_usd` to $5 and `budget_check_usd` to $1, so no call can exceed its cap.
The reviewer count assumes at most 2 `checks.json` items per run.

| Batch | Arms | Extract calls x $5 | Reviewer calls x $1 | Worst case |
| - | - | - | - | - |
| A | `skill`, `baseline` | 6 = $30 | 12 = $12 | $42 |
| B | `skill-sonnet` | 3 = $15 | 6 = $6 | $21 |
| All 9 runs | | | | $63 |

A run with more than 2 `checks.json` items would exceed its row, so the first batch's item counts are
checked against the assumption before the next batch runs.

## Expected

Each call runs headless with `--strict-mcp-config`, which keeps the context near 14k tokens at the start
(about 125k when connectors and ToolSearch load, which this harness avoids). The reference harness measured
$2.60 to $4.70 per headless Opus 5.5 run that reads files and writes a report, so an Opus extract call is
expected at about $2 to $4 and a reviewer call, which has no tools and one short reply, well under $1.
Expected batch A: about $15 to $25 notional. A Sonnet extract call is expected well below an Opus one, so
batch B is expected under about $10. The measured numbers from the owner-confirmed first run replace these
estimates.

## Window check and split

One 5-hour plan window held at least about $65 notional of Opus; 75% of it is about $49. All 9 runs together
($63 worst case) exceed that, so the work is split into two batches, each in its own window:

```bash
python evals/dream/run.py --arm skill --arm baseline --out <dir> --confirm-paid   # batch A, worst case $42
python evals/dream/run.py --arm skill-sonnet --out <dir> --confirm-paid           # batch B, worst case $21
```

Each batch stays within $49 at worst case. A repeat run or a second model is a new batch with its own estimate.

Runs draw on the signed-in plan; the dollar figures are API list price, not a bill.
