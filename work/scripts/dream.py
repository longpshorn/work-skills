"""Nightly memory consolidation ("dream") for work.py: config, paths and subcommand wiring."""

import copy
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

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


@dataclass
class Turn:
    uuid: str
    session: str
    cwd: str
    timestamp: str
    role: str
    text: str
    flags: List[str] = field(default_factory=list)


STRIPPED_BLOCKS = ("pasted_content", "system-reminder", "task-notification", "agent-message")
NON_TYPED_PREFIXES = ("<command-name>", "<command-message>", "<local-command-", "<bash-input>",
                      "<bash-stdout>", "<bash-stderr>", "<user-prompt-submit-hook>")
NON_TYPED_ANYWHERE = ("<artifact-content-authored-by-others",)
BLOCK_RES = [re.compile(r"<\s*%s\b[^>]*>.*?(?:<\s*/\s*%s\s*>|\Z)" % (tag, tag), re.DOTALL | re.IGNORECASE)
             for tag in STRIPPED_BLOCKS]
LEFTOVER_TAG_RE = re.compile(r"<\s*/?\s*(?:%s)\b" % "|".join(STRIPPED_BLOCKS), re.IGNORECASE)


def _text_blocks(content):
    """The text of a message's content, or None when it holds anything but typed text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") == "tool_result":
            return None
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return " ".join(parts)


def user_text(entry, agent_patterns):
    """The user's own typed text and whether it opens an agent session, or None for anything else."""
    if entry.get("type") != "user" or entry.get("isSidechain"):
        return None
    if entry.get("isMeta") or entry.get("isCompactSummary") or "toolUseResult" in entry:
        return None
    message = entry.get("message")
    raw = _text_blocks(message.get("content")) if isinstance(message, dict) else None
    if raw is None:
        return None
    for pattern in BLOCK_RES:
        raw = pattern.sub("", raw)
    text = raw.strip()
    lowered = text.lower()
    if (not text or lowered.startswith(NON_TYPED_PREFIXES) or any(t in lowered for t in NON_TYPED_ANYWHERE)
            or LEFTOVER_TAG_RE.search(text)):
        return None
    return text, any(re.search(p, text) for p in agent_patterns)


def final_reply(entries):
    """(uuid, text) of the turn's last assistant message, when it holds text and no tool call."""
    groups = []
    for entry in entries:
        message = entry.get("message")
        if entry.get("type") != "assistant" or entry.get("isSidechain") or not isinstance(message, dict):
            continue
        blocks = message.get("content")
        blocks = [b for b in blocks if isinstance(b, dict)] if isinstance(blocks, list) else []
        msg_id = message.get("id")
        if groups and groups[-1][0] == msg_id:
            groups[-1][1].append((entry, blocks))
        else:
            groups.append((msg_id, [(entry, blocks)]))
    groups = [g for g in groups if any(b.get("type") in ("text", "tool_use") for _, bs in g[1] for b in bs)]
    if not groups:
        return None
    lines = groups[-1][1]
    if any(b.get("type") == "tool_use" for _, bs in lines for b in bs):
        return None
    texts = [(e, b["text"]) for e, bs in lines for b in bs
             if b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip()]
    if not texts:
        return None
    return texts[-1][0].get("uuid"), "\n".join(t for _, t in texts).strip()


def _json_lines(path):
    """Parsed lines of a transcript; bad lines are skipped, a truncated last line ends reading."""
    pieces = path.read_text(encoding="utf-8", errors="replace").split("\n")
    for index, piece in enumerate(pieces):
        if not piece.strip():
            continue
        try:
            entry = json.loads(piece)
        except ValueError:
            if index == len(pieces) - 1:
                return
            continue
        if isinstance(entry, dict):
            yield entry


def read_turns(path, after_uuid, agent_patterns):
    """Turns after after_uuid (all when None or unknown) and the last turn's uuid."""
    turns = []
    pending = []

    def flush():
        reply = final_reply(pending)
        if reply:
            turns.append(Turn(reply[0], pending[-1].get("sessionId", ""), pending[-1].get("cwd") or "",
                              pending[-1].get("timestamp", ""), "claude", reply[1]))
        pending.clear()

    for entry in _json_lines(path):
        typed = user_text(entry, agent_patterns)
        if typed:
            flush()
            turns.append(Turn(entry.get("uuid", ""), entry.get("sessionId", ""), entry.get("cwd") or "",
                              entry.get("timestamp", ""), "user", typed[0],
                              ["agent_session"] if typed[1] else []))
        elif entry.get("type") == "assistant":
            pending.append(entry)
    flush()
    last = turns[-1].uuid if turns else None
    if after_uuid:
        seen = [i for i, t in enumerate(turns) if t.uuid == after_uuid]
        if seen:
            turns = turns[seen[0] + 1:]
    return turns, last
