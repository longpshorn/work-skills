---
name: new
description: Start tracking a new workstream in the user's work store. Use for "/work:new <area>/<name>", "track this", "start a new project", or when /work:resume finds no match.
---

# Start tracking a workstream

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. **Store.** If `<store>` doesn't exist, run `work-tools init` and pass on what it printed, including any "not committed" warning (a missing git identity, or git's own commit error).
2. **Parse `<area>/<name>`.** Both parts are lower-kebab-case; ask for whatever is missing.
3. **New area?** If `<store>/<area>/` does not exist, ask for a one-line purpose and write `<area>/AREA.md`:

   ```markdown
   ---
   description: <the purpose, one line>
   ---
   # <Area title>

   ## How the workstreams relate

   <one line per workstream as they appear>
   ```

4. **Number.** `NN` is the next free two-digit number in the area (`01` if there are none).
5. **Write `<area>/NN-<name>.md`** from this template:
   - `repos`: if the current directory is inside a git repo, use `git rev-parse --show-toplevel` with the home folder written as `~`; otherwise `[]`.
   - Take the ask, its one-sentence summary for `description`, and the first next step from the conversation; ask the user only if they are unclear.

   ```markdown
   ---
   title: <Title>
   description: <one sentence: what this workstream delivers>
   state: scoped         # idea | scoped | active | blocked | review | done
   next: <first next step>
   repos: [<~/path>]
   artifacts: []
   ---
   # NN · <Title>

   ## The ask

   ## Where things stand

   ## Open questions

   ## Next steps

   ## Log

   - <today> · started tracking
   ```

6. Run `work-tools touch <area>/NN-<name>`, which writes the `updated` date and the OKF `generated` stamp. Then run `work-tools index` (it must exit 0; it adds each new file's OKF `type` from `TYPES` in `work.py`, so the templates above leave it out), then commit in the store: `git -C "<store>" add -A && git -C "<store>" commit -m "new: <area>/NN-<name>"`. The store's only branch is `log` (never `main`); that is expected.
7. Confirm with the file path and `/work:resume <name>`.

Only Claude Code gets a post-compaction reminder to checkpoint. In any other agent, run `/work:checkpoint` after each milestone and before your context fills.
