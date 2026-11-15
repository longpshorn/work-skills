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


def test_standup_offers_missing_descriptions_with_approval():
    text = (SKILLS / "standup" / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = text.split("---")[1]
    assert "Read-only apart from" in frontmatter and "approve" in frontmatter
    step = next(line for line in text.splitlines() if "work-tools list --no-description" in line)
    for part in ("/work:checkpoint", "step 2", "Claude Code: `AskUserQuestion`", "elsewhere",
                 "at most 4 options", "more than 4", "work-tools index", "already listed in step 1",
                 'commit -m "standup: describe', "nothing is written"):
        assert part in step, part
    assert "work-tools touch" not in step, "touch would reset a stale workstream's age"
    assert "work-tools list --no-description 2>/dev/null" in step, "a bad file must be listed once"


def test_new_checks_for_a_pre_okf_store_before_writing_anything():
    """touch refuses a pre-OKF store, so a workstream written there would have no date at all."""
    lines = (SKILLS / "new" / "SKILL.md").read_text(encoding="utf-8").splitlines()
    write = next(i for i, line in enumerate(lines) if line.startswith("5. **Write"))
    check = next(i for i, line in enumerate(lines) if "predates the OKF format" in line)
    assert check < write
    for part in ("work-tools index", "upgrade hint", "stop without creating the workstream"):
        assert part in lines[check], part


def test_checkpoint_says_what_to_do_when_the_store_predates_okf():
    step = next(line for line in (SKILLS / "checkpoint" / "SKILL.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("3. "))
    for part in ("predates the OKF format", "upgrade hint", "rather than editing headers by hand",
                 "still commit", "once the store is upgraded"):
        assert part in step, part
