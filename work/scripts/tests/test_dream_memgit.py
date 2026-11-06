import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dream
from dream_helpers import init_repo

TODAY = dt.date(2026, 11, 5)


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def count(repo):
    return int(git(repo, "rev-list", "--count", "HEAD"))


def test_snapshot_commits_dirty_tree_and_returns_head(tmp_path):
    repo = init_repo(tmp_path / "mem")
    (repo / "a.md").write_text("new\n", encoding="utf-8")
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    head = dream.snapshot(repo, TODAY)
    assert head == git(repo, "rev-parse", "HEAD")
    assert git(repo, "log", "-1", "--format=%s") == "pre-dream snapshot"
    assert git(repo, "status", "--porcelain") == ""


def test_snapshot_clean_tree_makes_no_commit(tmp_path):
    repo = init_repo(tmp_path / "mem")
    before = count(repo)
    assert dream.snapshot(repo, TODAY) == git(repo, "rev-parse", "HEAD")
    assert count(repo) == before


def test_snapshot_refuses_a_non_repo_with_the_install_hint(tmp_path):
    folder = tmp_path / "mem"
    folder.mkdir()
    with pytest.raises(dream.ConfigError, match="dream-install --init-memory"):
        dream.snapshot(folder, TODAY)


def test_snapshot_refuses_a_repo_without_a_commit(tmp_path):
    folder = tmp_path / "mem"
    folder.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(folder), check=True)
    with pytest.raises(dream.ConfigError, match="dream-install --init-memory"):
        dream.snapshot(folder, TODAY)


def test_snapshot_refuses_a_folder_inside_another_repo(tmp_path):
    outer = init_repo(tmp_path / "outer")
    inner = outer / "mem"
    inner.mkdir()
    with pytest.raises(dream.ConfigError, match="dream-install --init-memory"):
        dream.snapshot(inner, TODAY)
    with pytest.raises(dream.ConfigError):
        dream.reset_to(inner, git(outer, "rev-parse", "HEAD"))


def test_missing_git_is_a_clear_error(tmp_path, monkeypatch):
    repo = init_repo(tmp_path / "mem")
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    with pytest.raises(dream.ConfigError, match="git"):
        dream.snapshot(repo, TODAY)


def test_copy_global_commits_only_on_change(tmp_path):
    repo = init_repo(tmp_path / "mem")
    source = tmp_path / "CLAUDE.md"
    dream.copy_global(repo, tmp_path / "absent.md")
    assert count(repo) == 1
    source.write_text("rules\n", encoding="utf-8")
    dream.copy_global(repo, source)
    assert (repo / "_global" / "CLAUDE.md").read_text(encoding="utf-8") == "rules\n"
    assert count(repo) == 2
    dream.copy_global(repo, source)
    assert count(repo) == 2
    source.write_text("rules v2\n", encoding="utf-8")
    (repo / "other.md").write_text("pending\n", encoding="utf-8")
    dream.copy_global(repo, source)
    assert count(repo) == 3
    assert git(repo, "status", "--porcelain") == "?? other.md"


def test_commit_run_commits_everything_and_returns_hash(tmp_path):
    repo = init_repo(tmp_path / "mem")
    (repo / "a.md").write_text("x\n", encoding="utf-8")
    head = dream.commit_run(repo, "dream: test")
    assert head == git(repo, "rev-parse", "HEAD")
    assert git(repo, "log", "-1", "--format=%s") == "dream: test"
    assert dream.commit_run(repo, "dream: again") == head


def test_commit_run_without_identity_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = init_repo(tmp_path / "mem")
    git(repo, "config", "--unset", "user.name")
    git(repo, "config", "--unset", "user.email")
    git(repo, "config", "user.useConfigOnly", "true")
    (repo / "a.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(dream.ConfigError, match="user.name"):
        dream.commit_run(repo, "dream: test")


def test_reset_to_discards_changes_and_untracked_files(tmp_path):
    repo = init_repo(tmp_path / "mem")
    (repo / "keep" / "deep").mkdir(parents=True)
    (repo / "keep" / "deep" / "k.md").write_text("k\n", encoding="utf-8")
    snap = dream.snapshot(repo, TODAY)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    (repo / "keep" / "deep" / "k.md").unlink()
    (repo / "new.md").write_text("n\n", encoding="utf-8")
    (repo / "newdir" / "sub").mkdir(parents=True)
    (repo / "newdir" / "sub" / "n.md").write_text("n\n", encoding="utf-8")
    (repo / "staged.md").write_text("s\n", encoding="utf-8")
    git(repo, "add", "staged.md")
    dream.commit_run(repo, "dream: partial")
    (repo / "later.md").write_text("l\n", encoding="utf-8")
    nested = repo / "nested"
    nested.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(nested), check=True)
    (nested / "f.md").write_text("f\n", encoding="utf-8")
    dream.reset_to(repo, snap)
    assert git(repo, "rev-parse", "HEAD") == snap
    assert git(repo, "status", "--porcelain", "--ignored") == ""
    assert sorted(p.name for p in repo.iterdir()) == [".git", "README.md", "keep"]
    assert (repo / "keep" / "deep" / "k.md").exists()


