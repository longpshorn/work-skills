import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dream
import work

CAPS = {"index_lines": 150, "index_bytes": 18432}

OLD = (
    "---\nname: {name}\ndescription: {desc}\nmetadata:\n  node_type: memory\n"
    "  type: feedback\n  originSessionId: 1234\n---\nBody\n"
)


def memory(tmp_path, files, index_lines=None):
    root = tmp_path / "mem"
    root.mkdir()
    for fname, text in files.items():
        path = root / fname
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if index_lines is None:
        index_lines = ["- [%s](%s) — hook" % (f[:-3], f) for f in files if "/" not in f]
    (root / "MEMORY.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return root


def old(name):
    return OLD.format(name=name, desc="about " + name)


def test_valid_folder_passes(tmp_path):
    root = memory(tmp_path, {"a.md": old("a"), "b.md": old("b")})
    assert dream.check_memory(root, CAPS) == []


def test_parse_memory_reads_nested_metadata_and_lists():
    meta = dream.parse_memory(
        "---\nname: a\nseen: [2026-01-01, 2026-01-02]\nmetadata:\n  type: user\n---\nbody")
    assert meta["metadata"] == {"type": "user"}
    assert meta["seen"] == ["2026-01-01", "2026-01-02"]


@pytest.mark.parametrize("text", ["no frontmatter", "---\nname: a\nno end"])
def test_parse_memory_rejects_bad_block(text):
    with pytest.raises(dream.FrontmatterError):
        dream.parse_memory(text)


def test_missing_required_field_is_reported(tmp_path):
    text = "---\nname: a\nmetadata:\n  type: user\n---\n"
    problems = dream.check_memory(memory(tmp_path, {"a.md": text}), CAPS)
    assert len(problems) == 1 and "a.md" in problems[0] and "description" in problems[0]


def test_missing_metadata_type_is_reported(tmp_path):
    text = "---\nname: a\ndescription: d\nmetadata:\n  node_type: memory\n---\n"
    problems = dream.check_memory(memory(tmp_path, {"a.md": text}), CAPS)
    assert len(problems) == 1 and "metadata.type" in problems[0]


def test_unparseable_file_is_reported(tmp_path):
    problems = dream.check_memory(memory(tmp_path, {"a.md": "plain"}), CAPS)
    assert len(problems) == 1 and "a.md" in problems[0]


def test_index_line_to_missing_file_and_unindexed_file_are_reported(tmp_path):
    root = memory(tmp_path, {"a.md": old("a")}, ["- [Gone](gone.md) — hook"])
    problems = dream.check_memory(root, CAPS)
    assert len(problems) == 2
    assert any("gone.md" in p for p in problems)
    assert any("a.md" in p and "index" in p for p in problems)


def test_size_caps(tmp_path):
    files = {"a.md": old("a")}
    lines = ["- [a](a.md) — hook"] + ["filler"] * 149
    assert dream.check_memory(memory(tmp_path, files, lines), CAPS) == []
    over = tmp_path / "over"
    over.mkdir()
    assert any("lines" in p for p in dream.check_memory(
        memory(over, files, lines + ["x"]), CAPS))
    big = tmp_path / "big"
    big.mkdir()
    fat = ["- [a](a.md) — hook", "y" * 19000]
    assert any("bytes" in p for p in dream.check_memory(memory(big, files, fat), CAPS))


def test_retired_needs_superseded_by_and_date_and_no_index_line(tmp_path):
    good = old("r").replace("---\nBody", "superseded_by: none\nretired: 2026-11-01\n---\nBody")
    root = memory(tmp_path, {"a.md": old("a"), "_retired/r.md": good})
    assert dream.check_memory(root, CAPS) == []

    bad = tmp_path / "bad"
    bad.mkdir()
    root = memory(bad, {"a.md": old("a"), "_retired/r.md": old("r")})
    problems = dream.check_memory(root, CAPS)
    assert any("superseded_by" in p for p in problems)
    assert any("retired" in p for p in problems)

    indexed = tmp_path / "indexed"
    indexed.mkdir()
    root = memory(indexed, {"a.md": old("a"), "_retired/r.md": good},
                  ["- [a](a.md) — hook", "- [r](_retired/r.md) — hook"])
    assert any("r.md" in p and "retired" in p for p in dream.check_memory(root, CAPS))


def test_promoted_to_must_be_non_empty(tmp_path):
    ok = old("a").replace("---\nBody", "promoted_to: CLAUDE.md\n---\nBody")
    assert dream.check_memory(memory(tmp_path, {"a.md": ok}), CAPS) == []
    empty = tmp_path / "empty"
    empty.mkdir()
    blank = old("a").replace("---\nBody", "promoted_to:\n---\nBody")
    assert any("promoted_to" in p for p in dream.check_memory(memory(empty, {"a.md": blank}), CAPS))


def test_cli_exit_codes(tmp_path, dream_env, capsys):
    good = memory(tmp_path, {"a.md": old("a")})
    assert work.main(["dream-check", "--memory-dir", str(good)]) == 0
    (good / "b.md").write_text(old("b"), encoding="utf-8")
    assert work.main(["dream-check", "--memory-dir", str(good)]) == 1
    assert "b.md" in capsys.readouterr().err
