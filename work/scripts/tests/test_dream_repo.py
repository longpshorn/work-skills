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
    state_file.write_text('{"state": "OPEN"}')
    fake_bin(bin_dir, "gh", 'echo "gh $*" >> "%s"\n'
             'case "$2" in create) echo https://github.com/acme/widgets/pull/7;; '
             'view) cat "%s";; list) cat "%s";; esac\n' % (log, state_file, tmp_path / "pr-list"))
    fake_bin(bin_dir, "glab", 'echo "glab $*" >> "%s"\n'
             'case "$2" in create) echo https://gitlab.example.com/acme/widgets/-/merge_requests/9;; '
             'view) cat "%s";; list) cat "%s";; esac\n' % (log, state_file, tmp_path / "pr-list"))
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    memory = tmp_path / "mem"
    memory.mkdir()
    cfg = {"memory_dir": memory, "caps": CAPS, "repos": [RULE]}
    listing = tmp_path / "pr-list"
    listing.write_text("[]")
    return {"listing": listing, "bare": bare, "repo": repo, "log": log, "cfg": cfg, "pr_state": state_file}


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
    assert state["open_mrs"][str(repo.resolve())]["url"] == url
    assert git(repo, "worktree", "list").count("\n") == 0
    assert git(world["bare"], "rev-parse", "main") == git(repo, "rev-parse", "main")


def test_second_night_with_open_mr_adds_a_commit_not_a_second_mr(world):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "one", TODAY, state, world["cfg"])
    later = TODAY + dt.timedelta(days=1)
    url = dream.propose(repo, RULE, op("# Notes\nmore\n"), "two", later, state, world["cfg"])
    assert url == state["open_mrs"][str(repo.resolve())]["url"]
    branch = "docs/TKT-1-memory-2026-11-05"
    assert git(world["bare"], "rev-list", "--count", "main..%s" % branch) == "2"
    assert git(world["bare"], "branch", "--list", "docs/*").count("docs/") == 1
    assert world["log"].read_text().count("pr create") == 1


def test_closed_mr_gets_a_fresh_branch_and_mr(world):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "one", TODAY, state, world["cfg"])
    world["pr_state"].write_text('{"state": "MERGED"}')
    dream.propose(repo, RULE, op("# Notes\nmore\n"), "two", TODAY + dt.timedelta(days=1), state, world["cfg"])
    assert world["log"].read_text().count("pr create") == 2


def block_pushes(world):
    hook = world["bare"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    return hook


BRANCH = "docs/TKT-1-memory-2026-11-05"


def test_failed_push_is_retried_next_night_on_the_same_branch(world):
    repo, state = world["repo"], dream.default_state()
    hook = block_pushes(world)
    notes = []
    assert dream.propose(repo, RULE, op(), "tidy", TODAY, state, world["cfg"], notes) is None
    assert notes
    record = state["open_mrs"][str(repo.resolve())]
    assert record["branch"] == BRANCH and record["number"] is None
    commit = git(repo, "rev-parse", BRANCH)
    hook.unlink()
    later = TODAY + dt.timedelta(days=1)
    url = dream.propose(repo, RULE, op(), "tidy", later, state, world["cfg"])
    assert url == "https://github.com/acme/widgets/pull/7"
    assert git(world["bare"], "rev-parse", BRANCH) == commit
    assert git(world["bare"], "branch", "--list", "docs/*").count("docs/") == 1


def test_retry_pushes_publishes_an_orphan_branch(world):
    repo, state = world["repo"], dream.default_state()
    hook = block_pushes(world)
    dream.propose(repo, RULE, op(), "tidy", TODAY, state, world["cfg"])
    hook.unlink()
    dream.retry_pushes(state, world["cfg"])
    assert state["open_mrs"][str(repo.resolve())]["number"] == 7
    assert git(world["bare"], "rev-parse", BRANCH) == git(repo, "rev-parse", BRANCH)


def test_create_failure_is_retried_on_the_same_branch(world, monkeypatch):
    repo, state = world["repo"], dream.default_state()
    real = dream.create_mr

    def boom(*a):
        raise dream.ConfigError("down")

    monkeypatch.setattr(dream, "create_mr", boom)
    assert dream.propose(repo, RULE, op(), "tidy", TODAY, state, world["cfg"]) is None
    monkeypatch.setattr(dream, "create_mr", real)
    url = dream.propose(repo, RULE, op(), "tidy", TODAY + dt.timedelta(days=1), state, world["cfg"])
    assert url and state["open_mrs"][str(repo.resolve())]["branch"] == BRANCH
    assert git(world["bare"], "branch", "--list", "docs/*").count("docs/") == 1


def test_closed_mr_whose_name_is_still_taken_is_skipped(world):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "one", TODAY, state, world["cfg"])
    world["pr_state"].write_text('{"state": "MERGED"}')
    notes = []
    assert dream.propose(repo, RULE, op("# N\nz\n"), "two", TODAY, state, world["cfg"], notes) is None
    assert notes and state["open_mrs"] == {}


