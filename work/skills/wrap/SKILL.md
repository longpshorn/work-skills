---
name: wrap
description: Conclude a working session on a tracked workstream in the user's work store: checkpoint, surface loose ends, propose memory updates, archive if done, and hand back the resume command. Use for "/work:wrap", "wrap up", "let's stop here", "end of session".
---

# Wrap up a session

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. Run the full `/work:checkpoint` procedure.
2. **Loose ends.** Run `work-tools drift <key>` and present each item: uncommitted or unpushed repo work, and linked source files changed since `updated`. Where a changed file is the source of one of the workstream's `artifacts`, say that artifact may need a republish. Ask what to do with each: commit, push, republish or leave. Do nothing to any repo or artifact without an explicit yes.
3. **Memory.** List candidate durable lessons from this session (corrections the user made, preferences they confirmed, non-obvious project facts), following the memory rules: no duplicates, and nothing the store or the repo already records. Write only the ones the user approves, to the agent's memory (Claude Code: its memory files; elsewhere the agent's own memory, or, if it has none, list the approved lessons for the user to keep).
4. **Done?** Ask whether the workstream is finished. If yes:
   - set `state: done`, add a Log line and run `work-tools touch <key>`
   - create `<store>/_archive/<area>` if it is missing
   - `git -C "<store>" mv <area>/<file> _archive/<area>/<file>`
   - run `work-tools index`; it also marks the archived file with OKF `status: deprecated` (`ARCHIVED_STATUS` in the plugin's `work.py`)
   - commit: `git -C "<store>" add -A && git -C "<store>" commit -m "wrap: archive <key>"`
5. **Hand back.** End the reply with the one-line state. If the workstream stays open, add the resume command: `/work:resume <q>`, where `<q>` is the shortest name for which `work-tools find <q>` exits 0 on this workstream (verify it before printing). If it was archived in step 4, say "Archived; nothing to resume" instead, since `find` does not search `_archive/`.
