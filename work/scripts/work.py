#!/usr/bin/env python3
"""Work-store helper for the work plugin: /work:resume, :checkpoint, :wrap, :new and :standup.

Store layout and header rules: the store's README.md. The store is WORK_STORE, or ~/.work.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

STATES = ("idea", "scoped", "active", "blocked", "review", "done")
ARCHIVED_STATUS = "deprecated"
REQUIRED = ("title", "state", "next", "updated")
ACTOR = "process:work-tools"
TYPES = {"status file": "workstream", "AREA.md": "area", "README.md": "guide"}
INDEX = "index.md"
LOG = "log.md"
RESERVED = (INDEX, LOG)
OKF_VERSION = "0.2"
STALE_DAYS = 14
GIT_TIMEOUT = 10
IDENTITY_ONLY = ("-c", "user.useConfigOnly=true")
NUDGE = ("Context was just compacted. If this session touched a tracked "
         "workstream, run /work:checkpoint now from the summary.")


class HeaderError(ValueError):
    pass


@dataclass
class Workstream:
    area: str
    path: Path
    meta: dict

    @property
    def slug(self):
        return self.path.stem

    @property
    def name(self):
        return re.sub(r"^\d+-", "", self.slug)

    @property
    def key(self):
        return f"{self.area}/{self.slug}"


def store_root():
    return abspath(os.environ.get("WORK_STORE", "~/.work"))


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def strip_comment(raw):
    opener = re.match(r"[^:]*:\s*(['\"])", raw)
    for match in re.finditer(r"\s{2,}#", raw):
        head = raw[:match.start()]
        if not opener or head.count(opener.group(1)) % 2 == 0:
            return head
    return raw


def parse_generated(value):
    """OKF's generated: { by: <actor>, at: <ISO 8601 datetime with a UTC offset> }, as a dict."""
    if not (isinstance(value, str) and value.startswith("{") and value.endswith("}")):
        raise HeaderError(f"bad generated {value!r}")
    pairs = dict(part.partition(":")[::2] for part in value[1:-1].split(",") if part.strip())
    generated = {k.strip(): unquote(v.strip()) for k, v in pairs.items()}
    if not generated.get("by"):
        raise HeaderError(f"bad generated {value!r}")
    if "at" in generated:
        try:
            at = dt.datetime.fromisoformat(re.sub(r"Z$", "+00:00", generated["at"]))
        except ValueError:
            at = None
        if at is None or at.tzinfo is None:
            raise HeaderError(f"bad generated {value!r}")
        generated["at"] = at
    return generated


