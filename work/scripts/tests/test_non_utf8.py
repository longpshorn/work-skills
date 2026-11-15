import work
from helpers import header

LATIN1 = header(title="Café").encode("latin-1")


def write_bytes(store, key, data):
    path = store / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_index_reports_a_non_utf8_file_and_indexes_the_rest(store, write, capsys):
    write("ai/01-a", header(title="Alpha") + "- 2026-10-01 · did a thing\n")
    bad = write_bytes(store, "ai/02-bad", LATIN1)
    assert work.main(["index"]) == 1
    index = (store / "index.md").read_text(encoding="utf-8")
    assert "[Alpha](ai/01-a.md)" in index
    assert "* [ai/02-bad.md](ai/02-bad.md) - not valid UTF-8" in index
    assert "did a thing" in (store / "log.md").read_text(encoding="utf-8")
    err = capsys.readouterr().err
    assert err.count("ai/02-bad.md: not valid UTF-8") == 1
    assert "Traceback" not in err
    assert bad.read_bytes() == LATIN1


def test_index_reports_a_non_utf8_archived_file(store, write, capsys):
    write("ai/01-a", header())
    bad = write_bytes(store, "_archive/ai/02-bad", LATIN1)
    assert work.main(["index"]) == 1
    assert "_archive/ai/02-bad.md: not valid UTF-8" in capsys.readouterr().err
    assert bad.read_bytes() == LATIN1


def test_index_accepts_a_utf8_file_with_a_bom(store, write):
    write("ai/01-a", "\ufeff" + header(title="Café"))
    assert work.main(["index"]) == 0
    assert "[Café](ai/01-a.md)" in (store / "index.md").read_text(encoding="utf-8")


def test_list_reports_a_non_utf8_file_on_stderr_and_exits_0(store, write, capsys):
    write("ai/01-a", header(next="Ship"))
    write_bytes(store, "ai/02-bad", LATIN1)
    assert work.main(["list"]) == 0
    out, err = capsys.readouterr()
    assert out == "ai/01-a · active · Ship\n"
    assert "ai/02-bad.md: not valid UTF-8" in err


def test_list_no_description_keeps_stdout_to_keys(store, write, capsys):
    write("ai/01-a", header())
    write_bytes(store, "ai/02-bad", LATIN1)
    assert work.main(["list", "--no-description"]) == 0
    out, err = capsys.readouterr()
    assert out == "ai/01-a\n"
    assert "ai/02-bad.md: not valid UTF-8" in err


def test_touch_on_another_workstream_succeeds(store, write):
    path = write("ai/01-a", header())
    write_bytes(store, "ai/02-bad", LATIN1)
    assert work.main(["--now", "2026-10-05T12:00:00+00:00", "touch", "ai/01-a"]) == 0
    assert "at: 2026-10-05T12:00:00+00:00" in path.read_text(encoding="utf-8")


def test_touch_on_the_non_utf8_file_fails_clearly(store, write, capsys):
    write("ai/01-a", header())
    bad = write_bytes(store, "ai/02-bad", LATIN1)
    assert work.main(["touch", "ai/02-bad"]) == 1
    err = capsys.readouterr().err
    assert "ai/02-bad: not valid UTF-8" in err and "Traceback" not in err
    assert bad.read_bytes() == LATIN1


def test_drift_all_skips_a_non_utf8_file(store, write, capsys):
    write("ai/01-a", header())
    write_bytes(store, "ai/02-bad", LATIN1)
    assert work.main(["drift", "--all"]) == 0


def test_index_reports_a_non_utf8_area_or_readme(store, write, capsys):
    write("ai/01-a", header())
    area = write_bytes(store, "ai/AREA", b"# Caf\xe9\n")
    readme = write_bytes(store, "README", b"# Caf\xe9\n")
    assert work.main(["index"]) == 1
    err = capsys.readouterr().err
    assert err.count("ai/AREA.md: not valid UTF-8") == 1
    assert err.count("README.md: not valid UTF-8") == 1
    assert "[ai/AREA.md](ai/AREA.md) - not valid UTF-8" in (store / "index.md").read_text(encoding="utf-8")
    assert area.read_bytes() == b"# Caf\xe9\n" and readme.read_bytes() == b"# Caf\xe9\n"
