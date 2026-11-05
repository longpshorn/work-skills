"""Nightly memory consolidation ("dream") for work.py: config, paths and subcommand wiring."""

import copy
import datetime as dt
import json
import os
import re
import subprocess
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
        "dream-check": "validate the memory folder",
        "dream-run": "run one consolidation pass",
        "dream-status": "show the last run and the next gate",
        "dream-install": "install the nightly schedule",
    }
    parsers = {name: sub.add_parser(name, help=helps[name]) for name in COMMANDS}
    parsers["dream-gather"].add_argument("--since", help="ISO time bounding a first run (default: now minus first_run_days)")
    parsers["dream-gather"].add_argument("--out", help="digest folder (default: <state>/digests)")
    parsers["dream-check"].add_argument("--memory-dir", help="memory folder (default: the configured memory_dir)")
    return parsers


def run_command(args):
    if args.cmd == "dream-gather":
        return _gather_command(args)
    if args.cmd == "dream-status":
        return _status_command()
    if args.cmd == "dream-check":
        return _check_command(args)
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


OWN_MARKERS = ("[work-dream]", "[headless-job]")
FLAG_PATTERNS = {
    "correction": r"\b(?:no|don't|dont|that's wrong|actually|stop)\b",
    "confirmation": r"\b(?:yes exactly|perfect|that's right)\b",
    "remember": r"\bremember\b",
    "rule": r"\b(?:always|never|from now on)\b",
    "decision": r"\b(?:decided|let's go with|we'll use)\b",
}


def flag_text(text):
    """Heuristic annotations for a typed message; they never filter anything."""
    lowered = text.lower().replace("\u2019", "'")
    return [name for name, pattern in FLAG_PATTERNS.items() if re.search(pattern, lowered)]


def repo_of(cwd):
    """The main checkout of the repository holding cwd, or None."""
    if not cwd or not os.path.isdir(cwd):
        return None
    try:
        done = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-common-dir"], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = done.stdout.strip()
    if done.returncode != 0 or not out:
        return None
    common = (Path(cwd) / out).resolve()
    return str(common.parent if common.name == ".git" else common)


def _indent(text):
    return text.replace("\n", "\n  ")


def _reply_tag(text):
    verified = re.search(r"\bVerified\b", text) and re.search(r"`[^`\n]+`", text)
    return "[verified-outcome]" if verified else "[context-only]"


def _digest(header, turns, agent_session):
    lines = ["%s: %s" % pair for pair in header]
    for turn in turns:
        if turn.role == "claude":
            lines.append("[%s] %s CLAUDE-FINAL: %s" % (turn.uuid, _reply_tag(turn.text), _indent(turn.text)))
        elif not (agent_session and "agent_session" in turn.flags):
            flags = flag_text(turn.text)
            tag = " [%s]" % ",".join(flags) if flags else ""
            lines.append("[%s]%s USER: %s" % (turn.uuid, tag, _indent(turn.text)))
    return "\n".join(lines) + "\n"


def _is_own_run(turns):
    first = next((t for t in turns if t.role == "user"), None)
    return bool(first) and any(marker in first.text for marker in OWN_MARKERS)


def gather(highwater, since, now, out_dir, cfg):
    """Digest every ended conversation with new turns; returns one record per digest written."""
    idle = cfg["caps"]["idle_hours"] * 3600
    patterns = cfg.get("agent_prompts") or []
    results = []
    for path in sorted(projects_dir().glob("*/*.jsonl")):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        mark = highwater.get(str(path))
        if now.timestamp() - mtime < idle or mtime <= (mark["mtime"] if mark else since.timestamp()):
            continue
        turns, last_uuid = read_turns(path, None, patterns)
        if not turns or _is_own_run(turns):
            continue
        agent_session = turns[0].role == "user" and "agent_session" in turns[0].flags
        if mark and mark.get("uuid"):
            seen = [i for i, t in enumerate(turns) if t.uuid == mark["uuid"]]
            if seen:
                turns = turns[seen[0] + 1:]
        if not any(t.role == "user" and not (agent_session and "agent_session" in t.flags) for t in turns):
            continue
        cwd = next((t.cwd for t in turns if t.cwd), "")
        repo = repo_of(cwd)
        first, last = turns[0].timestamp, turns[-1].timestamp
        header = [("session", path.stem), ("project", path.parent.name), ("cwd", cwd or "none"),
                  ("repo", repo or "none"), ("span", "%s .. %s" % (first, last))]
        if agent_session:
            header.append(("agent-session", "yes"))
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / (path.stem + ".md")
        target.write_text(_digest(header, turns, agent_session), encoding="utf-8")
        results.append({"session": path.stem, "project": path.parent.name, "cwd": cwd or None, "repo": repo,
                        "digest": target.read_text(encoding="utf-8"), "path": str(target),
                        "last_uuid": last_uuid, "mtime": mtime, "first": first, "last": last,
                        "agent_session": agent_session})
    return results


