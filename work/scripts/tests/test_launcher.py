import json
import os
import re
import subprocess
from pathlib import Path

import pytest

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


def run_hook(env, root=None):
    # Claude Code leaves ${CLAUDE_PLUGIN_ROOT} in hook commands for the shell to expand from the environment.
    root_env = {"CLAUDE_PLUGIN_ROOT": root or str(PLUGIN)}
    return subprocess.run(["sh", "-c", compact_hook_command()], capture_output=True, env={**os.environ, **root_env, **env})


def test_hook_prints_the_nudge_when_the_store_exists(tmp_path):
    result = run_hook({"WORK_STORE": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert "/work:checkpoint" in result.stdout.decode("utf-8")


def test_hook_is_silent_without_a_store(tmp_path):
    result = run_hook({"WORK_STORE": str(tmp_path / "missing")})
    assert result.returncode == 0 and result.stdout == b""


def unc(path):
    drive, rest = os.path.splitdrive(str(path))
    return "\\\\localhost\\" + drive.rstrip(":") + "$" + rest


needs_unc = pytest.mark.skipif(os.name != "nt" or not os.path.isdir(unc(PLUGIN)),
                               reason="needs Windows and the drive's admin share")


@needs_unc
@pytest.mark.parametrize("form", ["backslash", "forward-slash"])
def test_hook_reaches_the_helper_from_a_unc_plugin_root(form, tmp_path):
    root = unc(PLUGIN) if form == "backslash" else unc(PLUGIN).replace("\\", "/")
    result = run_hook({"WORK_STORE": str(tmp_path)}, root=root)
    assert result.returncode == 0, result.stderr
    assert "/work:checkpoint" in result.stdout.decode("utf-8")


def skill_helper_calls():
    return {path.parent.name: re.search(r"^Helper: `(.+?)`", path.read_text(encoding="utf-8"), re.M).group(1)
            for path in sorted((PLUGIN / "skills").glob("*/SKILL.md"))}


def test_every_skill_uses_the_hook_helper_call():
    helper = compact_hook_command().rsplit(" ", 1)[0]
    assert skill_helper_calls() == {name: helper for name in skill_helper_calls()}


@needs_unc
def test_skill_helper_call_reaches_the_helper_from_a_unc_plugin_root(tmp_path):
    # Claude Code writes the plugin root into skill text with forward slashes, e.g. //localhost/C$/...
    root = unc(PLUGIN).replace("\\", "/")
    command =skill_helper_calls()["resume"].replace("${CLAUDE_PLUGIN_ROOT}", root) + " root"
    result = subprocess.run(["sh", "-c", command], capture_output=True,
                            env={**os.environ, "WORK_STORE": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8").strip() == str(tmp_path)
