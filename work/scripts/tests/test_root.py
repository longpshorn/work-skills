import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_root_expands_tilde(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("WORK_STORE", "~/notes")
    assert run_root(capsys) == (0, str(tmp_path / "notes"))


def test_relative_work_store_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WORK_STORE", "rel")
    rc = work.main(["root"])
    err = capsys.readouterr().err
    assert rc == 4 and "must be an absolute path" in err
    assert work.main(["init"]) == 4
    assert not (tmp_path / "rel").exists()


@pytest.mark.skipif(os.name != "nt", reason="drive-letter paths are absolute only on Windows")
@pytest.mark.parametrize("value", ["C:/Users/you/notes", "C:\\Users\\you\\notes"])
def test_windows_work_store_forms_are_accepted(value, monkeypatch, capsys):
    monkeypatch.setenv("WORK_STORE", value)
    assert run_root(capsys) == (0, "C:\\Users\\you\\notes")


def test_root_works_without_a_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORK_STORE", str(tmp_path / "missing"))
    assert run_root(capsys) == (0, str(tmp_path / "missing"))


def test_output_survives_a_non_utf8_stdout(store, write):
    write("home/01-a", header())
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "WORK_STORE": str(store)}
    result = subprocess.run([sys.executable, str(WORK_PY), "list"], capture_output=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "·" in result.stdout.decode("utf-8")
