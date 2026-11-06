import os
import re
from pathlib import Path

import pytest

import work
from test_launcher import compact_hook_command

PLUGIN = Path(work.__file__).resolve().parents[1]
REPO = PLUGIN.parent
SKILL = PLUGIN / "skills" / "dream" / "SKILL.md"

TICKET_KEY = re.compile(r"[A-Z]{2,}-\d+")
ALLOWED_KEYS = {"KEY-1", "UTF-8"}

DENYLIST_ENV = "WORK_PORTABILITY_DENYLIST"
DENYLIST_DEFAULT = "~/.config/work/portability-denylist.txt"


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def body_lines():
    lines = skill_text().splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return lines[end + 1:]


def flat(text):
    return " ".join(text.lower().split())


def readme_dream_sections():
    text = (REPO / "README.md").read_text(encoding="utf-8")
    sections = re.split(r"(?m)^(?=#)", text)
    return "".join(s for s in sections if s.startswith("#") and "dream" in s.splitlines()[0].lower())


def portable_texts():
    paths = [PLUGIN / "scripts" / "dream.py", SKILL,
             PLUGIN / "templates" / "com.work.dream.plist", PLUGIN / "templates" / "dream.example.jsonc"]
    paths += sorted(p for p in (REPO / "evals" / "dream").glob("**/*") if p.is_file())
    texts = {str(p.relative_to(REPO)): p.read_text(encoding="utf-8", errors="replace") for p in paths}
    texts["README.md (dream sections)"] = readme_dream_sections()
    return texts


def denylist_path():
    return Path(os.path.expanduser(os.environ.get(DENYLIST_ENV) or DENYLIST_DEFAULT))


def read_denylist(path):
    """Lowercased tokens, one per line; blank lines and # comments are ignored."""
    lines = (line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
    return [line.lower() for line in lines if line]


def denied_tokens(text, tokens):
    lowered = text.lower()
    return {token for token in tokens if token in lowered}


def test_skill_is_under_500_lines_and_names_helper_line():
    assert len(skill_text().splitlines()) < 500
    first = next(line for line in body_lines() if line.strip() and not line.startswith("#"))
    helper = compact_hook_command().rsplit(" ", 1)[0]
    assert first.startswith("Helper: `%s`" % helper)


def test_skill_frontmatter_names_the_nightly_run():
    head = skill_text().split("---")[1]
    assert re.search(r"(?m)^name: dream$", head)
    description = re.search(r"(?m)^description: (.+)$", head).group(1).lower()
    assert "nightly" in description and "dream-run" in description


def test_skill_states_the_required_rules():
    text = flat(skill_text())
    required = [
        "only the user's own words",
        "tool output",
        "pasted",
        "never evidence",
        "`sources:`",
        "`_retired/`",
        "`superseded_by:`",
        "only when new evidence touches it",
        "`repo:`",
        "read-only",
        "`unverified:",
        "`checks.json`",
        "contradiction",
        "promotion",
        "at most 5 promotions",
        "nothing private",
        "repo file",
        "by a `contradiction` item in `checks.json`, never directly",
        "every `seen:` and `sources:` entry of the files it absorbs",
        "`]:`",
        "quote only the sentence that states what was proven",
        "`_global/` holds a read-only copy",
        "instead of retiring it",
        "adds no step, rule or scope",
    ]
    missing = [phrase for phrase in required if phrase not in text]
    assert missing == []


def test_skill_names_both_stage_modes():
    text = skill_text()
    assert "`extract`" in text and "`reorganize`" in text


def test_dream_files_name_no_ticket_key():
    found = {}
    for name, text in portable_texts().items():
        keys = set(TICKET_KEY.findall(text)) - ALLOWED_KEYS
        if keys:
            found[name] = sorted(keys)
    assert found == {}


def test_dream_files_name_no_org_or_person():
    path = denylist_path()
    if not path.is_file():
        pytest.skip("no denylist at %s: create it (one organization or person token per line, # comments allowed) "
                    "or point %s at one" % (path, DENYLIST_ENV))
    tokens = read_denylist(path)
    found = {name: sorted(hits) for name, text in portable_texts().items() for hits in [denied_tokens(text, tokens)]
             if hits}
    assert found == {}


def test_denylist_reader_follows_the_env_path_and_ignores_comments(tmp_path, monkeypatch):
    listing = tmp_path / "deny.txt"
    listing.write_text("# a comment\n\nZqxToken  # trailing note\n  other\n", encoding="utf-8")
    monkeypatch.setenv(DENYLIST_ENV, str(listing))
    assert denylist_path() == listing
    tokens = read_denylist(denylist_path())
    assert tokens == ["zqxtoken", "other"]
    assert denied_tokens("prefix-ZQXTOKEN-suffix, a comment", tokens) == {"zqxtoken"}


def test_skill_has_no_unfilled_markers():
    assert not re.search(r"\b(?:TBD|TODO)\b", skill_text())


def test_readme_lists_the_dream_command_and_install():
    text = flat((REPO / "README.md").read_text(encoding="utf-8"))
    for phrase in ("| `/work:dream`", "dream-install", "dream.json", "never merges", "unattended",
                   "paid models", "default branch"):
        assert phrase in text


def test_wrap_points_at_dream_for_memory():
    step = next(line for line in (PLUGIN / "skills" / "wrap" / "SKILL.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("3. **Memory.**"))
    assert "nightly dream run" in step


def test_standup_shows_dream_status():
    text = (PLUGIN / "skills" / "standup" / "SKILL.md").read_text(encoding="utf-8")
    assert "work-tools dream-status" in text
    assert "only when it prints" in text


def test_store_readme_lists_dream_among_skills():
    text = (PLUGIN / "templates" / "store-README.md").read_text(encoding="utf-8")
    assert "`/work:dream`" in next(line for line in text.splitlines() if line.startswith("Skills:"))


def test_readme_says_how_to_turn_it_off():
    text = flat((REPO / "README.md").read_text(encoding="utf-8"))
    assert "launchctl bootout gui/$(id -u)/com.work.dream" in text
    assert "launchctl disable gui/$(id -u)/com.work.dream" in text
    assert "delete `~/library/launchagents/com.work.dream.plist`" in text
    assert "dream-install --load" in text


def test_skill_takes_the_config_path_from_the_system_prompt():
    text = (Path(__file__).resolve().parents[2] / "skills" / "dream" / "SKILL.md").read_text(encoding="utf-8")
    assert "WORK_DREAM_CONFIG" not in text
    assert "the config file the system prompt names" in text
