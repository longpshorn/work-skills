import datetime as dt
import os
import subprocess
import sys

import pytest

import dream
import work


def test_state_round_trip_and_defaults(dream_env):
    assert dream.load_state() == {"version": 1, "transcripts": {}, "last_run": None, "last_success": None,
                                  "reorganized": False, "open_mrs": {}, "pending_pushes": []}
    state = dream.load_state()
    state["transcripts"]["a"] = {"mtime": 1.5, "uuid": "u1"}
    dream.save_state(state)
    assert dream.load_state() == state
    assert [p.name for p in dream_env.state.iterdir()] == ["state.json"]


def test_corrupt_state_is_set_aside(dream_env):
    dream_env.state.mkdir(parents=True)
    (dream_env.state / "state.json").write_text("{not json", encoding="utf-8")
    assert dream.load_state()["transcripts"] == {}
    assert (dream_env.state / "state.json.bad").read_text(encoding="utf-8") == "{not json"
    assert not (dream_env.state / "state.json").exists()


def _dead_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_lock_blocks_a_live_pid_and_takes_over_a_dead_one(dream_env):
    dream_env.state.mkdir(parents=True)
    lock = dream_env.state / "lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    with pytest.raises(dream.Busy):
        with dream.RunLock():
            pass
    assert lock.read_text(encoding="utf-8") == str(os.getpid())
    lock.write_text(str(_dead_pid()), encoding="utf-8")
    with dream.RunLock():
        assert lock.read_text(encoding="utf-8") == str(os.getpid())


def test_lock_with_unreadable_pid_is_taken_over(dream_env):
    dream_env.state.mkdir(parents=True)
    (dream_env.state / "lock").write_text("garbage", encoding="utf-8")
    with dream.RunLock():
        pass


def test_lock_is_released_on_exit_and_on_exception(dream_env):
    lock = dream_env.state / "lock"
    with dream.RunLock():
        assert lock.exists()
    assert not lock.exists()
    with pytest.raises(RuntimeError):
        with dream.RunLock():
            raise RuntimeError("boom")
    assert not lock.exists()


def test_log_line_format():
    counts = {"added": 2, "updated": 1, "retired": 0, "promoted": 3}
    day = dt.date(2026, 11, 5)
    assert dream.log_line(day, 7, counts, ["https://x/1", "https://x/2"], True) == (
        "2026-11-05 | read=7 | added=2 updated=1 retired=0 promoted=3 | mrs=https://x/1 https://x/2 | ok")
    assert dream.log_line(day, 0, {}, [], False, "no login") == (
        "2026-11-05 | read=0 | added=0 updated=0 retired=0 promoted=0 | mrs=- | failed: no login")


def test_append_log_appends_lines(dream_env):
    dream.append_log("one")
    dream.append_log("two")
    assert (dream_env.state / "run.log").read_text(encoding="utf-8") == "one\ntwo\n"


TODAY = dt.date(2026, 11, 5)


def _ok(day):
    return dream.log_line(day, 3, {}, [], True)


def test_status_silent_when_healthy_and_never_run(dream_env):
    assert dream.dream_status(TODAY) is None
    dream.append_log(_ok(TODAY))
    state = dream.load_state()
    state["last_success"] = TODAY.isoformat()
    dream.save_state(state)
    assert dream.dream_status(TODAY) is None


def test_status_reports_failed_last_run(dream_env):
    dream.append_log(_ok(TODAY - dt.timedelta(days=1)))
    dream.append_log(dream.log_line(TODAY, 0, {}, [], False, "no login"))
    state = dream.load_state()
    state["last_success"] = (TODAY - dt.timedelta(days=1)).isoformat()
    dream.save_state(state)
    assert dream.dream_status(TODAY) == "dream: last run failed (no login)"


def test_status_reports_three_days_without_success(dream_env):
    dream.append_log(_ok(TODAY - dt.timedelta(days=4)))
    state = dream.load_state()
    state["last_success"] = (TODAY - dt.timedelta(days=4)).isoformat()
    dream.save_state(state)
    assert dream.dream_status(TODAY) == "dream: no successful run in 4 days"


def test_cli_dream_status_prints_only_when_unhealthy_and_exits_zero(dream_env, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("WORK_STORE", str(tmp_path / "missing"))
    assert work.main(["dream-status"]) == 0
    assert capsys.readouterr().out == ""
    dream.append_log(dream.log_line(dt.date.today(), 0, {}, [], False, "boom"))
    assert work.main(["dream-status"]) == 0
    assert capsys.readouterr().out == "dream: last run failed (boom)\n"
