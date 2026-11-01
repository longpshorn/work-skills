import work
from helpers import header


def test_index_groups_by_area_and_flags_stale(store, write):
    write("garden/01-a", header(title="Alpha", updated="2026-09-01"))
    write("ai/01-b", header(title="Beta", next="x | y"))
    write("ai/02-c", header(title="Done one", status="done", updated="2026-01-01"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    text = (store / "INDEX.md").read_text(encoding="utf-8")
    assert text.startswith("# Work Index\n")
    assert text.index("## ai") < text.index("## garden")
    assert "| [Alpha](garden/01-a.md) | active | Do it | 2026-09-01 (34d) ⚠ stale |" in text
    assert "| [Beta](ai/01-b.md) | active | x \\| y | 2026-10-01 (4d) |" in text
    assert "Done one" in text
    assert text.count("⚠") == 1


def test_index_reports_errors_and_exits_1(store, write, capsys):
    write("ai/01-b", header())
    write("ai/02-bad", header(status="doing"))
    assert work.main(["index"]) == 1
    text = (store / "INDEX.md").read_text(encoding="utf-8")
    assert "## Errors" in text
    assert "- `ai/02-bad.md`: bad status 'doing'" in text
    assert "ai/02-bad.md: bad status 'doing'" in capsys.readouterr().err


def test_list_prints_one_line_each(store, write, capsys):
    write("ai/01-b", header(status="blocked", next="Wait for data"))
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
    text = (store / "INDEX.md").read_text(encoding="utf-8")
    assert "| [One-off](side/01-a.md) | active · off-report | Do it | 2026-10-01 (4d) |" in text
    assert "| [Reported](ai/01-b.md) | active | Do it | 2026-10-01 (4d) |" in text


def test_index_links_encode_spaces_in_target_only(store, write):
    write("my area/01-x one", header(title="X one"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    text = (store / "INDEX.md").read_text(encoding="utf-8")
    assert "| [X one](my%20area/01-x%20one.md) | active | Do it | 2026-10-01 (4d) |" in text
