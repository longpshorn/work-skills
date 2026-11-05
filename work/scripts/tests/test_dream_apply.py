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
    root.mkdir()
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
        {"op": "write", "root": "target", "path": "docs/b.md", "content": "B"},
    ]
    touched = dream.apply_ops(ops, mem, target, TODAY, CAPS)
    assert (mem / "a.md").read_text() == "A"
    assert (target / "docs" / "b.md").read_text() == "B"
    assert touched == ["a.md", "docs/b.md"]


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
