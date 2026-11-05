import datetime as dt
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dream

CAPS = {"claude_md_lines": 200}
TODAY = dt.date(2026, 11, 5)
NOTE = "---\nname: {n}\ndescription: d\nmetadata:\n  type: feedback\n---\nBody\n"


def memory_dir(tmp_path):
    root = tmp_path / "mem"
    root.mkdir(parents=True)
    return root


def test_safe_path_rejects_escapes(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(str(outside), str(root / "link"), target_is_directory=True)
        linked = True
    except (OSError, NotImplementedError):
        linked = False
    bad = ["../x", "/etc/passwd", "a/../../x", "\\evil", "C:/evil", ""]
    if linked:
        bad += ["link/x.md", "link"]
    for rel in bad:
        with pytest.raises(dream.UnsafePath):
            dream.safe_path(root, rel)
    assert dream.safe_path(root, "a/b/c.md") == root.resolve() / "a" / "b" / "c.md"


def test_unsafe_op_aborts_the_whole_batch(tmp_path):
    mem = memory_dir(tmp_path)
    ops = [
        {"op": "write", "root": "memory", "path": "good.md", "content": "x"},
        {"op": "write", "root": "memory", "path": "../bad.md", "content": "x"},
    ]
    with pytest.raises(dream.UnsafePath):
        dream.apply_ops(ops, mem, None, TODAY, CAPS)
    assert not (mem / "good.md").exists()
    assert not (tmp_path / "bad.md").exists()


def test_malformed_ops_abort_the_batch(tmp_path):
    mem = memory_dir(tmp_path)
    good = {"op": "write", "root": "memory", "path": "good.md", "content": "x"}
    for bad in (
        {"op": "delete", "path": "a.md"},
        {"op": "write", "root": "elsewhere", "path": "a.md", "content": "x"},
        {"op": "write", "root": "target", "path": "a.md", "content": "x"},
        {"op": "write", "root": "memory", "path": "a.md"},
        {"op": "retire", "path": "missing.md", "superseded_by": "n"},
        {"op": "index", "section": "S\nT", "line": "- x"},
    ):
        with pytest.raises(ValueError):
            dream.apply_ops([good, bad], mem, None, TODAY, CAPS)
        assert not (mem / "good.md").exists()


def test_write_ops_reach_memory_and_target_roots(tmp_path):
    mem = memory_dir(tmp_path)
    target = tmp_path / "repo"
    target.mkdir()
    ops = [
        {"op": "write", "root": "memory", "path": "a.md", "content": "A"},
        {"op": "write", "root": "target", "path": "docs/AGENTS.md", "content": "B"},
    ]
    touched = dream.apply_ops(ops, mem, target, TODAY, CAPS)
    assert (mem / "a.md").read_text() == "A"
    assert (target / "docs" / "AGENTS.md").read_text() == "B"
    assert touched == ["a.md", "docs/AGENTS.md"]


def test_retire_moves_file_stamps_frontmatter_and_drops_index_line(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "old.md").write_text(NOTE.format(n="old"), encoding="utf-8")
    (mem / "keep.md").write_text(NOTE.format(n="keep"), encoding="utf-8")
    (mem / "MEMORY.md").write_text(
        "# Index\n- [old](old.md) - hook\n- [keep](keep.md) - hook\n", encoding="utf-8"
    )
    dream.apply_ops(
        [{"op": "retire", "path": "old.md", "superseded_by": "new"}], mem, None, TODAY, CAPS
    )
    assert not (mem / "old.md").exists()
    moved = (mem / "_retired" / "old.md").read_text(encoding="utf-8")
    meta = dream.parse_memory(moved)
    assert meta["superseded_by"] == "new"
    assert meta["retired"] == "2026-11-05"
    assert moved.endswith("---\nBody\n")
    index = (mem / "MEMORY.md").read_text(encoding="utf-8")
    assert "old.md" not in index and "keep.md" in index


def test_index_op_inserts_under_section_and_creates_missing_section(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "MEMORY.md").write_text(
        "# Index\n\n## Feedback\n- [a](a.md) - x\n\n## Reference\n- [r](r.md) - y\n",
        encoding="utf-8",
    )
    dream.apply_ops(
        [
            {"op": "index", "section": "Feedback", "line": "- [b](b.md) - z"},
            {"op": "index", "section": "Projects", "line": "- [p](p.md) - w"},
        ],
        mem,
        None,
        TODAY,
        CAPS,
    )
    lines = (mem / "MEMORY.md").read_text(encoding="utf-8").splitlines()
    assert lines.index("- [b](b.md) - z") == lines.index("- [a](a.md) - x") + 1
    assert lines.index("- [b](b.md) - z") < lines.index("## Reference")
    assert lines[-2:] == ["## Projects", "- [p](p.md) - w"]


def test_claude_md_over_200_lines_is_refused_and_untouched(tmp_path):
    mem = memory_dir(tmp_path)
    target = tmp_path / "repo"
    target.mkdir()
    (target / "CLAUDE.md").write_text("old\n", encoding="utf-8")
    ops = [
        {"op": "write", "root": "memory", "path": "good.md", "content": "x"},
        {"op": "write", "root": "target", "path": "CLAUDE.md", "content": "l\n" * 201},
    ]
    with pytest.raises(dream.TooLong):
        dream.apply_ops(ops, mem, target, TODAY, CAPS)
    assert (target / "CLAUDE.md").read_text() == "old\n"
    assert not (mem / "good.md").exists()
    dream.apply_ops(
        [{"op": "write", "root": "target", "path": "AGENTS.md", "content": "l\n" * 200}],
        mem, target, TODAY, CAPS,
    )


def test_mark_promoted_is_idempotent(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")
    dream.mark_promoted(mem, "a.md", "CLAUDE.md")
    first = (mem / "a.md").read_text(encoding="utf-8")
    dream.mark_promoted(mem, "a.md", "CLAUDE.md")
    assert (mem / "a.md").read_text(encoding="utf-8") == first
    assert dream.parse_memory(first)["promoted_to"] == "CLAUDE.md"
    assert first.count("promoted_to") == 1
    with pytest.raises(dream.UnsafePath):
        dream.mark_promoted(mem, "../a.md", "CLAUDE.md")


def w(root, path, content="x"):
    return {"op": "write", "root": root, "path": path, "content": content}


def rejects(ops, mem, target=None, exc=ValueError):
    good = w("memory", "good.md")
    with pytest.raises(exc):
        dream.apply_ops([good] + ops, mem, target, TODAY, CAPS)
    assert not (mem / "good.md").exists()


def test_target_writes_are_limited_to_instruction_files(tmp_path):
    mem = memory_dir(tmp_path)
    target = tmp_path / "repo"
    (target / ".git" / "hooks").mkdir(parents=True)
    for path in (".git/hooks/pre-commit", ".GIT/config", ".git", ".claude/settings.json", "notes.md"):
        rejects([w("target", path)], mem, target, dream.UnsafePath)
    rejects([w("target", "claude.md", "l\n" * 201)], mem, target, dream.TooLong)
    rejects([w("target", "Agents.MD", "l\n" * 201)], mem, target, dream.TooLong)


def test_target_instruction_symlink_is_refused(tmp_path):
    mem = memory_dir(tmp_path)
    target = tmp_path / "repo"
    target.mkdir()
    (target / "real.txt").write_text("keep")
    try:
        os.symlink(str(target / "real.txt"), str(target / "CLAUDE.md"))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    rejects([w("target", "CLAUDE.md", "l\n" * 300)], mem, target, dream.UnsafePath)
    assert (target / "real.txt").read_text() == "keep"


def test_retire_cannot_touch_the_index_or_retired_by_case(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "MEMORY.md").write_text("# Index\n", encoding="utf-8")
    (mem / "_retired").mkdir()
    (mem / "_retired" / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")
    rejects([{"op": "retire", "path": "memory.md", "superseded_by": "n"}], mem)
    rejects([{"op": "retire", "path": "_RETIRED/a.md", "superseded_by": "n"}], mem)
    assert (mem / "MEMORY.md").exists()


def test_line_separators_cannot_forge_frontmatter_or_index_entries(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "old.md").write_text(NOTE.format(n="old"), encoding="utf-8")
    (mem / "MEMORY.md").write_text("# Index\n", encoding="utf-8")
    for sep in ("\x0b", "\x0c", "\x85", "\u2028", "\u2029", "\x1c"):
        rejects([{"op": "retire", "path": "old.md", "superseded_by": "n" + sep + "type: x"}], mem)
        rejects([{"op": "index", "section": "S", "line": "- [a](a.md)" + sep + "- [b](b.md)"}], mem)
        rejects([{"op": "index", "section": "S" + sep + "T", "line": "- [a](a.md)"}], mem)


def test_index_line_may_link_only_to_bare_md_names(tmp_path):
    mem = memory_dir(tmp_path)
    for bad in ("- [a](../a.md)", "- [a](x/a.md)", "- [a](a.txt)", "- [a](/etc/a.md)"):
        rejects([{"op": "index", "section": "S", "line": bad}], mem)


def test_mark_promoted_rejects_separator_injection(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")
    with pytest.raises(ValueError):
        dream.mark_promoted(mem, "a.md", "x\x0btype: y")
    assert "promoted_to" not in (mem / "a.md").read_text(encoding="utf-8")


def test_memory_writes_reject_dot_segments(tmp_path):
    mem = memory_dir(tmp_path)
    for path in (".git/hooks/pre-commit", ".GIT/config", ".git", "sub/.claude/settings.json", ".hidden.md"):
        rejects([w("memory", path)], mem, None, dream.UnsafePath)


def test_apply_time_failures_are_caught_in_validation(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "bare.md").write_text("no frontmatter\n", encoding="utf-8")
    (mem / "bin.md").write_bytes(b"\xff\xfe\x00")
    (mem / "ok.md").write_text(NOTE.format(n="ok"), encoding="utf-8")
    (mem / "adir").mkdir()
    retire = lambda name: {"op": "retire", "path": name, "superseded_by": "n"}
    rejects([retire("bare.md")], mem)
    rejects([retire("bin.md")], mem)
    rejects([retire("ok.md"), retire("ok.md")], mem)
    rejects([w("memory", "adir")], mem)
    assert (mem / "ok.md").exists() and not (mem / "_retired").exists()


def snapshot(root):
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def untouched(ops, mem, setup=None, exc=ValueError):
    """The batch (good write first) is refused and the folder is byte-identical."""
    if setup:
        setup(mem)
    before = snapshot(mem)
    with pytest.raises(exc):
        dream.apply_ops([w("memory", "good.md")] + ops, mem, None, TODAY, CAPS)
    assert snapshot(mem) == before


def retire(name):
    return {"op": "retire", "path": name, "superseded_by": "n"}


def idx(line="- [a](a.md)"):
    return {"op": "index", "section": "S", "line": line}


def test_unusual_line_breaks_retire_cleanly_and_unencodable_content_is_refused(tmp_path):
    for n, raw in enumerate((b"---\x0bname: a\x0b---\nbody\n", b"---\rname: a\r---\rbody\r")):
        mem = memory_dir(tmp_path / str(n))
        (mem / "a.md").write_bytes(raw)
        dream.apply_ops([retire("a.md")], mem, None, TODAY, CAPS)
        meta = dream.parse_memory((mem / "_retired" / "a.md").read_text(encoding="utf-8"))
        assert meta["superseded_by"] == "n" and not (mem / "a.md").exists()
    untouched([w("memory", "s.md", "\ud800")], memory_dir(tmp_path / "3"))


def test_file_directory_conflicts_leave_everything_untouched(tmp_path):
    untouched([w("memory", "d/x.md"), w("memory", "d")], memory_dir(tmp_path / "1"))
    untouched([w("memory", "a.md"), w("memory", "a.md/b.md")], memory_dir(tmp_path / "2"))
    untouched(
        [w("memory", "f.md/b.md")],
        memory_dir(tmp_path / "3"),
        lambda m: (m / "f.md").write_text("x"),
    )


def test_bad_index_file_leaves_everything_untouched(tmp_path):
    def note(m):
        (m / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")

    def binary_index(m):
        note(m)
        (m / "MEMORY.md").write_bytes(b"# I\n\xff\n")

    untouched([retire("a.md")], memory_dir(tmp_path / "1"), binary_index)
    untouched([idx()], memory_dir(tmp_path / "2"), binary_index)
    untouched([idx()], memory_dir(tmp_path / "3"), lambda m: (m / "MEMORY.md").mkdir())


def test_retire_whose_destination_was_written_earlier_is_refused(tmp_path):
    mem = memory_dir(tmp_path)
    untouched(
        [w("memory", "_retired/a.md", "MINE"), retire("a.md")],
        mem,
        lambda m: (m / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8"),
    )


def test_retire_then_rewrite_the_same_name_is_applied(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")
    dream.apply_ops([retire("a.md"), w("memory", "a.md", "new")], mem, None, TODAY, CAPS)
    assert (mem / "a.md").read_text() == "new"
    assert (mem / "_retired" / "a.md").exists()


def test_a_failing_write_rolls_back_the_earlier_ones(tmp_path, monkeypatch):
    mem = memory_dir(tmp_path)
    (mem / "keep.md").write_text("old", encoding="utf-8")
    before = snapshot(mem)
    real = dream._put
    calls = []

    def flaky(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(dream, "_put", flaky)
    ops = [w("memory", "keep.md", "new"), w("memory", "sub/dir/b.md"), w("memory", "c.md")]
    with pytest.raises(OSError):
        dream.apply_ops(ops, mem, None, TODAY, CAPS)
    assert len(calls) == 2
    assert snapshot(mem) == before


def test_index_lines_accept_only_the_plain_form(tmp_path):
    mem = memory_dir(tmp_path)
    for bad in (
        "- [a](<../x.md>)",
        "[1]: ../../etc/passwd",
        "- [a](a.md) <../../etc/x.md>",
        "- [a](C:secret.md)",
        "- [a](https:evil.md)",
        "- [a](a.md) [b](b.md)",
        "- [a](a.md) [1]: ../x",
        "- [a](a.md \"t\")",
        "just text",
    ):
        untouched([idx(bad)], mem)
    dream.apply_ops([idx("- [a](a.md) - a hook, with (parens)")], mem, None, TODAY, CAPS)


def test_hidden_directory_reached_through_a_symlink_is_refused(tmp_path):
    mem = memory_dir(tmp_path)
    (mem / ".git" / "hooks").mkdir(parents=True)
    try:
        os.symlink(".git", str(mem / "g"))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    untouched([w("memory", "g/hooks/pre-commit")], mem, None, dream.UnsafePath)


def test_unprintable_path_segments_are_refused(tmp_path):
    mem = memory_dir(tmp_path)
    for path in ("a\x0bb.md", "a\u202eb.md", "d\x85/x.md"):
        untouched([w("memory", path)], mem, None, dream.UnsafePath)


def test_rollback_removes_nested_created_directories(tmp_path, monkeypatch):
    mem = memory_dir(tmp_path)
    real = dream._put
    calls = []

    def flaky(path, data):
        calls.append(path)
        if len(calls) == 3:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(dream, "_put", flaky)
    ops = [w("memory", "a/b/x.md"), w("memory", "a/b/c/y.md"), w("memory", "z.md")]
    with pytest.raises(OSError):
        dream.apply_ops(ops, mem, None, TODAY, CAPS)
    assert snapshot(mem) == {}


def test_failed_restore_never_loses_a_retired_note_and_names_the_path(tmp_path, monkeypatch):
    mem = memory_dir(tmp_path)
    (mem / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")
    real_put, real_undo = dream._put, dream._undo

    def flaky_put(path, data):
        if path.name == "a.md":
            raise OSError("disk full")
        real_put(path, data)

    def flaky_undo(path, data):
        if path.name == "good.md":
            raise OSError("cannot restore")
        real_undo(path, data)

    monkeypatch.setattr(dream, "_put", flaky_put)
    monkeypatch.setattr(dream, "_undo", flaky_undo)
    with pytest.raises(dream.RestoreFailed) as info:
        dream.apply_ops([w("memory", "good.md"), retire("a.md")], mem, None, TODAY, CAPS)
    assert "good.md" in str(info.value)
    assert isinstance(info.value.__cause__, OSError)
    assert (mem / "a.md").exists()


def test_retiring_a_note_written_in_the_same_batch_leaves_only_the_retired_copy(tmp_path):
    mem = memory_dir(tmp_path)
    dream.apply_ops([w("memory", "n.md", NOTE.format(n="n")), retire("n.md")], mem, None, TODAY, CAPS)
    assert not (mem / "n.md").exists()
    assert dream.parse_memory((mem / "_retired" / "n.md").read_text())["superseded_by"] == "n"


def test_file_directory_conflicts_compare_case_insensitively(tmp_path):
    untouched([w("memory", "D"), w("memory", "d/x.md")], memory_dir(tmp_path))


def test_case_variant_spellings_of_one_path_are_refused(tmp_path):
    def note(m):
        (m / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")

    untouched([retire("a.md"), w("memory", "A.md", NOTE.format(n="new"))], memory_dir(tmp_path / "1"), note)
    untouched([w("memory", "A.md", NOTE.format(n="new")), retire("a.md")], memory_dir(tmp_path / "2"), note)


def test_a_retired_path_cannot_become_a_directory(tmp_path):
    def note(m):
        (m / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")

    untouched([retire("a.md"), w("memory", "a.md/x.md")], memory_dir(tmp_path / "1"), note)
    untouched([retire("a.md"), w("memory", "A.md/x.md")], memory_dir(tmp_path / "2"), note)


def test_failed_original_restore_keeps_every_written_copy(tmp_path, monkeypatch):
    mem = memory_dir(tmp_path)
    for n in ("a", "b"):
        (mem / (n + ".md")).write_text(NOTE.format(n=n), encoding="utf-8")
    real_unlink, real_undo = Path.unlink, dream._undo

    def flaky_unlink(self, *args, **kwargs):
        if self.name == "b.md" and self.parent.name != "_retired":
            raise OSError("unlink failed")
        real_unlink(self, *args, **kwargs)

    def flaky_undo(path, data):
        if path.name == "a.md" and path.parent.name != "_retired":
            raise OSError("cannot restore")
        real_undo(path, data)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(dream, "_undo", flaky_undo)
    with pytest.raises(dream.RestoreFailed) as info:
        dream.apply_ops([retire("a.md"), retire("b.md")], mem, None, TODAY, CAPS)
    assert "a.md" in str(info.value)
    assert isinstance(info.value.__cause__, OSError)
    copies = [p for p in mem.rglob("a.md") if b"name: a" in p.read_bytes()]
    assert copies


def test_case_variant_spellings_are_refused_where_paths_resolve_to_the_existing_case(tmp_path, monkeypatch):
    real = dream.safe_path

    def canonical(root, rel):
        full = real(root, rel)
        if full.parent.is_dir():
            same = [p for p in full.parent.iterdir() if p.name.casefold() == full.name.casefold()]
            if same:
                return same[0]
        return full

    monkeypatch.setattr(dream, "safe_path", canonical)

    def note(m):
        (m / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")

    untouched([retire("a.md"), w("memory", "A.md", NOTE.format(n="new"))], memory_dir(tmp_path / "1"), note)
    untouched([w("memory", "A.md", NOTE.format(n="new")), retire("a.md")], memory_dir(tmp_path / "2"), note)
    untouched([w("memory", "a.md", NOTE.format(n="x")), w("memory", "A.md", NOTE.format(n="y"))],
              memory_dir(tmp_path / "3"), note)


def test_one_spelling_written_twice_is_allowed(tmp_path):
    mem = memory_dir(tmp_path)
    dream.apply_ops([w("memory", "b.md", NOTE.format(n="x")), w("memory", "b.md", NOTE.format(n="b"))],
                    mem, None, TODAY, CAPS)
    assert (mem / "b.md").read_text(encoding="utf-8") == NOTE.format(n="b")


@pytest.mark.parametrize("spelling", ["_retired/a.md", "_RETIRED/a.md", "_Retired/new.md"])
def test_memory_writes_into_the_retired_folder_are_refused(tmp_path, spelling):
    def note(m):
        (m / "a.md").write_text(NOTE.format(n="a"), encoding="utf-8")

    untouched([retire("a.md"), w("memory", spelling, NOTE.format(n="forged"))], memory_dir(tmp_path / "1"), note)
    untouched([w("memory", spelling, NOTE.format(n="forged"))], memory_dir(tmp_path / "2"), note)
