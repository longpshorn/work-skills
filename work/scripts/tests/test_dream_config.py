import json
from pathlib import Path

import pytest

import dream
import work

EXAMPLE = Path(__file__).resolve().parents[2] / "templates" / "dream.example.jsonc"


def write_settings(env, data):
    env.settings.parent.mkdir(parents=True, exist_ok=True)
    env.settings.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def write_config(env, text):
    env.config.parent.mkdir(parents=True, exist_ok=True)
    env.config.write_text(text, encoding="utf-8")


def test_defaults_when_config_missing_and_settings_name_memory_dir(dream_env):
    write_settings(dream_env, {"autoMemoryDirectory": "~/mem"})
    cfg = dream.load_config()
    assert cfg["memory_dir"] == Path(dream_env.home / "mem")
    assert cfg["caps"]["index_lines"] == 150
    assert cfg["caps"]["index_bytes"] == 18432
    assert cfg["caps"]["promotions"] == 5
    assert cfg["global_claude_md"] == Path(dream_env.home / ".claude" / "CLAUDE.md")


def test_config_overrides_merge_and_comments_are_ignored(dream_env):
    write_config(dream_env, '// note\n{"caps": {"promotions": 2}, "memory_dir": "/x"}\n')
    cfg = dream.load_config()
    assert cfg["caps"]["promotions"] == 2
    assert cfg["caps"]["index_lines"] == 150
    assert cfg["memory_dir"] == Path("/x")


def test_missing_memory_dir_everywhere_raises(dream_env):
    write_settings(dream_env, {})
    with pytest.raises(dream.ConfigError, match="autoMemoryDirectory"):
        dream.load_config()


def test_invalid_or_absent_settings_json_is_a_config_error_not_a_traceback(dream_env):
    write_settings(dream_env, "{")
    with pytest.raises(dream.ConfigError, match="autoMemoryDirectory"):
        dream.load_config()
    write_config(dream_env, '{"memory_dir": "/x"}')
    assert dream.load_config()["memory_dir"] == Path("/x")


def test_env_overrides_for_paths(dream_env):
    assert dream.config_path() == dream_env.config
    assert dream.state_dir() == dream_env.state
    assert dream.projects_dir() == dream_env.projects


def test_cli_dispatch_needs_no_work_store(dream_env, monkeypatch, tmp_path):
    monkeypatch.setenv("WORK_STORE", str(tmp_path / "missing"))
    assert work.main(["dream-status"]) != 4


def test_example_config_parses():
    data = json.loads(dream.strip_comments(EXAMPLE.read_text(encoding="utf-8")))
    allowed = set(dream.DEFAULTS) | {"memory_dir", "global_claude_md"}
    assert set(data) <= allowed
    assert set(data) == allowed