def test_unreadable_mr_status_skips_the_repo(world):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "one", TODAY, state, world["cfg"])
    world["pr_state"].write_text("not json")
    notes = []
    assert dream.propose(repo, RULE, op("# N\nz\n"), "two", TODAY + dt.timedelta(days=1),
                         state, world["cfg"], notes) is None
    assert notes and world["log"].read_text().count("pr create") == 1


def test_github_calls_are_pinned_to_the_repo_slug(world):
    dream.propose(world["repo"], RULE, op(), "one", TODAY, dream.default_state(), world["cfg"])
    assert "-R acme/widgets" in world["log"].read_text()


def test_gitlab_create_and_view(world):
    repo, state = world["repo"], dream.default_state()
    glab = "https://gitlab.example.com/acme/widgets.git"
    git(repo, "remote", "set-url", "origin", glab)
    git(repo, "config", "url.%s.insteadOf" % world["bare"], glab)
    rule = dict(RULE, match="gitlab.example.com/acme/widgets")
    url = dream.propose(repo, rule, op(), "one", TODAY, state, world["cfg"])
    assert url.endswith("/merge_requests/9")
    world["pr_state"].write_text('{"state": "opened"}')
    again = dream.propose(repo, rule, op("# N\nz\n"), "two", TODAY + dt.timedelta(days=1), state, world["cfg"])
    assert again == url
    log = world["log"].read_text()
    assert "glab mr create" in log and "glab mr view 9 -F json" in log


def test_case_variant_of_the_default_branch_is_refused(world):
    rule = dict(RULE, branch="Main")
    head = git(world["repo"], "rev-parse", "main")
    with pytest.raises(ValueError):
        dream.propose(world["repo"], rule, op(), "x", TODAY, dream.default_state(), world["cfg"])
    assert git(world["repo"], "rev-parse", "main") == head


def test_branch_checked_out_in_another_worktree_is_refused(world, tmp_path):
    git(world["repo"], "worktree", "add", "-q", "-b", "Docs/Mine", str(tmp_path / "other"))
    rule = dict(RULE, branch="docs/mine")
    with pytest.raises(ValueError):
        dream.propose(world["repo"], rule, op(), "x", TODAY, dream.default_state(), world["cfg"])


def test_existing_unrecorded_branch_is_skipped_and_untouched(world):
    repo = world["repo"]
    git(repo, "branch", BRANCH)
    head = git(repo, "rev-parse", BRANCH)
    notes = []
    assert dream.propose(repo, RULE, op(), "x", TODAY, dream.default_state(), world["cfg"], notes) is None
    assert notes and git(repo, "rev-parse", BRANCH) == head
    assert git(world["bare"], "branch", "--list", "docs/*") == ""


