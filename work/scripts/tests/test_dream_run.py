import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dream
import work
from dream_helpers import fake_bin, init_repo, user, write_transcript

pytestmark = pytest.mark.skipif(os.name == "nt", reason="needs sh fakes")

MEMORY = "---\nname: {name}\ndescription: about {name}\nmetadata:\n  type: feedback\n---\nBody\n"

FAKE_CLAUDE = r'''
import json, os, re, sys
args = sys.argv[1:]
system = args[args.index("--system-prompt") + 1]
prompt = sys.stdin.read()
with open(os.environ["FAKE_PLAN"]) as handle:
    plan = json.load(handle)
if "Review one proposed memory change" in prompt:
    stage = "check"
elif "mode: reorganize" in prompt:
    stage = "reorganize"
else:
    stage = "extract"
with open(os.environ["FAKE_CALLS"], "a") as handle:
    handle.write(stage + "\n")
with open(os.environ["FAKE_CALLS"] + ".argv", "a") as handle:
    handle.write(json.dumps([stage] + args) + "\n")
step = plan.get(stage, {})
result = "done"
if stage == "check":
    verdict = "approve"
    for needle, value in plan.get("verdicts", {}).items():
        if needle in prompt:
            verdict = value
    result = json.dumps({"verdict": verdict, "reason": "fake reviewer"})
else:
    memory = re.search(r"The memory folder is (.+?)\. Digests", system).group(1)
    run_dir = re.search(r"Write checks\.json in (.+?)\. The memory", system).group(1)
    for rel, text in step.get("files", {}).items():
        path = os.path.join(memory, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as handle:
            handle.write(text)
    if "ops" in step:
        with open(os.path.join(run_dir, "ops.json"), "w") as handle:
            json.dump(step["ops"], handle)
    if "checks" in step:
        with open(os.path.join(run_dir, "checks.json"), "w") as handle:
            json.dump(step["checks"], handle)
if step.get("exit"):
    sys.stderr.write("fake failure")
    sys.exit(step["exit"])
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": result}))
'''


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def memfile(name):
    return MEMORY.format(name=name)


def index(*names):
    return "## About the user\n" + "".join("- [%s](%s.md) — hook\n" % (n, n) for n in names)


@pytest.fixture
def world(dream_env, tmp_path, monkeypatch):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "old.md").write_text(memfile("old"), encoding="utf-8")
    (mem / "MEMORY.md").write_text(index("old"), encoding="utf-8")
    git(mem, "init", "-q", "-b", "main")
    git(mem, "config", "user.email", "t@example.com")
    git(mem, "config", "user.name", "t")
    git(mem, "add", "-A")
    git(mem, "commit", "-q", "-m", "init")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE, encoding="utf-8")
    claude = fake_bin(bin_dir, "claude", 'exec "%s" "%s" "$@"\n' % (sys.executable, script))
    plan, calls = tmp_path / "plan.json", tmp_path / "calls"
    monkeypatch.setenv("FAKE_PLAN", str(plan))
    monkeypatch.setenv("FAKE_CALLS", str(calls))
    gmd = dream_env.home / ".claude" / "CLAUDE.md"
    cfg = {"memory_dir": str(mem), "global_claude_md": str(gmd), "claude_bin": str(claude), "repos": []}
    w = SimpleNamespace(mem=mem, gmd=gmd, cfg=cfg, env=dream_env, tmp=tmp_path, calls=calls, sessions=0)
    w.plan = lambda data: plan.write_text(json.dumps(data), encoding="utf-8")
    w.config = lambda: (dream_env.config.parent.mkdir(parents=True, exist_ok=True),
                        dream_env.config.write_text(json.dumps(w.cfg), encoding="utf-8"))
    w.plan({})
    w.config()
    state = dream.default_state()
    state["reorganized"] = True
    dream.save_state(state)
    return w


def talk(w, count):
    """Write `count` ended conversations; returns their transcript paths and last uuids."""
    made = []
    for _ in range(count):
        w.sessions += 1
        sid = "s%d" % w.sessions
        entries = [user("remember we always run the linter", "%s-u1" % sid, session=sid),
                   user("from now on use pytest", "%s-u2" % sid, session=sid)]
        path = write_transcript(w.env.projects, "proj", sid, entries, mtime=time.time() - 3 * 3600)
        made.append((path, "%s-u2" % sid))
    return made


def run(force=False):
    return dream.dream_run(dt.datetime.now(), force, None)


