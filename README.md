# work-skills

Claude Code skills for keeping track of ongoing work across sessions. Each workstream gets one status file (what was asked, where it stands, the single next step, and a dated log), so a fresh session can pick up exactly where the last one stopped.

| Command | What it does |
| - | - |
| `/work:new <area>/<name>` | Start tracking a workstream. On a machine with no store yet, it creates one first. |
| `/work:resume [name]` | Find a workstream (by name, or by the repo you're in), check what changed since last time, and brief you on the next step. Read-only. |
| `/work:checkpoint` | Log this session's decisions and results, update the next step, and commit, without ending the session. |
| `/work:wrap` | Checkpoint, surface loose ends (uncommitted work, changed sources), propose memory updates (when the nightly dream run is installed, it picks up anything missed), archive the workstream if it's done, and hand back the resume command. |
| `/work:standup` | Every workstream at a glance: blocked, stale, loose ends, and the top five next steps. It adds one line when the nightly dream run is failing or has gone quiet. |
| `/work:dream` | The nightly memory run: consolidates Claude's auto-memory folder from your recent conversations. Normally launched by the scheduler, not by hand. See [Nightly dream](#nightly-dream). |

After Claude Code compacts a conversation, the plugin reminds the session to run `/work:checkpoint`.

## Install

```sh
claude plugin marketplace add longpshorn/work-skills
claude plugin install work@work-skills
```

Then restart Claude Code. Your first `/work:new` creates the store.

## Where your notes live

The store is a folder of Markdown files with its own local git history, on branch `log` and with no remote. It stays on the machine; the plugin never pushes it anywhere. Its `README.md` explains the file format.

The store is also an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) (OKF) v0.2 bundle, so OKF tools can read it without knowing this plugin. Every file carries an OKF `type`; workstreams and areas carry a one-line `description`, and each workstream records when it last changed in OKF's `generated`, and archived workstreams carry OKF `status: deprecated`. `index.md` is the bundle's navigation file, and `log.md` gathers every workstream's Log lines by date. A store made before OKF support needs no migration: the next `/work:checkpoint` or `/work:standup` adds the missing types, area descriptions and archived workstreams' `status`, and renames `INDEX.md` to `index.md`, and each workstream gains its `description` and `generated` at its next checkpoint.

The store is `~/.work` unless you choose another folder. To use another folder, set `WORK_STORE` in the `env` block of `~/.claude/settings.json`, so every Claude Code session, the hook and the helper see it:

```json
{
  "env": {
    "WORK_STORE": "/absolute/path/to/your/notes"
  }
}
```

The path must be absolute or start with `~`; the helper refuses a relative one. On Windows, write the drive path with forward slashes, `"C:/Users/you/notes"`, or with doubled backslashes, `"C:\\Users\\you\\notes"`. A single backslash is not valid JSON.

