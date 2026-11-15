"""install-skills: rendered copies of the skills for agents other than Claude Code (herdr-skills#30's design)."""
import json
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import work

PLUGIN_ROOT = str(Path(work.__file__).resolve().parents[1])
SKILLS = sorted(p.name for p in (Path(PLUGIN_ROOT) / "skills").iterdir() if (p / "SKILL.md").is_file())

SKILL_TEXT = """---
name: checkpoint
description: Save progress. Use for "/work:checkpoint".
---

# Checkpoint a workstream

Helper: `sh "${CLAUDE_PLUGIN_ROOT}/scripts/work-tools"`, written `work-tools` below.
"""


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=T", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
                   check=True, capture_output=True)


def _mark(folder, data):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, work.SKILLS_MARKER), "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _symlink(target, link, directory=True):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip("this OS won't create a symlink here: %s" % error)


def render(root="/home/u/work-skills/work"):
    return work.render_skill(SKILL_TEXT, "work", "checkpoint", root)


def test_render_replaces_the_plugin_root():
    text = render()
    assert "CLAUDE_PLUGIN_ROOT" not in text
    assert '`sh "/home/u/work-skills/work/scripts/work-tools"`' in text


def test_render_writes_a_windows_root_with_forward_slashes():
    assert 'sh "C:/Users/u/work-skills/work/scripts/work-tools"' in render("C:\\Users\\u\\work-skills\\work")


def test_render_prefixes_the_name_with_the_plugin():
    text = render()
    assert "\nname: work-checkpoint\n" in text
    assert "\nname: checkpoint\n" not in text


def test_render_says_how_the_claude_names_map_and_how_to_update():
    note = render().split("# Checkpoint a workstream\n", 1)[1].lstrip("\n").split("\n", 1)[0]
    assert note.startswith("> ")
    assert "`/work:<name>`" in note and "`work-<name>`" in note
    assert 'sh "/home/u/work-skills/work/scripts/work-tools" install-skills --update' in note


def test_render_file_only_fills_in_the_root():
    assert work.render_file("Read `${CLAUDE_PLUGIN_ROOT}/templates/x.md`.", "/r/work") == "Read `/r/work/templates/x.md`."


def test_every_tool_has_a_folder_and_agents_is_the_default():
    dirs = work.skill_dirs(env={})
    home = os.path.expanduser("~")
    assert dirs["agents"] == os.path.join(home, ".agents", "skills")
    assert dirs["codex"] == dirs["agents"]
    assert dirs["gemini"] == os.path.join(home, ".gemini", "skills")
    assert dirs["opencode"] == os.path.join(home, ".config", "opencode", "skills")
    assert dirs["omp"] == os.path.join(home, ".omp", "agent", "skills")
    assert work.DEFAULT_SKILLS_TOOL == "agents"


def test_opencode_honours_xdg_config_home():
    assert work.skill_dirs(env={"XDG_CONFIG_HOME": "/x/cfg"})["opencode"] == os.path.join("/x/cfg", "opencode", "skills")


@pytest.fixture
def dest(tmp_path):
    return str(tmp_path / "skills")


def install(dest, tool="agents", **options):
    return work.install_skills(PLUGIN_ROOT, dest, tool=tool, commit="abc123", **options)


def read(dest, *parts):
    return Path(dest, *parts).read_text(encoding="utf-8")


def test_install_writes_every_skill_rendered_with_a_marker(dest):
    result = install(dest)
    assert sorted(result["installed"]) == ["work-" + s for s in SKILLS]
    assert sorted(os.listdir(dest)) == ["work-" + s for s in SKILLS]
    for skill in SKILLS:
        text = read(dest, "work-" + skill, "SKILL.md")
        assert f"name: work-{skill}\n" in text
        assert "CLAUDE_PLUGIN_ROOT" not in text
        assert PLUGIN_ROOT.replace("\\", "/") + "/scripts/work-tools" in text
    marker = json.loads(read(dest, "work-checkpoint", work.SKILLS_MARKER))
    assert marker == {"plugin": "work", "skill": "checkpoint", "root": PLUGIN_ROOT, "tool": "agents",
                      "commit": "abc123"}


