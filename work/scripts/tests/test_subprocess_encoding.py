"""Child output is decoded as UTF-8 whatever the locale says (cp1252 on Windows)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import dream
import work
from dream_helpers import init_repo
from helpers import header

SCRIPTS = Path(__file__).resolve().parents[1]
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
# A locale whose preferred encoding is ASCII: C, with PEP 538 coercion and PEP 540 UTF-8 mode both off. Windows
# ignores LC_ALL, and there the locale encoding is cp1252, which garbles UTF-8 instead of raising.
NON_UTF8_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
EM_DASH = "—"


# ---- Behaviour under a non-UTF-8 locale -----------------------------------------------------------------------------

def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=GIT_ENV)


def under_non_utf8_locale(code, **env):
    """Run CODE in a child Python whose locale encoding is not UTF-8; return its stdout (ASCII by construction)."""
    script = "import sys; sys.path.insert(0, %r)\n%s" % (str(SCRIPTS), textwrap.dedent(code))
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **NON_UTF8_LOCALE, **env})
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_git_reads_an_em_dash_subject_under_a_non_utf8_locale(tmp_path):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", str(repo))
    message = tmp_path / "message.txt"
    message.write_bytes(("checkpoint %s store" % EM_DASH).encode("utf-8"))
    git(repo, "commit", "-q", "--allow-empty", "-F", str(message))
    out = under_non_utf8_locale("""
        import work
        code, subject = work.git(%r, "log", "-1", "--format=%%s")
        print(ascii((code, subject)))
        """ % str(repo))
    assert out.strip() == ascii((0, "checkpoint %s store\n" % EM_DASH))


def test_drift_counts_a_non_ascii_file_under_a_non_utf8_locale(tmp_path, store, write):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "config", "core.quotepath", "false")  # git prints the name raw, as UTF-8 bytes
    (repo / "café.txt").write_text("x", encoding="utf-8")
    write("p/01-a", header(repos=f"[{repo}]"))
    out = under_non_utf8_locale("""
        import work
        sys.exit(work.main(["drift", "p/01-a"]))
        """, WORK_STORE=str(store))
    assert out == f"p/01-a\n  {repo}: 1 uncommitted, no upstream\n"


@pytest.mark.skipif(sys.platform != "linux", reason="only Linux file systems accept a name that is not UTF-8")
def test_drift_names_a_repo_whose_git_output_is_not_utf8(tmp_path, store, write, capsys):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "config", "core.quotepath", "false")
    (repo / os.fsdecode(b"caf\xe9.txt")).write_text("x", encoding="utf-8")  # a Latin-1 name
    write("p/01-a", header(repos=f"[{repo}]"))
    assert work.main(["drift", "p/01-a"]) == 0
    assert capsys.readouterr().out == f"p/01-a\n  {repo}: git printed non-UTF-8 output\n"


LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="only Linux file systems accept a name that is not UTF-8")
LATIN1_NAME = os.fsdecode(b"caf\xe9")


@LINUX_ONLY
def test_dream_reports_memory_git_output_that_is_not_utf8(tmp_path):
    repo = init_repo(tmp_path / "mem")
    rev = dream._out(repo, ["rev-parse", "HEAD"])
    (repo / (LATIN1_NAME + ".md")).write_text("x\n", encoding="utf-8")
    with pytest.raises(dream.ConfigError, match="git diff output is not UTF-8"):
        dream.changes_since(repo, rev)


@LINUX_ONLY
def test_repo_of_is_none_when_git_prints_a_path_that_is_not_utf8(tmp_path):
    main = init_repo(tmp_path / LATIN1_NAME)
    tree = tmp_path / "tree"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(tree)], check=True, capture_output=True)
    assert dream.repo_of(str(tree)) is None
    assert dream.repo_of(str(main)) == str(main)