def _gather_command(args):
    try:
        cfg = load_config()
    except ConfigError as exc:
        print("work.py: %s" % exc, file=sys.stderr)
        return 1
    now = dt.datetime.now()
    raw = args.since.replace("Z", "+00:00") if args.since else None
    since = dt.datetime.fromisoformat(raw) if raw else now - dt.timedelta(days=cfg["caps"]["first_run_days"])
    out_dir = Path(args.out) if args.out else state_dir() / "digests"
    print(json.dumps(gather({}, since, now, out_dir, cfg), indent=2))
    return 0


def default_state():
    return {"version": 1, "transcripts": {}, "last_run": None, "last_success": None,
            "reorganized": False, "open_mrs": {}, "pending_pushes": []}


def load_state():
    path = state_dir() / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state is not an object")
    except FileNotFoundError:
        return default_state()
    except (OSError, ValueError):
        try:
            os.replace(str(path), str(path) + ".bad")
        except OSError:
            pass
        return default_state()
    return _merge(default_state(), data)


def save_state(state):
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / "state.json.tmp"
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(str(temp), str(directory / "state.json"))


class Busy(Exception):
    pass


def _lock_file(fd):
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(fd):
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


class RunLock:
    """Single-run lock: an OS advisory lock on a file the kernel frees when the holder dies."""

    def __enter__(self):
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "lock"
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT)
        try:
            _lock_file(fd)
        except OSError:
            os.close(fd)
            raise Busy(str(path))
        self.fd = fd
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(self, *exc):
        try:
            _unlock_file(self.fd)
        finally:
            os.close(self.fd)
        return False


def log_line(date, read, counts, mrs, ok, reason=None):
    tally = " ".join("%s=%d" % (key, counts.get(key, 0)) for key in ("added", "updated", "retired", "promoted"))
    outcome = "ok" if ok else "failed: %s" % reason
    return "%s | read=%d | %s | mrs=%s | %s" % (date.isoformat(), read, tally, " ".join(mrs) or "-", outcome)


