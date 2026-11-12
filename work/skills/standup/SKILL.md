---
name: standup
description: Cross-workstream status view from the user's work store. Use for "/work:standup", "what's on my plate", "what's stale", "status of everything", or weekly planning. Read-only apart from regenerating index.md and log.md and, when the user approves, adding missing workstream descriptions.
---

# Standup: every workstream at a glance

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. Run `work-tools index`. Exit 1 means some status files have header errors; list them first and offer to fix them. Exit 4 means there is no work store yet; say so, offer `/work:new`, and stop.
2. Read `<store>/index.md` and run `work-tools drift --all`. Also run `work-tools dream-status`; it prints one line only when the nightly dream run is failing or stale.
3. Print these sections, leaving out any that are empty:
   - **Blocked:** workstream · next
   - **Stale** (⚠, 14+ days): workstream · age
   - **Uncommitted / unpushed / changed sources:** from drift
   - **Top 5 next steps:** order by state (`active`, `review`, `blocked`, `scoped`, `idea`), then oldest `updated` first
   - **Dream:** the `dream-status` line, shown under the sections only when it prints something
4. Offer `/work:resume <name>` for the top item.
5. **Missing descriptions.** Run `work-tools list --no-description`; if it prints nothing, skip this step. Otherwise list those workstreams once and offer to describe them, drafting each from its title and body by the rule in `/work:checkpoint` step 2 (after `title`, one sentence on what the workstream delivers, taken from its ask). Show every draft, then ask which to write: some, all or none (Claude Code: `AskUserQuestion`, multi-select, at most 4 options; elsewhere, or with more than 4 drafts, number the drafts and ask for numbers, "all" or "none"). Add only the approved ones, with Edit, and leave `updated` and `generated` alone so a stale workstream stays stale. If at least one was written, run `work-tools index`: it must exit 0, or exit 1 naming only files already listed in step 1 that the user chose not to fix; fix any header error in a file you just edited. Then commit once in the store: `git -C "<store>" add -A && git -C "<store>" commit -m "standup: describe <n> workstreams"`. If the user declines them all, nothing is written and nothing is committed.

Apart from step 5's commit, do not commit the regenerated `index.md` and `log.md` or the OKF `type` fields `index` may add; the next `/work:checkpoint` will. Change nothing else.
