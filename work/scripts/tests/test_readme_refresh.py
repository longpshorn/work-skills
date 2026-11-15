"""index refreshes an unedited older copy of the store README and keeps an edited one (#47)."""
import hashlib
import subprocess
from pathlib import Path

import pytest

import work

REPO = Path(work.__file__).resolve().parents[2]
TEMPLATE_PATH = work.TEMPLATE.relative_to(REPO).as_posix()


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def shallow():
    try:
        return git("rev-parse", "--is-shallow-repository").strip() == "true"
    except (OSError, subprocess.CalledProcessError):
        return True


needs_history = pytest.mark.skipif(shallow(), reason="needs the template's full git history (fetch-depth: 0)")


def committed_versions():
    """The text of every committed version of the store README template, oldest first, LF line endings."""
    revs = git("rev-list", "--reverse", "HEAD", "--", TEMPLATE_PATH).split()
    return [git("show", f"{rev}:{TEMPLATE_PATH}") for rev in revs]


def current():
    return work.TEMPLATE.read_text(encoding="utf-8")


def past_versions():
    now = work.readme_fingerprint(current())
    return [text for text in committed_versions() if work.readme_fingerprint(text) != now]


def read_raw(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_raw(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def edited():
    return current().replace("Private working notes", "My own notes", 1)


@pytest.fixture
def readme(store):
    (store / ".git").mkdir()
    return store / "README.md"


@needs_history
def test_past_templates_cover_the_template_history():
    expected = {work.readme_fingerprint(text) for text in past_versions()}
    missing = expected - work.PAST_TEMPLATES
    assert not missing, f"add these to work.PAST_TEMPLATES: {sorted(missing)}"
    assert work.PAST_TEMPLATES == expected


@needs_history
def test_index_refreshes_every_past_copy(readme):
    versions = past_versions()
    assert versions
    for text in versions:
        write_raw(readme, text)
        assert work.main(["index"]) == 0
        assert read_raw(readme) == current()


@needs_history
def test_index_refreshes_a_past_copy_an_earlier_index_already_typed(readme):
    oldest = committed_versions()[0]
    write_raw(readme, work.upgraded(oldest, "README.md"))
    assert work.main(["index"]) == 0
    assert read_raw(readme) == current()


@needs_history
def test_index_refreshes_a_bom_crlf_past_copy_keeping_both(readme):
    old = past_versions()[-1]
    write_raw(readme, "﻿" + old.replace("\n", "\r\n"))
    assert work.main(["index"]) == 0
    assert read_raw(readme) == "﻿" + current().replace("\n", "\r\n")


@needs_history
def test_index_twice_after_a_refresh_changes_nothing(readme):
    write_raw(readme, past_versions()[-1])
    work.main(["index"])
    after = read_raw(readme)
    mtime = readme.stat().st_mtime_ns
    assert work.main(["index"]) == 0
    assert read_raw(readme) == after and readme.stat().st_mtime_ns == mtime


def test_index_keeps_an_edited_readme_and_says_so_once(readme, capsys):
    write_raw(readme, edited())
    assert work.main(["index"]) == 0
    assert read_raw(readme) == edited()
    err = capsys.readouterr().err
    assert err.count("README.md: ") == 1 and "kept it as it is" in err and str(work.TEMPLATE) in err
    assert "# Errors" not in (readme.parent / "index.md").read_text(encoding="utf-8")
    assert work.main(["index"]) == 0
    assert read_raw(readme) == edited()
    assert "README.md" not in capsys.readouterr().err


def test_index_says_so_again_after_the_readme_changes(readme, capsys):
    write_raw(readme, edited())
    work.main(["index"])
    capsys.readouterr()
    write_raw(readme, edited() + "\nMore of my own notes.\n")
    work.main(["index"])
    assert "README.md: " in capsys.readouterr().err


def test_index_keeps_an_edited_readme_in_a_store_without_git(store, capsys):
    path = store / "README.md"
    write_raw(path, edited())
    for _ in range(2):
        assert work.main(["index"]) == 0
        assert read_raw(path) == edited()
        assert "README.md: " in capsys.readouterr().err
    assert not (store / ".git").exists()


def test_index_leaves_the_current_template_alone(readme, capsys):
    write_raw(readme, current())
    mtime = readme.stat().st_mtime_ns
    assert work.main(["index"]) == 0
    assert read_raw(readme) == current() and readme.stat().st_mtime_ns == mtime
    assert "README.md" not in capsys.readouterr().err


def test_index_reports_a_non_utf8_readme_and_never_writes_it(readme, capsys):
    data = current().encode("utf-8").replace(b"Private", b"Priv\xe9te", 1)
    readme.write_bytes(data)
    assert work.main(["index"]) == 1
    assert readme.read_bytes() == data
    assert "README.md: not valid UTF-8" in capsys.readouterr().err


def test_fingerprint_ignores_bom_crlf_and_the_type_index_adds():
    text = current()
    untyped = text.replace("type: guide\n", "", 1)
    assert untyped != text
    same = {work.readme_fingerprint(t) for t in (text, "﻿" + text, text.replace("\n", "\r\n"), untyped)}
    assert same == {work.readme_fingerprint(text)}
    assert work.readme_fingerprint(edited()) != work.readme_fingerprint(text)
    assert len(work.readme_fingerprint(text)) == len(hashlib.sha256().hexdigest())
