import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "store"
    root.mkdir()
    monkeypatch.setenv("WORK_STORE", str(root))
    return root


@pytest.fixture
def write(store):
    def _write(key, text):
        path = store / f"{key}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
    return _write


@pytest.fixture
def dream_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    paths = SimpleNamespace(
        home=home,
        config=tmp_path / "config" / "dream.json",
        state=tmp_path / "state",
        projects=tmp_path / "projects",
        settings=home / ".claude" / "settings.json",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("WORK_DREAM_CONFIG", str(paths.config))
    monkeypatch.setenv("WORK_DREAM_STATE", str(paths.state))
    monkeypatch.setenv("WORK_DREAM_PROJECTS", str(paths.projects))
    return paths
