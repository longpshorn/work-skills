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


@pytest.fixture
def garden(monkeypatch, tmp_path):
    """A home whose ~/code/garden is the repo find --cwd runs in (#52)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return str(tmp_path / "code" / "garden" / "src")


def cwd_cause(cwd, rel):
    return f"work.py: no workstream matches {cwd!r}; {rel} matches it but its header can't be read (error above)"


def test_find_cwd_names_a_legacy_file_linked_to_the_repo(store, broken, write, garden, capsys):
    path = write("garden/01-beds", header(title="Beds", state=None, status="active", repos="[~/code/garden]"))
    before = path.read_bytes()
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (3, "")
    assert_both_errors(err)
    assert "garden/01-beds.md: legacy 'status: active' key" in err
    assert cwd_cause(garden, "garden/01-beds.md") in err
    assert "ai/02-bad.md matches it" not in err and "ai/03-legacy.md matches it" not in err
    assert path.read_bytes() == before


def test_find_cwd_names_an_unreadable_file_with_a_bad_line(store, write, garden, capsys):
    text = header(title="Beds", repos="~/code/garden").replace("---\n", "---\nnot a key value line\n", 1)
    write("garden/01-beds", text)
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (3, "")
    assert "garden/01-beds.md: line 2: expected 'key: value'" in err
    assert cwd_cause(garden, "garden/01-beds.md") in err


def test_find_cwd_skips_a_non_utf8_file_that_names_the_repo(store, garden, capsys):
    data = header(title="Caf\xe9", repos="[~/code/garden]").encode("latin-1")
    bad = store / "garden" / "01-beds.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(data)
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (3, "")
    assert err == (f"garden/01-beds.md: not valid UTF-8 (byte 0xe9 at offset {data.index(0xe9)}); re-save it as UTF-8\n"
                   f"work.py: no workstream matches {garden!r}\n")
    assert bad.read_bytes() == data


def test_find_cwd_prefers_a_readable_linked_workstream(store, write, garden, capsys):
    write("garden/01-beds", header(title="Beds", repos="[~/code/garden]"))
    write("garden/02-old", header(state=None, status="active", repos="[~/code/garden]"))
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (0, f"{store / 'garden' / '01-beds.md'}\n")
    assert "garden/02-old.md: legacy 'status: active' key" in err
    assert "can't be read (error above)" not in err


def test_find_cwd_unrelated_repo_gets_no_cause_line(store, write, garden, capsys):
    write("garden/01-beds", header(state=None, status="active", repos="[~/code/orchard]"))
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (3, "")
    assert "garden/01-beds.md: legacy 'status: active' key" in err
    assert "can't be read (error above)" not in err


def test_find_cwd_names_a_file_whose_repos_list_is_unterminated(store, write, garden, capsys):
    write("garden/01-beds", header(title="Beds", repos="[~/code/orchard, ~/code/garden"))
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (3, "")
    assert "garden/01-beds.md: line 6: unterminated list" in err
    assert cwd_cause(garden, "garden/01-beds.md") in err


def test_find_cwd_skips_a_file_with_unterminated_front_matter(store, write, garden, capsys):
    path = write("garden/01-beds", "---\ntitle: Beds\nrepos: [~/code/garden]\n")
    rc, out, err = run(capsys, "find", "--cwd", garden)
    assert (rc, out) == (3, "")
    assert err == f"garden/01-beds.md: unterminated front-matter\nwork.py: no workstream matches {garden!r}\n"
    assert path.read_text(encoding="utf-8") == "---\ntitle: Beds\nrepos: [~/code/garden]\n"
