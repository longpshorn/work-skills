import datetime as dt
import subprocess

import pytest

import work
from helpers import header


def test_index_groups_by_area_and_flags_stale(store, write):
    write("garden/01-a", header(title="Alpha", updated="2026-09-01"))
    write("ai/01-b", header(title="Beta", next="x | y"))
    write("ai/02-c", header(title="Done one", state="done", updated="2026-01-01"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    text = (store / "index.md").read_text(encoding="utf-8")
    assert text.startswith('---\nokf_version: "0.2"\n---\n\n# ai\n')
    assert text.index("# ai") < text.index("# garden")
    assert "* [Alpha](garden/01-a.md) - active · Do it · 2026-09-01 (34d) ⚠ stale\n" in text
    assert "* [Beta](ai/01-b.md) - active · x | y · 2026-10-01 (4d)\n" in text
    assert "Done one" in text
    assert text.count("⚠") == 1


def test_index_reports_errors_and_exits_1(store, write, capsys):
    write("ai/01-b", header())
    write("ai/02-bad", header(state="doing"))
    assert work.main(["index"]) == 1
    text = (store / "index.md").read_text(encoding="utf-8")
    assert "\n# Errors\n\n* [ai/02-bad.md](ai/02-bad.md) - bad state 'doing'\n" in text
    assert "ai/02-bad.md: bad state 'doing'" in capsys.readouterr().err


def test_list_prints_one_line_each(store, write, capsys):
    write("ai/01-b", header(state="blocked", next="Wait for data"))
    write("ai/02-c", header(next="Ship"))
    assert work.main(["list"]) == 0
    assert capsys.readouterr().out == "ai/01-b · blocked · Wait for data\nai/02-c · active · Ship\n"


def test_missing_store_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORK_STORE", str(tmp_path / "nope"))
    for command in ("index", "list"):
        assert work.main([command]) == 4
        assert "no work store at" in capsys.readouterr().err


def test_index_marks_off_report_workstreams(store, write):
    write("side/01-a", header(title="One-off", report="false"))
    write("ai/01-b", header(title="Reported"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    text = (store / "index.md").read_text(encoding="utf-8")
    assert "* [One-off](side/01-a.md) - active · off-report · Do it · 2026-10-01 (4d)\n" in text
    assert "* [Reported](ai/01-b.md) - active · Do it · 2026-10-01 (4d)\n" in text


def test_index_links_encode_spaces_in_target_only(store, write):
    write("my area/01-x one", header(title="X one"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    text = (store / "index.md").read_text(encoding="utf-8")
    assert "* [X one](my%20area/01-x%20one.md) - active · Do it · 2026-10-01 (4d)\n" in text


def test_index_links_encode_markdown_specials_in_target_only(store, write):
    write("a(b)/01-x)#z%", header(title="X z"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    text = (store / "index.md").read_text(encoding="utf-8")
    assert "* [X z](a%28b%29/01-x%29%23z%25.md) - active · Do it · 2026-10-01 (4d)\n" in text


def row_for(tmp_path, area, filename, title="T"):
    meta = {"title": title, "state": "active", "next": "Do it",
            "updated": dt.date(2026, 10, 1), "report": True}
    item = work.Workstream(area, tmp_path / area / filename, meta)
    text = work.render_index(tmp_path, [item], [], dt.date(2026, 10, 5))
    return next(line for line in text.splitlines() if line.startswith("* ["))


def test_index_links_encode_characters_windows_cannot_store(tmp_path):
    assert row_for(tmp_path, "ai", "01-a<b>|c.md") == \
        "* [T](ai/01-a%3Cb%3E%7Cc.md) - active · Do it · 2026-10-01 (4d)"


def test_index_link_text_escapes_brackets_and_backslashes(tmp_path):
    assert row_for(tmp_path, "ai", "01-b.md", title="Fix ] [x \\ bug") == \
        "* [Fix \\] \\[x \\\\ bug](ai/01-b.md) - active · Do it · 2026-10-01 (4d)"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True).stdout


def names(root):
    return sorted(p.name for p in root.iterdir() if p.name.lower() == "index.md")


def test_index_renames_a_tracked_legacy_index_in_git(store, write):
    write("ai/01-b", header())
    (store / "INDEX.md").write_text("old\n", encoding="utf-8")
    git(store, "init", "-q")
    git(store, "add", "-A")
    assert work.main(["index"]) == 0
    assert names(store) == ["index.md"]
    git(store, "add", "-A")
    tracked = git(store, "ls-files").split()
    assert "index.md" in tracked and "INDEX.md" not in tracked


def test_index_renames_an_untracked_legacy_index(store, write):
    write("ai/01-b", header())
    (store / "INDEX.md").write_text("old\n", encoding="utf-8")
    assert work.main(["index"]) == 0
    assert names(store) == ["index.md"]
    assert "* [T](ai/01-b.md)" in (store / "index.md").read_text(encoding="utf-8")


def test_index_drops_a_legacy_index_beside_a_new_one(store, write):
    (store / "index.md").write_text("new\n", encoding="utf-8")
    (store / "INDEX.md").write_text("old\n", encoding="utf-8")
    if names(store) != ["INDEX.md", "index.md"]:
        pytest.skip("case-insensitive file system: the two names are one file")
    assert work.main(["index"]) == 0
    assert names(store) == ["index.md"]
