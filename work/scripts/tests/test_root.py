import os
import subprocess
import sys
from pathlib import Path

import work
from helpers import header

WORK_PY = Path(work.__file__)


def run_root(capsys):
    rc = work.main(["root"])
    return rc, capsys.readouterr().out.strip()


def test_default_store_is_dot_work(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("WORK_STORE", raising=False)
    assert run_root(capsys) == (0, str(tmp_path / ".work"))


def test_root_expands_tilde_and_relative(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("WORK_STORE", "~/notes")
    assert run_root(capsys) == (0, str(tmp_path / "notes"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WORK_STORE", "rel")
    assert run_root(capsys) == (0, str(tmp_path / "rel"))


def test_root_works_without_a_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORK_STORE", str(tmp_path / "missing"))
    assert run_root(capsys) == (0, str(tmp_path / "missing"))


def test_output_survives_a_non_utf8_stdout(store, write):
    write("home/01-a", header())
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "WORK_STORE": str(store)}
    result = subprocess.run([sys.executable, str(WORK_PY), "list"], capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "·" in result.stdout.decode("utf-8")
