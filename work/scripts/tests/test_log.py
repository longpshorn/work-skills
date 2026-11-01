import okf_check
import work
from helpers import header


def with_log(*lines, **fields):
    return header(**fields) + "".join(f"{line}\n" for line in lines)


def log_text(store):
    assert work.main(["index"]) == 0
    return (store / "log.md").read_text(encoding="utf-8")


def test_log_groups_entries_by_date_newest_first_with_links(store, write):
    write("garden/01-a", with_log("- 2026-09-01 · started tracking", "- 2026-10-02 · planted",
                                  title="Alpha"))
    write("ai/01-b", with_log("- 2026-10-02 · chose SQLite", title="Beta"))
    assert log_text(store) == (
        "# Work store log\n\n"
        "## 2026-10-02\n\n"
        "* [Beta](ai/01-b.md): chose SQLite\n"
        "* [Alpha](garden/01-a.md): planted\n\n"
        "## 2026-09-01\n\n"
        "* [Alpha](garden/01-a.md): started tracking\n"
    )


def test_log_lists_a_workstreams_same_day_entries_newest_first(store, write):
    write("ai/01-b", with_log("- 2026-10-02 · first", "* 2026-10-02 · second"))
    assert "* [T](ai/01-b.md): second\n* [T](ai/01-b.md): first\n" in log_text(store)


def test_log_skips_malformed_lines_and_text_outside_the_log_section(store, write):
    write("ai/01-b", header().replace("## Log", "## Notes\n\n- 2026-10-03 · not a log line\n\n## Log")
          + "- 2026-10-02 · kept\n"
            "- 2026-10-02 - wrong separator\n"
            "- 2026-13-01 · impossible date\n"
            "- 02/10/2026 · wrong date form\n"
            "- 2026-10-02 · \n"
            "plain prose\n"
            "\n## Later\n\n- 2026-10-04 · after the Log section\n")
    assert log_text(store) == "# Work store log\n\n## 2026-10-02\n\n* [T](ai/01-b.md): kept\n"


def test_log_reads_bom_and_crlf_status_files(store):
    path = store / "ai" / "01-b.md"
    path.parent.mkdir()
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("﻿" + with_log("- 2026-10-02 · windows").replace("\n", "\r\n"))
    assert "* [T](ai/01-b.md): windows\n" in log_text(store)


def test_log_includes_archived_and_off_report_workstreams(store, write):
    write("side-work/01-once", with_log("- 2026-10-02 · one-off", title="Once", report="false"))
    write("_archive/ai/02-old", with_log("- 2026-10-01 · finished", title="Old", state="done"))
    text = log_text(store)
    assert "* [Once](side-work/01-once.md): one-off\n" in text
    assert "* [Old](_archive/ai/02-old.md): finished\n" in text


def test_log_ignores_header_errors_in_archived_files(store, write):
    write("_archive/ai/02-bad", with_log("- 2026-10-01 · lost", state="doing"))
    assert log_text(store) == "# Work store log\n"


def test_log_links_encode_the_target_and_escape_the_text(store, write):
    write("my area/01-x)#z%", with_log("- 2026-10-02 · moved", title="Fix ] bug"))
    assert "* [Fix \\] bug](my%20area/01-x%29%23z%25.md): moved\n" in log_text(store)


def test_log_is_byte_identical_when_history_is_unchanged(store, write):
    write("ai/01-b", with_log("- 2026-10-02 · one"))
    write("garden/01-a", with_log("- 2026-10-02 · two"))
    log_text(store)
    first = (store / "log.md").read_bytes()
    assert work.main(["--today", "2027-01-01", "index"]) == 0
    assert (store / "log.md").read_bytes() == first


def test_log_conforms_to_okf(store, write):
    write("ai/01-b", with_log("- 2026-09-01 · a", "- 2026-10-02 · b"))
    log_text(store)
    assert [p for p in okf_check.problems(store) if p.startswith("log.md")] == []


def test_a_workstream_file_named_log_is_never_read(store, write):
    write("ai/LOG", with_log("- 2026-10-02 · hidden"))
    write("ai/01-b", with_log("- 2026-10-02 · shown"))
    text = log_text(store)
    assert "shown" in text and "hidden" not in text
