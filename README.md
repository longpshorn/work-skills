# work-skills

[![AgentAvow](https://agentavow.com/api/v1/public/scan/longpshorn/work-skills/badge)](https://agentavow.com/check/longpshorn/work-skills)

Skills for keeping track of ongoing work across sessions, for Claude Code and [other coding agents](#other-coding-agents). Each workstream gets one status file (what was asked, where it stands, the single next step, and a dated log), so a fresh session can pick up exactly where the last one stopped.

| Command | What it does |
| - | - |
| `/work:new <area>/<name>` | Start tracking a workstream. On a machine with no store yet, it creates one first. |
| `/work:resume [name]` | Find a workstream (by name, or by the repo you're in), check what changed since last time, and brief you on the next step. Read-only. |
| `/work:checkpoint` | Log this session's decisions and results, update the next step, and commit, without ending the session. |
| `/work:wrap` | Checkpoint, surface loose ends (uncommitted work, changed sources), propose memory updates, archive the workstream if it's done, and hand back the resume command. |
| `/work:standup` | Every workstream at a glance: blocked, stale, loose ends, and the top five next steps. |

After Claude Code compacts a conversation, the plugin reminds the session to run `/work:checkpoint`. That reminder is a Claude Code hook; for other agents, see [Other coding agents](#other-coding-agents).

## Install

```sh
claude plugin marketplace add longpshorn/work-skills
claude plugin install work@work-skills
```

Then restart Claude Code. Your first `/work:new` creates the store.

## Other coding agents

Claude Code installs the skills as a plugin (above), and that stays the main way in. Other coding agents read plain skill folders: Codex, Gemini CLI, OpenCode and omp all read `~/.agents/skills`. `install-skills` writes a copy of each skill there.

```sh
git clone https://github.com/longpshorn/work-skills ~/code/work-skills   # any folder that stays put
sh ~/code/work-skills/work/scripts/work-tools install-skills             # into ~/.agents/skills: all four tools
sh ~/code/work-skills/work/scripts/work-tools install-skills --update    # later: pull the clone, refresh the copies
```

- **What it writes.** One folder per skill, named `work-<skill>` (`work-new`, `work-resume`, `work-checkpoint`, `work-wrap`, `work-standup`), so generic names such as `new` and `resume` can't collide with another package's skills. In each copy `${CLAUDE_PLUGIN_ROOT}`, which only Claude Code fills in, is replaced by the clone's absolute `work` folder (forward slashes on Windows too), so every skill finds its helper. A note under the heading says that `/work:<name>` in the text means the `work-<name>` skill.
- **Where.** `--tool` picks a tool's own folder instead of the shared one, and `--dest` any folder. Run it once per tool you want, or once for all four with the default. Install into one folder per tool: Gemini CLI warns when the same skill is in both of its folders.

  | `--tool` | Folder | Source |
  | - | - | - |
  | `agents` (default), `codex` | `~/.agents/skills` | [Codex skills](https://learn.chatgpt.com/docs/build-skills) (`~/.codex/skills` is deprecated); also read by Gemini CLI, OpenCode and omp |
  | `gemini` | `~/.gemini/skills` | [Gemini CLI skills](https://geminicli.com/docs/cli/skills/) |
  | `opencode` | `$XDG_CONFIG_HOME/opencode/skills` (default `~/.config/opencode/skills`) | [OpenCode skills](https://opencode.ai/docs/skills/) |
  | `omp` | `~/.omp/agent/skills` | [omp skills](https://github.com/can1357/oh-my-pi/blob/main/docs/skills.md) |

- **Safe to re-run.** Each copy holds a `.skills-install.json` marker (plugin, skill, clone, tool, commit). Only folders with work's marker are ever replaced or removed; a `work-*` folder without one stops the install before anything is written. `--dry-run` shows what would change. `--update` refuses a clone with local changes (`--no-pull` re-renders without pulling). `--uninstall` removes the copies. A copy made with `--dest` is updated and removed with the same `--dest`.
- **Install from a clone.** It refuses a folder outside a git clone, such as Claude Code's plugin cache, because that folder moves on every update and the copies would point at nothing.
- **Never edits another tool's settings.** When a tool needs one, it prints it. Gemini CLI reads `GEMINI.md`, not `AGENTS.md`, unless `~/.gemini/settings.json` has `"context": {"fileName": ["AGENTS.md", "GEMINI.md"]}`.
- **The store.** It is the same `~/.work`, or `WORK_STORE`. Outside Claude Code, set `WORK_STORE` in your shell profile instead of `~/.claude/settings.json`. Allow rules for fewer permission prompts (below) are Claude Code's; other agents have their own approval settings.
- **Claude Code-only parts.** Where a skill names a Claude Code tool (`AskUserQuestion`), the same line says what to do elsewhere. The post-compaction checkpoint reminder is a Claude Code hook (`work/hooks/hooks.json`). Nothing depends on it: without it, `/work:resume` and `/work:new` tell the agent to run `/work:checkpoint` after each milestone and before its context fills.

### The checkpoint reminder in other agents (optional)

Codex and Gemini CLI have a hook event at compaction, so you can wire the reminder in yourself. `install-skills` prints these snippets with your clone's path filled in; it never writes them. Merge each into the tool's existing `hooks` block.

- **Codex**, in `~/.codex/hooks.json`. Codex runs `SessionStart` hooks with source `compact` right after it compacts, and adds their output to the model's context, as Claude Code does ([Codex hooks](https://learn.chatgpt.com/docs/hooks)). Review and trust the hook with `/hooks` before it runs.

  ```json
  {"hooks": {"SessionStart": [{"matcher": "^compact$", "hooks": [
    {"type": "command", "command": "sh \"/path/to/work-skills/work/scripts/work-tools\" nudge", "timeout": 10}]}]}}
  ```

- **Gemini CLI**, in `~/.gemini/settings.json`. Its `PreCompress` event fires before it compresses the history, but can only show a message to you, not the model ([Gemini CLI hooks](https://geminicli.com/docs/hooks/reference/)). When you see it, ask the agent to checkpoint. `nudge --json` prints the reminder as the `systemMessage` the hook expects.

  ```json
  {"hooks": {"PreCompress": [{"hooks": [
    {"type": "command", "name": "work-nudge", "command": "sh \"/path/to/work-skills/work/scripts/work-tools\" nudge --json", "timeout": 10000}]}]}}
  ```

- **OpenCode and omp** have no snippet. OpenCode's compaction hooks are JavaScript plugins, and its only one that adds context (`experimental.session.compacting`) feeds the summary rather than reminding afterwards ([OpenCode plugins](https://opencode.ai/docs/plugins/)). omp has `session_compact` extension events, but no documented hook config. Rely on the skill text there.

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

## Requirements

- Python 3.9 or later, as `python3`, `python` or `py -3`.
- `sh`: built in on macOS and Linux. On Windows it comes with Git for Windows, which Claude Code uses to run commands.
- git, with `user.name` and `user.email` set. Without them, `/work:new` still creates the store but can't commit, and says so.

## Fewer permission prompts

In Claude Code, the skills run the helper as `sh "<plugin>/scripts/work-tools" <subcommand>` and git as `git -C "<store>" <subcommand>`. To stop Claude Code asking each time, add allow rules in `/permissions`. A rule matches the command text as written, so keep the double quotes and use absolute paths, exactly as the permission prompt shows them (no `~`). On Windows that means forward slashes in the plugin path (`C:/Users/you/.claude/plugins/...`) and backslashes in the store path (`C:\Users\you\.work`).

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

The helper is `work/scripts/work.py` (standard library only). The skills and the hook run it through `work/scripts/work-tools`, which finds a Python. Its `install-skills` subcommand is the same mechanism as herdr-skills' (`render_skill`, `install_skills`, `SKILL_DIRS` and `SKILLS_MARKER`); keep the two in step, since `/herdr:retire` finds this plugin's launcher through a `work-*` copy's marker.

```sh
python -m pip install pytest
python -m pytest work/scripts/tests -q
```

CI runs the tests on Linux, macOS and Windows.

## License

MIT