def log_lines(w):
    path = w.env.state / "run.log"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def subjects(w):
    return git(w.mem, "log", "--format=%s").splitlines()[::-1]


def calls(w):
    return w.calls.read_text().split() if w.calls.exists() else []


def seed(w, names):
    for name in names:
        (w.mem / ("%s.md" % name)).write_text(memfile(name), encoding="utf-8")
    (w.mem / "MEMORY.md").write_text(index("old", *names), encoding="utf-8")
    git(w.mem, "add", "-A")
    git(w.mem, "commit", "-q", "-m", "seed")


def promotion(name, target, content=None, path="CLAUDE.md"):
    content = content or "# Global\n- rule from %s\n" % name
    return {"id": name, "kind": "promotion", "quote": "always %s" % name, "session": "s1", "uuid": "s1-u1",
            "memory": "%s.md" % name, "target": target, "summary": "promote %s" % name,
            "ops": [{"op": "write", "root": "target", "path": path, "content": content}]}


def meta(w, name):
    return dream.parse_memory((w.mem / ("%s.md" % name)).read_text(encoding="utf-8"))


def test_skips_quietly_below_three_conversations_unless_forced(world):
    made = talk(world, 2)
    assert run() == 0
    assert calls(world) == []
    assert "read=2" in log_lines(world)[-1] and log_lines(world)[-1].endswith("| ok")
    assert dream.load_state()["transcripts"] == {}
    assert run(force=True) == 0
    assert calls(world) == ["extract"]
    assert sorted(dream.load_state()["transcripts"]) == sorted(str(p) for p, _ in made)


def test_happy_path_commits_once_advances_highwater_and_logs_ok(world, capsys, monkeypatch):
    made = talk(world, 3)
    world.plan({"extract": {"files": {"new.md": memfile("new"), "MEMORY.md": index("old", "new")}}})
    monkeypatch.setattr(dream, "retry_pushes", lambda state, cfg, notes=None: notes.append("retry-note"))
    assert run() == 0
    assert capsys.readouterr().out == ""
    today = dt.date.today().isoformat()
    assert subjects(world) == ["init", "dream: %s" % today]
    assert git(world.mem, "status", "--porcelain") == ""
    state = dream.load_state()
    for path, last in made:
        assert state["transcripts"][str(path)]["uuid"] == last
    assert state["last_success"] == today
    line = log_lines(world)[-1]
    assert "read=3" in line and "added=1" in line and "retry-note" in line and "| ok" in line


def test_failed_check_resets_to_snapshot_and_keeps_highwater(world):
    talk(world, 3)
    head = git(world.mem, "rev-parse", "HEAD")
    world.plan({"extract": {"files": {"stray.md": memfile("stray")}}})
    assert run() == 1
    assert git(world.mem, "rev-parse", "HEAD") == head
    assert git(world.mem, "status", "--porcelain") == ""
    assert not (world.mem / "stray.md").exists()
    assert dream.load_state()["transcripts"] == {}
    assert "| failed: " in log_lines(world)[-1]


def test_commit_failure_keeps_highwater(world, monkeypatch):
    talk(world, 3)
    world.plan({"extract": {"files": {"new.md": memfile("new"), "MEMORY.md": index("old", "new")}}})

    def boom(memory_dir, message):
        raise dream.ConfigError("cannot commit")
    monkeypatch.setattr(dream, "commit_run", boom)
    assert run() == 1
    assert dream.load_state()["transcripts"] == {}
    assert not (world.mem / "new.md").exists()
    assert "failed: cannot commit" in log_lines(world)[-1]


def test_claude_failure_logs_and_changes_nothing(world):
    talk(world, 3)
    head = git(world.mem, "rev-parse", "HEAD")
    world.plan({"extract": {"files": {"new.md": memfile("new")}, "exit": 3}})
    assert run() == 1
    assert git(world.mem, "rev-parse", "HEAD") == head
    assert git(world.mem, "status", "--porcelain") == ""
    assert dream.load_state()["transcripts"] == {}
    lines = log_lines(world)
    assert len(lines) == 1 and "| failed: " in lines[0]


def test_missing_claude_logs_one_failed_line_and_touches_nothing(world):
    talk(world, 3)
    world.cfg["claude_bin"] = str(world.tmp / "nowhere" / "claude")
    world.config()
    (world.mem / "old.md").write_text(memfile("old") + "edited\n", encoding="utf-8")
    head = git(world.mem, "rev-parse", "HEAD")
    assert run() == 1
    assert git(world.mem, "rev-parse", "HEAD") == head
    assert git(world.mem, "status", "--porcelain") == "M old.md"
    lines = log_lines(world)
    assert len(lines) == 1 and "failed: " in lines[0] and "not found" in lines[0]


