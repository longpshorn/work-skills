import pytest

import okf_check
import work
from helpers import header, stamp


def read_raw(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_raw(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def test_index_adds_type_keeping_bom_crlf_and_comments(store):
    path = store / "ai" / "01-a.md"
    write_raw(path, "\ufeff---\r\ntitle: A\r\nstate: active   # idea | active\r\n"
                    "next: Go\r\nupdated: 2026-10-01\r\n---\r\n# A\r\n")
    assert work.main(["index"]) == 0
    assert read_raw(path) == ("\ufeff---\r\ntype: workstream\r\ntitle: A\r\nstate: active   # idea | active\r\n"
                              f"next: Go\r\ngenerated: {stamp('2026-10-01')}\r\n---\r\n# A\r\n")


@pytest.mark.parametrize("key", ["ai/01-a", "_archive/ai/01-old"])
def test_index_reports_a_legacy_status_file_and_leaves_its_key(store, write, capsys, key):
    write("ai/02-ok", header())
    path = write(key, header(state=None, status="done"))
    assert work.main(["index"]) == 1
    text = path.read_text(encoding="utf-8")
    assert "\nstatus: done\n" in text and "state:" not in text
    assert work.ARCHIVED_STATUS not in text
    err = capsys.readouterr().err
    assert f"{key}.md: legacy 'status: done'" in err and "54fbc56" in err
    assert f"{key}.md) - legacy 'status: done'" in (store / "index.md").read_text(encoding="utf-8")


def test_index_still_ignores_other_header_errors_in_archived_files(store, write):
    write("ai/01-a", header())
    write("_archive/ai/01-old", header(state="done", next=None))
    assert work.main(["index"]) == 0
    assert "# Errors" not in (store / "index.md").read_text(encoding="utf-8")


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
    path = write("_archive/ai/01-old", header(state="done"))
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
    write_raw(path, "\ufeff---\r\ntype: workstream\r\ntitle: Old\r\nstate: done   # finished\r\n"
                    "next: None\r\nupdated: 2026-10-01\r\n---\r\n# Old\r\n")
    work.main(["index"])
    assert read_raw(path) == ("\ufeff---\r\ntype: workstream\r\ntitle: Old\r\nstate: done   # finished\r\n"
                              f"status: {work.ARCHIVED_STATUS}\r\n"
                              f"next: None\r\ngenerated: {stamp('2026-10-01')}\r\n---\r\n# Old\r\n")


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


def test_index_backfills_generated_from_a_lone_updated_in_place_keeping_bom_crlf_and_comments(store):
    path = store / "ai" / "01-a.md"
    write_raw(path, "\ufeff---\r\ntype: workstream\r\ntitle: A\r\nstate: active\r\nnext: Go\r\n"
                    "updated: 2026-09-14   # set by touch\r\nrepos: []\r\n---\r\n# A\r\n")
    work.main(["index"])
    text = read_raw(path)
    assert text == ("\ufeff---\r\ntype: workstream\r\ntitle: A\r\nstate: active\r\nnext: Go\r\n"
                    f"generated: {stamp('2026-09-14')}   # set by touch\r\nrepos: []\r\n---\r\n# A\r\n")
    meta = work.parse_header(text)
    assert str(meta["date"]) == "2026-09-14" and meta["generated"]["by"] == work.ACTOR


def test_index_drops_updated_when_generated_is_already_there(store, write):
    path = write("ai/01-a", header(type="workstream", updated="2026-01-01"))
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == header(type="workstream")


def test_backfill_run_twice_is_idempotent(store, write):
    path = write("_archive/ai/01-old", header(generated=None, updated="2026-09-14", state="done"))
    write("ai/02-b", header(generated=None, updated="2026-09-15"))
    work.main(["index"])
    once = path.read_text(encoding="utf-8")
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == once
    assert "updated" not in once and once.count("generated:") == 1


def test_a_store_with_only_updated_headers_conforms_after_one_index_run(store, write):
    write("README", "---\ntype: guide\n---\n")
    write("ai/01-a", header(generated=None, updated="2026-09-14"))
    write("_archive/ai/02-old", header(generated=None, updated="2026-01-01", state="done"))
    assert work.main(["--today", "2026-10-05", "index"]) == 0
    assert okf_check.problems(store) == []
    assert "2026-09-14 (21d)" in (store / "index.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("generated", ["{ by: human:x }", "", "{ by: human:x, at: 2026-10-01 }"])
def test_index_keeps_updated_when_generated_has_no_usable_at(store, write, generated):
    path = write("ai/01-a", header(type="workstream", updated="2026-09-14", generated=generated))
    before = path.read_text(encoding="utf-8")
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("day", ["0001-01-01", "9999-12-31"])
def test_index_keeps_working_with_an_updated_date_at_the_calendar_edge(store, write, day):
    path = write("ai/01-a", header(type="workstream", generated=None, updated=day))
    assert work.main(["index"]) == 0
    assert str(work.parse_header(path.read_text(encoding="utf-8"))["date"]) == day


def test_index_drops_updated_next_to_a_quoted_generated(store, write):
    quoted = f'"{stamp("2026-10-01")}"'
    path = write("ai/01-a", header(type="workstream", generated=quoted, updated="2026-09-14"))
    work.main(["index"])
    assert path.read_text(encoding="utf-8") == header(type="workstream", generated=quoted)


LEGACY = "---\ntitle: T\nstatus: active\nnext: N\nupdated: 2026-10-01\n---\n"


@pytest.mark.parametrize("legacy", ["ai/01-old", "_archive/ai/01-old"])
def test_index_leaves_every_updated_alone_while_the_store_predates_okf(store, write, legacy):
    """The release the upgrade hint names requires updated, so index must not retire it until that run."""
    old = write(legacy, LEGACY)
    ok = write("ai/02-ok", header(generated=None, updated="2026-10-02"))
    both = write("ai/03-both", header(updated="2026-10-03"))
    assert work.main(["index"]) == 1
    assert "\nupdated: 2026-10-01\n" in old.read_text(encoding="utf-8")
    assert "\nupdated: 2026-10-02\n" in ok.read_text(encoding="utf-8")
    assert "generated" not in ok.read_text(encoding="utf-8")
    assert "\nupdated: 2026-10-03\n" in both.read_text(encoding="utf-8")


def test_index_retires_updated_once_the_store_is_upgraded(store, write):
    old = write("ai/01-old", LEGACY)
    ok = write("ai/02-ok", header(generated=None, updated="2026-10-02"))
    assert work.main(["index"]) == 1
    old.write_text(LEGACY.replace("status:", "state:"), encoding="utf-8")  # what the upgrade release does
    assert work.main(["index"]) == 0
    for path, day in ((old, "2026-10-01"), (ok, "2026-10-02")):
        text = path.read_text(encoding="utf-8")
        assert "updated" not in text and f"generated: {stamp(day)}" in text