def test_origin_head_is_resolved_without_set_head(world):
    repo = world["repo"]
    git(repo, "config", "remote.origin.followRemoteHEAD", "never")
    git(repo, "remote", "set-head", "origin", "-d")
    url = dream.propose(repo, RULE, op(), "one", TODAY, dream.default_state(), world["cfg"])
    assert url
    assert git(repo, "symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False) == ""


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


def test_orphan_branch_under_a_case_variant_directory_is_reused(world):
    repo, state = world["repo"], dream.default_state()
    git(repo, "branch", "Docs/other")
    hook = block_pushes(world)
    dream.propose(repo, RULE, op(), "x", TODAY, state, world["cfg"])
    commit = git(repo, "rev-parse", "refs/heads/" + BRANCH)
    hook.unlink()
    url = dream.propose(repo, RULE, op("# Notes\nmore\n"), "y", TODAY + dt.timedelta(days=1), state, world["cfg"])
    assert url
    assert git(world["bare"], "rev-parse", "refs/heads/" + BRANCH + "~1") == commit


def test_second_night_under_a_case_variant_directory_adds_a_commit(world):
    repo, state = world["repo"], dream.default_state()
    git(repo, "branch", "Docs/other")
    notes = []
    first = dream.propose(repo, RULE, op(), "x", TODAY, state, world["cfg"], notes)
    second = dream.propose(repo, RULE, op("# Notes\nmore\n"), "y", TODAY + dt.timedelta(days=1),
                           state, world["cfg"], notes)
    assert first and first == second, notes
    assert git(world["bare"], "rev-list", "--count", "main..refs/heads/" + BRANCH) == "2"


def test_an_open_mr_for_the_branch_is_adopted_not_duplicated(world):
    world["listing"].write_text('[{"number": 12, "url": "https://github.com/acme/widgets/pull/12"}]')
    repo, state = world["repo"], dream.default_state()
    url = dream.propose(repo, RULE, op(), "x", TODAY, state, world["cfg"])
    assert url.endswith("/pull/12")
    assert state["open_mrs"][str(repo.resolve())]["number"] == 12
    log = world["log"].read_text()
    assert "pr create" not in log and "pr list --head " + BRANCH in log and "-R acme/widgets" in log


def test_a_gitlab_mr_for_the_branch_is_adopted(world):
    repo, state = world["repo"], dream.default_state()
    glab = "https://gitlab.example.com/acme/widgets.git"
    git(repo, "remote", "set-url", "origin", glab)
    git(repo, "config", "url.%s.insteadOf" % world["bare"], glab)
    world["listing"].write_text('[{"iid": 5, "web_url": "https://gitlab.example.com/acme/widgets/-/merge_requests/5"}]')
    rule = dict(RULE, match="gitlab.example.com/acme/widgets")
    url = dream.propose(repo, rule, op(), "x", TODAY, state, world["cfg"])
    assert url.endswith("/merge_requests/5")
    log = world["log"].read_text()
    assert "mr create" not in log and "glab mr list --source-branch " + BRANCH + " -F json" in log


def test_create_that_printed_no_number_is_adopted_next_night(world, monkeypatch):
    repo, state = world["repo"], dream.default_state()
    real = dream.create_mr
    monkeypatch.setattr(dream, "create_mr", lambda *a: "https://github.com/acme/widgets/pulls")
    assert dream.propose(repo, RULE, op(), "x", TODAY, state, world["cfg"]) is None
    monkeypatch.setattr(dream, "create_mr", real)
    world["listing"].write_text('[{"number": 3, "url": "https://github.com/acme/widgets/pull/3"}]')
    url = dream.propose(repo, RULE, op(), "x", TODAY + dt.timedelta(days=1), state, world["cfg"])
    assert url.endswith("/pull/3") and world["log"].read_text().count("pr create") == 0


def test_diverged_recorded_branch_skips_the_repo_without_pushing(world, tmp_path):
    repo, state = world["repo"], dream.default_state()
    dream.propose(repo, RULE, op(), "x", TODAY, state, world["cfg"])
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(world["bare"]), str(other)], check=True)
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    git(other, "checkout", "-q", "-B", BRANCH, "origin/main")
    (other / "x.md").write_text("x\n")
    git(other, "add", ".")
    git(other, "commit", "-q", "-m", "reviewer edit")
    git(other, "push", "-q", "-f", "origin", BRANCH)
    remote_head = git(world["bare"], "rev-parse", "refs/heads/" + BRANCH)
    notes = []
    assert dream.propose(repo, RULE, op("# Notes\nmore\n"), "y", TODAY + dt.timedelta(days=1),
                         state, world["cfg"], notes) is None
    assert any("diverge" in n for n in notes)
    assert git(world["bare"], "rev-parse", "refs/heads/" + BRANCH) == remote_head


def test_retry_pushes_continues_past_a_failing_repo(world):
    repo, state = world["repo"], dream.default_state()
    hook = block_pushes(world)
    dream.propose(repo, RULE, op(), "x", TODAY, state, world["cfg"])
    hook.unlink()
    good = state["open_mrs"].pop(str(repo.resolve()))
    state["open_mrs"]["/nonexistent/repo"] = {"branch": "x", "forge": "github", "number": None, "url": None}
    state["open_mrs"][str(repo.resolve())] = good
    notes = []
    dream.retry_pushes(state, world["cfg"], notes)
    assert notes
    assert state["open_mrs"][str(repo.resolve())]["number"] == 7


def test_default_state_has_no_pending_pushes():
    assert "pending_pushes" not in dream.default_state()
