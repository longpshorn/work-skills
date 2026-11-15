import work
from helpers import header
from test_upgrade import read_raw, write_raw

NOW = "2026-10-05T23:30:00-05:00"
STAMP = "generated: { by: process:work-tools, at: 2026-10-05T23:30:00-05:00 }"


def test_touch_writes_generated_only(store, write):
    path = write("ai/01-a", header(generated=None, repos="[~/a]"))
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 0
    text = path.read_text(encoding="utf-8")
    assert text == f"---\ntitle: T\nstate: active\nnext: Do it\nrepos: [~/a]\n{STAMP}\n---\n\n## Log\n\n"
    assert "updated" not in text
    meta = work.parse_header(text)
    assert meta["generated"]["by"] == work.ACTOR and meta["generated"]["at"].isoformat() == NOW


def test_touch_replaces_generated_and_removes_updated_keeping_bom_crlf_and_comments(store):
    path = store / "ai" / "01-a.md"
    write_raw(path, "\ufeff---\r\ntitle: A\r\nstate: active\r\nnext: Go\r\nupdated: 2026-01-01\r\n"
                    "generated: { by: human:x, at: 2026-01-01T00:00:00Z }   # set by touch\r\n---\r\n# A\r\n")
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 0
    assert read_raw(path) == ("\ufeff---\r\ntitle: A\r\nstate: active\r\nnext: Go\r\n"
                              f"{STAMP}   # set by touch\r\n---\r\n# A\r\n")


def test_touch_puts_generated_where_a_lone_updated_was(store):
    path = store / "ai" / "01-a.md"
    write_raw(path, "---\r\ntitle: A\r\nupdated: 2026-01-01   # old\r\nstate: active\r\nnext: Go\r\n---\r\n")
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 0
    assert read_raw(path) == f"---\r\ntitle: A\r\n{STAMP}   # old\r\nstate: active\r\nnext: Go\r\n---\r\n"


def test_touch_defaults_to_the_current_time_with_an_offset(store, write):
    path = write("ai/01-a", header())
    assert work.main(["touch", "ai/01-a"]) == 0
    at = work.parse_header(path.read_text(encoding="utf-8"))["generated"]["at"]
    assert at.utcoffset() is not None and at.microsecond == 0


def test_touch_unknown_key_exits_3(store, write, capsys):
    write("ai/01-a", header())
    assert work.main(["touch", "ai/02-b"]) == 3
    assert "no workstream 'ai/02-b'" in capsys.readouterr().err


def test_touch_leaves_a_file_without_front_matter_alone(store, write, capsys):
    path = write("ai/01-a", "no header\n")
    assert work.main(["touch", "ai/01-a"]) == 1
    assert path.read_text(encoding="utf-8") == "no header\n"
    assert "ai/01-a: missing front-matter" in capsys.readouterr().err


def test_touch_refuses_a_store_that_predates_okf_and_changes_nothing(store, write, capsys):
    write("ai/01-old", "---\ntitle: T\nstatus: active\nnext: N\nupdated: 2026-10-01\n---\n")
    path = write("ai/02-a", header(generated=None, updated="2026-10-02"))
    before = path.read_text(encoding="utf-8")
    assert work.main(["--now", NOW, "touch", "ai/02-a"]) == 1
    assert path.read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "ai/01-old.md" in err and work.LEGACY_UPGRADE in err


def test_touch_refuses_a_store_with_a_legacy_index_file(store, write, capsys):
    (store / "INDEX.md").write_text("old\n", encoding="utf-8")
    path = write("ai/01-a", header(generated=None, updated="2026-10-02"))
    before = path.read_text(encoding="utf-8")
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 1
    assert path.read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "INDEX.md" in err and work.LEGACY_UPGRADE in err