def parse_header(text):
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        raise HeaderError("missing front-matter")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise HeaderError("unterminated front-matter")
    meta = {}
    for number, raw in enumerate(lines[1:end], start=2):
        line = strip_comment(raw).strip()
        if not line:
            continue
        match = re.match(r"([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not match:
            raise HeaderError(f"line {number}: expected 'key: value'")
        key, value = match.group(1), match.group(2).strip()
        if value.startswith("["):
            if not value.endswith("]"):
                raise HeaderError(f"line {number}: unterminated list")
            meta[key] = [unquote(v.strip()) for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key] = unquote(value)
    if "state" not in meta and meta.get("status") in STATES:
        meta["state"] = meta.pop("status")
    missing = [k for k in REQUIRED if not meta.get(k)]
    if missing:
        raise HeaderError("missing " + ", ".join(missing))
    if meta["state"] not in STATES:
        raise HeaderError(f"bad state {meta['state']!r}")
    if meta.get("type", TYPES["status file"]) != TYPES["status file"]:
        raise HeaderError(f"bad type {meta['type']!r}")
    try:
        meta["updated"] = dt.date.fromisoformat(meta["updated"])
    except ValueError:
        raise HeaderError(f"bad updated {meta['updated']!r}") from None
    if "generated" in meta:
        meta["generated"] = parse_generated(meta["generated"])
    report = meta.get("report", "true")
    if report not in ("true", "false"):
        raise HeaderError(f"bad report {report!r}")
    meta["report"] = report == "true"
    for key in ("repos", "artifacts"):
        value = meta.get(key, [])
        values = [value] if isinstance(value, str) else value
        meta[key] = [v for v in values if v]
    return meta


def load_store(root):
    items, errors = [], []
    areas = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    for area in areas:
        for path in sorted(area.glob("*.md")):
            if path.name == "AREA.md" or path.name.lower() in RESERVED:
                continue
            try:
                meta = parse_header(path.read_text(encoding="utf-8"))
            except HeaderError as e:
                errors.append((path, str(e)))
                continue
            items.append(Workstream(area.name, path, meta))
    return items, errors


def cmd_nudge(as_json=False):
    """The post-compaction reminder, if the store exists. --json wraps it as a Gemini CLI hook's systemMessage."""
    if store_root().is_dir():
        print(json.dumps({"systemMessage": NUDGE}) if as_json else NUDGE)
    return 0


def link_text(text):
    return str(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def link(text, target):
    return f"[{link_text(text)}]({quote(target, safe='/')})"


def render_index(root, items, errors, today):
    """The store's OKF index.md (spec section 8): a section per area, one linked entry per workstream,
    led by its description."""
    out = ["---", f'okf_version: "{OKF_VERSION}"', "---", ""]
    for area in sorted({w.area for w in items}):
        out += [f"# {area}", ""]
        for w in items:
            if w.area != area:
                continue
            m = w.meta
            age = (today - m["updated"]).days
            flag = " ⚠ stale" if age >= STALE_DAYS and m["state"] != "done" else ""
            state = m["state"] if m["report"] else f"{m['state']} · off-report"
            facts = [m["description"]] if m.get("description") else []
            facts += [state, m["next"], f"{m['updated']} ({age}d){flag}"]
            out.append(f"* {link(m['title'], f'{w.area}/{w.path.name}')} - {' · '.join(facts)}")
        out.append("")
    if errors:
        out += ["# Errors", ""]
        for path, msg in errors:
            name = path.relative_to(root).as_posix()
            out.append(f"* {link(name, name)} - {msg}")
        out.append("")
    return "\n".join(out)


LOG_LINE = re.compile(r"[-*]\s+(\d{4}-\d{2}-\d{2})\s+·\s+(.*\S)")
HEADING = re.compile(r"(#{1,2})\s+(.*?)\s*$")


def log_entries(text):
    """(date, fact) for each well-formed `- YYYY-MM-DD · <fact>` line under `## Log`, in file order."""
    entries, in_log = [], False
    for line in text.lstrip("\ufeff").splitlines():
        heading = HEADING.match(line)
        if heading:
            in_log = heading.group(1) == "##" and heading.group(2) == "Log"
            continue
        match = LOG_LINE.fullmatch(line.strip()) if in_log else None
        if match:
            try:
                entries.append((dt.date.fromisoformat(match.group(1)), match.group(2)))
            except ValueError:
                pass
    return entries


def render_log(root, items):
    """The store's OKF log.md (spec section 9): every workstream Log line under its date, newest first."""
    by_date = {}
    for target, w in sorted((w.path.relative_to(root).as_posix(), w) for w in items):
        for day, fact in reversed(log_entries(w.path.read_text(encoding="utf-8"))):
            by_date.setdefault(day, []).append(f"* {link(w.meta['title'], target)}: {fact}")
    out = ["# Work store log"]
    for day in sorted(by_date, reverse=True):
        out += ["", f"## {day}", "", *by_date[day]]
    return "\n".join(out) + "\n"


def git_tracks(root, name):
    return (root / ".git").exists() and git(root, "ls-files", "--error-unmatch", name)[0] == 0


def retire_legacy_index(root):
    """Rename an index.md spelled in another case (the pre-OKF INDEX.md) so git records the new name.

    macOS and Windows treat both spellings as one file, so a plain rename leaves git tracking the old one.
    """
    for legacy in [p for p in root.iterdir() if p.name.lower() == INDEX and p.name != INDEX]:
        tracked = git_tracks(root, legacy.name)
        if any(p.name == INDEX for p in root.iterdir()):
            if tracked:
                git(root, "rm", "-q", "--cached", legacy.name)
            legacy.unlink()
        elif tracked:
            git(root, "mv", "-f", legacy.name, INDEX)
        else:
            os.replace(legacy, root / INDEX)


KEY = re.compile(r"\s*([A-Za-z_][\w-]*):")
PURPOSE = re.compile(r"^\*\*Purpose:\*\*\s*(.+?)\s*$", re.M)


def yaml_scalar(text):
    """TEXT as a YAML scalar: plain, or double-quoted where plain YAML would misread it."""
    if re.search(r"^[-?:,\[\]{}#&*!|>'\"%@`]|: |\s#|:$", text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def front_matter(lines):
    """(index of the closing ---, {key: index of its first line}) for LINES, or None without a complete block."""
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return None
    keys = {}
    for i in range(1, end):
        match = KEY.match(lines[i])
        if match:
            keys.setdefault(match.group(1), i)
    return end, keys


def upgraded(text, kind, archived=False):
    """TEXT with the OKF type for KIND added, a legacy status key renamed to state, an AREA.md's
    **Purpose:** line copied to its description and, when ARCHIVED, a workstream's missing OKF status
    set to ARCHIVED_STATUS; nothing else changes."""
    bom = "﻿" if text.startswith("﻿") else ""
    lines = text[len(bom):].splitlines(keepends=True)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    if not lines or lines[0].strip() != "---":
        if kind == "status file":
            return text
        lines = [f"---{newline}", f"---{newline}", newline] + lines
    block = front_matter(lines)
    if block is None:
        return text
    end, keys = block
    if kind == "AREA.md" and "description" not in keys:
        purpose = PURPOSE.search("".join(lines[end + 1:]))
        if purpose:
            lines.insert(end, f"description: {yaml_scalar(purpose.group(1))}{newline}")
    if kind == "status file" and "state" not in keys and "status" in keys:
        i = keys["status"]
        value = unquote(strip_comment(lines[i]).split(":", 1)[1].strip())
        if value in STATES:
            lines[i] = lines[i].replace("status", "state", 1)
            keys["state"] = keys.pop("status")
    if kind == "status file" and archived and "status" not in keys:
        lines.insert(keys["state"] + 1 if "state" in keys else end, f"status: {ARCHIVED_STATUS}{newline}")
    if "type" not in keys:
        lines.insert(1, f"type: {TYPES[kind]}{newline}")
    return bom + "".join(lines)


def with_value(line, value):
    """LINE, a 'key: value' header line, holding VALUE instead; its comment and line ending stay."""
    head = strip_comment(line.rstrip("\r\n"))
    return f"{head.split(':', 1)[0]}: {value}{line[len(head):]}"


def stamped(text, now):
    """TEXT with updated set to NOW's date and generated to { by: ACTOR, at: NOW }; nothing else changes."""
    bom = "﻿" if text.startswith("﻿") else ""
    lines = text[len(bom):].splitlines(keepends=True)
    block = front_matter(lines)
    if block is None:
        raise HeaderError("missing front-matter")
    end, keys = block
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    values = {"updated": now.date().isoformat(), "generated": f"{{ by: {ACTOR}, at: {now.isoformat()} }}"}
    for key, value in values.items():
        if key in keys:
            lines[keys[key]] = with_value(lines[keys[key]], value)
        else:
            at = keys["updated"] + 1 if "updated" in keys else end
            lines.insert(at, f"{key}: {value}{newline}")
            keys[key], end = at, end + 1
    return bom + "".join(lines)


def cmd_touch(root, args):
    path = root / f"{args.key}.md"
    if not path.is_file():
        print(f"work.py: no workstream {args.key!r}", file=sys.stderr)
        return 3
    now = args.now or dt.datetime.now().astimezone().replace(microsecond=0)
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    try:
        new = stamped(text, now)
    except HeaderError as e:
        print(f"{args.key}: {e}", file=sys.stderr)
        return 1
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return 0


def upgrade_file(path, kind, archived=False):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    new = upgraded(text, kind, archived)
    if new != text:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)


def upgrade_store(root):
    """Give every store file its OKF type, and archived workstreams their status, with no migration needed."""
    if (root / "README.md").is_file():
        upgrade_file(root / "README.md", "README.md")
    archive = root / "_archive"
    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))]
    folders += [p for p in archive.iterdir() if p.is_dir()] if archive.is_dir() else []
    for folder in folders:
        for path in sorted(folder.glob("*.md")):
            if path.name.lower() not in RESERVED:
                upgrade_file(path, "AREA.md" if path.name == "AREA.md" else "status file",
                             archived=folder.parent == archive)


