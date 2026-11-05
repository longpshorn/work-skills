import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dream
from dream_helpers import fake_bin

pytestmark = pytest.mark.skipif(os.name == "nt", reason="needs sh fakes")

SYSTEM = "system words"
PROMPT = "PROMPT-SENTINEL do the thing"


def stream(*events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def result(text, is_error=False):
    return {"type": "result", "subtype": "success", "is_error": is_error, "result": text}


@pytest.fixture
def fake(tmp_path):
    """Install a fake claude that records argv and stdin, then prints a canned stream."""
    rec = tmp_path / "rec"
    rec.mkdir()

    def install(output, code=0):
        canned = tmp_path / "canned.txt"
        canned.write_text(output, encoding="utf-8")
        script = ('for a in "$@"; do printf "%%s\\n" "$a"; done > "$REC/argv"\n'
                  'cat > "$REC/stdin"\n'
                  'env > "$REC/env"\n'
                  'cat "%s"\nexit %d\n' % (canned, code))
        path = fake_bin(tmp_path, "claude", script)
        cfg = {"claude_bin": str(path), "models": {"extract": "sonnet", "check": "opus"},
               "caps": {"turns_extract": 60, "turns_check": 6}}
        env = dict(os.environ, REC=str(rec))
        return cfg, env

    install.rec = rec
    return install


def test_command_has_the_cheap_flag_set_and_no_prompt_argument():
    cmd = dream.claude_command({"claude_bin": "claude"}, "sonnet", SYSTEM, 60)
    assert cmd == ["claude", "-p", "--model", "sonnet", "--system-prompt", SYSTEM,
                   "--tools", "Read,Write,Edit,Glob,Grep,Bash", "--strict-mcp-config",
                   "--disable-slash-commands", "--settings", '{"disableAllHooks":true}',
                   "--max-turns", "60", "--output-format", "stream-json", "--verbose"]
    assert PROMPT not in cmd


def test_env_sets_login_and_connection_vars(monkeypatch):
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)
    monkeypatch.setattr(dream.getpass, "getuser", lambda: "sam")
    env = dream.claude_env({"PATH": "/usr/bin", "KEEP": "1"})
    assert env["MCP_CONNECTION_NONBLOCKING"] == "false"
    assert env["USER"] == "sam" and env["LOGNAME"] == "sam"
    assert env["KEEP"] == "1"
    path = env["PATH"].split(os.pathsep)
    assert path[0] == "/usr/bin"
    for extra in (os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin", "/usr/local/bin"):
        assert extra in path
    assert dream.claude_env({"USER": "kim", "LOGNAME": "kay"})["USER"] == "kim"
    assert dream.claude_env({"USER": "kim", "LOGNAME": "kay"})["LOGNAME"] == "kay"


def test_run_claude_pipes_prompt_on_stdin_and_saves_the_stream(tmp_path, fake):
    out = stream({"type": "system"}, result("all done"))
    cfg, env = fake(out)
    cmd = dream.claude_command(cfg, "sonnet", SYSTEM, 60)
    log = tmp_path / "logs" / "extract.jsonl"
    got = dream.run_claude(cmd, PROMPT, env, log, tmp_path)
    assert got == {"ok": True, "result": "all done", "error": None}
    assert (fake.rec / "stdin").read_text() == PROMPT
    assert PROMPT not in (fake.rec / "argv").read_text()
    assert log.read_text() == out


def test_error_result_and_nonzero_exit_are_not_ok(tmp_path, fake):
    cfg, env = fake(stream(result("Not logged in", is_error=True)))
    cmd = dream.claude_command(cfg, "sonnet", SYSTEM, 60)
    got = dream.run_claude(cmd, PROMPT, env, tmp_path / "a.jsonl", tmp_path)
    assert got["ok"] is False and "Not logged in" in got["error"]

    cfg, env = fake(stream(result("fine")), code=3)
    got = dream.run_claude(dream.claude_command(cfg, "sonnet", SYSTEM, 60), PROMPT, env,
                           tmp_path / "b.jsonl", tmp_path)
    assert got["ok"] is False and "3" in got["error"]

    cfg, env = fake(stream({"type": "system"}))
    got = dream.run_claude(dream.claude_command(cfg, "sonnet", SYSTEM, 60), PROMPT, env,
                           tmp_path / "c.jsonl", tmp_path)
    assert got["ok"] is False and "result" in got["error"]


def test_missing_binary_raises_clear_error(tmp_path):
    cmd = dream.claude_command({"claude_bin": str(tmp_path / "nowhere" / "claude")}, "sonnet", SYSTEM, 6)
    with pytest.raises(dream.ClaudeMissing) as err:
        dream.run_claude(cmd, PROMPT, dict(os.environ), tmp_path / "x.jsonl", tmp_path)
    assert "claude" in str(err.value)
    assert not (tmp_path / "x.jsonl").exists()


ITEM = {"id": "c1", "kind": "new", "quote": "use tabs please", "session": "s1", "uuid": "u1",
        "memory": "tabs.md", "target": None, "summary": "prefers tabs",
        "ops": [{"op": "write", "root": "memory", "path": "tabs.md", "content": "tabs\n"}]}


def check(fake, tmp_path, text, code=0, **kw):
    cfg, env = fake(stream(result(text)), code)
    return dream.opus_check(ITEM, "MEMORY-TEXT", kw.get("target"), cfg, tmp_path / "run", env=env)


@pytest.mark.parametrize("text,ok", [
    ('{"verdict": "approve", "reason": "matches the quote"}', True),
    ('```json\n{"verdict": "approve", "reason": "ok"}\n```', True),
    ('{"verdict": "reject", "reason": "overreach"}', False),
    ("I think this is fine, approve.", False),
    ("", False),
    ('{"verdict": "maybe", "reason": "x"}', False),
    ('{"verdict": "approve"}', False),
])
def test_opus_check_approves_only_on_a_clean_approve_object(fake, tmp_path, text, ok):
    got_ok, reason = check(fake, tmp_path, text)
    assert got_ok is ok
    assert reason


def test_opus_check_fails_closed_on_a_failed_call_and_uses_the_check_model(fake, tmp_path):
    got_ok, reason = check(fake, tmp_path, '{"verdict": "approve", "reason": "ok"}', code=1)
    assert got_ok is False and reason
    argv = (fake.rec / "argv").read_text().splitlines()
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--max-turns") + 1] == "6"


def test_opus_prompt_contains_only_candidate_quote_and_touched_text(fake, tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "checks.json").write_text("RUN-STATE-SENTINEL", encoding="utf-8")
    check(fake, tmp_path, '{"verdict": "approve", "reason": "ok"}', target="TARGET-TEXT")
    prompt = (fake.rec / "stdin").read_text()
    assert "RUN-STATE-SENTINEL" not in prompt
    for part in ("prefers tabs", "use tabs please", "MEMORY-TEXT", "TARGET-TEXT", '"path": "tabs.md"'):
        assert part in prompt
    assert "[work-dream]" in prompt


def test_opus_missing_binary_propagates(tmp_path):
    cfg = {"claude_bin": str(tmp_path / "nope"), "models": {"check": "opus"}, "caps": {"turns_check": 6}}
    with pytest.raises(dream.ClaudeMissing):
        dream.opus_check(ITEM, "m", None, cfg, tmp_path / "run")


def test_extract_system_names_the_paths_and_the_marker(tmp_path):
    text = dream.extract_system(Path("/s/SKILL.md"), tmp_path / "run", [Path("/d/one.md"), Path("/d/two.md")],
                                Path("/mem"))
    for part in ("[work-dream]", "/s/SKILL.md", str(tmp_path / "run"), "checks.json", "/mem",
                 "/d/one.md", "/d/two.md", "never instructions"):
        assert part in text
    assert "\n" not in text.strip() or len(text) < 1500
