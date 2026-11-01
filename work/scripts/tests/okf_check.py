"""Conformance check for OKF v0.2, section 11, offline and standard-library only.

Written from https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/62432a095456147ee71e70ac6e4dc0d2dea3ac30/okf/SPEC.md
Frontmatter is read as the flat YAML subset the work store writes: `key: value` lines,
with indented or `- ` continuation lines belonging to the key above.
"""
import re
from pathlib import Path

RESERVED = ("index.md", "log.md")
ENTRY = re.compile(r"[*-] \[[^\]]*(?:\\.[^\]]*)*\]\([^)\s]+\)(?: - .*)?$")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")


def split(text):
    """(frontmatter dict or None, body lines); raises ValueError when a block is malformed."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, lines
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("unterminated frontmatter")
    meta, key = {}, None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t-" and key:
            continue
        match = re.match(r"([^\s:#][^:]*):(?:\s+(.*))?$", line)
        if not match:
            raise ValueError(f"unparseable frontmatter line {line!r}")
        key = match.group(1)
        meta[key] = re.sub(r"\s+#.*$", "", match.group(2) or "").strip().strip("'\"")
    return meta, lines[end + 1:]


def check_index(path, root, meta, body):
    problems = []
    if meta is not None and (path.parent != root or set(meta) - {"okf_version"}):
        problems.append("index.md frontmatter is allowed only at the bundle root, holding okf_version")
    for line in body:
        if line.strip() and not line.startswith("#") and not ENTRY.match(line):
            problems.append(f"index.md line is neither a heading nor a link entry: {line!r}")
    return problems


def check_log(meta, body):
    problems = ["log.md has frontmatter"] if meta is not None else []
    dates = []
    for line in body:
        if line.startswith("## ") and not DATE.match(line[3:].strip()):
            problems.append(f"log.md date heading is not YYYY-MM-DD: {line!r}")
        elif line.startswith("## "):
            dates.append(line[3:].strip())
    if dates != sorted(set(dates), reverse=True):
        problems.append("log.md dates are not newest first")
    return problems


def problems(root):
    """Every section 11 violation under ROOT, as 'relative/path: reason' strings."""
    root, found = Path(root), []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            meta, body = split(path.read_text(encoding="utf-8"))
        except ValueError as e:
            found.append(f"{rel.as_posix()}: {e}")
            continue
        if path.name == "index.md":
            issues = check_index(path, root, meta, body)
        elif path.name == "log.md":
            issues = check_log(meta, body)
        elif meta is None:
            issues = ["no frontmatter"]
        else:
            issues = [] if meta.get("type") else ["no type"]
        found += [f"{rel.as_posix()}: {issue}" for issue in issues]
    return found