def test_install_leaves_the_skill_source_unchanged_for_claude_code(dest):
    before = {s: (Path(PLUGIN_ROOT) / "skills" / s / "SKILL.md").read_bytes() for s in SKILLS}
    install(dest)
    assert {s: (Path(PLUGIN_ROOT) / "skills" / s / "SKILL.md").read_bytes() for s in SKILLS} == before
    assert all(b"${CLAUDE_PLUGIN_ROOT}/scripts/work-tools" in text for text in before.values())


def test_a_dry_run_writes_nothing(dest):
    assert install(dest, dry_run=True)["installed"]
    assert not os.path.exists(dest)


def test_installing_again_replaces_its_own_copies(dest):
    install(dest)
    Path(dest, "work-checkpoint", "stale.md").write_text("old")
    install(dest)
    assert not Path(dest, "work-checkpoint", "stale.md").exists()


def test_refuses_a_folder_it_did_not_write_and_writes_nothing(dest):
    Path(dest, "work-new").mkdir(parents=True)
    Path(dest, "work-new", "SKILL.md").write_text("mine")
    with pytest.raises(work.InstallError, match="work-new"):
        install(dest)
    assert os.listdir(dest) == ["work-new"]
    assert read(dest, "work-new", "SKILL.md") == "mine"


def test_removes_its_copy_of_a_skill_the_plugin_no_longer_has(dest):
    install(dest)
    gone = Path(dest, "work-gone")
    gone.mkdir()
    (gone / work.SKILLS_MARKER).write_text(json.dumps({"plugin": "work", "skill": "gone"}))
    assert install(dest)["removed"] == ["work-gone"]
    assert not gone.exists()


def test_leaves_other_plugins_skills_alone(dest):
    other = Path(dest, "herdr-status")
    other.mkdir(parents=True)
    (other / work.SKILLS_MARKER).write_text(json.dumps({"plugin": "herdr", "skill": "status"}))
    install(dest)
    work.uninstall_skills(dest)
    assert os.listdir(dest) == ["herdr-status"]


def test_a_folder_marked_work_but_not_named_work_is_never_removed(dest):
    other = os.path.join(dest, "checkpoint")
    _mark(other, {"plugin": "work", "skill": "checkpoint"})
    install(dest)
    assert work.plugin_copies(dest, "work").keys() == {"work-" + s for s in SKILLS}
    work.uninstall_skills(dest)
    assert os.listdir(dest) == ["checkpoint"]
    assert os.path.isfile(os.path.join(other, work.SKILLS_MARKER))


def test_uninstall_removes_only_its_own_copies(dest):
    install(dest)
    Path(dest, "work-mine").mkdir()
    assert "work-checkpoint" in work.uninstall_skills(dest)["removed"]
    assert os.listdir(dest) == ["work-mine"]


def test_uninstall_dry_run_and_a_missing_folder_remove_nothing(dest, tmp_path):
    install(dest)
    assert work.uninstall_skills(dest, dry_run=True)["removed"]
    assert "work-checkpoint" in os.listdir(dest)
    assert work.uninstall_skills(str(tmp_path / "nowhere"))["removed"] == []


def test_gemini_gets_a_note_about_agents_md_and_nothing_is_written_for_it(dest, tmp_path):
    result = install(dest, tool="gemini")
    assert any("AGENTS.md" in note and "settings.json" in note for note in result["notes"])
    assert sorted(os.listdir(tmp_path)) == ["skills"]


# ---- hardening: symlinks --------------------------------------------------------------------------------------------

def test_refuses_a_symlinked_copy_and_touches_nothing(dest, tmp_path):
    outside = str(tmp_path / "outside")
    _mark(outside, {"plugin": "work", "skill": "new"})
    os.makedirs(dest)
    _symlink(outside, os.path.join(dest, "work-new"))
    for action in (lambda: install(dest), lambda: work.uninstall_skills(dest)):
        with pytest.raises(work.InstallError) as caught:
            action()
        assert "symlink" in str(caught.value) and "work-new" in str(caught.value)
        assert os.listdir(dest) == ["work-new"]
        assert os.path.isfile(os.path.join(outside, work.SKILLS_MARKER))


def test_refuses_a_symlink_to_a_work_copy_under_another_name(dest, tmp_path):
    outside = str(tmp_path / "outside")
    _mark(outside, {"plugin": "work", "skill": "new"})
    os.makedirs(dest)
    _symlink(outside, os.path.join(dest, "linked"))
    with pytest.raises(work.InstallError) as caught:
        work.uninstall_skills(dest)
    assert "linked" in str(caught.value)
    assert os.path.isfile(os.path.join(outside, work.SKILLS_MARKER))