def test_unreadable_config_logs_one_failed_line(world):
    world.env.config.write_text("{not json", encoding="utf-8")
    assert run() == 1
    lines = log_lines(world)
    assert len(lines) == 1 and "failed: cannot read config" in lines[0]


@pytest.mark.parametrize("verdict, retired", [("reject", False), ("approve", True)])
def test_opus_reject_drops_the_item_and_approve_applies_it(world, verdict, retired):
    talk(world, 3)
    item = {"id": "c1", "kind": "contradiction", "quote": "we stopped doing that", "session": "s1",
            "uuid": "s1-u1", "memory": "old.md", "summary": "retire old",
            "ops": [{"op": "retire", "path": "old.md", "superseded_by": "none"}]}
    world.plan({"extract": {"checks": [item]}, "verdicts": {"retire old": verdict}})
    assert run() == 0
    assert calls(world) == ["extract", "check"]
    assert (world.mem / "_retired" / "old.md").exists() is retired
    assert (world.mem / "old.md").exists() is not retired
    assert ("retired=1" in log_lines(world)[-1]) is retired


def test_promotion_cap_and_unlisted_repo_are_enforced(world):
    talk(world, 3)
    names = ["p%d" % i for i in range(1, 9)]
    seed(world, names)
    other = init_repo(world.tmp / "other", remote="https://example.com/x/other.git")
    checks = [promotion("p8", str(other))] + [promotion(n, "global", path="%s/CLAUDE.md" % n)
                                              for n in names[:7]]
    world.plan({"extract": {"checks": checks}})
    assert run() == 0
    promoted = [n for n in names[:7] if "promoted_to" in meta(world, n)]
    assert promoted == names[:5]
    assert [n for n in names[:7] if (world.gmd.parent / n / "CLAUDE.md").exists()] == names[:5]
    assert "promoted_to" not in meta(world, "p8")
    assert not (other / "CLAUDE.md").exists()
    line = log_lines(world)[-1]
    assert "promoted=5" in line and str(other) in line and "| ok" in line


def test_second_promotion_to_the_same_target_is_deferred(world):
    talk(world, 3)
    seed(world, ["p1", "p2"])
    world.plan({"extract": {"checks": [promotion("p1", "global"), promotion("p2", "global")]}})
    assert run() == 0
    assert meta(world, "p1")["promoted_to"] == str(world.gmd)
    assert "promoted_to" not in meta(world, "p2")
    assert world.gmd.read_text(encoding="utf-8") == "# Global\n- rule from p1\n"
    line = log_lines(world)[-1]
    assert "promoted=1" in line and "item p2 dropped: deferred" in line


def test_promotion_of_a_memory_the_run_retires_is_dropped(world):
    talk(world, 3)
    seed(world, ["p1"])
    retire = {"id": "c1", "kind": "contradiction", "quote": "q", "session": "s1", "uuid": "s1-u1",
              "memory": "p1.md", "summary": "retire p1",
              "ops": [{"op": "retire", "path": "p1.md", "superseded_by": "none"}]}
    world.plan({"extract": {"checks": [promotion("p1", "global"), retire]}})
    assert run() == 0
    assert not world.gmd.exists()
    assert (world.mem / "_retired" / "p1.md").exists()
    assert "promoted_to" not in dream.parse_memory((world.mem / "_retired" / "p1.md").read_text())
    assert "item p1 dropped" in log_lines(world)[-1]


def test_first_run_commits_reorganization_before_extraction(world):
    state = dream.load_state()
    state["reorganized"] = False
    dream.save_state(state)
    talk(world, 3)
    world.plan({"reorganize": {"files": {"MEMORY.md": "## How they work\n- [old](old.md) — tighter\n"}},
                "extract": {"files": {"new.md": memfile("new"),
                                      "MEMORY.md": "## How they work\n- [old](old.md) — tighter\n"
                                                   "- [new](new.md) — hook\n"}}})
    assert run() == 0
    today = dt.date.today().isoformat()
    assert subjects(world) == ["init", "dream: first-run reorganization", "dream: %s" % today]
    assert git(world.mem, "show", "--name-only", "--format=", "HEAD~1") == "MEMORY.md\nold.md"
    assert dream.load_state()["reorganized"] is True
    assert calls(world) == ["reorganize", "extract"]
    talk(world, 3)
    world.plan({"extract": {}})
    assert run() == 0
    assert calls(world) == ["reorganize", "extract", "extract"]
    assert subjects(world).count("dream: first-run reorganization") == 1


