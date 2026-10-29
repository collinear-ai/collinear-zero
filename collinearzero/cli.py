"""The `cz` command line."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, harnesses, install, render
from .workspace import DIFF_EXCLUDES, format_diff, init, load_state, revert, save_state, tree_diff, ws


def _task_text(arg: str) -> str:
    return sys.stdin.read() if arg == "-" else Path(arg).read_text()


def cmd_init(a):
    print(init(Path(a.repo), _task_text(a.task), a.force))


def cmd_status(a):
    st = load_state()
    if not st:
        print(f"no task (workspace {ws()})")
        return
    repo = Path(a.repo).resolve()
    tag = "active task for this repository" if st.get("repo") == str(repo) and st.get("stage") != "done" else "no active task for this repository"
    print(f"{tag}: workspace {ws()}, repository {st.get('repo')}, stage {st.get('stage')}")


def cmd_reset(a):
    if ws().exists():
        shutil.rmtree(ws())
    print(f"removed {ws()}")


def cmd_diff(a):
    orig = ws() / "orig"
    if not orig.exists():
        raise SystemExit("cz diff: no snapshot; run `cz init` first")
    repo = Path(a.repo).resolve()
    out = format_diff(orig, repo, tree_diff(orig, repo, DIFF_EXCLUDES))
    print(out or "no changes")


def cmd_revert(a):
    src = ws() / ("orig" if a.to == "orig" else "pre_review")
    if not src.exists():
        raise SystemExit(f"cz revert: {src} does not exist")
    print(json.dumps(revert(Path(a.repo).resolve(), src)))


def cmd_triage(a):
    from .triage import forward_body, repo_path_checker, triage
    rep = _task_text(a.report)
    t = triage(rep, repo_path_checker(Path(a.repo)))
    print(json.dumps({k: v for k, v in t.items()}, indent=2) if a.json else (forward_body(t) or "nothing forwarded"))


def _harness_for(a, model_attr="model"):
    st = load_state()
    name = a.harness or st.get("harness") or "claude"
    return harnesses.get(name, Path(a.repo).resolve(), getattr(a, model_attr, None))


def cmd_review(a):
    from .review import Clock, review_loop, summary
    repo = Path(a.repo).resolve()
    st = load_state()
    if not st or st.get("repo") != str(repo):
        raise SystemExit("cz review: no active task for this repository; run `cz init` first")
    tester = _harness_for(a, "tester_model")
    agent = _harness_for(a)
    info = review_loop(agent, tester, repo, a.session, Clock(None), a.tester_cap, not a.no_recheck)
    print(summary(info))
    if info.get("forward") and not a.session:
        print("\n--- give this to your agent, let it act, then run `cz recheck` ---\n")
        print(info["forward"])


def cmd_recheck(a):
    from .review import Clock, recheck_phase, summary
    repo = Path(a.repo).resolve()
    st = load_state()
    info = json.loads((ws() / "review.json").read_text()) if (ws() / "review.json").exists() else {}
    info["tester_session"] = st.get("tester_session") or info.get("tester_session")
    recheck_phase(_harness_for(a, "tester_model"), repo, info, Clock(None))
    st["stage"] = "done"
    save_state(st)
    (ws() / "review.json").write_text(json.dumps(info, indent=2))
    print(summary(info))


def cmd_run(a):
    from .run import run
    rec = run(_task_text(a.task), Path(a.repo), a.harness, a.model, a.tester_model, a.time_limit, a.reserve,
              a.tester_cap, not a.no_recheck, a.continue_on_length, a.harness_arg)
    sys.exit(0 if rec.get("agent", {}).get("session") else 1)


def cmd_gate(a):
    from .gate import main
    sys.exit(main())


def cmd_regress(a):
    from .regress import regress
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        raise SystemExit("usage: cz regress [--timeout S] -- <test command>")
    rc, out = regress(Path(a.repo).resolve(), " ".join(cmd), a.timeout)
    print(out)
    sys.exit(rc)


def cmd_tests(a):
    from .blindtests import tests
    rc, out = tests(Path(a.repo).resolve(), a.timeout)
    print(out)
    sys.exit(rc)


def cmd_install(a):
    for h in a.harness:
        done = install.install(h, a.scope, Path(a.repo).resolve(), a.with_blind_tests, not a.no_gate)
        print(f"{h}: installed\n  " + "\n  ".join(done))
        if h == "claude" and not a.no_gate:
            print("  finish gate: Stop hook `cz gate` (runs the review when the agent stops)")


def cmd_uninstall(a):
    for h in a.harness:
        print(f"{h}: removed\n  " + "\n  ".join(install.uninstall(h, a.scope, Path(a.repo).resolve()) or ["nothing"]))


def cmd_render(a):
    root = install.root_dir(a.harness, a.scope, Path(a.repo).resolve())
    print(render.rules(a.harness, root, a.with_blind_tests))


def main(argv=None):
    p = argparse.ArgumentParser(prog="cz", description="Collinear Zero: fix a described security weakness, then review "
                                "the patch with an independent attack-tester.")
    p.add_argument("--version", action="version", version=f"Collinear Zero {__version__}")
    p.add_argument("-C", "--repo", default=".", help="repository root (default: current directory)")
    sub = p.add_subparsers(dest="cmd", required=True)
    H = ("opencode", "claude", "codex")

    s = sub.add_parser("run", help="fix a finding end to end: agent, then the review loop")
    s.add_argument("--task", required=True, help="file with the finding, verbatim ('-' = stdin)")
    s.add_argument("--harness", required=True, choices=H)
    s.add_argument("--model", help="model for the patching agent (harness syntax)")
    s.add_argument("--tester-model", help="model for the attack-tester (default: --model)")
    s.add_argument("--time-limit", type=float, default=3600, help="wall-clock limit for the whole run, s (3600)")
    s.add_argument("--reserve", type=float, default=900, help="the agent stops this many s before the limit (900)")
    s.add_argument("--tester-cap", type=float, default=1500, help="most time the tester gets, s (1500)")
    s.add_argument("--no-recheck", action="store_true", help="skip the recheck after the fix round")
    s.add_argument("--continue-on-length", type=int, default=2, help="opencode: continuations after an output-limit stop (2)")
    s.add_argument("--harness-arg", action="append", default=[], help="extra argument for the harness CLI (repeatable)")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("init", help="record the finding and snapshot the repository")
    s.add_argument("--task", required=True, help="file with the finding, verbatim ('-' = stdin)")
    s.add_argument("--force", action="store_true", help="start over even if a task is active")
    s.set_defaults(func=cmd_init)
    sub.add_parser("status", help="show the active task").set_defaults(func=cmd_status)
    sub.add_parser("reset", help="delete the workspace").set_defaults(func=cmd_reset)
    sub.add_parser("diff", help="list the patch: the working tree against the snapshot").set_defaults(func=cmd_diff)

    s = sub.add_parser("review", help="run the attack-tester and the triage on the current tree")
    s.add_argument("--harness", choices=H, help="harness for the tester (default: the run's, else claude)")
    s.add_argument("--session", help="agent session id to continue for the fix round (else the findings are printed)")
    s.add_argument("--model")
    s.add_argument("--tester-model")
    s.add_argument("--tester-cap", type=float, default=1500)
    s.add_argument("--no-recheck", action="store_true")
    s.set_defaults(func=cmd_review)
    s = sub.add_parser("recheck", help="after a manual fix round: recheck, and restore the checkpoint if it broke")
    s.add_argument("--harness", choices=H)
    s.add_argument("--tester-model")
    s.set_defaults(func=cmd_recheck)
    s = sub.add_parser("revert", help="restore the review checkpoint (or --to orig)")
    s.add_argument("--to", choices=("checkpoint", "orig"), default="checkpoint")
    s.set_defaults(func=cmd_revert)
    s = sub.add_parser("triage", help="triage a tester report (file or '-')")
    s.add_argument("report")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_triage)
    sub.add_parser("gate", help="Claude Code Stop hook (reads the hook JSON on stdin)").set_defaults(func=cmd_gate)

    s = sub.add_parser("regress", help="run the repository's tests on the original and on the patch")
    s.add_argument("--timeout", type=float, default=1800)
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_regress)
    s = sub.add_parser("tests", help="opt-in: validate and run the blind test-writer's tests")
    s.add_argument("--timeout", type=float, default=180)
    s.set_defaults(func=cmd_tests)

    for name, fn in (("install", cmd_install), ("uninstall", cmd_uninstall)):
        s = sub.add_parser(name, help=f"{name} the rules, skill and agents for one or more harnesses")
        s.add_argument("--harness", required=True, nargs="+", choices=H)
        s.add_argument("--scope", choices=("user", "project"), default="user")
        if name == "install":
            s.add_argument("--with-blind-tests", action="store_true", help="also install the opt-in blind test-writer")
            s.add_argument("--no-gate", action="store_true", help="claude: do not install the Stop-hook finish gate")
        s.set_defaults(func=fn)
    s = sub.add_parser("render", help="print the rules as rendered for a harness")
    s.add_argument("--harness", required=True, choices=H)
    s.add_argument("--scope", choices=("user", "project"), default="user")
    s.add_argument("--with-blind-tests", action="store_true")
    s.set_defaults(func=cmd_render)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
