import work
from helpers import header
from test_upgrade import read_raw, write_raw

NOW = "2026-10-05T23:30:00-05:00"
STAMP = "generated: { by: process:work-tools, at: 2026-10-05T23:30:00-05:00 }"


def test_touch_sets_updated_and_adds_generated_after_it(store, write):
    path = write("ai/01-a", header(repos="[~/a]"))
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 0
    assert path.read_text(encoding="utf-8") == header(updated="2026-10-05", generated=STAMP[11:], repos="[~/a]")
    meta = work.parse_header(path.read_text(encoding="utf-8"))
    assert meta["generated"]["by"] == work.ACTOR


def test_touch_replaces_both_values_keeping_bom_crlf_and_comments(store):
    path = store / "ai" / "01-a.md"
    write_raw(path, "﻿---\r\ntitle: A\r\nstate: active\r\nnext: Go\r\nupdated: 2026-01-01   # set by the skills\r\n"
                    "generated: { by: human:x, at: 2026-01-01T00:00:00Z }\r\n---\r\n# A\r\n")
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 0
    assert read_raw(path) == ("﻿---\r\ntitle: A\r\nstate: active\r\nnext: Go\r\nupdated: 2026-10-05   # set by the skills\r\n"
                              f"{STAMP}\r\n---\r\n# A\r\n")


def test_touch_adds_updated_when_missing(store, write):
    path = write("ai/01-a", header(updated=None))
    assert work.main(["--now", NOW, "touch", "ai/01-a"]) == 0
    meta = work.parse_header(path.read_text(encoding="utf-8"))
    assert str(meta["updated"]) == "2026-10-05" and meta["generated"]["at"].isoformat() == NOW


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
