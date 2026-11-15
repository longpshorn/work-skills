"""Child output is decoded as UTF-8 whatever the locale says (cp1252 on Windows), and the rule stays enforced."""
import ast
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
CALLS = {"run", "Popen", "check_output", "check_call", "call"}
LOCALE_ONLY = {"getoutput", "getstatusoutput"}
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
# A locale whose preferred encoding is ASCII: C, with PEP 538 coercion and PEP 540 UTF-8 mode both off. Windows
# ignores LC_ALL, and there the locale encoding is cp1252, which garbles UTF-8 instead of raising.
NON_UTF8_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
EM_DASH = "\u2014"


# ---- The static rule ------------------------------------------------------------------------------------------------

def _is_false(node):
    return isinstance(node, ast.Constant) and node.value is False


def _is_none(node):
    return isinstance(node, ast.Constant) and node.value is None


def _subprocess_names(tree):
    """The names the module binds subprocess to (`import subprocess [as x]`) and the functions it imports from it
    (`from subprocess import run [as r]`, mapped to their real name)."""
    modules, functions = {"subprocess"}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname for a in node.names if a.name == "subprocess" and a.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            functions.update((a.asname or a.name, a.name) for a in node.names)
    return modules, functions


def _called(func, modules, functions):
    """The subprocess function a call's target names, or None."""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules:
        return func.attr
    if isinstance(func, ast.Name):
        return functions.get(func.id)
    return None


def unnamed_encodings(source, filename="<src>"):
    """Line numbers of subprocess calls that decode text with the locale encoding."""
    tree = ast.parse(source, filename)
    modules, functions = _subprocess_names(tree)
    found = []
    for node in ast.walk(tree):
        name = _called(node.func, modules, functions) if isinstance(node, ast.Call) else None
        if name in LOCALE_ONLY:
            found.append(node.lineno)
            continue
        if name not in CALLS:
            continue
        kwargs = {k.arg: k.value for k in node.keywords if k.arg}
        spread = any(k.arg is None for k in node.keywords)
        text = any(name in kwargs and not _is_false(kwargs[name]) for name in ("text", "universal_newlines"))
        text = text or "errors" in kwargs  # errors= alone turns on text mode with the locale encoding
        named = "encoding" in kwargs and not _is_none(kwargs["encoding"])
        if (text or spread) and not named:
            found.append(node.lineno)
    return sorted(found)


def test_the_rule_flags_locale_decoding_and_passes_named_or_bytes_mode():
    src = textwrap.dedent("""\
        import subprocess
        subprocess.run(a, text=True)
        subprocess.run(a, universal_newlines=True)
        subprocess.Popen(a, errors="replace")
        subprocess.check_output(a, text=True, encoding=None)
        subprocess.run(a, **kw)
        subprocess.getoutput("x")
        subprocess.run(a, text=True, encoding="utf-8", errors="strict")
        subprocess.run(a, encoding="utf-8")
        subprocess.run(a, capture_output=True)
        subprocess.run(a, text=False)
        subprocess.run(a, encoding="utf-8", **kw)
        """)
    assert unnamed_encodings(src) == [2, 3, 4, 5, 6, 7]


def test_the_rule_follows_aliases_and_names_imported_from_subprocess():
    src = textwrap.dedent("""\
        import subprocess as sp
        from subprocess import run, Popen as P, getoutput
        sp.run(a, text=True)
        run(a, text=True)
        P(a, universal_newlines=True)
        getoutput("x")
        run(a, encoding="utf-8")
        sp.check_output(a)
        """)
    assert unnamed_encodings(src) == [3, 4, 5, 6]


def test_every_text_mode_subprocess_call_names_its_encoding():
    offenders = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        lines = unnamed_encodings(path.read_text(encoding="utf-8"), str(path))
        offenders += ["%s:%d" % (path.relative_to(SCRIPTS).as_posix(), n) for n in lines]
    assert offenders == [], "pass encoding= (and a deliberate errors=) to these subprocess calls"


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
    (repo / "caf\u00e9.txt").write_text("x", encoding="utf-8")
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
    (repo / latin1_name(".txt")).write_text("x", encoding="utf-8")  # a Latin-1 name
    write("p/01-a", header(repos=f"[{repo}]"))
    assert work.main(["drift", "p/01-a"]) == 0
    assert capsys.readouterr().out == f"p/01-a\n  {repo}: git printed non-UTF-8 output\n"


LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="only Linux file systems accept a name that is not UTF-8")
def latin1_name(suffix=""):
    """A file name that is not UTF-8. Built per test: on Windows os.fsdecode is strict, so at import time it would
    stop the whole module from loading."""
    return os.fsdecode(b"caf\xe9" + suffix.encode("ascii"))


@LINUX_ONLY
def test_dream_reports_memory_git_output_that_is_not_utf8(tmp_path):
    repo = init_repo(tmp_path / "mem")
    rev = dream._out(repo, ["rev-parse", "HEAD"])
    (repo / latin1_name(".md")).write_text("x\n", encoding="utf-8")
    with pytest.raises(dream.ConfigError, match="git diff output is not UTF-8"):
        dream.changes_since(repo, rev)


@LINUX_ONLY
def test_repo_of_is_none_when_git_prints_a_path_that_is_not_utf8(tmp_path):
    main = init_repo(tmp_path / latin1_name())
    tree = tmp_path / "tree"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(tree)], check=True, capture_output=True)
    assert dream.repo_of(str(tree)) is None
    assert dream.repo_of(str(main)) == str(main)


@LINUX_ONLY
def test_drift_ignores_non_utf8_stderr_from_git(tmp_path, store, write, capsys):
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", latin1_name(), str(repo))  # no upstream: git names the branch on stderr
    git(repo, "commit", "-q", "--allow-empty", "-m", "a")
    write("p/01-a", header(repos=f"[{repo}]"))
    assert work.main(["drift", "p/01-a"]) == 0
    assert capsys.readouterr().out == "p/01-a\n  clean\n"
