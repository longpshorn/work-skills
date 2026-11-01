import datetime as dt

import pytest

import work
from helpers import header


def test_parses_required_fields_and_lists():
    meta = work.parse_header(header(repos="[~/a, ~/b]", artifacts="https://x"))
    assert meta["title"] == "T" and meta["state"] == "active" and meta["next"] == "Do it"
    assert meta["updated"] == dt.date(2026, 10, 1)
    assert meta["repos"] == ["~/a", "~/b"]
    assert meta["artifacts"] == ["https://x"]


def test_optional_lists_default_empty():
    meta = work.parse_header(header())
    assert meta["repos"] == [] and meta["artifacts"] == []


@pytest.mark.parametrize("fields,message", [
    ({"next": None}, "missing next"),
    ({"state": "doing"}, "bad state 'doing'"),
    ({"type": "area"}, "bad type 'area'"),
    ({"updated": "Oct 1"}, "bad updated 'Oct 1'"),
    ({"repos": "[~/a"}, "unterminated list"),
])
def test_rejects_bad_headers(fields, message):
    with pytest.raises(work.HeaderError, match=message):
        work.parse_header(header(**fields))


def test_rejects_missing_front_matter():
    with pytest.raises(work.HeaderError, match="missing front-matter"):
        work.parse_header("# just a doc\n")


def test_rejects_unterminated_front_matter():
    with pytest.raises(work.HeaderError, match="unterminated front-matter"):
        work.parse_header("---\ntitle: T\n")


def test_hash_in_value_is_kept_but_spaced_comment_is_dropped():
    meta = work.parse_header(header(next="Fix issue #12", state="active   # idea | active"))
    assert meta["next"] == "Fix issue #12"
    assert meta["state"] == "active"


def test_quoted_values_are_unquoted():
    assert work.parse_header(header(title='"Quoted: title"'))["title"] == "Quoted: title"


def test_bom_and_crlf_are_accepted():
    meta = work.parse_header("﻿" + header().replace("\n", "\r\n"))
    assert meta["title"] == "T"


def test_load_store_skips_area_md_and_underscore_dirs(store, write):
    write("garden/01-alpha", header())
    write("garden/AREA", "# Garden\n")
    write("_archive/garden/02-old", header())
    write("garden/02-bad", "no header\n")
    items, errors = work.load_store(store)
    assert [w.key for w in items] == ["garden/01-alpha"]
    assert items[0].name == "alpha" and items[0].slug == "01-alpha"
    assert [(p.name, msg) for p, msg in errors] == [("02-bad.md", "missing front-matter")]


def test_nudge_prints_when_store_exists(store, capsys):
    assert work.main(["nudge"]) == 0
    assert capsys.readouterr().out == (
        "Context was just compacted. If this session touched a tracked "
        "workstream, run /work:checkpoint now from the summary.\n")


def test_nudge_silent_without_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WORK_STORE", str(tmp_path / "nope"))
    assert work.main(["nudge"]) == 0
    assert capsys.readouterr().out == ""


def test_empty_repos_values_are_dropped():
    assert work.parse_header(header(repos=""))["repos"] == []
    assert work.parse_header(header(repos='[""]'))["repos"] == []


def test_quoted_value_keeps_double_spaced_hash():
    assert work.parse_header(header(next='"a  # b"'))["next"] == "a  # b"


def test_report_defaults_true_and_parses_false():
    assert work.parse_header(header())["report"] is True
    assert work.parse_header(header(report="true"))["report"] is True
    assert work.parse_header(header(report="false"))["report"] is False


def test_rejects_bad_report_value():
    with pytest.raises(work.HeaderError, match="bad report 'no'"):
        work.parse_header(header(report="no"))


def test_type_is_optional_and_workstream_is_accepted():
    assert "type" not in work.parse_header(header())
    assert work.parse_header(header(type=work.TYPES["status file"]))["type"] == "workstream"


def test_legacy_status_is_read_as_state():
    meta = work.parse_header(header(state=None, status="blocked"))
    assert meta["state"] == "blocked"


def test_state_wins_and_okf_status_is_left_alone():
    meta = work.parse_header(header(state="review", status="deprecated"))
    assert meta["state"] == "review" and meta["status"] == "deprecated"


def test_okf_status_alone_is_missing_state():
    with pytest.raises(work.HeaderError, match="missing state"):
        work.parse_header(header(state=None, status="stable"))