def cmd_index(root, args):
    upgrade_store(root)
    items, errors = load_store(root)
    retire_legacy_index(root)
    (root / INDEX).write_text(render_index(root, items, errors, args.today), encoding="utf-8")
    archived = load_store(root / "_archive")[0] if (root / "_archive").is_dir() else []
    (root / LOG).write_text(render_log(root, items + archived), encoding="utf-8")
    for path, msg in errors:
        print(f"{path.relative_to(root).as_posix()}: {msg}", file=sys.stderr)
    return 1 if errors else 0


def cmd_list(root, args):
    items, _ = load_store(root)
    for w in items:
        print(f"{w.key} · {w.meta['state']} · {w.meta['next']}")
    return 0


def abspath(path):
    return Path(os.path.abspath(os.path.expanduser(path)))


def find(items, query=None, cwd=None):
    if query:
        q = query.lower()
        exact = [w for w in items if q in (w.key.lower(), w.slug.lower(), w.name.lower())]
        if exact:
            return exact
        area = [w for w in items if w.area.lower() == q]
        if area:
            return area
        return [w for w in items if q in w.slug.lower() or q in w.meta["title"].lower()]
    here = abspath(cwd)
    return [w for w in items
            if any(r == here or r in here.parents for r in map(abspath, w.meta["repos"]))]


