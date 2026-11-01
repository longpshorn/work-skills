---
name: checkpoint
description: Save this session's progress on a tracked workstream to the user's work store without ending the session. Use for "/work:checkpoint", "save progress", "note that down", before risky steps, when context is getting full, and immediately when a post-compaction reminder asks for it.
---

# Checkpoint a workstream

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. **Which workstream?** Use the one `/work:resume` loaded. Otherwise, match the session's work with `work-tools find`. If the session touched several workstreams, ask which (multi-select; checkpoint each one). If none is tracked, offer `/work:new`.
2. **Update the status file** with Edit (never rewrite the whole file):
   - **Log:** append to `## Log`, one line per decision or result: `- YYYY-MM-DD · <what was decided, built or found, with paths/URLs>`. Facts only; mark anything unverified as such.
   - **Header:** set `state` and `next`. Add any new artifact URLs to `artifacts`. If there is no `description`, add one after `title`: one sentence on what the workstream delivers, taken from its ask; otherwise change it only when it is now wrong. Leave `updated` and `generated` to the next step.
   - **Body:** edit sections only where they are now wrong, for example to move an answered open question into the Log.
3. Run `work-tools touch <area>/<slug>`, which sets `updated` to today and stamps OKF `generated`, then `work-tools index`. It must exit 0; fix any header error you introduced. It also adds a missing OKF `type` and renames an old `status` key to `state`; commit those changes with the checkpoint.
4. Commit in the store only:
   `git -C "<store>" add -A && git -C "<store>" commit -m "checkpoint: <area>/<slug> — <five-word gist>"`
   The store's branch is `log`. Never switch it to `main`.
5. Confirm in one line: "Checkpointed <key>: <gist>."

Never commit or push in any other repo. Never alter dates or version numbers inside source documents.