def test_reset_to_leaves_everything_outside_the_folder(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    sibling = tmp_path / "sibling.txt"
    sibling.write_text("s\n", encoding="utf-8")
    repo = init_repo(outer / "mem")
    snap = dream.snapshot(repo, TODAY)
    (repo / "x.md").write_text("x\n", encoding="utf-8")
    dream.reset_to(repo, snap)
    assert sibling.read_text(encoding="utf-8") == "s\n"
    assert outer.exists()


def test_reset_to_refuses_an_option_shaped_rev(tmp_path):
    repo = init_repo(tmp_path / "mem")
    (repo / "x.md").write_text("x\n", encoding="utf-8")
    with pytest.raises(dream.ConfigError):
        dream.reset_to(repo, "--hard")
    assert (repo / "x.md").exists()


def test_changes_since_classifies_added_updated_retired(tmp_path):
    repo = init_repo(tmp_path / "mem")
    (repo / "_retired").mkdir()
    (repo / "old.md").write_text("old\n" * 20, encoding="utf-8")
    (repo / "edit.md").write_text("one\n", encoding="utf-8")
    (repo / "gone.md").write_text("gone memory body\n", encoding="utf-8")
    snap = dream.snapshot(repo, TODAY)
    (repo / "fresh one.md").write_text("fresh\n", encoding="utf-8")
    (repo / "edit.md").write_text("two\n", encoding="utf-8")
    (repo / "old.md").rename(repo / "_retired" / "old.md")
    (repo / "gone.md").unlink()
    (repo / "_retired" / "gone.md").write_text("---\nretired: x\n---\ntotally different\n", encoding="utf-8")
    (repo / "MEMORY.md").write_text("- index\n", encoding="utf-8")
    (repo / "notes.txt").write_text("t\n", encoding="utf-8")
    assert dream.changes_since(repo, snap) == {
        "added": ["fresh one"], "updated": ["edit"], "retired": ["gone", "old"]}
    dream.commit_run(repo, "dream: x")
    assert dream.changes_since(repo, snap)["added"] == ["fresh one"]


def test_commit_message_lists_names():
    message = dream.commit_message(
        ["session:a", "session:b"],
        {"added": ["x", "y"], "updated": ["z"], "retired": [], "promoted": ["p"]},
        TODAY)
    lines = message.splitlines()
    assert lines[0] == "dream: 2026-11-05"
    assert lines[1] == ""
    body = "\n".join(lines[2:])
    assert "Read: 2 conversations (session:a, session:b)" in body
    assert "Added: x, y" in body
    assert "Updated: z" in body
    assert "Promoted: p" in body
    assert "Retired" not in body


@pytest.mark.skipif(sys.platform == "win32", reason="needs symlinks")
@pytest.mark.parametrize("link", ["_global", "_global/CLAUDE.md"])
def test_copy_global_refuses_a_global_copy_that_leaves_the_folder(tmp_path, link):
    repo = init_repo(tmp_path / "mem")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "CLAUDE.md").write_text("theirs\n", encoding="utf-8")
    if link == "_global":
        (repo / "_global").symlink_to(outside, target_is_directory=True)
    else:
        (repo / "_global").mkdir()
        (repo / "_global" / "CLAUDE.md").symlink_to(outside / "CLAUDE.md")
    source = tmp_path / "CLAUDE.md"
    source.write_text("rules\n", encoding="utf-8")
    with pytest.raises(dream.ConfigError, match="_global"):
        dream.copy_global(repo, source)
    assert (outside / "CLAUDE.md").read_text(encoding="utf-8") == "theirs\n"


def test_reset_to_ignores_git_dir_and_work_tree_from_the_environment(tmp_path, monkeypatch):
    outer = init_repo(tmp_path / "outer")
    (outer / "dirty.md").write_text("outer work\n", encoding="utf-8")
    outer_head = git(outer, "rev-parse", "HEAD")
    repo = init_repo(tmp_path / "mem")
    snap = dream.snapshot(repo, TODAY)
    (repo / "x.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))
    dream.reset_to(repo, snap)
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    assert (outer / "dirty.md").read_text(encoding="utf-8") == "outer work\n"
    assert git(outer, "rev-parse", "HEAD") == outer_head
    assert not (repo / "x.md").exists()