def cmd_find(root, args):
    items, _ = load_store(root)
    cwd = args.cwd or os.getcwd()
    hits = find(items, args.query, None if args.query else cwd)
    if len(hits) == 1:
        print(hits[0].path)
        return 0
    if hits:
        print("\n".join(w.key for w in hits))
        return 2
    print(f"work.py: no workstream matches {args.query or cwd!r}", file=sys.stderr)
    return 3


LINK = re.compile(r"(?:(?<=[`(\s])|^)((?:~?/|[A-Za-z]:[\\/])[^\s`)\]>\"']+)", re.M)


def vm_root():
    """A mount whose repos drift must not run git on (a VM's shared folder, say); none unless WORK_VM_ROOT is set."""
    value = os.environ.get("WORK_VM_ROOT")
    return abspath(value) if value else None


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            timeout=GIT_TIMEOUT)
    return result.returncode, result.stdout


def repo_issue(written):
    repo, vm = abspath(written), vm_root()
    if vm and (repo == vm or vm in repo.parents):
        return f"{written}: on a mount set by WORK_VM_ROOT — check it there"
    if not repo.exists():
        return f"{written}: MISSING"
    try:
        return git_state(repo, written)
    except subprocess.TimeoutExpired:
        return f"{written}: git timed out"


def git_state(repo, written):
    rc, out = git(repo, "status", "--porcelain")
    if rc:
        return f"{written}: not a git repo"
    dirty = sum(1 for line in out.splitlines() if line.strip())
    rc, out = git(repo, "rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if rc:
        return f"{written}: {dirty} uncommitted, no upstream" if dirty else None
    behind, ahead = map(int, out.split())
    if not (dirty or ahead or behind):
        return None
    return f"{written}: {dirty} uncommitted, {ahead} ahead, {behind} behind"


def modified(path):
    if path.is_file():
        return path.stat().st_mtime
    if path.is_dir():
        files = [p for p in path.iterdir() if p.is_file() and not p.name.startswith(".")]
        return max((p.stat().st_mtime for p in files), default=None)
    return None


def changed_sources(w):
    since, changed = w.meta["updated"], []
    for match in LINK.finditer(w.path.read_text(encoding="utf-8")):
        written = match.group(1).rstrip(".,;:")
        path = Path(os.path.expanduser(written))
        mtime = modified(path)
        if written in changed or mtime is None:
            continue
        if dt.date.fromtimestamp(mtime) > since:
            changed.append(written)
    return changed


def drift_lines(w):
    lines = [issue for issue in map(repo_issue, w.meta["repos"]) if issue]
    lines += [f"changed since {w.meta['updated']}: {p}" for p in changed_sources(w)]
    return lines


def cmd_drift(root, args):
    items, _ = load_store(root)
    targets = items if args.all else [w for w in items if w.key == args.key]
    if not targets and not args.all:
        print(f"work.py: no workstream {args.key!r}", file=sys.stderr)
        return 3
    for w in targets:
        lines = drift_lines(w)
        if lines or not args.all:
            print(w.key)
            print("\n".join(f"  {line}" for line in lines) if lines else "  clean")
    return 0


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "store-README.md"


def enclosing_repo(path):
    """The git work tree holding PATH (or its nearest existing parent), or None."""
    probe = path
    while not probe.exists():
        probe = probe.parent
    rc, out = git(probe, "rev-parse", "--show-toplevel")
    return out.strip() if rc == 0 else None


def cmd_init(root):
    if root.exists() and not root.is_dir():
        print(f"work.py: {root} is a file, not a folder; nothing changed", file=sys.stderr)
        return 5
    if (root / ".git").exists():
        print(f"work.py: a work store already exists at {root}; nothing changed", file=sys.stderr)
        print(root)
        return 0
    if not shutil.which("git"):
        print("work.py: git is not installed or not on PATH; install it, then run init again", file=sys.stderr)
        return 5
    outer = enclosing_repo(root)
    if outer:
        print(f"work.py: {root} is inside the git repo {outer}; the store needs its own history, "
              "so choose a folder outside any repo", file=sys.stderr)
        return 5
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "symbolic-ref", "HEAD", "refs/heads/log")
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    git(root, "add", "-A")
    commit = subprocess.run(["git", "-C", str(root), *IDENTITY_ONLY, "commit", "-q",
                             "-m", "init: work store"], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    if commit.returncode and not has_git_identity(root):
        print(f"work.py: created {root}, but not committed: git has no identity here. "
              "Set one with git config user.name and git config user.email, then commit in the store.",
              file=sys.stderr)
    elif commit.returncode:
        print(f"work.py: created {root}, but not committed: git commit failed:\n{commit.stderr.rstrip()}\n"
              "Fix that, then commit in the store.", file=sys.stderr)
    print(root)
    return 0


def has_git_identity(root):
    return all(git(root, *IDENTITY_ONLY, "var", ident)[0] == 0
               for ident in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"))


# ---- Skills for other coding agents ---------------------------------------------------------------------------------
# Claude Code installs the plugin and substitutes ${CLAUDE_PLUGIN_ROOT} in skill text. Other agents (Codex, Gemini CLI,
# OpenCode, omp) read plain skill folders and set no such variable, so install-skills writes rendered copies: the
# placeholder becomes the clone's absolute plugin root, and each skill is named <plugin>-<skill> so generic names
# (new, resume) can't collide. A marker file in each copy records what wrote it, so only those copies are ever
# replaced or removed, and --update finds them again. This mirrors herdr-skills#30, which also reads the marker to find
# this plugin's launcher: keep the names, the marker and its fields identical.

class InstallError(Exception):
    pass


PLUGIN_NAME = "work"
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"
SKILLS_MARKER = ".skills-install.json"
DEFAULT_SKILLS_TOOL = "agents"
# Each tool's user-scope skills folder, relative to home (opencode's to XDG_CONFIG_HOME, default ~/.config).
# ~/.agents/skills is read by Codex (its documented user folder; ~/.codex/skills is deprecated), Gemini CLI (an alias
# of ~/.gemini/skills), OpenCode and omp, so the default covers all four.
SKILL_DIRS = {
    "agents": (".agents", "skills"),
    "codex": (".agents", "skills"),
    "gemini": (".gemini", "skills"),
    "opencode": ("<config>", "opencode", "skills"),
    "omp": (".omp", "agent", "skills"),
}
SKILLS_NOTES = {
    "gemini": "Gemini CLI reads GEMINI.md, not AGENTS.md, unless told to. To have it read a repo's AGENTS.md, add "
              '"context": {"fileName": ["AGENTS.md", "GEMINI.md"]} to ~/.gemini/settings.json yourself; '
              "install-skills never edits another tool's settings.",
}
# Opt-in stand-ins for the Claude Code compaction hook (hooks/hooks.json), for the tools whose hook systems have a
# compaction event: Codex's SessionStart with source "compact" adds the hook's stdout to the model's context; Gemini
# CLI's PreCompress can only show its systemMessage to the user. OpenCode and omp have no verified equivalent.
NUDGE_HOOKS = {
    "codex": ("~/.codex/hooks.json", "Codex adds the reminder to the model's context after it compacts. Review and "
              "trust the hook with /hooks before it runs.",
              lambda launcher: {"hooks": {"SessionStart": [{"matcher": "^compact$", "hooks": [
                  {"type": "command", "command": 'sh "%s" nudge' % launcher, "timeout": 10}]}]}}),
    "gemini": ("~/.gemini/settings.json", "Gemini CLI shows the reminder to you, not the model, before it compresses "
               "the history; ask the agent to checkpoint when you see it.",
               lambda launcher: {"hooks": {"PreCompress": [{"hooks": [
                   {"type": "command", "name": "work-nudge", "command": 'sh "%s" nudge --json' % launcher,
                    "timeout": 10000}]}]}}),
}
NUDGE_HOOK_TOOLS = {"agents": ("codex", "gemini"), "codex": ("codex",), "gemini": ("gemini",)}


def skill_dirs(env=None):
    """{tool: its user-scope skills folder}, from SKILL_DIRS, resolved against this machine's home folder."""
    env = os.environ if env is None else env
    home = os.path.expanduser("~")
    config = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return {tool: os.path.join(config, *parts[1:]) if parts[0] == "<config>" else os.path.join(home, *parts)
            for tool, parts in SKILL_DIRS.items()}


def render_file(text, root):
    """A skill file's text with ${CLAUDE_PLUGIN_ROOT} replaced by root, in forward slashes as Claude Code writes it."""
    return text.replace(ROOT_PLACEHOLDER, root.replace("\\", "/"))


def render_skill(text, plugin, skill, root):
    """A SKILL.md for an agent other than Claude Code: the root filled in, the name <plugin>-<skill>, and a note
    under the first heading on how the Claude Code names map and how to update the copy."""
    text = render_file(text, root)
    text = re.sub(r"(?m)\A(---\n(?:.*\n)*?)name: *%s *\n" % re.escape(skill),
                  lambda m: "%sname: %s-%s\n" % (m.group(1), plugin, skill), text, count=1)
    note = ("> Installed by install-skills for agents other than Claude Code. `/%s:<name>` in this text means the "
            "`%s-<name>` skill. Don't edit this copy; to update it, run "
            '`sh "%s/scripts/%s-tools" install-skills --update`.' % (plugin, plugin, root.replace("\\", "/"), plugin))
    return re.sub(r"(?m)^(# .*\n)", lambda m: "%s\n%s\n" % (m.group(1), note), text, count=1)


def skills_notes(tool, plugin_root):
    """What the user may want to set up by hand for tool: install-skills prints these and never writes them."""
    notes = [SKILLS_NOTES[tool]] if tool in SKILLS_NOTES else []
    launcher = plugin_root.replace("\\", "/") + "/scripts/work-tools"
    for name in NUDGE_HOOK_TOOLS.get(tool, ()):
        path, effect, snippet = NUDGE_HOOKS[name]
        notes.append("Optional post-compaction checkpoint reminder (the Claude Code plugin's hook): merge this into "
                     "%s yourself. %s %s" % (path, effect, json.dumps(snippet(launcher))))
    return notes


def read_json_or_none(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def skill_marker(folder):
    marker = read_json_or_none(os.path.join(folder, SKILLS_MARKER))
    return marker if isinstance(marker, dict) else None


def plugin_copies(dest, plugin):
    """{folder name: marker} of the copies of plugin's skills in dest."""
    if not os.path.isdir(dest):
        return {}
    found = {}
    for name in sorted(os.listdir(dest)):
        marker = skill_marker(os.path.join(dest, name))
        if marker and marker.get("plugin") == plugin:
            found[name] = marker
    return found


def install_skills(plugin_root, dest, tool, commit, plugin=PLUGIN_NAME, dry_run=False):
    """Write a rendered copy of each of plugin_root's skills into dest. Refuses, writing nothing, when a target folder
    exists that this command didn't write; removes its own copies of skills the plugin no longer has."""
    skills_root = os.path.join(plugin_root, "skills")
    skills = sorted(n for n in os.listdir(skills_root) if os.path.isfile(os.path.join(skills_root, n, "SKILL.md")))
    ours = plugin_copies(dest, plugin)
    foreign = [plugin + "-" + s for s in skills
               if os.path.exists(os.path.join(dest, plugin + "-" + s)) and plugin + "-" + s not in ours]
    if foreign:
        raise InstallError("%s already holds %s, which install-skills did not write (no %s). Move or remove it, or "
                           "install somewhere else with --dest." % (dest, ", ".join(foreign), SKILLS_MARKER))
    stale = [name for name, marker in ours.items() if marker.get("skill") not in skills]
    result = {"dest": dest, "tool": tool, "installed": [plugin + "-" + s for s in skills], "removed": stale,
              "notes": skills_notes(tool, plugin_root), "dry_run": dry_run}
    if dry_run:
        return result
    for name in stale:
        shutil.rmtree(os.path.join(dest, name))
    for skill in skills:
        source, target = os.path.join(skills_root, skill), os.path.join(dest, plugin + "-" + skill)
        if os.path.exists(target):
            shutil.rmtree(target)
        for folder, _, files in os.walk(source):
            out = os.path.join(target, os.path.relpath(folder, source))
            os.makedirs(out, exist_ok=True)
            for name in files:
                path = os.path.join(folder, name)
                if name.endswith(".md"):
                    with open(path, encoding="utf-8") as handle:
                        text = handle.read()
                    if folder == source and name == "SKILL.md":
                        text = render_skill(text, plugin, skill, plugin_root)
                    else:
                        text = render_file(text, plugin_root)
                    with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as handle:
                        handle.write(text)
                else:
                    shutil.copy2(path, os.path.join(out, name))
        with open(os.path.join(target, SKILLS_MARKER), "w", encoding="utf-8") as handle:
            json.dump({"plugin": plugin, "skill": skill, "root": plugin_root, "tool": tool, "commit": commit},
                      handle, indent=2)
    return result


def uninstall_skills(dest, plugin=PLUGIN_NAME, dry_run=False):
    """Remove plugin's copies from dest, and nothing else."""
    removed = list(plugin_copies(dest, plugin))
    if not dry_run:
        for name in removed:
            shutil.rmtree(os.path.join(dest, name))
    return {"dest": dest, "removed": removed, "dry_run": dry_run}


def installed_skill_dirs(plugin, folders):
    """[(folder, tool)] for each distinct skills folder that holds copies of plugin, in table order."""
    seen, found = set(), []
    for tool, folder in folders.items():
        if folder in seen:
            continue
        seen.add(folder)
        copies = plugin_copies(folder, plugin)
        if copies:
            found.append((folder, next(iter(copies.values())).get("tool") or tool))
    return found


def refresh_skills(plugin_root, folders, commit, plugin=PLUGIN_NAME, dry_run=False):
    """Re-render plugin's copies in every folder that holds some."""
    return [install_skills(plugin_root, folder, tool, commit, plugin, dry_run)
            for folder, tool in installed_skill_dirs(plugin, folders)]


def plugin_commit(plugin_root):
    """The commit of the git clone holding plugin_root. Copies must point at a clone: a plugin cache folder moves on
    every update."""
    code, out = git(plugin_root, "rev-parse", "HEAD")
    if code != 0 or not out.strip():
        raise InstallError("%s is not in a git clone. Install from a clone of the repository (git clone ...), not "
                           "from a plugin cache, so the copies keep pointing at a folder that stays put." % plugin_root)
    return out.strip()


def pull_plugin(plugin_root):
    """Fast-forward the clone holding plugin_root; refuses on local changes."""
    code, porcelain = git(plugin_root, "status", "--porcelain")
    if code != 0:
        raise InstallError("%s is not in a git clone; nothing to pull." % plugin_root)
    if porcelain.strip():
        raise InstallError("The clone at %s has local changes; commit or remove them, or re-render without pulling "
                           "(install-skills --update --no-pull).\n%s" % (plugin_root, porcelain.rstrip()))
    proc = subprocess.run(["git", "-C", plugin_root, "pull", "--ff-only"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise InstallError("git pull --ff-only failed in %s:\n%s" % (plugin_root, (proc.stderr or proc.stdout).strip()))
    return proc.stdout.strip()


def install_skills_command(args):
    """install-skills: install, update or uninstall the rendered copies, printing JSON."""
    folders = skill_dirs()
    if args.uninstall:
        dest = args.dest or folders[args.tool or DEFAULT_SKILLS_TOOL]
        return uninstall_skills(dest, dry_run=args.dry_run)
    if args.update:
        if args.dest:
            folders = {"dest": args.dest}
        elif args.tool:
            folders = {args.tool: folders[args.tool]}
        pulled = None
        if not args.no_pull and not args.dry_run:
            pulled = pull_plugin(PLUGIN_ROOT)
            # Render with the code just pulled, not the code already loaded.
            argv = [sys.executable, os.path.abspath(__file__), "install-skills", "--update", "--no-pull"]
            argv += ["--dest", args.dest] if args.dest else ["--tool", args.tool] if args.tool else []
            proc = subprocess.run(argv, capture_output=True, text=True)
            if proc.returncode != 0:
                raise InstallError(proc.stderr.strip() or proc.stdout.strip())
            return {"pulled": pulled, "refreshed": json.loads(proc.stdout)["refreshed"]}
        refreshed = refresh_skills(PLUGIN_ROOT, folders, plugin_commit(PLUGIN_ROOT), dry_run=args.dry_run)
        if not refreshed:
            raise InstallError("No installed %s skills found in %s; install them first." % (
                PLUGIN_NAME, ", ".join(dict.fromkeys(folders.values()))))
        return {"pulled": pulled, "refreshed": refreshed}
    tool = args.tool or DEFAULT_SKILLS_TOOL
    return install_skills(PLUGIN_ROOT, args.dest or folders[tool], tool, plugin_commit(PLUGIN_ROOT),
                          dry_run=args.dry_run)


HANDLERS = {"index": cmd_index, "list": cmd_list, "find": cmd_find, "drift": cmd_drift, "touch": cmd_touch}


def build_parser():
    parser = argparse.ArgumentParser(prog="work.py", description=__doc__)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today(),
                        help=argparse.SUPPRESS)
    parser.add_argument("--now", type=dt.datetime.fromisoformat, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    nudger = sub.add_parser("nudge", help="print the post-compaction reminder if the store exists")
    nudger.add_argument("--json", action="store_true", help="as a Gemini CLI hook's JSON systemMessage")
    sub.add_parser("root", help="print the store's path, whether or not it exists")
    sub.add_parser("init", help="create the store (git on branch log, no remote) unless it exists")
    sub.add_parser("index", help="regenerate index.md and log.md and add missing OKF types; exit 1 on header errors")
    sub.add_parser("list", help="one line per workstream")
    finder = sub.add_parser("find", help="match a workstream by name, or by --cwd inside a linked repo")
    finder.add_argument("query", nargs="?")
    finder.add_argument("--cwd")
    drifter = sub.add_parser("drift", help="uncommitted/unpushed repo work and linked files changed since 'updated'")
    target = drifter.add_mutually_exclusive_group(required=True)
    target.add_argument("key", nargs="?")
    target.add_argument("--all", action="store_true")
    toucher = sub.add_parser("touch", help="stamp a workstream's updated date and OKF generated datetime")
    toucher.add_argument("key")
    installer = sub.add_parser("install-skills", help="install rendered skill copies for agents other than Claude Code")
    installer.add_argument("--tool", choices=sorted(SKILL_DIRS), help="install into this tool's own skills folder")
    installer.add_argument("--dest", help="install into this skills folder instead")
    installer.add_argument("--dry-run", action="store_true")
    mode = installer.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="pull the clone, then re-render every installed copy")
    mode.add_argument("--uninstall", action="store_true")
    installer.add_argument("--no-pull", action="store_true", help="with --update: re-render without pulling")
    return parser, sub


def main(argv=None):
    parser, _ = build_parser()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser.parse_args(argv)
    if args.cmd == "nudge":
        return cmd_nudge(args.json)
    if args.cmd == "install-skills":  # needs no store
        try:
            print(json.dumps(install_skills_command(args), indent=2))
        except InstallError as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    raw = os.environ.get("WORK_STORE")
    if raw and not os.path.isabs(os.path.expanduser(raw)):
        print(f"work.py: WORK_STORE must be an absolute path (or start with ~), not {raw!r}", file=sys.stderr)
        return 4
    root = store_root()
    if args.cmd == "root":
        print(root)
        return 0
    if args.cmd == "init":
        return cmd_init(root)
    if not root.is_dir():
        print(f"work.py: no work store at {root}", file=sys.stderr)
        return 4
    return HANDLERS[args.cmd](root, args)


if __name__ == "__main__":
    sys.exit(main())
