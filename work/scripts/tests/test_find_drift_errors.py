"""find and drift report every per-file header error on stderr, as list does (#50)."""
import pytest

import work
from helpers import header

BAD = "ai/02-bad.md: not valid UTF-8"
LEGACY = "ai/03-legacy.md: legacy 'status: active' key"


@pytest.fixture
def broken(store, write):
    write("home/01-roof-fix", header(title="Roof fix"))
    write("home/02-shelf-build", header(title="Shelf build"))
    bad = store / "ai" / "02-bad.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(header(title="Caf\xe9").encode("latin-1"))
    write("ai/03-legacy", header(state=None, status="active"))


@pytest.fixture
def clean(write):
    write("home/01-roof-fix", header(title="Roof fix"))
    write("home/02-shelf-build", header(title="Shelf build"))


def run(capsys, *argv):
    rc = work.main(list(argv))
    out, err = capsys.readouterr()
    return rc, out, err


def assert_both_errors(err):
    assert err.count(BAD) == 1
    assert err.count(LEGACY) == 1
    assert "Traceback" not in err


def test_find_one_match_keeps_stdout_and_exit_0(store, broken, capsys):
    rc, out, err = run(capsys, "find", "roof")
    assert (rc, out) == (0, f"{store / 'home' / '01-roof-fix.md'}\n")
    assert_both_errors(err)


def test_find_ambiguous_keeps_keys_and_exit_2(broken, capsys):
    rc, out, err = run(capsys, "find", "home")
    assert (rc, out) == (2, "home/01-roof-fix\nhome/02-shelf-build\n")
    assert_both_errors(err)


def test_find_no_match_keeps_exit_3_without_a_cause_line(broken, capsys):
    rc, out, err = run(capsys, "find", "zebra")
    assert (rc, out) == (3, "")
    assert_both_errors(err)
    assert "no workstream matches 'zebra'" in err
    assert "can't be read" not in err


def test_find_cwd_inside_linked_repo_reports_errors(store, broken, write, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    write("garden/01-beds", header(title="Beds", repos="[~/code/garden]"))
    rc, out, err = run(capsys, "find", "--cwd", str(tmp_path / "code" / "garden" / "src"))
    assert (rc, out) == (0, f"{store / 'garden' / '01-beds.md'}\n")
    assert_both_errors(err)


@pytest.mark.parametrize("query, rel", [
    ("02-bad", "ai/02-bad.md"),
    ("bad", "ai/02-bad.md"),
    ("ai/02-bad", "ai/02-bad.md"),
    ("legacy", "ai/03-legacy.md"),
    ("ai/03-legacy", "ai/03-legacy.md"),
])
def test_find_matching_only_an_unreadable_file_names_the_cause(broken, capsys, query, rel):
    rc, out, err = run(capsys, "find", query)
    assert (rc, out) == (3, "")
    assert_both_errors(err)
    assert (f"work.py: no workstream matches {query!r}; {rel} matches it "
            "but its header can't be read (error above)") in err
    assert err.index(BAD) < err.index("no workstream matches")


def test_find_area_of_unreadable_files_names_each(broken, capsys):
    rc, out, err = run(capsys, "find", "ai")
    assert (rc, out) == (3, "")
    assert "ai/02-bad.md matches it but its header can't be read" in err
    assert "ai/03-legacy.md matches it but its header can't be read" in err


def test_find_prefers_a_readable_match_over_an_unreadable_one(store, broken, write, capsys):
    write("home/03-bad-roof", header(title="Bad roof"))
    rc, out, err = run(capsys, "find", "bad")
    assert (rc, out) == (0, f"{store / 'home' / '03-bad-roof.md'}\n")
    assert_both_errors(err)
    assert "can't be read (error above)" not in err


def test_drift_key_keeps_stdout_and_exit_0(broken, capsys):
    rc, out, err = run(capsys, "drift", "home/01-roof-fix")
    assert (rc, out) == (0, "home/01-roof-fix\n  clean\n")
    assert_both_errors(err)


def test_drift_all_keeps_stdout_and_exit_0(broken, capsys):
    rc, out, err = run(capsys, "drift", "--all")
    assert (rc, out) == (0, "")
    assert_both_errors(err)


@pytest.mark.parametrize("key, rel", [
    ("ai/02-bad", "ai/02-bad.md"),
    ("ai/03-legacy", "ai/03-legacy.md"),
])
def test_drift_key_of_an_unreadable_file_names_the_cause(broken, capsys, key, rel):
    rc, out, err = run(capsys, "drift", key)
    assert (rc, out) == (3, "")
    assert_both_errors(err)
    assert (f"work.py: no workstream {key!r}; {rel} has that key "
            "but its header can't be read (error above)") in err


def test_drift_unknown_key_keeps_the_plain_message(broken, capsys):
    rc, out, err = run(capsys, "drift", "ai/zebra")
    assert (rc, out) == (3, "")
    assert_both_errors(err)
    assert "no workstream 'ai/zebra'" in err and "can't be read (error above)" not in err


@pytest.mark.parametrize("argv, rc_out_err", [
    (("find", "roof"), (0, None, "")),
    (("find", "home"), (2, "home/01-roof-fix\nhome/02-shelf-build\n", "")),
    (("find", "zebra"), (3, "", "work.py: no workstream matches 'zebra'\n")),
    (("drift", "home/01-roof-fix"), (0, "home/01-roof-fix\n  clean\n", "")),
    (("drift", "--all"), (0, "", "")),
    (("drift", "home/zebra"), (3, "", "work.py: no workstream 'home/zebra'\n")),
])
def test_clean_store_prints_nothing_new(store, clean, capsys, argv, rc_out_err):
    want_rc, want_out, want_err = rc_out_err
    rc, out, err = run(capsys, *argv)
    assert (rc, err) == (want_rc, want_err)
    if want_out is not None:
        assert out == want_out
