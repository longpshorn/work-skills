import json
import os
import subprocess
from pathlib import Path

import work

PLUGIN = Path(work.__file__).resolve().parents[1]
LAUNCHER = PLUGIN / "scripts" / "work-tools"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def launch(*args, env):
    return subprocess.run(["sh", str(LAUNCHER), *args], capture_output=True, env={**os.environ, **env})


def test_launcher_runs_root(tmp_path):
    result = launch("root", env={"WORK_STORE": str(tmp_path / "s")})
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8").strip() == str(tmp_path / "s")


def test_launcher_passes_paths_with_spaces(tmp_path):
    store = tmp_path / "my notes" / "store"
    env = {"WORK_STORE": str(store), **IDENTITY}
    created = launch("init", env=env)
    assert created.returncode == 0, created.stderr
    assert (store / "README.md").is_file()
    assert launch("root", env=env).stdout.decode("utf-8").strip() == str(store)


def compact_hook_command():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    [entry] = [e for e in hooks["SessionStart"] if e["matcher"] == "compact"]
    [hook] = entry["hooks"]
    return hook["command"]


def run_hook(env):
    command = compact_hook_command().replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN))
    return subprocess.run(["sh", "-c", command], capture_output=True, env={**os.environ, **env})


def test_hook_prints_the_nudge_when_the_store_exists(tmp_path):
    result = run_hook({"WORK_STORE": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert "/work:checkpoint" in result.stdout.decode("utf-8")


def test_hook_is_silent_without_a_store(tmp_path):
    result = run_hook({"WORK_STORE": str(tmp_path / "missing")})
    assert result.returncode == 0 and result.stdout == b""
