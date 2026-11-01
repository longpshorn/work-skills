import work
from helpers import header


def read_raw(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_raw(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def test_index_adds_type_and_renames_legacy_status_keeping_bom_crlf_and_comments(store):
    path = store / "ai" / "01-a.md"
    write_raw(path, "﻿---\r\ntitle: A\r\nstatus: active   # idea | active\r\n"
                    "next: Go\r\nupdated: 2026-10-01\r\n---\r\n# A\r\n")
    work.main(["index"])
    assert read_raw(path) == ("﻿---\r\ntype: workstream\r\ntitle: A\r\nstate: active   # idea | active\r\n"
                              "next: Go\r\nupdated: 2026-10-01\r\n---\r\n# A\r\n")


def test_index_keeps_an_okf_status_next_to_state(store, write):
    path = write("ai/01-a", header(status="deprecated"))
    work.main(["index"])
    text = path.read_text(encoding="utf-8")
    assert "\nstatus: deprecated\n" in text and "\nstate: active\n" in text


def test_index_gives_area_and_readme_a_front_matter_block(store, write):
    area = write("garden/AREA", "# Garden\n\n**Purpose:** grow\n")
    readme = write("README", "# Work store\n")
    work.main(["index"])
    assert area.read_text(encoding="utf-8") == "---\ntype: area\n---\n\n# Garden\n\n**Purpose:** grow\n"
    assert readme.read_text(encoding="utf-8") == "---\ntype: guide\n---\n\n# Work store\n"


def test_index_upgrades_archived_workstreams(store, write):
    path = write("_archive/ai/01-old", header(state=None, status="done"))
    work.main(["index"])
    assert path.read_text(encoding="utf-8").startswith("---\ntype: workstream\n")
    assert "\nstate: done\n" in path.read_text(encoding="utf-8")


def test_upgrade_is_idempotent_and_leaves_broken_files_alone(store, write):
    good = write("ai/01-a", header(type="workstream"))
    broken = write("ai/02-b", "no header\n")
    before = good.read_text(encoding="utf-8")
    work.main(["index"])
    work.main(["index"])
    assert good.read_text(encoding="utf-8") == before
    assert broken.read_text(encoding="utf-8") == "no header\n"
