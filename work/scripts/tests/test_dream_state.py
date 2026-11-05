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


CHILD = (
    "import sys, time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import dream\n"
    "lock = dream.RunLock().__enter__()\n"
    "print('locked', flush=True)\n"
    "time.sleep(60)\n"
)


def _hold_in_child():
    scripts = os.path.dirname(os.path.abspath(dream.__file__))
    child = subprocess.Popen([sys.executable, "-c", CHILD, scripts], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "locked"
    return child


def test_second_lock_while_held_is_busy_and_leaves_holder_intact(dream_env):
    with dream.RunLock():
        with pytest.raises(dream.Busy):
            with dream.RunLock():
                pass
        with pytest.raises(dream.Busy):
            with dream.RunLock():
                pass
    with dream.RunLock():
        pass


def test_lock_held_by_a_killed_child_is_free_afterwards(dream_env):
    child = _hold_in_child()
    try:
        with pytest.raises(dream.Busy):
            with dream.RunLock():
                pass
    finally:
        child.kill()
        child.wait()
        child.stdout.close()
    with dream.RunLock():
        pass


def test_leftover_lock_file_without_a_holder_is_taken(dream_env):
    dream_env.state.mkdir(parents=True)
    lock = dream_env.state / "lock"
    lock.write_text("garbage", encoding="utf-8")
    with dream.RunLock():
        pass
    lock.write_text(str(os.getpid()), encoding="utf-8")
    with dream.RunLock():
        pass


def test_lock_is_released_on_exit_and_on_exception(dream_env):
    with dream.RunLock():
        pass
    with pytest.raises(RuntimeError):
        with dream.RunLock():
            raise RuntimeError("boom")
    with dream.RunLock():
        pass
    assert (dream_env.state / "lock").exists()


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
