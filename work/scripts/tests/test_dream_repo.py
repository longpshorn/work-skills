import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dream
from dream_helpers import fake_bin, init_repo

pytestmark = pytest.mark.skipif(os.name == "nt", reason="needs sh fakes")

TODAY = dt.date(2026, 11, 5)
URL = "https://github.com/acme/widgets.git"
RULE = {"match": "github.com/acme/widgets", "branch": "docs/{ticket}-memory-{date}",
        "commit": "docs: {ticket} {summary}", "ticket": "TKT-1", "reviewers": ["ann", "bob"],
        "promote": True}
CAPS = {"claude_md_lines": 200}


def git(repo, *args, check=True):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check:
        assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def op(content="# Notes\nline\n"):
    return [{"op": "write", "root": "target", "path": "CLAUDE.md", "content": content}]


@pytest.fixture
def world(tmp_path, monkeypatch):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = init_repo(tmp_path / "seed", remote=str(bare))
    git(seed, "push", "-q", "origin", "main")
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(bare), str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "remote", "set-url", "origin", URL)
    git(repo, "config", "url.%s.insteadOf" % bare, URL)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "cli.log"
    state_file = tmp_path / "pr-state"
    state_file.write_text("OPEN")
    fake_bin(bin_dir, "gh", 'echo "gh $*" >> "%s"\n'
             'case "$2" in create) echo https://github.com/acme/widgets/pull/7;; '
             'view) cat "%s";; esac\n' % (log, state_file))
    fake_bin(bin_dir, "glab", 'echo "glab $*" >> "%s"\n' % log)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    memory = tmp_path / "mem"
    memory.mkdir()
    cfg = {"memory_dir": memory, "caps": CAPS, "repos": [RULE]}
    return {"bare": bare, "repo": repo, "log": log, "cfg": cfg, "pr_state": state_file}


def test_rule_for_requires_a_matching_promote_true_rule():
    cfg = {"repos": [dict(RULE, promote=False)]}
    assert dream.rule_for(URL, cfg) is None
    assert dream.rule_for("https://github.com/other/x.git", {"repos": [RULE]}) is None
    assert dream.rule_for(URL, {"repos": [RULE]}) is RULE


def test_forge_of_picks_by_host():
    assert dream.forge_of("git@github.com:a/b.git") == "github"
    assert dream.forge_of("https://github.com/a/b") == "github"
    assert dream.forge_of("ssh://git@gitlab.example.com/a/b.git") == "gitlab"
    assert dream.forge_of("https://code.example.com/a/b") is None
    assert dream.forge_of("/tmp/some/github.com/dir") is None


def test_propose_cuts_branch_in_a_worktree_commits_pushes_and_opens_one_mr(world):
    repo, state = world["repo"], dream.default_state()
    url = dream.propose(repo, RULE, op(), "tidy notes", TODAY, state, world["cfg"])
    assert url == "https://github.com/acme/widgets/pull/7"
    branch = "docs/TKT-1-memory-2026-11-05"
    assert git(repo, "branch", "--show-current") == "main"
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "CLAUDE.md").exists()
    assert git(world["bare"], "log", "-1", "--format=%s", branch) == "docs: TKT-1 tidy notes"
    assert git(world["bare"], "show", "%s:CLAUDE.md" % branch) == "# Notes\nline"
    assert "--reviewer ann,bob" in world["log"].read_text()
    assert state["open_mrs"][str(repo)]["url"] == url
    assert git(repo, "worktree", "list").count("\n") == 0
    assert git(world["bare"], "rev-parse", "main") == git(repo, "rev-parse", "main")


def test_second_night_with_open_mr_adds_a_commit_not_a_second_mr(world):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "one", TODAY, state, world["cfg"])
    later = TODAY + dt.timedelta(days=1)
    url = dream.propose(repo, RULE, op("# Notes\nmore\n"), "two", later, state, world["cfg"])
    assert url == state["open_mrs"][str(repo)]["url"]
    branch = "docs/TKT-1-memory-2026-11-05"
    assert git(world["bare"], "rev-list", "--count", "main..%s" % branch) == "2"
    assert git(world["bare"], "branch", "--list", "docs/*").count("docs/") == 1
    assert world["log"].read_text().count("pr create") == 1


def test_closed_mr_gets_a_fresh_branch_and_mr(world):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "one", TODAY, state, world["cfg"])
    world["pr_state"].write_text("MERGED")
    dream.propose(repo, RULE, op("# Notes\nmore\n"), "two", TODAY + dt.timedelta(days=1), state, world["cfg"])
    assert world["log"].read_text().count("pr create") == 2


def test_failed_push_is_recorded_and_retried_from_the_same_commit(world):
    repo, state = world["repo"], dream.default_state()
    hook = world["bare"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    assert dream.propose(repo, RULE, op(), "tidy", TODAY, state, world["cfg"]) is None
    branch = "docs/TKT-1-memory-2026-11-05"
    assert state["pending_pushes"] == [{"repo": str(repo), "branch": branch}]
    assert state["open_mrs"] == {}
    commit = git(repo, "rev-parse", branch)
    hook.unlink()
    dream.retry_pushes(state)
    assert state["pending_pushes"] == []
    assert git(world["bare"], "rev-parse", branch) == commit


def test_never_pushes_to_the_default_branch(world):
    rule = dict(RULE, branch="main")
    with pytest.raises(ValueError):
        dream.propose(world["repo"], rule, op(), "x", TODAY, dream.default_state(), world["cfg"])
    assert git(world["bare"], "rev-list", "--count", "main") == "1"


def test_over_length_claude_md_aborts_before_commit(world):
    before = git(world["bare"], "branch", "--list")
    with pytest.raises(dream.TooLong):
        dream.propose(world["repo"], RULE, op("x\n" * 201), "x", TODAY, dream.default_state(), world["cfg"])
    assert git(world["bare"], "branch", "--list") == before
    assert git(world["repo"], "branch", "--list") == "* main"
    assert git(world["repo"], "worktree", "list").count("\n") == 0
