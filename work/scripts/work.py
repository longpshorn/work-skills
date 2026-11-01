#!/usr/bin/env python3
"""Work-store helper for the work plugin: /work:resume, :checkpoint, :wrap, :new and :standup.

Store layout and header rules: the store's README.md. The store is WORK_STORE, or ~/.work.
"""
import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

STATES = ("idea", "scoped", "active", "blocked", "review", "done")
REQUIRED = ("title", "state", "next", "updated")
ACTOR = "process:work-tools"
TYPES = {"status file": "workstream", "AREA.md": "area", "README.md": "guide"}
INDEX = "index.md"
RESERVED = (INDEX, "log.md")
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


def cmd_nudge():
    if store_root().is_dir():
        print(NUDGE)
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


def upgraded(text, kind):
    """TEXT with the OKF type for KIND added, a legacy status key renamed to state, and an AREA.md's
    **Purpose:** line copied to its description; nothing else changes."""
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


def upgrade_file(path, kind):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    new = upgraded(text, kind)
    if new != text:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new)


def upgrade_store(root):
    """Give every store file its OKF type, so stores written before OKF conform without a migration."""
    if (root / "README.md").is_file():
        upgrade_file(root / "README.md", "README.md")
    archive = root / "_archive"
    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))]
    folders += [p for p in archive.iterdir() if p.is_dir()] if archive.is_dir() else []
    for folder in folders:
        for path in sorted(folder.glob("*.md")):
            if path.name.lower() not in RESERVED:
                upgrade_file(path, "AREA.md" if path.name == "AREA.md" else "status file")


def cmd_index(root, args):
    upgrade_store(root)
    items, errors = load_store(root)
    retire_legacy_index(root)
    (root / INDEX).write_text(render_index(root, items, errors, args.today), encoding="utf-8")
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


HANDLERS = {"index": cmd_index, "list": cmd_list, "find": cmd_find, "drift": cmd_drift, "touch": cmd_touch}


def build_parser():
    parser = argparse.ArgumentParser(prog="work.py", description=__doc__)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today(),
                        help=argparse.SUPPRESS)
    parser.add_argument("--now", type=dt.datetime.fromisoformat, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("nudge", help="print the post-compaction reminder if the store exists")
    sub.add_parser("root", help="print the store's path, whether or not it exists")
    sub.add_parser("init", help="create the store (git on branch log, no remote) unless it exists")
    sub.add_parser("index", help="regenerate index.md and add missing OKF types; exit 1 on header errors")
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
    return parser, sub


def main(argv=None):
    parser, _ = build_parser()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser.parse_args(argv)
    if args.cmd == "nudge":
        return cmd_nudge()
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
