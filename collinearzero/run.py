"""`cz run`: the whole setup, non-interactively.

  init (task + snapshot) -> the patching agent, capped at time_limit - reserve -> the review loop in the remaining time.

Defaults are the benchmarked ones: a 3,600 s limit, the agent stops 900 s early, the tester gets at most 1,500 s, the
recheck is on, and opencode continues a response cut off at the output limit up to twice.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import harnesses, install
from .review import Clock, review_loop, summary
from .workspace import DIFF_EXCLUDES, init, load_state, save_state, tree_diff, ws


def run(task: str, repo: Path, harness: str, model: str | None = None, tester_model: str | None = None,
        time_limit: float = 3600, reserve: float = 900, tester_cap: float = 1500, recheck: bool = True,
        continue_on_length: int = 2, extra_args: list[str] | None = None) -> dict:
    repo = repo.resolve()
    kw = {"continue_on_length": continue_on_length} if harness == "opencode" else {}
    agent = harnesses.get(harness, repo, model, extra_args, **kw)
    tester = harnesses.get(harness, repo, tester_model or model, extra_args, **kw)
    problem = agent.check() or (None if install.installed(harness, repo) else
                                f"the Collinear Zero rules are not installed for {harness}: run `cz install --harness {harness}`")
    if problem:
        raise SystemExit(f"cz run: {problem}")
    print(init(repo, task, force=True))
    st = load_state()
    st.update(harness=harness, mode="run", model=model, tester_model=tester_model or model)
    save_state(st)
    t0 = time.time()
    clock = Clock(t0 + time_limit)
    print(f"cz run: agent phase ({harness}, at most {int(time_limit - reserve)} s)", flush=True)
    s = agent.agent(task, time_limit - reserve)
    rec = {"agent": {"session": s.sid, "secs": round(s.secs, 1), "rc": s.rc, "timed_out": s.timed_out, "log": s.log}}
    if not s.sid:
        rec["stop"] = "the agent session did not start"
        (ws() / "run.json").write_text(json.dumps(rec, indent=2))
        raise SystemExit(f"cz run: the agent session did not start; see {s.log}")
    print(f"cz run: review ({int(clock.left())} s left)", flush=True)
    rec["review"] = review_loop(agent, tester, repo, s.sid, clock, tester_cap, recheck)
    rec["total_s"] = round(time.time() - t0, 1)
    rec["patch"] = [f"{k} {r}" for k, r in tree_diff(ws() / "orig", repo, DIFF_EXCLUDES)]
    (ws() / "run.json").write_text(json.dumps(rec, indent=2))
    print("cz run: " + summary(rec["review"]))
    print(f"cz run: the patch changes {len(rec['patch'])} path(s)" + (": " + ", ".join(rec["patch"][:10]) if rec["patch"]
          else "; the agent made no change (see its last message in logs/agent.log)"))
    print(f"cz run: records in {ws()} (run.json, review.json, review_*.md, logs/)")
    return rec
