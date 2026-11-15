---
name: checkpoint
description: Save this session's progress on a tracked workstream to the user's work store without ending the session. Use for "/work:checkpoint", "save progress", "note that down", before risky steps, when context is getting full, and immediately when a post-compaction reminder asks for it.
---

# Checkpoint a workstream

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. **Which workstream?** Use the one `/work:resume` loaded. Otherwise, match the session's work with `work-tools find`. If the session touched several workstreams, ask which (multi-select; checkpoint each one). If none is tracked, offer `/work:new`, unless `find`'s stderr says a file matches "but its header can't be read": then show that file's error and offer to fix the header first. Other stderr lines (`<path>: <message>`) are header errors in other status files; mention them in one line and carry on.
2. **Update the status file** with Edit (never rewrite the whole file):
   - **Log:** append to `## Log`, one line per decision or result: `- YYYY-MM-DD · <what was decided, built or found, with paths/URLs>`. Facts only; mark anything unverified as such.
   - **Header:** set `state` and `next`. Add any new artifact URLs to `artifacts`. If there is no `description`, add one after `title`: one sentence on what the workstream delivers, taken from its ask; otherwise change it only when it is now wrong. Leave `generated` to the next step.
   - **Body:** edit sections only where they are now wrong, for example to move an answered open question into the Log.
3. Run `work-tools touch <area>/<slug>`, which stamps OKF `generated` with the current time, then `work-tools index`. It must exit 0; fix any header error you introduced. It also adds a missing OKF `type`, marks workstreams under `_archive/` with OKF `status` and, once the store is upgraded, turns an old `updated` date into `generated`; commit those changes with the checkpoint. If `touch` or `index` reports that the store predates the OKF format, pass its upgrade hint to the user rather than editing headers by hand, and still commit the Log and header edits in step 4.
4. Commit in the store only:
   `git -C "<store>" add -A && git -C "<store>" commit -m "checkpoint: <area>/<slug> — <five-word gist>"`
   The store's branch is `log`. Never switch it to `main`.
5. Confirm in one line: "Checkpointed <key>: <gist>."

Never commit or push in any other repo. Never alter dates or version numbers inside source documents.
