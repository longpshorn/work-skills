import os
import re
from pathlib import Path

import pytest

import okf_check
import work
from helpers import header

SKILLS = Path(work.__file__).resolve().parents[1] / "skills"


def build(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


GOOD = {
    "index.md": '---\nokf_version: "0.2"\n---\n\n# Tables\n\n* [Orders](tables/orders.md) - One row per order\n'
                "* [Tables](tables/) - All tables\n",
    "log.md": "# Directory Update Log\n\n## 2026-05-22\n* **Update**: Added orders.\n",
    "tables/index.md": "# Tables\n\n* [Orders](orders.md)\n",
    "tables/orders.md": "---\ntype: BigQuery Table\ntitle: Orders\ntags: [sales]\n"
                        "generated: { by: human:x, at: 2026-06-30T14:00:00Z }\n"
                        "sources:\n  - id: a\n    resource: https://x\n---\n\n# Schema\n",
}


def test_checker_passes_a_conformant_bundle(tmp_path):
    assert okf_check.problems(build(tmp_path, GOOD)) == []


@pytest.mark.parametrize("name,text,reason", [
    ("a.md", "# no frontmatter\n", "a.md: no frontmatter"),
    ("a.md", "---\ntitle: A\n---\n", "a.md: no type"),
    ("a.md", "---\ntype: \n---\n", "a.md: no type"),
    ("a.md", "---\ntype: X\n", "a.md: unterminated frontmatter"),
    ("notes/INDEX.md", "# Work Index\n", "notes/INDEX.md: no frontmatter"),
    ("sub/index.md", '---\nokf_version: "0.2"\n---\n', "sub/index.md: index.md frontmatter is allowed only"),
    ("index.md", "# A\n\n| [T](t.md) | x |\n", "index.md: index.md line is neither"),
    ("log.md", "# Log\n\n## May 22\n", "log.md: log.md date heading is not YYYY-MM-DD"),
    ("log.md", "# Log\n\n## 2026-05-15\n\n## 2026-05-22\n", "log.md: log.md dates are not newest first"),
    ("log.md", "# Log\n\n## 2026-05-22\n\n## 2026-05-22\n", "log.md: log.md dates are not newest first"),
])
def test_checker_reports_each_violation(tmp_path, name, text, reason):
    found = okf_check.problems(build(tmp_path, {**GOOD, name: text}))
    assert len(found) == 1 and found[0].startswith(reason)


def skill_templates(skill):
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    return [re.sub(r"(?m)^   ", "", block) for block in re.findall(r"```markdown\n(.*?)```", text, re.S)]


def fill(template):
    return re.sub(r"<[^>]*>", "x", template)


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    root = tmp_path / "store"
    monkeypatch.setenv("WORK_STORE", str(root))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "t")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@t")
    return root


def test_a_store_written_by_init_and_the_new_skill_conforms(fresh):
    assert work.main(["init"]) == 0
    area, status = map(fill, skill_templates("new"))
    build(fresh, {"garden/AREA.md": area, "garden/01-plant.md": status})
    assert work.main(["touch", "garden/01-plant"]) == 0
    assert work.main(["index"]) == 0
    assert (fresh / "log.md").is_file()
    assert okf_check.problems(fresh) == []
    meta = work.parse_header((fresh / "garden/01-plant.md").read_text(encoding="utf-8"))
    assert meta["type"] == "workstream" and meta["description"] and meta["generated"]["by"] == work.ACTOR
    area_meta, _ = okf_check.split((fresh / "garden/AREA.md").read_text(encoding="utf-8"))
    assert area_meta["type"] == "area" and area_meta["description"]


def test_a_workstream_archived_by_the_wrap_skill_is_deprecated_and_conforms(fresh):
    assert work.main(["init"]) == 0
    area, status = map(fill, skill_templates("new"))
    build(fresh, {"garden/AREA.md": area, "garden/01-plant.md": status.replace("state: scoped", "state: done")})
    assert work.main(["touch", "garden/01-plant"]) == 0
    (fresh / "_archive/garden").mkdir(parents=True)
    os.replace(fresh / "garden/01-plant.md", fresh / "_archive/garden/01-plant.md")
    assert work.main(["index"]) == 0
    meta = work.parse_header((fresh / "_archive/garden/01-plant.md").read_text(encoding="utf-8"))
    assert meta["state"] == "done" and meta["status"] == work.ARCHIVED_STATUS
    assert okf_check.problems(fresh) == []


def test_a_store_from_before_okf_conforms_after_one_index_run(store):
    build(store, {
        "README.md": "# Work store\n",
        "INDEX.md": "# Work Index\n\n| Workstream | Status |\n|---|---|\n",
        "garden/AREA.md": "# Garden\n\n**Purpose:** grow\n",
        "garden/01-plant.md": header(state=None, status="active   # idea | active"),
        "side-work/01-once.md": header(state=None, status="idea", report="false"),
        "_archive/garden/02-old.md": header(state=None, status="done"),
    })
    assert okf_check.problems(store) != []
    assert work.main(["index"]) == 0
    assert okf_check.problems(store) == []
    archived = work.parse_header((store / "_archive/garden/02-old.md").read_text(encoding="utf-8"))
    assert archived["status"] == work.ARCHIVED_STATUS
