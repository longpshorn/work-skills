# Dream: nightly memory consolidation

## Intent

Claude Code's auto-memory (a folder of one-fact Markdown files plus a `MEMORY.md` index, loaded at the start of every session) grows by hand, one `/work:wrap` at a time. Lessons that never get written down are lost. Facts that were written down go stale, get duplicated or get contradicted. A nightly **dream** run reviews the day's conversations and keeps that memory accurate, deduplicated and easy to retrieve. It also promotes durable facts into the `CLAUDE.md` / `AGENTS.md` files that load whenever the user works in a given project, so every future session starts with the right facts and doesn't forget them, repeat mistakes or invent things.

The audience is future Claude sessions, not the user. Success means a session on any project starts with what matters already in context, and nothing in context is wrong.

## Goals

- **Extract** durable lessons from conversations that ended since the last run: corrections the user made, preferences they stated or confirmed, decisions, non-obvious project facts, and explicit "remember this" requests.
- **Consolidate** the memory folder:
  - merge duplicates
  - resolve contradictions (newer evidence wins)
  - convert relative dates to absolute
  - add `[[links]]` between related memories
  - retire facts that are stale or contradicted
- **Keep the index retrievable.** One terse line per memory, organized by topic, well under Claude Code's load limit (the first 200 lines or 25 KB of `MEMORY.md`).
- **Promote** facts that matter every time a project is worked on:
  - Cross-project facts about the user and how they work go into the global `~/.claude/CLAUDE.md`.
  - Repo facts go into that repo's `CLAUDE.md` or `AGENTS.md`.
- **Run unattended every night**, incrementally, cheaply, and with every change undoable.

## Non-goals

- A report for the user to read. A run leaves no output unless it fails.
- Real-time memory writes during a session. `/work:wrap` and the in-session memory rules still do that.
- Cleaning up briefs or other files from herdr-skills or irt-skills. That is a separate design.
- Merging anything. The run opens merge requests; people merge them.

## Anti-goals (failure even if it "works")