def append_log(line):
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with open(str(directory / "run.log"), "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _last_log_line():
    try:
        lines = (state_dir() / "run.log").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return next((line for line in reversed(lines) if line.strip()), None)


def dream_status(today):
    """One line when the last run failed or no run succeeded for 3 days; None when healthy or never run."""
    last = _last_log_line()
    if last is None:
        return None
    failed = re.search(r"\| failed: (.*)$", last)
    if failed:
        return "dream: last run failed (%s)" % failed.group(1)
    success = load_state().get("last_success")
    try:
        days = (today - dt.date.fromisoformat(success)).days
    except (TypeError, ValueError):
        return None
    return "dream: no successful run in %d days" % days if days >= 3 else None


def _status_command():
    line = dream_status(dt.date.today())
    if line:
        print(line)
    return 0


class FrontmatterError(ValueError):
    pass


def _scalar(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
    return raw.strip("\"'")


def parse_memory(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("missing frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise FrontmatterError("unterminated frontmatter")
    meta = {}
    nested = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        if line[0] in " \t" and nested is not None:
            nested[key.strip()] = _scalar(value)
        elif not value.strip():
            nested = meta[key.strip()] = {}
        else:
            nested = None
            meta[key.strip()] = _scalar(value)
    return meta


_INDEX_LINE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<file>[^)]+\.md)\)")


def _front(path, problems, label):
    try:
        return parse_memory(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append("%s: %s" % (label, exc))
        return None


def _check_live(meta, label, problems):
    for field_name in ("name", "description"):
        if not meta.get(field_name):
            problems.append("%s: missing %s" % (label, field_name))
    inner = meta.get("metadata")
    if not ((isinstance(inner, dict) and inner.get("type")) or meta.get("type")):
        problems.append("%s: missing metadata.type" % label)
    if "promoted_to" in meta and not (isinstance(meta["promoted_to"], str) and meta["promoted_to"]):
        problems.append("%s: promoted_to must be a non-empty string" % label)


def check_memory(memory_dir, caps):
    problems = []
    live = sorted(p.name for p in memory_dir.glob("*.md") if p.name != "MEMORY.md")
    for name in live:
        meta = _front(memory_dir / name, problems, name)
        if meta is not None:
            _check_live(meta, name, problems)
    retired = sorted((memory_dir / "_retired").glob("*.md"))
    for path in retired:
        label = "_retired/" + path.name
        meta = _front(path, problems, label)
        if meta is None:
            continue
        for field_name in ("superseded_by", "retired"):
            if not meta.get(field_name):
                problems.append("%s: missing %s" % (label, field_name))
    try:
        raw = (memory_dir / "MEMORY.md").read_bytes()
    except OSError:
        return problems + ["MEMORY.md: missing"]
    index_lines = raw.decode("utf-8", "replace").splitlines()
    if len(index_lines) > caps["index_lines"]:
        problems.append("MEMORY.md: %d lines exceeds %d" % (len(index_lines), caps["index_lines"]))
    if len(raw) > caps["index_bytes"]:
        problems.append("MEMORY.md: %d bytes exceeds %d" % (len(raw), caps["index_bytes"]))
    indexed = set()
    for line in index_lines:
        match = _INDEX_LINE.match(line)
        if not match:
            continue
        target = match.group("file")
        if target.startswith("_retired/"):
            problems.append("MEMORY.md: retired file %s is still indexed" % target)
        elif target not in live:
            problems.append("MEMORY.md: index line points to missing file %s" % target)
        else:
            indexed.add(target)
    for name in live:
        if name not in indexed:
            problems.append("%s: no index line in MEMORY.md" % name)
    return problems



class UnsafePath(ValueError):
    pass


class TooLong(ValueError):
    pass


def safe_path(root, rel):
    if not isinstance(rel, str) or not rel.strip():
        raise UnsafePath("empty path")
    flat = rel.replace("\\", "/")
    if flat.startswith("/") or re.match(r"^[A-Za-z]:", flat) or Path(rel).is_absolute():
        raise UnsafePath("absolute path: %s" % rel)
    if ".." in flat.split("/"):
        raise UnsafePath("path escapes its root: %s" % rel)
    base = root.resolve()
    full = (base / rel).resolve()
    try:
        full.relative_to(base)
    except ValueError:
        raise UnsafePath("path resolves outside its root: %s" % rel)
    if full == base:
        raise UnsafePath("path is the root itself: %s" % rel)
    return full


_INSTRUCTION_FILES = ("claude.md", "agents.md")
_LINK = re.compile(r"\]\(([^)]*)\)")
_BARE_MD = re.compile(r"^[^/\\]+\.md$")


def _read(path):
    return path.read_bytes().decode("utf-8")


def _put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _single_line(value, what):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be one non-empty line" % what)
    if len(value.splitlines()) != 1 or not value.isprintable():
        raise ValueError("%s must be one printable line" % what)


def _stamp(text, fields):
    lines = text.split("\n")
    parse_memory(text)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    keys = tuple(k + ":" for k in fields)
    kept = [l for l in lines[1:end] if not l.startswith(keys)]
    stamped = ["%s: %s" % (k, v) for k, v in fields.items()]
    return "\n".join([lines[0]] + kept + stamped + lines[end:])


def _not_dir(full, rel):
    if full.is_dir():
        raise ValueError("write op names a directory: %s" % rel)
    return full


def _write_path(op, memory_dir, target_root, caps):
    """Resolve and vet a write op; raises before any byte is written."""
    if op.get("root") not in ("memory", "target"):
        raise ValueError("write op needs root memory or target")
    if not isinstance(op.get("content"), str):
        raise ValueError("write op needs string content")
    rel = op.get("path")
    base = memory_dir if op["root"] == "memory" else target_root
    if base is None:
        raise ValueError("write op names a target root but none is available")
    full = safe_path(base, rel)
    if op["root"] == "memory":
        if any(part.startswith(".") for part in rel.replace("\\", "/").split("/")):
            raise UnsafePath("hidden path segment: %s" % rel)
        return _not_dir(full, rel)
    if rel.replace("\\", "/").split("/")[-1].casefold() not in _INSTRUCTION_FILES:
        raise UnsafePath("target writes are limited to CLAUDE.md and AGENTS.md: %s" % rel)
    if (base.resolve() / rel).is_symlink():
        raise UnsafePath("instruction file is a symlink: %s" % rel)
    if len(op["content"].splitlines()) > caps["claude_md_lines"]:
        raise TooLong("%s would exceed %d lines" % (rel, caps["claude_md_lines"]))
    return _not_dir(full, rel)


def _retire_path(op, memory_dir):
    full = safe_path(memory_dir, op.get("path"))
    if (
        full.parent != memory_dir.resolve()
        or full.suffix.casefold() != ".md"
        or full.name.casefold() == "memory.md"
    ):
        raise ValueError("retire op needs a live memory file: %s" % op.get("path"))
    if op["path"].replace("\\", "/").split("/")[0].casefold() == "_retired":
        raise ValueError("already retired: %s" % op["path"])
    return full


def _validate_ops(ops, memory_dir, target_root, caps):
    """Vet every op, or raise before anything is written."""
    written = {}
    retired = set()
    for op in ops:
        if not isinstance(op, dict):
            raise ValueError("op must be an object")
        kind = op.get("op")
        if kind == "write":
            full = _write_path(op, memory_dir, target_root, caps)
            if op["root"] == "memory":
                written[full] = op["content"]
        elif kind == "retire":
            full = _retire_path(op, memory_dir)
            _single_line(op.get("superseded_by"), "superseded_by")
            if full.name.casefold() in retired:
                raise ValueError("retired twice: %s" % full.name)
            if safe_path(memory_dir, "_retired/" + full.name).exists():
                raise ValueError("already retired: %s" % full.name)
            if full in written:
                text = written[full]
            elif full.is_file():
                try:
                    text = _read(full)
                except (OSError, ValueError) as exc:
                    raise ValueError("cannot read %s: %s" % (full.name, exc))
            else:
                raise ValueError("retire op names a missing file: %s" % op["path"])
            parse_memory(text)
            retired.add(full.name.casefold())
        elif kind == "index":
            _single_line(op.get("section"), "section")
            _single_line(op.get("line"), "line")
            for link in _LINK.findall(op["line"]):
                if not _BARE_MD.match(link) or ".." in link:
                    raise ValueError("index line may link only to a bare .md name: %s" % link)
        else:
            raise ValueError("unknown op: %r" % (kind,))


def _insert_in_section(text, section, line):
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    heading = "## " + section.strip()
    start = next((i for i, l in enumerate(lines) if l.strip() == heading), None)
    if start is None:
        return "\n".join(lines + ([""] if lines else []) + [heading, line]) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, line)
    return "\n".join(lines) + "\n"


def _drop_index_line(text, name):
    needle = "](%s)" % name
    return "".join(l for l in text.splitlines(True) if needle not in l)


def apply_ops(ops, memory_dir, target_root, today, caps):
    _validate_ops(ops, memory_dir, target_root, caps)
    touched = []
    index_path = safe_path(memory_dir, "MEMORY.md")
    for op in ops:
        if op["op"] == "write":
            _put(_write_path(op, memory_dir, target_root, caps), op["content"])
            touched.append(op["path"])
        elif op["op"] == "retire":
            full = _retire_path(op, memory_dir)
            dest = safe_path(memory_dir, "_retired/" + full.name)
            fields = {"superseded_by": op["superseded_by"], "retired": today.isoformat()}
            _put(dest, _stamp(_read(full), fields))
            full.unlink()
            if index_path.is_file():
                _put(index_path, _drop_index_line(_read(index_path), full.name))
            touched.append(op["path"])
        else:
            current = _read(index_path) if index_path.is_file() else ""
            _put(index_path, _insert_in_section(current, op["section"], op["line"]))
            touched.append("MEMORY.md")
    return touched


def mark_promoted(memory_dir, memory_rel, promoted_to):
    path = safe_path(memory_dir, memory_rel)
    text = _read(path)
    if "promoted_to" in parse_memory(text):
        return
    _single_line(promoted_to, "promoted_to")
    _put(path, _stamp(text, {"promoted_to": promoted_to}))


def _check_command(args):
    if args.memory_dir:
        memory_dir, caps = Path(args.memory_dir), DEFAULTS["caps"]
    else:
        try:
            cfg = load_config()
        except ConfigError as exc:
            print("work.py: %s" % exc, file=sys.stderr)
            return 1
        memory_dir, caps = cfg["memory_dir"], cfg["caps"]
    problems = check_memory(memory_dir, caps)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0
