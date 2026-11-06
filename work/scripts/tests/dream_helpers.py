"""Synthetic transcript entries and fakes for the dream tests."""

import json
import os
import subprocess
from pathlib import Path


def _base(kind, uuid, session, cwd, ts, extra):
    entry = {"type": kind, "uuid": uuid, "sessionId": session, "cwd": cwd,
             "timestamp": ts, "isSidechain": False}
    entry.update(extra)
    return entry


def user(text, uuid, session="s1", cwd="/w", ts="2026-11-04T10:00:00.000Z", **extra):
    entry = _base("user", uuid, session, cwd, ts, extra)
    entry["message"] = {"role": "user", "content": text}
    return entry


def assistant(blocks, msg_id, uuid, session="s1", cwd="/w", ts="2026-11-04T10:00:01.000Z", **extra):
    entry = _base("assistant", uuid, session, cwd, ts, extra)
    entry["message"] = {"role": "assistant", "id": msg_id, "content": blocks}
    return entry


def tool_result(text, uuid, session="s1", cwd="/w", ts="2026-11-04T10:00:02.000Z", **extra):
    entry = _base("user", uuid, session, cwd, ts, extra)
    entry["toolUseResult"] = {"stdout": text}
    entry["message"] = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": text}]}
    return entry


def write_transcript(dirpath, project, session, entries, mtime=None):
    folder = Path(dirpath) / project
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def fake_bin(dirpath, name, script):
    path = Path(dirpath) / name
    path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
    path.chmod(0o755)
    return path


def init_repo(path, remote=None):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", "init")
    if remote:
        run("remote", "add", "origin", remote)
    return path
