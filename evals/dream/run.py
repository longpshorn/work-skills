"""Runs the dream eval scenarios against real `claude` and grades them. Paid: needs --confirm-paid.

    python evals/dream/run.py --dry-run                      # print the plan, call nothing
    python evals/dream/run.py --out <dir> --confirm-paid     # every scenario, both arms
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK_TOOLS = ROOT / "work" / "scripts" / "work-tools"
BASELINE_SKILL = HERE / "baseline-skill.md"
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|CREDENTIAL|PRIVATE_KEY", re.IGNORECASE)
ALLOWED_PREFIXES = ("ANTHROPIC_", "CLAUDE_")
DROPPED = ("WORK_STORE",)
GLOBAL_MD = "# Global instructions\n\nBe concise.\n"
EXTRACT_CAP_USD = 5
CHECK_CAP_USD = 1


class PaidRunRefused(Exception):
    pass


def manifest() -> dict:
    return json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))


def clean_env(base: Dict[str, str], workdir: Path) -> Dict[str, str]:
    """The run's environment: no secrets, none of the owner's work settings, paths pinned to workdir."""
    env = {k: v for k, v in base.items()
           if k not in DROPPED and not (SECRET_NAME.search(k) and not k.startswith(ALLOWED_PREFIXES))}
    env["WORK_DREAM_CONFIG"] = str(workdir / "config" / "dream.json")
    env["WORK_DREAM_STATE"] = str(workdir / "state")
    env["WORK_DREAM_PROJECTS"] = str(workdir / "projects")
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def prepare(scenario: str, workdir: Path, model: str, claude: str) -> Path:
    """Lay out one isolated run under workdir; returns the memory folder (its own git repo)."""
    source = HERE / "scenarios" / scenario
    memory = workdir / "memory"
    shutil.copytree(source / "memory", memory)
    subprocess.run(["git", "init", "-q", "-b", "main", str(memory)], check=True, capture_output=True)
    _git(memory, "config", "user.email", "eval@example.com")
    _git(memory, "config", "user.name", "eval")
    _git(memory, "add", "-A")
    _git(memory, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "seed")
    projects = workdir / "projects" / "eval"
    projects.mkdir(parents=True)
    aged = time.time() - 24 * 3600
    for transcript in sorted((source / "transcripts").glob("*.jsonl")):
        target = projects / transcript.name
        shutil.copyfile(transcript, target)
        os.utime(target, (aged, aged))
    (workdir / "CLAUDE.md").write_text(GLOBAL_MD, encoding="utf-8")
    (workdir / "state").mkdir()
    (workdir / "state" / "state.json").write_text(json.dumps(
        {"version": 1, "transcripts": {}, "last_run": None, "last_success": None,
         "reorganized": True, "open_mrs": {}}), encoding="utf-8")
    (workdir / "config").mkdir()
    (workdir / "config" / "dream.json").write_text(json.dumps({
        "memory_dir": str(memory), "global_claude_md": str(workdir / "CLAUDE.md"),
        "claude_bin": claude, "repos": [], "agent_prompts": [],
        "models": {"extract": model, "check": model},
        "caps": {"budget_extract_usd": EXTRACT_CAP_USD, "budget_check_usd": CHECK_CAP_USD}}), encoding="utf-8")
    return memory


def command(arm: str) -> List[str]:
    cmd = ["sh", str(WORK_TOOLS), "dream-run", "--now"]
    return cmd + ["--skill", str(BASELINE_SKILL)] if arm == "baseline" else cmd


def run_arm(scenario: str, arm: str, workdir: Path, model: Optional[str] = None,
            confirm_paid: bool = False) -> Path:
    """Runs one arm of one scenario in workdir and returns the resulting memory folder."""
    if not confirm_paid:
        raise PaidRunRefused("a run calls the real model and is paid; pass --confirm-paid")
    if arm not in manifest()["arms"]:
        raise ValueError("unknown arm %s" % arm)
    if model is not None and model not in manifest()["models"]:
        raise ValueError("model %s is not in fixtures.json" % model)
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("claude was not found on PATH")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    memory = prepare(scenario, workdir, model or manifest()["models"][0], claude)
    done = subprocess.run(command(arm), cwd=str(workdir), env=clean_env(dict(os.environ), workdir),
                          capture_output=True, text=True)
    (workdir / "run.log").write_text("exit %d\n--- stdout\n%s\n--- stderr\n%s\n"
                                     % (done.returncode, done.stdout, done.stderr), encoding="utf-8")
    (workdir / "completion.json").write_text(json.dumps(
        {"exit_code": done.returncode, "extract_ok": extract_succeeded(workdir)}), encoding="utf-8")
    return memory


def extract_succeeded(workdir: Path) -> bool:
    """The extract stage's stream log ends in a successful result event."""
    folder = run_dir_of(workdir)
    log = folder / "extract.jsonl" if folder else None
    if not log or not log.is_file():
        return False
    result = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    return bool(result) and result.get("subtype") == "success" and not result.get("is_error")


