# work-skills

Claude Code skills for keeping track of ongoing work across sessions. Each workstream gets one status file (what was asked, where it stands, the single next step, and a dated log), so a fresh session can pick up exactly where the last one stopped.

| Command | What it does |
| - | - |
| `/work:new <area>/<name>` | Start tracking a workstream. On a machine with no store yet, it creates one first. |
| `/work:resume [name]` | Find a workstream (by name, or by the repo you're in), check what changed since last time, and brief you on the next step. Read-only. |
| `/work:checkpoint` | Log this session's decisions and results, update the next step, and commit, without ending the session. |
| `/work:wrap` | Checkpoint, surface loose ends (uncommitted work, changed sources), propose memory updates, archive the workstream if it's done, and hand back the resume command. |
| `/work:standup` | Every workstream at a glance: blocked, stale, loose ends, and the top five next steps. |

After Claude Code compacts a conversation, the plugin reminds the session to run `/work:checkpoint`.

## Install

```sh
claude plugin marketplace add longpshorn/work-skills
claude plugin install work@work-skills
```

Then restart Claude Code. Your first `/work:new` creates the store.

## Where your notes live

The store is a folder of Markdown files with its own local git history, on branch `log` and with no remote. It stays on the machine; the plugin never pushes it anywhere. Its `README.md` explains the file format.

The store is `~/.work` unless you choose another folder. To use another folder, set `WORK_STORE` in the `env` block of `~/.claude/settings.json`, so every Claude Code session, the hook and the helper see it:

```json
{
  "env": {
    "WORK_STORE": "/absolute/path/to/your/notes"
  }
}
```

`/work:resume` and `/work:wrap` check the repos a workstream lists for uncommitted or unpushed work. If some of your repos live on a mount where git is slow or wrong to run (a virtual machine's shared folder, for example), set `WORK_VM_ROOT` to that mount. Repos under it are then flagged instead of checked.

## Requirements

- Python 3.9 or later, as `python3`, `python` or `py -3`.
- `sh`: built in on macOS and Linux. On Windows it comes with Git for Windows, which Claude Code uses to run commands.
- git, with `user.name` and `user.email` set. Without them, `/work:new` still creates the store but can't commit, and says so.

## Fewer permission prompts

The skills run the helper and git in the store. To stop Claude Code asking each time, allow both in `/permissions`. Use the plugin's real path (in `~/.claude/plugins/installed_plugins.json`) and your store's path:

```
Bash(sh <plugin path>/scripts/work-tools:*)
Bash(git -C <store path>:*)
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