def test_other_symlinks_and_a_symlinked_skills_folder_are_fine(tmp_path):
    real = str(tmp_path / "real")
    os.makedirs(real)
    unrelated = str(tmp_path / "unrelated")
    os.makedirs(unrelated)
    _symlink(unrelated, os.path.join(real, "someone-else"))
    linked = str(tmp_path / "linked")
    _symlink(real, linked)
    install(linked)
    assert "work-new" in os.listdir(real)
    work.uninstall_skills(linked)
    assert os.listdir(real) == ["someone-else"]


def test_refuses_a_symlink_in_the_plugin_source(tmp_path, dest):
    root = str(tmp_path / "plugin")
    os.makedirs(os.path.join(root, "skills", "x"))
    with open(os.path.join(root, "skills", "x", "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write("---\nname: x\n---\n# x\n")
    secret = str(tmp_path / "secret.txt")
    with open(secret, "w", encoding="utf-8") as handle:
        handle.write("s")
    _symlink(secret, os.path.join(root, "skills", "x", "leak.txt"), directory=False)
    with pytest.raises(work.InstallError) as caught:
        work.install_skills(root, dest, tool="agents", commit="c")
    assert "symlink" in str(caught.value)
    assert not os.path.exists(os.path.join(dest, "work-x"))


# ---- hardening: atomic copies ---------------------------------------------------------------------------------------

def test_a_failed_render_leaves_the_old_copy_marked_and_no_temporary_folder(dest, monkeypatch):
    install(dest)
    real = work.render_skill

    def broken(text, plugin, skill, root):
        if skill == "new":
            raise OSError("disk full")
        return real(text, plugin, skill, root)

    monkeypatch.setattr(work, "render_skill", broken)
    with pytest.raises(OSError):
        install(dest)
    assert sorted(os.listdir(dest)) == ["work-" + s for s in SKILLS]
    assert work.skill_marker(os.path.join(dest, "work-new"))["commit"] == "abc123"


def test_a_failed_swap_puts_the_old_copy_back(dest, monkeypatch):
    install(dest)
    real = os.rename
    calls = []

    def rename(src, dst):
        calls.append((src, dst))
        if len(calls) == 2:
            raise OSError("busy")
        return real(src, dst)

    monkeypatch.setattr(work.os, "rename", rename)
    with pytest.raises(OSError):
        install(dest)
    monkeypatch.setattr(work.os, "rename", real)
    assert sorted(os.listdir(dest)) == ["work-" + s for s in SKILLS]
    assert work.skill_marker(os.path.join(dest, os.path.basename(calls[0][0])))["plugin"] == "work"


def test_leftovers_of_an_interrupted_run_are_cleared_next_time(dest):
    install(dest)
    leftover = os.path.join(dest, ".work-new.tmp-abc")
    _mark(leftover, {"plugin": "work", "skill": "new"})
    foreign = os.path.join(dest, ".work-resume.tmp-xyz")
    os.makedirs(foreign)
    result = install(dest)
    assert ".work-new.tmp-abc" in result["removed"]
    assert not os.path.exists(leftover)
    assert os.path.isdir(foreign)


def test_uninstall_also_clears_leftovers(dest):
    install(dest)
    _mark(os.path.join(dest, ".work-new.tmp-abc"), {"plugin": "work", "skill": "new"})
    assert ".work-new.tmp-abc" in work.uninstall_skills(dest)["removed"]
    assert os.listdir(dest) == []


def test_copies_are_lf(dest):
    install(dest)
    for name in ("SKILL.md", work.SKILLS_MARKER):
        assert b"\r\n" not in Path(dest, "work-new", name).read_bytes()


def hook_note(result, path):
    [note] = [n for n in result["notes"] if path in n and "hook" in n]
    return note


LAUNCHER = PLUGIN_ROOT.replace("\\", "/") + "/scripts/work-tools"


@pytest.mark.parametrize("tool", ["codex", "agents"])
def test_codex_is_shown_an_opt_in_compaction_hook_that_runs_the_nudge(dest, tool):
    note = hook_note(install(dest, tool=tool), "~/.codex/hooks.json")
    snippet = json.loads(note[note.index("{"):note.rindex("}") + 1])
    [entry] = snippet["hooks"]["SessionStart"]
    assert entry["matcher"] == "^compact$"
    assert entry["hooks"][0]["command"] == f'sh "{LAUNCHER}" nudge'


@pytest.mark.parametrize("tool", ["gemini", "agents"])
def test_gemini_is_shown_an_opt_in_precompress_hook_that_prints_json(dest, tool):
    note = hook_note(install(dest, tool=tool), "~/.gemini/settings.json")
    snippet = json.loads(note[note.index("{"):note.rindex("}") + 1])
    [entry] = snippet["hooks"]["PreCompress"]
    assert entry["hooks"][0]["command"] == f'sh "{LAUNCHER}" nudge --json'


@pytest.mark.parametrize("tool", ["opencode", "omp"])
def test_no_hook_is_offered_where_no_compaction_hook_was_verified(dest, tool):
    assert not any("hooks" in note for note in install(dest, tool=tool)["notes"])


def test_install_never_writes_another_tools_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for tool in work.SKILL_DIRS:
        work.install_skills(PLUGIN_ROOT, work.skill_dirs()[tool], tool=tool, commit="x")
    written = sorted(str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*")
                     if p.is_file() and p.name == "SKILL.md")
    assert {w.split("/skills/")[0] for w in written} == {".agents", ".gemini", ".config/opencode", ".omp/agent"}
    assert not (tmp_path / ".codex").exists()
    assert not (tmp_path / ".gemini" / "settings.json").exists()


def test_finds_the_folders_holding_a_plugins_copies_once_each(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    work.install_skills(PLUGIN_ROOT, a, tool="agents", commit="x")
    work.install_skills(PLUGIN_ROOT, b, tool="omp", commit="x")
    os.makedirs(c)
    dirs = {"agents": a, "codex": a, "omp": b, "gemini": c, "opencode": str(tmp_path / "none")}
    assert work.installed_skill_dirs("work", dirs) == [(a, "agents"), (b, "omp")]
    assert work.installed_skill_dirs("herdr", dirs) == []


def test_refresh_re_renders_each_installed_folder(tmp_path):
    a = str(tmp_path / "a")
    work.install_skills(PLUGIN_ROOT, a, tool="agents", commit="old")
    assert [r["dest"] for r in work.refresh_skills(PLUGIN_ROOT, {"agents": a}, commit="new")] == [a]
    assert json.loads(Path(a, "work-checkpoint", work.SKILLS_MARKER).read_text())["commit"] == "new"


def test_the_command_installs_into_dest_without_a_store(dest, monkeypatch, capsys):
    monkeypatch.setenv("WORK_STORE", "relative/not/allowed")
    assert work.main(["install-skills", "--dest", dest]) == 0
    assert "work-checkpoint" in os.listdir(dest)
    assert json.loads(capsys.readouterr().out)["dest"] == dest


def test_the_command_reports_a_refusal_on_stderr(dest, capsys):
    Path(dest, "work-new").mkdir(parents=True)
    assert work.main(["install-skills", "--dest", dest]) == 1
    assert "work-new" in capsys.readouterr().err


def test_update_without_any_install_says_so(dest, capsys):
    assert work.main(["install-skills", "--update", "--no-pull", "--dest", dest]) == 1
    assert "install them first" in capsys.readouterr().err


def test_update_no_pull_re_renders_in_place(dest, capsys):
    work.main(["install-skills", "--dest", dest])
    Path(dest, "work-new", "stale.md").write_text("old")
    capsys.readouterr()
    assert work.main(["install-skills", "--update", "--no-pull", "--dest", dest]) == 0
    assert not Path(dest, "work-new", "stale.md").exists()


def test_refuses_a_root_outside_a_git_checkout(tmp_path):
    copy = tmp_path / "cache" / "work"
    shutil.copytree(Path(PLUGIN_ROOT) / "skills", copy / "skills")
    with pytest.raises(work.InstallError, match="clone"):
        work.plugin_commit(str(copy))


def test_update_checks_for_copies_before_it_pulls(dest, monkeypatch, capsys):
    def pull(plugin_root):
        raise AssertionError("pulled before checking for copies")

    monkeypatch.setattr(work, "pull_plugin", pull)
    assert work.main(["install-skills", "--update", "--dest", dest]) == 1
    assert "install them first" in capsys.readouterr().err


def test_refuses_an_untracked_folder_inside_some_other_git_repo(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _git(home, "init", "-q")
    (home / "README").write_text("dotfiles\n", encoding="utf-8")
    _git(home, "add", "README")
    _git(home, "commit", "-q", "-m", "init")
    cache = home / "cache" / "work"
    shutil.copytree(Path(PLUGIN_ROOT) / "skills", cache / "skills")
    with pytest.raises(work.InstallError, match="clone"):
        work.plugin_commit(str(cache))


def test_update_refuses_a_clone_with_local_changes(tmp_path):
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    (clone / "dirty.txt").write_text("x")
    with pytest.raises(work.InstallError, match="local changes"):
        work.pull_plugin(str(clone))


def _plugin_clone(tmp_path):
    """An upstream repo holding a copy of this plugin, and a clone of it: (upstream, clone's plugin root)."""
    upstream = tmp_path / "upstream"
    ignore = shutil.ignore_patterns("tests", "__pycache__", "*.pyc", ".pytest_cache")
    shutil.copytree(PLUGIN_ROOT, str(upstream / "work"), ignore=ignore)
    shutil.copy(os.path.join(os.path.dirname(PLUGIN_ROOT), ".gitignore"), str(upstream / ".gitignore"))
    _git(tmp_path, "init", "-q", "-b", "main", str(upstream))
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "init")
    _git(tmp_path, "clone", "-q", str(upstream), str(tmp_path / "clone"))
    return upstream, str(tmp_path / "clone" / "work")


def _tools(root, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, os.path.join(root, "scripts", "work.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def test_pull_fast_forwards_a_clean_clone(tmp_path):
    upstream, root = _plugin_clone(tmp_path)
    (upstream / "work" / "NEW.md").write_text("new\n", encoding="utf-8")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "new")
    work.pull_plugin(root)
    assert os.path.isfile(os.path.join(root, "NEW.md"))


def test_update_pulls_then_re_renders_with_the_pulled_code(tmp_path):
    upstream, root = _plugin_clone(tmp_path)
    dest = str(tmp_path / "skills")
    done = _tools(root, "install-skills", "--dest", dest)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["dest"] == dest
    extra = upstream / "work" / "skills" / "extra"
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: extra\ndescription: d\n---\n\n# Extra\n\nRun `${CLAUDE_PLUGIN_ROOT}`.\n",
                                    encoding="utf-8")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-q", "-m", "extra")
    head = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    done = _tools(root, "install-skills", "--update", "--dest", dest)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert result["pulled"] is not None
    assert "work-extra" in result["refreshed"][0]["installed"]
    assert work.skill_marker(os.path.join(dest, "work-extra"))["commit"] == head
    text = read(dest, "work-extra", "SKILL.md")
    assert "name: work-extra" in text and root.replace("\\", "/") in text


def test_the_launcher_runs_install_skills(dest):
    launcher = Path(PLUGIN_ROOT) / "scripts" / "work-tools"
    result = subprocess.run(["sh", str(launcher), "install-skills", "--dest", dest, "--dry-run"], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["dry_run"] is True


def test_an_installed_skills_helper_call_runs_without_claude_plugin_root(dest, tmp_path):
    install(dest)
    text = read(dest, "work-resume", "SKILL.md")
    helper = text.split("Helper: `", 1)[1].split("`", 1)[0]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    result = subprocess.run(["sh", "-c", helper + " root"], capture_output=True,
                            env={**env, "WORK_STORE": str(tmp_path / "store")})
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8").strip() == str(tmp_path / "store")


def test_the_readme_shows_the_same_hook_snippets_install_skills_prints():
    readme = (Path(PLUGIN_ROOT).parent / "README.md").read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"```json\n *(\{\"hooks\".*?)\n *```", readme, re.S)]
    expected = [snippet("/path/to/work-skills/work/scripts/work-tools") for _, _, snippet in work.NUDGE_HOOKS.values()]
    assert blocks == expected


def test_the_readme_lists_every_skill_install_skills_writes(dest):
    install(dest)
    written = sorted(os.listdir(dest))
    readme = (Path(PLUGIN_ROOT).parent / "README.md").read_text(encoding="utf-8")
    bullet = next(line for line in readme.splitlines() if line.startswith("- **What it writes.**"))
    assert sorted(re.findall(r"`(work-[a-z]+)`", bullet)) == written
