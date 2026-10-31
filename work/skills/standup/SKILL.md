---
name: standup
description: Cross-workstream status view from the user's work store. Use for "/work:standup", "what's on my plate", "what's stale", "status of everything", or weekly planning. Read-only apart from regenerating INDEX.md.
---

# Standup: every workstream at a glance

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. Run `work-tools index`. Exit 1 means some status files have header errors; list them first and offer to fix them. Exit 4 means there is no work store yet; say so, offer `/work:new`, and stop.
2. Read `<store>/INDEX.md` and run `work-tools drift --all`.
3. Print these sections, leaving out any that are empty:
   - **Blocked:** workstream · next
   - **Stale** (⚠, 14+ days): workstream · age
   - **Uncommitted / unpushed / changed sources:** from drift
   - **Top 5 next steps:** order by status (`active`, `review`, `blocked`, `scoped`, `idea`), then oldest `updated` first
4. Offer `/work:resume <name>` for the top item.

Do not commit the regenerated index; the next `/work:checkpoint` will. Change nothing else.