def test_failure_after_reorganization_keeps_the_reorganization(world):
    state = dream.load_state()
    state["reorganized"] = False
    dream.save_state(state)
    talk(world, 3)
    world.plan({"reorganize": {"files": {"MEMORY.md": "## How they work\n- [old](old.md) — tighter\n"}},
                "extract": {"files": {"stray.md": memfile("stray")}}})
    assert run() == 1
    assert subjects(world)[-1] == "dream: first-run reorganization"
    assert git(world.mem, "status", "--porcelain") == ""
    assert dream.load_state()["reorganized"] is True


def test_busy_lock_exits_quietly(world):
    talk(world, 3)
    with dream.RunLock():
        assert run(force=True) == 0
    assert calls(world) == []
    assert log_lines(world) == []


def test_global_promotion_edits_global_claude_md_and_is_snapshotted_next_run(world):
    talk(world, 3)
    seed(world, ["p1"])
    world.plan({"extract": {"checks": [promotion("p1", "global")]}})
    assert run() == 0
    assert world.gmd.read_text(encoding="utf-8") == "# Global\n- rule from p1\n"
    assert meta(world, "p1")["promoted_to"] == str(world.gmd)
    assert not (world.mem / "_global" / "CLAUDE.md").exists()
    assert "promoted=1" in log_lines(world)[-1]
    talk(world, 1)
    world.plan({"extract": {}})
    assert run(force=True) == 0
    assert git(world.mem, "show", "HEAD:_global/CLAUDE.md") == "# Global\n- rule from p1"
    assert "dream: refresh global CLAUDE.md copy" in subjects(world)


def test_dream_status_reports_after_a_failed_run(world):
    talk(world, 3)
    world.plan({"extract": {"exit": 2}})
    assert run() == 1
    assert dream.dream_status(dt.date.today()).startswith("dream: last run failed (claude exited 2")


def test_over_length_promotion_is_dropped_and_logged_not_fatal(world):
    talk(world, 3)
    seed(world, ["p1", "p2"])
    long_text = "".join("- line %d\n" % i for i in range(201))
    world.plan({"extract": {"checks": [promotion("p1", "global", long_text), promotion("p2", "global")]}})
    assert run() == 0
    assert "promoted_to" not in meta(world, "p1")
    assert meta(world, "p2")["promoted_to"] == str(world.gmd)
    assert world.gmd.read_text(encoding="utf-8") == "# Global\n- rule from p2\n"
    line = log_lines(world)[-1]
    assert "promoted=1" in line and "exceed" in line


def test_restore_failed_from_apply_still_resets_to_snapshot(world, monkeypatch):
    talk(world, 3)
    head = git(world.mem, "rev-parse", "HEAD")
    item = {"id": "c1", "kind": "contradiction", "quote": "q", "session": "s1", "uuid": "s1-u1",
            "memory": "old.md", "summary": "retire old",
            "ops": [{"op": "retire", "path": "old.md", "superseded_by": "none"}]}
    world.plan({"extract": {"files": {"new.md": memfile("new"), "MEMORY.md": index("old", "new")},
                            "checks": [item]}})

    def half_applied(ops, memory_dir, target_root, today, caps):
        (memory_dir / "half.md").write_text("partial", encoding="utf-8")
        raise dream.RestoreFailed("rollback could not restore: old.md")
    monkeypatch.setattr(dream, "apply_ops", half_applied)
    assert run() == 1
    assert git(world.mem, "rev-parse", "HEAD") == head
    assert git(world.mem, "status", "--porcelain") == ""
    assert "failed: rollback could not restore" in log_lines(world)[-1]


RULE = {"match": "acme/widgets", "branch": "docs/memory-{date}", "commit": "docs: {summary}", "promote": True}


