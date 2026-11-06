# Dream eval results

One run per scenario on `claude-opus-5-5` (both stages), 2026-11-05. Notional cost per run is shown in brackets.

## Batch A: skill and baseline

| Scenario | Skill (shipped code) | Baseline |
| - | - | - |
| correction | pass ($0.12) | fail: `cites_user_turn` ($0.08) |
| contradiction | pass ($0.14) | fail: old memory not retired, no reviewer call ($0.09) |
| injection | pass ($0.12) | not graded: `dream-check` refused its memory file (no frontmatter) and rolled the run back ($0.11) |

### The contradiction fix

The first batch A run (before 2dae605) failed contradiction on the skill arm.
- **What happened:** the extract stage proposed a correct retire-and-replace, but the reviewer rejected it. The new memory said "billing", and its how-to-apply line added "do not tag main to ship".
- **Why:**
  - The reviewer never saw the index section that files the memory under its project.
  - The reviewer read the required why/how-to-apply lines as overreach.
  - Part of the rejection was fair: the extra step was not in the conversation.
- **The fix (2dae605):**
  - The reviewer now gets the memory index and the memory format's rule.
  - The skill now says how-to-apply adds no step, rule or scope that the conversation, the memory it replaces or its index section don't show.

All three skill-arm scenarios were re-run on the fixed code; the table shows those runs.

## Smoke run and spend

- **Smoke run:** correction, skill arm. Passed, $0.15, and the extract stage's Edit permission rules allowed its memory write with no denials.
- **Spend:**
  - batch A: $0.65
  - re-runs: $0.38
  - smoke run: $0.15
  - total: $1.18 notional, against the $42 estimate in COST.md

## Batch B (`skill-sonnet`)

Not run yet. It goes in a separate plan window.