`/work:resume` and `/work:wrap` check the repos a workstream lists for uncommitted or unpushed work. If some of your repos live on a mount where git is slow or wrong to run (a virtual machine's shared folder, for example), set `WORK_VM_ROOT` to that mount. Repos under it are then flagged instead of checked.

## Nightly dream

`/work:dream` keeps Claude's auto-memory folder (the one-fact Markdown files and the `MEMORY.md` index every session loads) current without you tending it. Each night `work-tools dream-run` digests the conversations that have ended, asks Claude to add, update, merge and retire memories, has a second model review every change that contradicts a memory or promotes one into an instruction file, then commits the result.

Know what you are installing:

- **It edits memory unattended.** Nobody reviews a run before it lands. The memory folder is its own local git repo, committed before and after each run that changes anything, and a run that fails before its memory commit is reset, so any run can be reverted. Only the changes the run lists for review (contradictions and promotions) get the second model's check; merges, the first-run reorganization and the stage's direct memory edits follow the skill and are not reviewed, and a repo rule's `match` is a plain substring of the origin URL, so make it specific.
- **It opens merge requests (pull requests on GitHub) but never merges.** A fact about one repo can be proposed as a change to that repo's `CLAUDE.md` or `AGENTS.md`, but only for a repo you have allowed with `"promote": true`. The run pushes a branch and opens one merge request per repo for you to review; it never merges and never pushes to the default branch. A proposal is deferred when your checkout of the file differs from the branch it would land on. Facts about you go only to your global `CLAUDE.md`, which the run edits directly.
- **Paid models run nightly on your plan.** Each run starts a Sonnet extraction stage and an Opus check per reviewed change, each with turn, time and dollar caps. A night with fewer than `min_conversations` ended conversations makes no model calls. The runs leave no session transcript, so they never appear in tomorrow's digest. The stages ignore your user settings (`--setting-sources project,local`), so your allow rules and plugins never widen what they can do.

The run keeps its own state (`run.log`, digests, a lock) in `~/.local/state/work-dream`. It reads transcripts in `~/.claude/projects` and never sends them anywhere but the models above.

### Install

macOS only (the scheduler is a LaunchAgent). The memory folder is `autoMemoryDirectory` from `~/.claude/settings.json`, or `memory_dir` in the config.

```sh
sh "<plugin>/scripts/work-tools" dream-install --init-memory --load
```

`dream-install` writes the private config `~/.config/work/dream.json` from the plugin's `dream.example.jsonc` if you have none (it never overwrites one), writes a launcher that finds the installed `work` plugin at run time so plugin updates need no reinstall, and writes `~/Library/LaunchAgents/com.work.dream.plist`. `--init-memory` makes the memory folder a git repo and creates the global `CLAUDE.md` if missing; `--load` loads the LaunchAgent with `launchctl`. It is idempotent. After changing `schedule`, run `dream-install --load` again: without `--load` the loaded agent keeps the old time.

### Turn it off

To pause across logins (launchd reloads every plist in `~/Library/LaunchAgents` at login), run `launchctl disable gui/$(id -u)/com.work.dream`, then `launchctl bootout gui/$(id -u)/com.work.dream` to stop the loaded job. To resume, run `launchctl enable gui/$(id -u)/com.work.dream`, then `dream-install --load`.

To uninstall, run `launchctl bootout gui/$(id -u)/com.work.dream`, then delete `~/Library/LaunchAgents/com.work.dream.plist`. Removing `~/.local/state/work-dream` and `~/.config/work/dream.json` is optional. The memory folder's git history stays.

### Config

`~/.config/work/dream.json` (full-line `//` comments allowed). Every key is optional.

| Key | Meaning |
| - | - |
| `memory_dir`, `global_claude_md` | The memory folder, and the user-level instructions file promotions may edit. |
| `models` | `extract` (default `sonnet`) and `check` (`opus`). |
| `caps` | Index size, instruction-file length, promotions per run, `min_conversations` and `idle_hours` gates, `first_run_days` lookback, `max_digests` (the oldest conversations read per run; the rest wait for the next night), and per-stage turn, timeout and dollar limits. |
| `schedule` | Local `hour` and `minute` (default 02:00). |
| `repos` | Per-repo rules: `match` (a substring of the origin URL), `branch`, `commit`, `ticket`, `reviewers` and `promote`. A repo without `"promote": true` is never touched. |
| `agent_prompts` | Regexes marking a conversation as an agent run, which is skipped. |
| `claude_bin` | The `claude` executable. |

Environment overrides: `WORK_DREAM_CONFIG`, `WORK_DREAM_STATE` and `WORK_DREAM_PROJECTS` move the config, the state folder and the transcripts folder; `dream-install` copies any that are set into the LaunchAgent.

### Commands

| Command | What it does |
| - | - |
| `work-tools dream-run [--now]` | One pass. `--now` runs even below `min_conversations`. Prints nothing on success; the outcome is a line in `run.log`. |
| `work-tools dream-status` | One line when the last run failed or none has succeeded for 3 days; nothing otherwise. `/work:standup` shows it. |
| `work-tools dream-check` | Validates the memory folder. |
| `work-tools dream-gather` | Writes the digests of recent conversations, for use by hand. |
| `work-tools dream-install` | As above. |

The first run reorganizes the existing folder before extracting; every run after it rewrites a memory only when new evidence touches it.

## Requirements

- Python 3.9 or later, as `python3`, `python` or `py -3`.
- `sh`: built in on macOS and Linux. On Windows it comes with Git for Windows, which Claude Code uses to run commands.
- git, with `user.name` and `user.email` set. Without them, `/work:new` still creates the store but can't commit, and says so.

## Fewer permission prompts

The skills run the helper as `sh "<plugin>/scripts/work-tools" <subcommand>` and git as `git -C "<store>" <subcommand>`. To stop Claude Code asking each time, add allow rules in `/permissions`. A rule matches the command text as written, so keep the double quotes and use absolute paths, exactly as the permission prompt shows them (no `~`). On Windows that means forward slashes in the plugin path (`C:/Users/you/.claude/plugins/...`) and backslashes in the store path (`C:\Users\you\.work`).

Which plugin path the skills run from depends on how you installed it:

- **From GitHub** (`claude plugin marketplace add longpshorn/work-skills`): from `~/.claude/plugins/cache/work-skills/work/<version>/`, a folder that changes with every update. Put a `*` in place of the version folder so the rule survives updates:

  ```
  Bash(sh "/Users/you/.claude/plugins/cache/work-skills/work/*/scripts/work-tools" *)
  ```

  The `*` matches any text, not just one folder name.

- **From a local clone** (`claude plugin marketplace add /path/to/work-skills`): from the clone itself, so the path stays the same:

  ```
  Bash(sh "/path/to/work-skills/work/scripts/work-tools" *)
  ```

For git, with your store's absolute path (`~/.work` unless you set `WORK_STORE`):

```
Bash(git -C "/Users/you/.work" *)
```

## Development

The helper is `work/scripts/work.py` (standard library only). The skills and the hook run it through `work/scripts/work-tools`, which finds a Python.

```sh
python -m pip install pytest
python -m pytest work/scripts/tests -q
```

CI runs the tests on Linux, macOS and Windows.

## License

MIT