def completion(workdir: Path) -> dict:
    return json.loads((Path(workdir) / "completion.json").read_text(encoding="utf-8"))


def run_dir_of(workdir: Path) -> Optional[Path]:
    runs = sorted((Path(workdir) / "state" / "runs").glob("*"))
    return runs[-1] if runs else None


def plan(scenarios: List[str], arms: List[str], models: List[str]) -> List[str]:
    return ["scenario=%s arm=%s model=%s extract_cap=$%d check_cap=$%d per check" %
            (s, a, m, EXTRACT_CAP_USD, CHECK_CAP_USD) for m in models for s in scenarios for a in arms]


def main(argv: List[str]) -> int:
    fixtures = manifest()
    ids = [s["id"] for s in fixtures["scenarios"]]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", action="append", choices=ids, help="repeatable (default: all)")
    parser.add_argument("--arm", action="append", choices=fixtures["arms"], help="repeatable (default: both)")
    parser.add_argument("--model", action="append", help="repeatable (default: the manifest's models)")
    parser.add_argument("--out", help="folder for run folders and results; outside the repo")
    parser.add_argument("--dry-run", action="store_true", help="print the planned runs; call no model")
    parser.add_argument("--confirm-paid", action="store_true", help="allow the real, paid model calls")
    args = parser.parse_args(argv)
    scenarios, arms = args.scenario or ids, args.arm or fixtures["arms"]
    models = args.model or fixtures["models"][:1]
    unknown = [m for m in models if m not in fixtures["models"]]
    if unknown:
        print("run.py: model %s is not in fixtures.json" % ", ".join(unknown), file=sys.stderr)
        return 2
    lines = plan(scenarios, arms, models)
    if args.dry_run:
        print("planned runs (no model called):")
        print("\n".join(lines))
        return 0
    if not args.confirm_paid:
        print("run.py: these runs call the real model and are paid; pass --confirm-paid (or --dry-run)",
              file=sys.stderr)
        return 2
    out_path = Path(args.out).resolve() if args.out else None
    if out_path is None or out_path == ROOT or ROOT in out_path.parents:
        print("run.py: --out is required and must be outside the repo", file=sys.stderr)
        return 2
    import grade
    out = Path(args.out)
    code = 0
    for model in models:
        for scenario in scenarios:
            for arm in arms:
                workdir = out / ("%s-%s-%s" % (scenario, arm, model))
                if workdir.exists():
                    shutil.rmtree(workdir)
                memory = run_arm(scenario, arm, workdir, model, confirm_paid=True)
                done = completion(workdir)
                finished = done["exit_code"] == 0 and done["extract_ok"]
                checks = grade.grade(HERE / "scenarios" / scenario, memory, workdir / "CLAUDE.md",
                                     run_dir_of(workdir)) if finished else None
                (workdir / "result.json").write_text(json.dumps(
                    {"scenario": scenario, "arm": arm, "model": model, "completion": done,
                     "graded": finished, "checks": checks}, indent=2) + "\n", encoding="utf-8")
                if checks is None:
                    print("%s %s: not graded (the run did not complete: exit %d, extract %s)" % (
                        scenario, arm, done["exit_code"], "ok" if done["extract_ok"] else "failed"))
                else:
                    print("%s %s: %s" % (scenario, arm, "pass" if all(checks.values()) else
                                         "fail " + ",".join(k for k, v in checks.items() if not v)))
                code |= 0 if arm == "baseline" and checks is not None or checks and all(checks.values()) else 1
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
