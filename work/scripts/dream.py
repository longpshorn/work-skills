"""Nightly memory consolidation ("dream") for work.py: config, paths and subcommand wiring."""

import copy
import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "models": {"extract": "sonnet", "check": "opus"},
    "caps": {
        "index_lines": 150,
        "index_bytes": 18432,
        "claude_md_lines": 200,
        "promotions": 5,
        "min_conversations": 3,
        "idle_hours": 2,
        "first_run_days": 14,
        "turns_extract": 60,
        "turns_check": 6,
    },
    "schedule": {"hour": 2, "minute": 0},
    "repos": [],
    "agent_prompts": [],
    "claude_bin": "claude",
}

COMMANDS = ("dream-gather", "dream-check", "dream-run", "dream-status", "dream-install")


class ConfigError(Exception):
    pass


def _env_path(name, default):
    return Path(os.path.expanduser(os.environ.get(name, default)))


def config_path():
    return _env_path("WORK_DREAM_CONFIG", "~/.config/work/dream.json")


def state_dir():
    return _env_path("WORK_DREAM_STATE", "~/.local/state/work-dream")


def projects_dir():
    return _env_path("WORK_DREAM_PROJECTS", "~/.claude/projects")


def strip_comments(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def _read_json(path, what):
    try:
        return json.loads(strip_comments(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {what} {path}: {exc}")


def _merge(base, over):
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _settings_memory_dir():
    path = Path(os.path.expanduser("~/.claude/settings.json"))
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("autoMemoryDirectory")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None


def load_config():
    cfg = copy.deepcopy(DEFAULTS)
    path = config_path()
    if path.is_file():
        _merge(cfg, _read_json(path, "config"))
    memory_dir = cfg.get("memory_dir") or _settings_memory_dir()
    if not memory_dir:
        raise ConfigError(
            f"no memory folder: set memory_dir in {path} or autoMemoryDirectory in ~/.claude/settings.json")
    cfg["memory_dir"] = Path(os.path.expanduser(memory_dir))
    cfg["global_claude_md"] = Path(os.path.expanduser(cfg.get("global_claude_md") or "~/.claude/CLAUDE.md"))
    return cfg


def add_parsers(sub):
    helps = {
        "dream-gather": "digest recent ended conversations and the current memory",
        "dream-check": "verify one memory claim against the code",
        "dream-run": "run one consolidation pass",
        "dream-status": "show the last run and the next gate",
        "dream-install": "install the nightly schedule",
    }
    return {name: sub.add_parser(name, help=helps[name]) for name in COMMANDS}


def run_command(args):
    print(f"work.py: {args.cmd} is not implemented yet", file=sys.stderr)
    return 2
