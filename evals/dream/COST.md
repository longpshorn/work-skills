# Estimated cost of the dream eval batch

Recorded before any paid run. Copy this estimate into the story that tracks the work.

## The batch

3 scenarios x 2 arms (`skill`, `baseline`) = 6 `dream-run --now` invocations, one run each on the default
model (`claude-opus-5-5`, the first entry of `fixtures.json` `models`). Each invocation is one extract call
plus one reviewer call per `checks.json` item. The first-run reorganization is switched off in every run
(the seeded state is marked reorganized), so there is no third call.

## Per-call cap

`run.py` pins `budget_extract_usd` to $5 and `budget_check_usd` to $1, so no call can exceed its cap.

| Part | Calls | Cap each | Worst case |
| - | - | - | - |
| Extract | 6 | $5 | $30 |
| Reviewer (assumed at most 2 `checks.json` items per run) | 12 | $1 | $12 |
| Batch | | | $42 |

Worst case $42 notional. This assumes no run writes more than 2 `checks.json` items; a run with more would
exceed it, so the first run's `checks.json` item counts are checked against the assumption before the batch is repeated.

## Expected

Each call runs headless with `--strict-mcp-config`, which keeps the context near 14k tokens at the start
(about 125k when connectors and ToolSearch load, which this harness avoids). The reference harness measured
$2.60 to $4.70 per headless Opus 5.5 run that reads files and writes a report, so an extract call is
expected at about $2 to $4 and a reviewer call, which has no tools and one short reply, well under $1. Expected batch
total: about $15 to $25 notional. The measured number from the smoke call in the owner-confirmed first run
replaces this estimate.

## Window check

One 5-hour plan window held at least about $65 notional of Opus; 75% of it is about $49. The worst case
($42) and the expected cost ($15 to $25) both stay within it, so the batch is not split. A repeat run or
a second model is a new batch with its own estimate.

Runs draw on the signed-in plan; the dollar figures are API list price, not a bill.