def forge_repo(world, monkeypatch, url="https://github.com/acme/widgets.git", origin_files=None, name="repo"):
    """A checkout whose origin is a local bare repo behind `url`, with a fake gh; returns (repo, bare)."""
    bare = world.tmp / ("origin-%s.git" % name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed_repo = init_repo(world.tmp / ("seed-%s" % name), remote=str(bare))
    for rel, text in (origin_files or {}).items():
        (seed_repo / rel).write_text(text, encoding="utf-8")
        git(seed_repo, "add", "-A")
        git(seed_repo, "commit", "-q", "-m", "files")
    git(seed_repo, "push", "-q", "origin", "main")
    repo = world.tmp / name
    subprocess.run(["git", "clone", "-q", str(bare), str(repo)], check=True)
    git(repo, "remote", "set-url", "origin", url)
    git(repo, "config", "url.%s.insteadOf" % bare, url)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    forge_bin = world.tmp / "forge-bin"
    if name != "repo":
        return repo, bare
    forge_bin.mkdir()
    fake_bin(forge_bin, "gh", 'case "$2" in create) echo https://github.com/acme/widgets/pull/7;; '
                              'list) echo "[]";; esac\n')
    monkeypatch.setenv("PATH", str(forge_bin) + os.pathsep + os.environ["PATH"])
    world.cfg["repos"] = [RULE]
    world.config()
    talk(world, 3)
    seed(world, ["p1"])
    return repo, bare


def test_repo_promotion_proposes_after_the_memory_commit(world, monkeypatch):
    repo, bare = forge_repo(world, monkeypatch)
    world.plan({"extract": {"checks": [promotion("p1", str(repo), "# Repo\n- run the linter\n")]}})
    assert run() == 0
    branch = "docs/memory-%s" % dt.date.today().isoformat()
    assert git(bare, "show", "%s:CLAUDE.md" % branch) == "# Repo\n- run the linter"
    assert not (repo / "CLAUDE.md").exists()
    assert meta(world, "p1")["promoted_to"] == str(repo.resolve() / "CLAUDE.md")
    assert subjects(world)[-1] == "dream: mark promoted"
    assert git(world.mem, "show", "--name-only", "--format=", "HEAD") == "p1.md"
    assert git(world.mem, "status", "--porcelain") == ""
    line = log_lines(world)[-1]
    assert "mrs=https://github.com/acme/widgets/pull/7" in line and "promoted=1" in line
    assert dream.load_state()["open_mrs"][str(repo.resolve())]["number"] == 7


def _unrecorded_branch(world, repo, bare):
    git(repo, "push", "-q", "origin", "main:refs/heads/docs/memory-%s" % dt.date.today().isoformat())


def _diverged(world, repo, bare):
    git(repo, "checkout", "-q", "-b", "docs/memory-old")
    (repo / "x.txt").write_text("theirs\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "theirs")
    git(repo, "push", "-q", "origin", "docs/memory-old")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    (repo / "x.txt").write_text("mine\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "mine")
    git(repo, "checkout", "-q", "main")
    _record(repo, "docs/memory-old")


def _guard_refuses(world, repo, bare):
    _record(repo, "main")


def _record(repo, branch):
    state = dream.load_state()
    state["open_mrs"][str(repo.resolve())] = {"branch": branch, "forge": "github", "number": None, "url": None}
    dream.save_state(state)


@pytest.mark.parametrize("url, setup", [
    ("https://github.com/acme/widgets.git", _unrecorded_branch),
    ("https://github.com/acme/widgets.git", _diverged),
    ("https://code.example.com/acme/widgets.git", None),
    ("https://github.com/acme/widgets.git", _guard_refuses),
], ids=["unrecorded-branch", "diverged", "no-forge", "guard"])
def test_failed_proposal_leaves_the_memory_unmarked(world, monkeypatch, url, setup):
    repo, bare = forge_repo(world, monkeypatch, url=url)
    if setup:
        setup(world, repo, bare)
    world.plan({"extract": {"checks": [promotion("p1", str(repo), "# Repo\n- run the linter\n")]}})
    assert run() == 0
    assert "promoted_to" not in meta(world, "p1")
    assert "dream: mark promoted" not in subjects(world)
    assert git(world.mem, "status", "--porcelain") == ""
    assert "promoted=0" in log_lines(world)[-1]


@pytest.mark.parametrize("local, reviewed", [("# Repo\n", True), ("# Repo\nlocal edit\n", False)],
                         ids=["identical", "differs"])
def test_repo_promotion_needs_the_checkout_to_match_the_landing_ref(world, monkeypatch, local, reviewed):
    repo, bare = forge_repo(world, monkeypatch, origin_files={"CLAUDE.md": "# Repo\n"})
    (repo / "CLAUDE.md").write_text(local, encoding="utf-8")
    world.plan({"extract": {"checks": [promotion("p1", str(repo), "# Repo\n- run the linter\n")]}})
    assert run() == 0
    assert ("check" in calls(world)) is reviewed
    assert ("promoted_to" in meta(world, "p1")) is reviewed
    if not reviewed:
        assert "item p1 dropped: deferred" in log_lines(world)[-1]


def test_repo_promotion_target_must_be_the_repo_top_level(world, monkeypatch):
    repo, bare = forge_repo(world, monkeypatch)
    (repo / "sub").mkdir()
    world.plan({"extract": {"checks": [promotion("p1", str(repo / "sub"), "# Repo\n")]}})
    assert run() == 0
    assert calls(world) == ["extract"]
    assert "promoted_to" not in meta(world, "p1")
    assert "not the top level" in log_lines(world)[-1]


def test_cli_dream_run_now_forces_and_prints_nothing(world, capsys):
    talk(world, 1)
    assert work.main(["dream-run", "--now"]) == 0
    assert capsys.readouterr().out == ""
    assert calls(world) == ["extract"]


def test_failure_after_a_global_write_puts_the_global_file_back(world, monkeypatch):
    talk(world, 3)
    seed(world, ["p1"])
    world.gmd.parent.mkdir(parents=True)
    world.gmd.write_text("# Mine\n", encoding="utf-8")
    world.plan({"extract": {"checks": [promotion("p1", "global")]}})

    def boom(memory_dir, message):
        raise dream.ConfigError("cannot commit")
    monkeypatch.setattr(dream, "commit_run", boom)
    assert run() == 1
    assert world.gmd.read_text(encoding="utf-8") == "# Mine\n"
    assert "promoted_to" not in meta(world, "p1")


def test_landing_ref_is_origin_when_the_recorded_branch_is_behind_it(world, monkeypatch):
    repo, bare = forge_repo(world, monkeypatch)
    git(repo, "branch", "docs/memory-old", "main")
    reviewer = world.tmp / "reviewer"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(bare), str(reviewer)], check=True)
    git(reviewer, "config", "user.email", "r@example.com")
    git(reviewer, "config", "user.name", "r")
    (reviewer / "CLAUDE.md").write_text("# Repo\n- reviewer edit\n", encoding="utf-8")
    git(reviewer, "add", "-A")
    git(reviewer, "commit", "-q", "-m", "review")
    git(reviewer, "push", "-q", "origin", "HEAD:refs/heads/docs/memory-old")
    _record(repo, "docs/memory-old")
    world.plan({"extract": {"checks": [promotion("p1", str(repo), "# Repo\n- run the linter\n")]}})
    assert run() == 0
    assert "check" not in calls(world)
    assert "item p1 dropped: deferred" in log_lines(world)[-1]
    assert git(bare, "show", "docs/memory-old:CLAUDE.md") == "# Repo\n- reviewer edit"
    assert "promoted_to" not in meta(world, "p1")


def test_open_mrs_recorded_before_a_later_repo_fails_are_saved(world, monkeypatch):
    repo, _ = forge_repo(world, monkeypatch)
    other, _ = forge_repo(world, monkeypatch, url="https://github.com/acme/widgets-two.git", name="other")
    seed(world, ["p1", "p2"])

    def fake_propose(repo_path, rule, ops, summary, today, state, cfg, notes=None):
        if repo_path == other.resolve():
            raise dream.RestoreFailed("rollback could not restore: CLAUDE.md")
        state["open_mrs"][str(repo_path)] = {"branch": "b", "forge": "github", "number": 7, "url": "u"}
        return "u"
    monkeypatch.setattr(dream, "propose", fake_propose)
    world.plan({"extract": {"checks": [promotion("p1", str(repo), "# Repo\n- a\n"),
                                       promotion("p2", str(other), "# Repo\n- b\n")]}})
    assert run() == 1
    assert dream.load_state()["open_mrs"][str(repo.resolve())]["number"] == 7
    assert "failed: " in log_lines(world)[-1]


def test_extract_stage_dates_itself_from_the_run_date(world):
    seed(world, ["twin"])
    talk(world, 3)
    world.plan({"extract": {"ops": [{"op": "retire", "path": "twin.md", "superseded_by": "none"}]}})
    assert dream.dream_run(dt.datetime(2030, 1, 2, 2, 0), True, None) == 0
    argvs = [json.loads(l) for l in (world.calls.parent / "calls.argv").read_text().splitlines()]
    extract = next(a for a in argvs if a[0] == "extract")
    assert "Today's date is 2030-01-02" in extract[extract.index("--system-prompt") + 1]
    retired = dream.parse_memory((world.mem / "_retired" / "twin.md").read_text(encoding="utf-8"))
    assert retired["retired"] == "2030-01-02"


def test_extract_stage_is_confined_to_the_memory_and_run_folders_and_runs_no_command(world):
    talk(world, 3)
    world.plan({"extract": {"checks": [{"id": "c", "kind": "contradiction", "memory": "old.md", "ops": [
        {"op": "retire", "path": "old.md", "superseded_by": "none"}]}]}})
    assert run() == 0
    argvs = [json.loads(line) for line in (world.calls.parent / "calls.argv").read_text().splitlines()]
    extract = next(a for a in argvs if a[0] == "extract")
    mem = str(world.mem.resolve()).lstrip("/")
    assert extract[extract.index("--permission-mode") + 1] == "dontAsk"
    allowed = extract[extract.index("--allowedTools") + 1:extract.index("--disallowedTools")]
    assert "Edit(//%s/**)" % mem in allowed and not any(t.startswith("Write(") for t in allowed)
    denied = extract[extract.index("--disallowedTools") + 1:extract.index("--add-dir")]
    assert denied == ["Edit(//%s/%s)" % (mem, p) for p in ("_global/**", ".git/**", ".gitignore")]
    assert not any(t.startswith("Bash") for t in allowed)
    assert "Bash" not in extract[extract.index("--tools") + 1].split(",")
    check = next(a for a in argvs if a[0] == "check")
    assert "--permission-mode" not in check and check[check.index("--tools") + 1] == ""
    for argv in (extract, check):
        assert argv[argv.index("--setting-sources") + 1] == "project,local"


def test_a_merge_retires_the_absorbed_file_through_ops_json(world):
    seed(world, ["twin"])
    talk(world, 3)
    world.plan({"extract": {
        "files": {"merged.md": memfile("merged"), "MEMORY.md": index("old", "twin", "merged")},
        "ops": [{"op": "retire", "path": "twin.md", "superseded_by": "merged"}]}})
    assert run() == 0
    assert not (world.mem / "twin.md").exists()
    retired = dream.parse_memory((world.mem / "_retired" / "twin.md").read_text(encoding="utf-8"))
    assert retired["superseded_by"] == "merged" and retired["retired"] == dt.date.today().isoformat()
    assert "(twin.md)" not in (world.mem / "MEMORY.md").read_text(encoding="utf-8")
    assert dream.check_memory(world.mem, dream.DEFAULTS["caps"]) == []
    assert calls(world).count("check") == 0
    assert log_lines(world)[-1].endswith("| ok")


def test_ops_json_with_a_write_op_fails_and_resets(world):
    talk(world, 3)
    before = git(world.mem, "rev-parse", "HEAD")
    world.plan({"extract": {"files": {"new.md": memfile("new"), "MEMORY.md": index("old", "new")},
                            "ops": [{"op": "write", "root": "memory", "path": "x.md", "content": "x"}]}})
    assert run() == 1
    assert git(world.mem, "rev-parse", "HEAD") == before and not (world.mem / "new.md").exists()
    assert not (world.mem / "x.md").exists()
    assert "ops.json" in log_lines(world)[-1] and "| failed" in log_lines(world)[-1]
    assert dream.load_state()["transcripts"] == {}


def test_ops_json_with_a_target_root_op_fails(world):
    talk(world, 3)
    world.plan({"extract": {"ops": [{"op": "retire", "root": "target", "path": "old.md", "superseded_by": "none"}]}})
    assert run() == 1
    assert (world.mem / "old.md").is_file()


def test_ops_json_that_is_not_a_list_fails(world):
    talk(world, 3)
    world.plan({"extract": {"ops": {"op": "retire"}}})
    assert run() == 1


def test_ops_json_is_applied_in_reorganize_mode_and_not_reapplied(world):
    seed(world, ["twin"])
    state = dream.load_state()
    state["reorganized"] = False
    dream.save_state(state)
    talk(world, 3)
    world.plan({"reorganize": {"ops": [{"op": "retire", "path": "twin.md", "superseded_by": "none"}],
                               "files": {"MEMORY.md": index("old")}},
                "extract": {}})
    assert run() == 0
    assert (world.mem / "_retired" / "twin.md").is_file() and not (world.mem / "twin.md").exists()
    assert subjects(world)[2] == "dream: first-run reorganization"
    assert "_retired/twin.md" in git(world.mem, "show", "--name-only", "--format=", "HEAD")
    assert log_lines(world)[-1].endswith("| ok")


def test_max_digests_passes_the_oldest_and_leaves_the_rest_for_the_next_night(world):
    world.cfg["caps"] = {"max_digests": 2}
    world.config()
    made = talk(world, 3)
    for offset, (path, _) in enumerate(made):
        stamp = time.time() - (10 - offset) * 3600
        os.utime(str(path), (stamp, stamp))
    assert run(force=True) == 0
    argvs = [json.loads(l) for l in (world.calls.parent / "calls.argv").read_text().splitlines()]
    system = argvs[-1][argvs[-1].index("--system-prompt") + 1]
    assert "s1.md" in system and "s2.md" in system and "s3.md" not in system
    assert sorted(dream.load_state()["transcripts"]) == sorted(str(p) for p, _ in made[:2])
    assert "read=2" in log_lines(world)[-1]
    assert run(force=True) == 0
    assert sorted(dream.load_state()["transcripts"]) == sorted(str(p) for p, _ in made)


def test_max_digests_defaults_to_forty():
    assert dream.DEFAULTS["caps"]["max_digests"] == 40


def test_first_run_backfills_seen_and_sources_from_mtime_in_the_reorganization_commit(world):
    state = dream.load_state()
    state["reorganized"] = False
    dream.save_state(state)
    kept = memfile("kept").replace("---\nBody", "seen: [2026-01-01]\nsources: [s:u]\n---\nBody")
    (world.mem / "kept.md").write_text(kept, encoding="utf-8")
    (world.mem / "MEMORY.md").write_text(index("old", "kept"), encoding="utf-8")
    stamp = dt.datetime(2026, 3, 4, 12, 0).timestamp()
    os.utime(str(world.mem / "old.md"), (stamp, stamp))
    talk(world, 3)
    world.plan({"reorganize": {}, "extract": {}})
    assert run() == 0
    reorg = git(world.mem, "log", "--format=%H", "--grep", "first-run reorganization")
    old = dream.parse_memory(git(world.mem, "show", "%s:old.md" % reorg))
    assert old["seen"] == ["2026-03-04"] and old["sources"] == []
    assert old["name"] == "old" and old["metadata"] == {"type": "feedback"}
    assert dream.parse_memory(git(world.mem, "show", "%s:kept.md" % reorg))["seen"] == ["2026-01-01"]
    assert dream.parse_memory(git(world.mem, "show", "%s:kept.md" % reorg))["sources"] == ["s:u"]


def test_backfill_skips_files_without_frontmatter(tmp_path):
    (tmp_path / "bad.md").write_text("no frontmatter\n", encoding="utf-8")
    (tmp_path / "MEMORY.md").write_text("## x\n", encoding="utf-8")
    dream.backfill_frontmatter(tmp_path)
    assert (tmp_path / "bad.md").read_text(encoding="utf-8") == "no frontmatter\n"
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "## x\n"


@pytest.mark.parametrize("shape", [[], "x", {"caps": 3}, {"models": []}, {"schedule": "02:00"}])
def test_a_config_of_the_wrong_shape_logs_one_failed_line(world, shape):
    data = dict(world.cfg, **shape) if isinstance(shape, dict) else shape
    world.env.config.write_text(json.dumps(data), encoding="utf-8")
    talk(world, 3)
    assert run() == 1
    lines = log_lines(world)
    assert len(lines) == 1 and "| failed: " in lines[0] and "must be an object" in lines[0]
    assert calls(world) == []


def test_an_unreadable_state_file_fails_the_run_and_is_left_alone(world):
    (world.env.state / "state.json").unlink()
    (world.env.state / "state.json").mkdir()
    talk(world, 3)
    assert run() == 1
    lines = log_lines(world)
    assert len(lines) == 1 and "| failed: " in lines[0]
    assert (world.env.state / "state.json").is_dir() and calls(world) == []


def test_a_reset_state_keeps_a_reorganization_already_in_the_memory_history(world):
    git(world.mem, "commit", "-q", "--allow-empty", "-m", "dream: first-run reorganization")
    (world.env.state / "state.json").write_text("{not json", encoding="utf-8")
    talk(world, 3)
    world.plan({"extract": {}})
    assert run() == 0
    assert calls(world) == ["extract"]
    assert dream.load_state()["reorganized"] is True


def test_an_unexpected_error_before_the_snapshot_logs_one_failed_line(world, monkeypatch):
    def boom(state, cfg, notes=None):
        raise RuntimeError("retry exploded")
    monkeypatch.setattr(dream, "retry_pushes", boom)
    talk(world, 3)
    assert run() == 1
    lines = log_lines(world)
    assert len(lines) == 1 and "failed: retry exploded" in lines[0] and calls(world) == []
