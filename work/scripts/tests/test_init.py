import os
import subprocess
from pathlib import Path

import pytest

import work
from helpers import header

TEMPLATE = Path(work.__file__).resolve().parents[1] / "templates" / "store-README.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    root = tmp_path / "store"
    monkeypatch.setenv("WORK_STORE", str(root))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return root


def git_out(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True).stdout.strip()


def init(capsys):
    rc = work.main(["init"])
    return rc, capsys.readouterr()


def test_init_creates_store_on_log_branch(fresh, monkeypatch, capsys):
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)
    rc, out = init(capsys)
    assert rc == 0 and out.out.strip() == str(fresh)
    assert git_out(fresh, "branch", "--show-current") == "log"
    assert git_out(fresh, "remote") == ""
    assert (fresh / "README.md").read_text(encoding="utf-8") == TEMPLATE.read_text(encoding="utf-8")
    assert git_out(fresh, "log", "--format=%s") == "init: work store"


def test_init_leaves_an_existing_store_untouched(fresh, monkeypatch, capsys):
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)
    fresh.mkdir()
    (fresh / "README.md").write_text("my own notes\n", encoding="utf-8")
    (fresh / "home").mkdir()
    (fresh / "home" / "01-a.md").write_text(header(), encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "log", str(fresh)], check=True)
    subprocess.run(["git", "-C", str(fresh), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(fresh), "commit", "-qm", "mine"], check=True)
    head = git_out(fresh, "rev-parse", "HEAD")
    rc, out = init(capsys)
    assert rc == 0 and "already exists" in out.err
    assert (fresh / "README.md").read_text(encoding="utf-8") == "my own notes\n"
    assert git_out(fresh, "rev-parse", "HEAD") == head
    assert git_out(fresh, "status", "--porcelain") == ""


def test_init_without_git_identity_creates_store_and_says_so(fresh, tmp_path, monkeypatch, capsys):
    for key in IDENTITY:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("EMAIL", "")
    rc, out = init(capsys)
    assert rc == 0
    assert (fresh / "README.md").is_file()
    assert git_out(fresh, "log", "--oneline") == ""
    assert "not committed" in out.err and "git config user.email" in out.err


def test_init_refuses_a_file_at_the_path(fresh, capsys):
    fresh.write_text("a file\n", encoding="utf-8")
    rc, out = init(capsys)
    assert rc == 5 and fresh.read_text(encoding="utf-8") == "a file\n"


def test_index_and_find_work_after_init(fresh, monkeypatch, capsys):
    for key, value in IDENTITY.items():
        monkeypatch.setenv(key, value)
    init(capsys)
    assert work.main(["index"]) == 0
    assert work.main(["find", "anything"]) == 3