- **A memory planted by content.** Text inside a conversation that the user did not write (tool output, pasted documents, fetched web pages, files, subagent reports, other agents' messages) must never become a memory or an instruction. Only the user's own words and outcomes Claude verified in the session count as evidence.
- **A hallucinated or over-generalized memory.** Every new or changed memory must be traceable to a quote in a named conversation. A fact about a file, function, flag or path is checked against the current code before it is kept.
- **Silent loss.** A still-valid fact deleted, or an index line dropped, with no way to see it was there.
- **Drift.** Repeated nightly rewording that slowly changes a memory's meaning. A memory is rewritten only when new evidence touches it.
- **Bloat.** The index or a `CLAUDE.md` growing night over night until it crowds out the context it exists to serve.
- **Anything outward without review.** No posts to Slack, Teams or email. No merges. No pushes to a default branch.

## Decisions the user made

- **The memory folder goes under git first**, as a local repository with no remote. It's the folder named by `autoMemoryDirectory` in `~/.claude/settings.json`, else Claude Code's default per-project memory folder.
- **The run edits committed `CLAUDE.md` / `AGENTS.md` files directly**, on a branch, and opens a merge request. The repo's normal merge-request review is the check. It never merges.
- **Repos with ticket rules use one standing ticket** for all of the run's `CLAUDE.md` changes, rather than the run filing a ticket per change. Such repos enforce ticket keys in branch names and require a ticket on every merge request.
- **The run plan below is approved as written** (schedule, transcript pre-filter, model split, what it leaves behind).

## The run

**Schedule.**
- A macOS LaunchAgent starts the run at about 02:00 local time. launchd runs a missed job when the Mac wakes.
- The run takes a lock, so it exits if another run is still going.
- It skips the night if fewer than 3 conversations ended since the last run. A conversation counts as ended when its transcript hasn't changed for 2 hours.
- The work-skills docs ship the LaunchAgent plist and an install command that writes it to `~/Library/LaunchAgents`, then loads it. Install is idempotent.

**Read (a script, not the model).** A tested `work-tools dream-gather` subcommand, which is deterministic and has fixture tests:
- Reads the transcript JSONL files under `~/.claude/projects/` changed since the high-water mark in the run state file.
- Keeps only:
  - the user's typed messages, without `<pasted_content>` blocks, system reminders or tool results
  - Claude's final reply text per turn
  - session id, project folder, cwd, timestamps and message uuids
- Flags likely evidence: corrections ("no", "don't", "that's wrong", "actually"), confirmations, "remember", rules ("always", "never", "from now on"), and decisions.
- Skips its own runs' transcripts and those of other headless jobs, identified by a marker in the prompt.
- Writes a compact digest per conversation and prints the list. It never sends anything anywhere.

**Think (the model).** A headless `claude -p` run using `/work:dream`:
- **Orient.** Read `MEMORY.md` and the memory files' frontmatter.
- **Extract.** From each digest, list candidate facts. Each one carries the session id, the message uuid and a short quote of the user's words, or of the verified outcome.
- **Match.** For each candidate, search the existing memories by name, description and body. Then decide:
  - add a new memory
  - update one
  - merge two or more
  - retire one
  - do nothing
- **Retire, not delete.** A retired memory moves to `_retired/` with `superseded_by:` (a memory name, or `none`) and `retired:` (a date) in its frontmatter. Its index line is removed. Git keeps the history too.
- **Verify** any memory that names a file, function, flag or path against the current checkout before keeping it. If it can't be verified, mark it `unverified: <date>` rather than state it as fact.
- **Reindex** `MEMORY.md`:
  - It's grouped under a few topic headings: about the user, how they want work done, each project, and references.
  - Each entry is one line: `- [Title](file.md) — hook`.
  - Hard cap: 150 lines or 18 KB, leaving headroom under the load limit. Over the cap, tighten the hooks and fold close topics together before dropping anything.
- **Promote** a fact into a `CLAUDE.md` only when all of these hold:
  - It came up on at least 2 separate days, or the user stated it as a rule.
  - The target file doesn't already say it.
  - It's stable: a rule, convention or fact, not a status.
  
  Further limits:
  - Cap: 5 promotions per run in total.
  - A promoted fact keeps its memory file, marked `promoted_to: <path>`, so it is never promoted twice.
  - Edit a `CLAUDE.md` concisely, in the file's existing voice and structure. If the edit would push the file past 200 lines, tighten the file instead of growing it.
- **Models.**
  - Extraction and matching run on Sonnet.
  - A candidate that contradicts an existing memory, and every promotion, gets a second check by an Opus subagent before it applies. The subagent sees only the candidate, the quote and the memory it touches.

**Write.**
- **Memory folder.** One commit per run. The message lists the conversations read and the memories added, updated, merged, retired and promoted, by name. Before committing, `work-tools dream-check` validates:
  - frontmatter schema
  - every index line points to a file
  - every live file has an index line
  - the size caps
  
  A failed check discards the run's working-tree changes and logs the failure.
- **Global `~/.claude/CLAUDE.md`.** Edited directly. Before each run, a copy is committed to the memory repo as `_global/CLAUDE.md`, so its history is there too.
- **Repo `CLAUDE.md` / `AGENTS.md`.**
  - Fetch the default branch and cut a new branch from it in a temporary worktree, never in the user's checkout.
  - Commit the edit and push.
  - Open a merge request with the forge's CLI: GitHub `gh` or GitLab `glab`, chosen by the `origin` URL.
  - At most one branch and one merge request per repo per night. If the run's previous merge request in that repo is still open, add a commit to its branch instead of opening a second.
  - No chat announcement.
  - The branch name, commit format, ticket key and reviewers come from the private config below.
- **State and log.**
  - `~/.local/state/work-dream/state.json` holds the high-water mark (per transcript: last processed uuid and mtime), the last run time and the open merge requests.
  - `run.log` holds one line per run: date, conversations read, counts, merge-request links, ok/failed.
  - `/work:standup` shows a line only when the last run failed, or when no run has succeeded in 3 days.

## Headless setup

Use the measured cheap invocation from the user's headless notes:
- `--system-prompt` with a short prompt that names `/work:dream` and the digest paths
- `--tools` restricted to the file tools, Bash and ToolSearch, with `--disallowedTools mcp__<server>` for every MCP server (the run needs none)
- `--disable-slash-commands`, and `--settings '{"disableAllHooks":true}'`
- `--setting-sources project,local`, so the user's own settings (allow rules, `env`, plugins) never reach the stages; the login stays in the keychain
- the prompt on stdin
- `MCP_CONNECTION_NONBLOCKING=false`, and `USER` and `LOGNAME` set for the keychain login
- `--output-format stream-json --verbose` saved per run, so a failure can be diagnosed

The prompt carries the marker that `dream-gather` uses to skip the run's own transcript.

## Private config (keeps the repo portable)

The work-skills repo names no organization, person or system. Anything org-specific lives in `~/.config/work/dream.json`, which the install step creates from a commented example:
- `memory_dir`, defaulting to `autoMemoryDirectory`
- `global_claude_md`
- `repos`: per-repo rules matched by `origin` URL substring, each with:
  - `branch` pattern, for example `docs/{ticket}-memory-{date}`
  - `commit` pattern, for example `docs: {ticket} {summary}`
  - `ticket`, the standing ticket key
  - `reviewers`
  - `promote: true|false`
  
  A repo with no matching rule is never edited (see question 4 below).
- `models`, `caps` and `schedule`

The user's own config gets:
- the standing DX ticket, created when this is built, titled along the lines of "Agent memory: CLAUDE.md updates from the nightly dream run"
- the org's branch and commit rules
- each repo's default reviewers

## Prerequisites (one-time, at install)

1. `git init` the memory folder: branch `main`, no remote, and an initial commit of what's there.
2. Create `~/.claude/CLAUDE.md` if missing. The run fills it.
3. Write the private config from the example, and the LaunchAgent plist. Load the agent.
4. Run the first dream by hand (`work-tools dream-run --now`) and check its commit.
5. The first run's high-water mark is "now minus 14 days", not all history, so the first night is bounded.

## Builder's questions, settled (the author's calls unless marked)

1. **One memory folder.**
   - The run requires `autoMemoryDirectory` to be set to one shared folder; the user's already is. If it isn't set, install stops and offers to set it. It never runs per project folder.
   - A run first commits any uncommitted memory changes as a `pre-dream snapshot`, so the tree is clean. If a live session writes during the run, its changes are committed together with the run's.
   - A failed `dream-check` resets to the snapshot commit.
2. **What counts as the user's words.** `dream-gather` keeps a user-role message only if it is typed text. It drops:
   - `isMeta` entries
   - slash-command and skill expansions
   - `<system-reminder>`, `<task-notification>`, `<agent-message>` and `<pasted_content>` blocks
   - tool results
   - hook output
   
   Other cases:
   - A herdr-spawned agent's session (its first prompt matches the spawn or `send-prompt` patterns) is an agent session. Its prompts are another Claude session's words, not the user's. Only messages the user typed into that pane later, which don't match the herdr prompt patterns, count, and they are flagged `agent-session`.
   - Claude's reply text is context, never a quote source. The one exception is an outcome the reply marks **Verified** alongside the command that proved it.
   - Fixtures cover each case, including injected text inside a tool result and inside a pasted block.
3. **Orchestration.**
   - `dream-run` calls `claude -p` separately for each stage: one Sonnet call for extract, match and write, then one small Opus call per contradiction or promotion. Each Opus call sees only the candidate, the quote and the memory it touches, and returns approve or reject.
   - The headless call reads the skill as a file (`work/skills/dream/SKILL.md`, path given in the system prompt), so `--disable-slash-commands` stays.
   - No Agent tool.
4. **Repos with no matching rule are not touched.** Promotion into a repo is allow-list only: `promote: true` in a `repos` rule. Repo facts for other repos stay memories.
5. **Repo mapping.**
   - A conversation maps to the git repo enclosing its `cwd`, resolved to the main checkout through `git rev-parse --git-common-dir`, so worktrees map to their repo. A missing cwd maps to no repo.
   - Claims are verified against the fresh default-branch worktree the run creates.
   - A fact tied to several repos, or none, stays a memory, unless it is about the user, in which case it can be promoted to global.
6. **Sightings.**
   - Memory frontmatter gains `seen:`, a list of dates on which a conversation supported the fact. `sources:` lists session id and message uuid pairs.
   - "Stated as a rule" means the quote contains the user stating a standing rule. The Opus check confirms it.
   - Memories written by hand count from their first `seen`, which is backfilled from the file's mtime.
7. **Nothing private reaches a repo file.** Only facts about the repo's own code, commands, conventions and tooling are promotable to that repo. Facts about people, strategy, customers or credentials, and the user's personal preferences, never are. Personal preferences go to global only. The Opus check enforces this and rejects anything doubtful.
8. **First run.** It is a one-time reorganization, committed on its own before any extraction:
   - normalize frontmatter (add missing fields, keep existing ones)
   - regroup `MEMORY.md` under the topic headings with one line each
   - merge clear duplicates
   - retire memories that the current code or a newer memory contradicts
   
   This matches the user's stated goal of a highly organized store; the single commit is the record. `dream-check`'s schema requires only `name`, `description` and `metadata.type`, so older files pass.
9. **Budget and failure.**
   - The run uses the logged-in subscription, not an API key. The Sonnet stage is capped at `--max-turns 60`, and each Opus check at 6.
   - On a login, rate-limit or tool failure: no retry; the failure is logged, and the next night picks up where it stopped.
   - The high-water mark advances only after the memory commit succeeds.
   - Repo pushes and merge requests run after that commit. A failed push is recorded in `state.json` and retried the next night from the same commit, never re-derived.

## Left to the builder

- Exact digest format, flag heuristics and fixture transcripts.
- How `dream-run` wraps `dream-gather`, `claude -p` and `dream-check`. Shell or Python in `work.py`, matching the existing helper.
- The skill text of `/work:dream`, following the team's skill-authoring rules: judgment in prose, deterministic steps in the tested script.
- Index topic headings, beyond the four named above.
- README and store-README updates, and any `/work:wrap` wording that should point to the dream run.
- Evals before merge: at least 3 scenarios (a correction to extract, a contradiction to retire, injected text in a tool result that must be ignored) with a baseline arm, per the skill-authoring rules.
