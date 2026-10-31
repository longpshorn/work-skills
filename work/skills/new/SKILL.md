---
name: new
description: Start tracking a new workstream in the user's work store. Use for "/work:new <area>/<name>", "track this", "start a new project", or when /work:resume finds no match.
---

# Start tracking a workstream

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. `work-tools root` prints the store's folder, written `<store>` below.

1. **Store.** If `<store>` doesn't exist, run `work-tools init` and pass on what it printed, including any "not committed" warning about git's identity.
2. **Parse `<area>/<name>`.** Both parts are lower-kebab-case; ask for whatever is missing.
3. **New area?** If `<store>/<area>/` does not exist, ask for a one-line purpose and write `<area>/AREA.md`:

   ```markdown
   # <Area title>

   **Purpose:** <one line>

   ## How the workstreams relate

   <one line per workstream as they appear>
   ```

4. **Number.** `NN` is the next free two-digit number in the area (`01` if there are none).
5. **Write `<area>/NN-<name>.md`** from this template:
   - `repos`: if the current directory is inside a git repo, use `git rev-parse --show-toplevel` with the home folder written as `~`; otherwise `[]`.
   - Take the ask and the first next step from the conversation; ask the user only if they are unclear.

   ```markdown
   ---
   title: <Title>
   status: scoped        # idea | scoped | active | blocked | review | done
   next: <first next step>
   updated: <today, YYYY-MM-DD>
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

6. Run `work-tools index` (it must exit 0), then commit in the store: `git -C "<store>" add -A && git -C "<store>" commit -m "new: <area>/NN-<name>"`. The store's only branch is `log` (never `main`); that is expected.
7. Confirm with the file path and `/work:resume <name>`.
