import pytest

import work
from helpers import header


@pytest.fixture
def three(write):
    write("home/09-roof-gutter-repair", header(title="Roof gutter repair"))
    write("home/06-kitchen-shelf-build", header(title="Kitchen Shelf Build"))
    write("garden/01-raised-beds", header(title="Raised beds",
                                       repos="[~/code/acme/garden-planner]"))


def run(capsys, *argv):
    rc = work.main(list(argv))
    return rc, capsys.readouterr()


def test_exact_name_without_number(store, three, capsys):
    rc, out = run(capsys, "find", "kitchen-shelf-build")
    assert rc == 0
    assert out.out.strip() == str(store / "home/06-kitchen-shelf-build.md")


def test_exact_key(store, three, capsys):
    assert run(capsys, "find", "home/09-roof-gutter-repair")[0] == 0


def test_area_with_single_workstream(store, three, capsys):
    rc, out = run(capsys, "find", "garden")
    assert rc == 0 and out.out.strip().endswith("garden/01-raised-beds.md")


def test_substring_on_key_or_title_is_case_insensitive(store, three, capsys):
    rc, out = run(capsys, "find", "gutter")
    assert rc == 0 and out.out.strip().endswith("09-roof-gutter-repair.md")
    rc, out = run(capsys, "find", "SHELF")
    assert rc == 0 and out.out.strip().endswith("06-kitchen-shelf-build.md")


def test_ambiguous_lists_candidates(store, three, capsys):
    rc, out = run(capsys, "find", "home")
    assert rc == 2
    assert out.out.splitlines() == ["home/06-kitchen-shelf-build",
                                    "home/09-roof-gutter-repair"]


def test_no_match(store, three, capsys):
    rc, out = run(capsys, "find", "zebra")
    assert rc == 3 and "no workstream matches 'zebra'" in out.err


def test_cwd_inside_linked_repo(store, three, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc, out = run(capsys, "find", "--cwd",
                  str(tmp_path / "code/acme/garden-planner/src"))
    assert rc == 0 and out.out.strip().endswith("garden/01-raised-beds.md")


def test_cwd_outside_any_repo(store, three, capsys, tmp_path):
    assert run(capsys, "find", "--cwd", str(tmp_path))[0] == 3


def test_substring_ignores_area_name(store, write, capsys):
    write("ai-initiatives/01-gate", header(title="Gate"))
    assert run(capsys, "find", "initiatives")[0] == 3
