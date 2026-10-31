---
name: resume
description: Resume a tracked workstream from the user's work store. Use when the user says "/work:resume", "resume <x>", "pick up <x>", "where were we on <x>", or opens a fresh thread on ongoing work. Finds the workstream, reads its status file, checks for drift, and gives a short brief ending with the next step. Read-only.
---

# Resume a workstream

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below. The store is the folder `work-tools root` prints; its conventions are in its `README.md`.

1. **Find it.**
   - With an argument: `work-tools find "<argument>"`. Without one: `work-tools find --cwd "$PWD"`.
   - Exit 0: stdout is the status-file path.
   - Exit 2: stdout lists candidate keys; ask the user which one (AskUserQuestion, at most 4 options; if more, show the list and ask for a narrower name).
   - Exit 3: no match; show `work-tools list` and offer `/work:new`.
   - Exit 4: there is no work store yet; say so and offer `/work:new`, which creates one.
2. **Read** the area's `AREA.md`, then the status file. Open other source files only where the status file says to read them first or the next step needs them; no bulk reading.
3. **Check drift:** `work-tools drift <area>/<slug>`.
4. **Brief** in at most 6 lines:
   - **Where it stands:** status plus one line.
   - **Since last time:** the drift lines, or "nothing changed".
   - **Next:** the `next` field.
   - **Gating questions:** at most 2 open questions or blockers that block the next step.

   End with: "Start on «next»?"

Rules:
- Change nothing; this skill only reads.
- Remember the workstream key (`<area>/<slug>`) for `/work:checkpoint` and `/work:wrap` later in the session.
- Dates and version numbers inside source documents are deliberate; never "correct" them.
