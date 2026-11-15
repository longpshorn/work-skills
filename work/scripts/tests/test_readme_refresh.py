"""index refreshes an unedited older copy of the store README and keeps an edited one (#47)."""
import hashlib
import subprocess
from pathlib import Path

import pytest

import work

REPO = Path(work.__file__).resolve().parents[2]
TEMPLATE_PATH = work.TEMPLATE.relative_to(REPO).as_posix()


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, encoding="utf-8", check=True).stdout


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
    """Coverage, not equality: a squash merge drops a branch's intermediate versions from main's history, and
    their fingerprints in PAST_TEMPLATES are harmless."""
    expected = {work.readme_fingerprint(text) for text in past_versions()}
    missing = expected - work.PAST_TEMPLATES
    assert not missing, f"add these to work.PAST_TEMPLATES: {sorted(missing)}"
    assert work.readme_fingerprint(current()) not in work.PAST_TEMPLATES


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
    write_raw(readme, "\ufeff" + old.replace("\n", "\r\n"))
    assert work.main(["index"]) == 0
    assert read_raw(readme) == "\ufeff" + current().replace("\n", "\r\n")


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


def listing(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_index_says_so_once_in_a_store_without_git(store, capsys):
    path = store / "README.md"
    write_raw(path, edited())
    assert work.main(["index"]) == 0
    assert "README.md: " in capsys.readouterr().err
    files = listing(store)
    assert files == sorted(["README.md", work.INDEX, work.LOG])
    assert work.main(["index"]) == 0
    assert read_raw(path) == edited()
    assert "README.md" not in capsys.readouterr().err
    assert listing(store) == files


def test_two_stores_without_git_each_say_so_once(tmp_path, monkeypatch, capsys):
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        write_raw(root / "README.md", edited())
        monkeypatch.setenv("WORK_STORE", str(root))
        assert work.main(["index"]) == 0
        assert "README.md: " in capsys.readouterr().err
    for name in ("one", "two"):
        monkeypatch.setenv("WORK_STORE", str(tmp_path / name))
        assert work.main(["index"]) == 0
        assert "README.md" not in capsys.readouterr().err


def test_a_state_folder_that_cannot_be_written_repeats_the_notice(store, tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "a-file"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv("WORK_DREAM_STATE", str(blocker / "state"))
    write_raw(store / "README.md", edited())
    for _ in range(2):
        assert work.main(["index"]) == 0
        assert "README.md: " in capsys.readouterr().err


def test_a_store_with_git_never_touches_the_state_folder(readme, isolated_state, capsys):
    write_raw(readme, edited())
    for _ in range(2):
        assert work.main(["index"]) == 0
    assert (readme.parent / ".git" / work.README_KEPT_MARKER).is_file()
    assert not isolated_state.exists()


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
    same = {work.readme_fingerprint(t) for t in (text, "\ufeff" + text, text.replace("\n", "\r\n"), untyped)}
    assert same == {work.readme_fingerprint(text)}
    assert work.readme_fingerprint(edited()) != work.readme_fingerprint(text)
    assert len(work.readme_fingerprint(text)) == len(hashlib.sha256().hexdigest())
