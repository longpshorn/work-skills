import datetime as dt
import os
import subprocess

import pytest

import work
from helpers import header

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=GIT_ENV)


@pytest.fixture
def repo(tmp_path):
    upstream = tmp_path / "up.git"
    git(tmp_path, "init", "-q", "--bare", str(upstream))
    clone = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(upstream), str(clone))
    (clone / "a.txt").write_text("a")
    git(clone, "add", "a.txt")
    git(clone, "commit", "-qm", "a")
    git(clone, "push", "-q", "-u", "origin", "HEAD")
    return clone


def drift(capsys, *argv):
    rc = work.main(["drift", *argv])
    return rc, capsys.readouterr().out


def test_clean_repo_reports_clean(store, write, repo, capsys):
    write("p/01-a", header(repos=f"[{repo}]"))
    assert drift(capsys, "p/01-a") == (0, "p/01-a\n  clean\n")


def test_dirty_and_ahead(store, write, repo, capsys):
    (repo / "b.txt").write_text("b")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-qm", "b")
    (repo / "a.txt").write_text("changed")
    write("p/01-a", header(repos=f"[{repo}]"))
    assert f"  {repo}: 1 uncommitted, 1 ahead, 0 behind\n" in drift(capsys, "p/01-a")[1]


def test_dirty_without_upstream(store, write, tmp_path, capsys):
    local = tmp_path / "local"
    git(tmp_path, "init", "-q", str(local))
    (local / "x.txt").write_text("x")
    write("p/01-a", header(repos=f"[{local}]"))
    assert f"  {local}: 1 uncommitted, no upstream\n" in drift(capsys, "p/01-a")[1]


def test_missing_repo_and_plain_folder(store, write, tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    write("p/01-a", header(repos=f"[{tmp_path / 'gone'}, {plain}]"))
    out = drift(capsys, "p/01-a")[1]
    assert f"  {tmp_path / 'gone'}: MISSING\n" in out
    assert f"  {plain}: not a git repo\n" in out


def test_vm_root_is_ignored_unless_set(store, write, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("WORK_VM_ROOT", raising=False)
    proj = tmp_path / "vm-share" / "proj"
    proj.mkdir(parents=True)
    git(proj, "init", "-q")
    write("p/01-a", header(repos=f"[{proj}]"))
    assert drift(capsys, "p/01-a")[1] == "p/01-a\n  clean\n"


def test_vm_root_when_set_is_not_touched(store, write, tmp_path, capsys, monkeypatch):
    mount = tmp_path / "mount"
    (mount / "proj").mkdir(parents=True)
    monkeypatch.setenv("WORK_VM_ROOT", str(mount))
    write("p/01-a", header(repos=f"[{mount / 'proj'}]"))
    expected = f"  {mount / 'proj'}: on a mount set by WORK_VM_ROOT — check it there\n"
    assert expected in drift(capsys, "p/01-a")[1]


def test_linked_files_changed_after_updated(store, write, tmp_path, capsys):
    old, new = tmp_path / "old.md", tmp_path / "new.md"
    for path, day in ((old, dt.datetime(2026, 9, 30)), (new, dt.datetime(2026, 10, 3))):
        path.write_text("x")
        os.utime(path, (day.timestamp(), day.timestamp()))
    write("p/01-a", header(updated="2026-10-01") + f"\nSee `{old}` and [new]({new}).\n")
    out = drift(capsys, "p/01-a")[1]
    assert f"  changed since 2026-10-01: {new}\n" in out
    assert str(old) not in out


def test_all_lists_only_workstreams_needing_attention(store, write, repo, tmp_path, capsys):
    write("p/01-clean", header(repos=f"[{repo}]"))
    write("p/02-gone", header(repos=f"[{tmp_path / 'gone'}]"))
    out = drift(capsys, "--all")[1]
    assert "p/02-gone" in out and "p/01-clean" not in out


def test_unknown_key(store, capsys):
    rc = work.main(["drift", "p/99-nope"])
    assert rc == 3 and "no workstream 'p/99-nope'" in capsys.readouterr().err


def test_linked_directory_with_changed_file(store, write, tmp_path, capsys):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "x.md").write_text("x")
    day = dt.datetime(2026, 10, 3).timestamp()
    os.utime(folder / "x.md", (day, day))
    write("p/01-a", header(updated="2026-10-01") + f"\nSee `{folder}/`.\n")
    assert f"  changed since 2026-10-01: {folder}/\n" in drift(capsys, "p/01-a")[1]


def test_git_timeout_is_reported_not_hung(store, write, tmp_path, capsys, monkeypatch):
    slow = tmp_path / "slow"
    slow.mkdir()

    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
    monkeypatch.setattr(work.subprocess, "run", hang)
    write("p/01-a", header(repos=f"[{slow}]"))
    assert f"  {slow}: git timed out\n" in drift(capsys, "p/01-a")[1]
