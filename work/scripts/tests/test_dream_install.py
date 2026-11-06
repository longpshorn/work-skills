import json
import os
import plistlib
import subprocess

import pytest

import dream
from dream_helpers import fake_bin

pytestmark = pytest.mark.skipif(os.name == "nt", reason="needs sh and a fake launchctl")

LABEL = "com.work.dream"


@pytest.fixture
def env(dream_env, tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    dream_env.settings.parent.mkdir(parents=True)
    dream_env.settings.write_text(json.dumps({"autoMemoryDirectory": str(memory)}), encoding="utf-8")
    (dream_env.home / ".gitconfig").write_text("[user]\n\tname = Tester\n\temail = t@example.com\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "launchctl.calls"
    fake_bin(bin_dir, "launchctl", 'echo "$@" >> "%s"\n' % calls)
    fake_bin(bin_dir, "claude", "exit 0\n")
    monkeypatch.setenv("PATH", "%s%s%s" % (bin_dir, os.pathsep, os.environ["PATH"]))
    dream_env.memory = memory
    dream_env.bin = bin_dir
    dream_env.calls = calls
    dream_env.plist = dream_env.home / "Library" / "LaunchAgents" / (LABEL + ".plist")
    return dream_env


def install(env, init_memory=False, load=False):
    return dream.dream_install(init_memory, load, launchctl=str(env.bin / "launchctl"), home=env.home)


def git(path, *args):
    return subprocess.run(["git", "-C", str(path)] + list(args), capture_output=True, text=True,
                          env=dict(os.environ, HOME=os.environ["HOME"])).stdout.strip()


def test_install_stops_when_memory_dir_is_not_configured(env, capsys):
    env.settings.write_text("{}", encoding="utf-8")
    assert install(env) == 1
    assert "autoMemoryDirectory" in capsys.readouterr().out
    assert not env.config.exists() and not env.plist.exists() and not env.state.exists()


def test_install_writes_config_and_plist_and_is_idempotent(env):
    assert install(env) == 0
    assert env.config.is_file() and env.plist.is_file()
    first = (env.config.read_bytes(), env.plist.read_bytes(), (env.state / "launcher.sh").read_bytes())
    env.config.write_text('{"schedule": {"hour": 2, "minute": 0}}', encoding="utf-8")
    edited = env.config.read_bytes()
    assert install(env) == 0
    assert env.config.read_bytes() == edited
    assert (env.plist.read_bytes(), (env.state / "launcher.sh").read_bytes()) == first[1:]


def test_plist_contains_schedule_label_launcher_and_dream_run(env):
    install(env)
    plist = plistlib.loads(env.plist.read_bytes())
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == ["sh", str(env.state / "launcher.sh"), "dream-run"]
    assert plist["StartCalendarInterval"] == {"Hour": 2, "Minute": 0}
    assert plist["StandardOutPath"].startswith(str(env.state))
    assert plist["StandardErrorPath"].startswith(str(env.state))


def test_plist_carries_a_minimal_environment_the_run_needs(env):
    install(env)
    vars_ = plistlib.loads(env.plist.read_bytes())["EnvironmentVariables"]
    assert vars_["HOME"] == str(env.home)
    assert vars_["USER"] and vars_["LOGNAME"]
    path = vars_["PATH"].split(os.pathsep)
    assert str(env.bin) in path
    for extra in ("/opt/homebrew/bin", "/usr/local/bin", str(env.home / ".local" / "bin")):
        assert extra in path
    assert vars_["WORK_DREAM_CONFIG"] == str(env.config)
    assert vars_["WORK_DREAM_STATE"] == str(env.state)


def test_plist_uses_the_configured_schedule(env):
    env.config.parent.mkdir(parents=True)
    env.config.write_text('{"schedule": {"hour": 4, "minute": 30}}', encoding="utf-8")
    install(env)
    assert plistlib.loads(env.plist.read_bytes())["StartCalendarInterval"] == {"Hour": 4, "Minute": 30}


def _plugin_copy(env, name, mtime):
    scripts = env.home / ".claude" / "plugins" / "cache" / "market" / "work" / name / "scripts"
    scripts.mkdir(parents=True)
    tool = scripts / "work-tools"
    tool.write_text('echo "ran %s $@"\n' % name, encoding="utf-8")
    os.utime(tool, (mtime, mtime))
    return scripts.parent


def _run_launcher(env, *args):
    done = subprocess.run(["sh", str(env.state / "launcher.sh")] + list(args), capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(env.home)))
    return done.stdout.strip()


def _installed_plugins(env, text):
    path = env.home / ".claude" / "plugins" / "installed_plugins.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_launcher_runs_the_copy_claude_code_has_installed_not_the_newest_file(env):
    install(env)
    old = _plugin_copy(env, "old", 1000)
    _plugin_copy(env, "new", 2000)
    entries = {"work@market": [{"scope": "project", "installPath": "/nowhere"},
                               {"scope": "user", "installPath": str(old), "version": "1"}],
               "other@market": [{"scope": "user", "installPath": "/elsewhere"}]}
    _installed_plugins(env, json.dumps({"version": 2, "plugins": entries}))
    assert _run_launcher(env, "dream-run") == "ran old dream-run"


@pytest.mark.parametrize("text", [None, "{not json", '{"plugins": {"work@m": [{"scope": "user", "installPath": "/gone"}]}}',
                                  '{"plugins": []}'])
def test_launcher_falls_back_to_the_installing_copy(env, text):
    install(env)
    _plugin_copy(env, "cached", 2000)
    if text is not None:
        _installed_plugins(env, text)
    assert "dream-run" in _run_launcher(env, "dream-run", "--help")
    assert "ran cached" not in _run_launcher(env, "dream-run", "--help")


def test_init_memory_inits_commits_and_creates_global_claude_md_without_overwriting(env):
    env.memory.mkdir()
    (env.memory / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    assert install(env, init_memory=True) == 0
    assert git(env.memory, "rev-parse", "--show-toplevel") == str(env.memory.resolve())
    assert git(env.memory, "log", "--format=%s") == "init: memory folder"
    assert git(env.memory, "config", "--local", "user.email") == "t@example.com"
    claude_md = env.home / ".claude" / "CLAUDE.md"
    assert claude_md.is_file()
    claude_md.write_text("mine\n", encoding="utf-8")
    head = git(env.memory, "rev-parse", "HEAD")
    assert install(env, init_memory=True) == 0
    assert claude_md.read_text(encoding="utf-8") == "mine\n"
    assert git(env.memory, "rev-parse", "HEAD") == head
    dream.snapshot(env.memory, "2026-11-05")


def test_init_memory_makes_a_folder_nested_in_a_larger_repo_its_own_repo(env, tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "-C", str(outer), "init", "-q"], check=True)
    env.settings.write_text(json.dumps({"autoMemoryDirectory": str(outer / "memory")}), encoding="utf-8")
    assert install(env, init_memory=True) == 0
    assert git(outer / "memory", "rev-parse", "--show-toplevel") == str((outer / "memory").resolve())
    dream.snapshot(outer / "memory", "2026-11-05")


def test_init_memory_without_any_git_identity_fails_clearly(env, capsys):
    (env.home / ".gitconfig").unlink()
    assert install(env, init_memory=True) == 1
    assert "user.name" in capsys.readouterr().out
    assert not (env.home / ".claude" / "CLAUDE.md").exists()


def test_load_calls_launchctl_bootstrap_only_with_the_flag(env):
    install(env)
    assert not env.calls.exists()
    assert install(env, load=True) == 0
    calls = env.calls.read_text(encoding="utf-8").splitlines()
    uid = str(os.getuid())
    assert calls[0] == "bootout gui/%s/%s" % (uid, LABEL)
    assert calls[1] == "bootstrap gui/%s %s" % (uid, env.plist)


def test_load_ignores_a_failing_bootout_but_reports_a_failing_bootstrap(env, capsys):
    fake_bin(env.bin, "launchctl", 'if [ "$1" = bootstrap ]; then echo denied >&2; exit 5; fi\nexit 3\n')
    assert install(env, load=True) == 1
    assert "denied" in capsys.readouterr().out


def test_load_reports_a_missing_launchctl_instead_of_crashing(env, capsys):
    assert dream.dream_install(False, True, launchctl=str(env.bin / "absent"), home=env.home) == 1
    assert "launchctl" in capsys.readouterr().out


def test_fresh_install_leaves_memory_dir_to_auto_memory_directory(env):
    assert install(env, init_memory=True) == 0
    assert dream.load_config(env.home)["memory_dir"] == env.memory
    assert (env.memory / ".git").is_dir()
