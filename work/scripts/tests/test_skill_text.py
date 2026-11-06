"""The skill text works in any agent: Claude Code-only tools come with an alternative, and the missing hook is covered."""
import re
from pathlib import Path

import work

SKILLS = Path(work.__file__).resolve().parents[1] / "skills"
# The same list herdr-skills checks (herdr-skills#30), so the three plugins agree on what is Claude Code-only.
CLAUDE_ONLY = ("run_in_background", "AskUserQuestion", "/permissions")


def skill_lines():
    for path in sorted(SKILLS.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield path, number, line


def test_claude_code_only_tools_are_named_only_beside_an_alternative():
    offenders = [f"{path.parent.name}:{number}: {tool}" for path, number, line in skill_lines() for tool in CLAUDE_ONLY
                 if tool in line and not re.search(r"Claude Code: `%s`[^)]*elsewhere" % re.escape(tool), line)]
    assert offenders == []


def test_wrap_does_not_assume_claude_code_memory():
    text = (SKILLS / "wrap" / "SKILL.md").read_text(encoding="utf-8")
    memory = next(line for line in text.splitlines() if "**Memory.**" in line)
    assert "elsewhere" in memory


def test_resume_and_new_say_to_checkpoint_without_a_compaction_reminder():
    for skill in ("resume", "new"):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert any(all(part in line for part in ("post-compaction reminder", "Claude Code", "/work:checkpoint"))
                   for line in text.splitlines()), skill


def test_only_the_helper_line_needs_the_plugin_root():
    lines = [(path.parent.name, line) for path, _, line in skill_lines() if "${CLAUDE_PLUGIN_ROOT}" in line]
    assert lines and all(line.startswith("Helper: `sh \"${CLAUDE_PLUGIN_ROOT}/scripts/work-tools\"`")
                         for _, line in lines)
