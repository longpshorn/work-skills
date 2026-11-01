import pytest

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
    assert area.read_text(encoding="utf-8") == ("---\ntype: area\ndescription: grow\n---\n\n"
                                                "# Garden\n\n**Purpose:** grow\n")
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


def test_index_gives_an_area_its_purpose_as_description_keeping_crlf(store):
    path = store / "garden" / "AREA.md"
    write_raw(path, "---\r\ntype: area\r\n---\r\n# Garden\r\n\r\n**Purpose:**  Grow: veg #1  \r\n")
    work.main(["index"])
    assert read_raw(path) == ('---\r\ntype: area\r\ndescription: "Grow: veg #1"\r\n---\r\n'
                              "# Garden\r\n\r\n**Purpose:**  Grow: veg #1  \r\n")


def test_index_keeps_an_area_description_and_skips_an_area_without_purpose(store, write):
    kept = write("garden/AREA", "---\ntype: area\ndescription: Mine\n---\n# Garden\n\n**Purpose:** grow\n")
    bare = write("ai/AREA", "# AI\n")
    before = kept.read_text(encoding="utf-8")
    work.main(["index"])
    assert kept.read_text(encoding="utf-8") == before
    assert bare.read_text(encoding="utf-8") == "---\ntype: area\n---\n\n# AI\n"


def test_yaml_scalar_quotes_only_what_plain_yaml_would_misread():
    assert work.yaml_scalar("Grow veg") == "Grow veg"
    assert work.yaml_scalar("a: b") == '"a: b"'
    assert work.yaml_scalar("a #b") == '"a #b"'
    assert work.yaml_scalar('[x] "y" \\') == '"[x] \\"y\\" \\\\"'


def test_index_marks_an_archived_workstream_deprecated_inserting_one_line(store):
    path = store / "_archive" / "ai" / "01-old.md"
    write_raw(path, "﻿---\r\ntype: workstream\r\ntitle: Old\r\nstate: done   # finished\r\n"
                    "next: None\r\nupdated: 2026-10-01\r\n---\r\n# Old\r\n")
    work.main(["index"])
    assert read_raw(path) == ("﻿---\r\ntype: workstream\r\ntitle: Old\r\nstate: done   # finished\r\n"
                              f"status: {work.ARCHIVED_STATUS}\r\n"
                              "next: None\r\nupdated: 2026-10-01\r\n---\r\n# Old\r\n")


def test_index_marks_a_legacy_archived_status_after_renaming_it_to_state(store, write):
    path = write("_archive/ai/01-old", header(state=None, status="done  # x"))
    work.main(["index"])
    assert f"\nstate: done  # x\nstatus: {work.ARCHIVED_STATUS}\n" in path.read_text(encoding="utf-8")


def test_index_marks_an_archived_file_without_state_before_the_closing_line(store, write):
    path = write("_archive/ai/01-old", "---\ntype: workstream\ntitle: Old\n---\n")
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == (
        f"---\ntype: workstream\ntitle: Old\nstatus: {work.ARCHIVED_STATUS}\n---\n")


@pytest.mark.parametrize("key,status", [("_archive/ai/01-old", "draft"),
                                        ("_archive/ai/02-old", "stable"),
                                        ("ai/01-a", "stable"),
                                        ("ai/02-b", "deprecated")])
def test_index_never_changes_a_status_the_user_wrote(store, write, key, status):
    path = write(key, header(type="workstream", state="done", status=status))
    before = path.read_text(encoding="utf-8")
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == before


def test_index_never_marks_a_live_workstream(store, write):
    path = write("ai/01-a", header(state="done"))
    work.main(["index"])
    assert "status:" not in path.read_text(encoding="utf-8")


def test_marking_archived_workstreams_is_idempotent(store, write):
    path = write("_archive/ai/01-old", header(state="done"))
    work.main(["index"])
    once = path.read_text(encoding="utf-8")
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == once
    assert once.count("status:") == 1
