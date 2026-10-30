"""The review loop, run after the patching agent stops:

  1. checkpoint the patched tree (WS/pre_review);
  2. the attack-tester reviews it in a NEW session (one retry if no session starts; one "report now" turn if it ends
     without a report); anything the tester changed in the tree is put back;
  3. deterministic triage of its report (triage.py);
  4. if anything was kept: one fix round in the agent's own session;
  5. recheck: the tester's session re-runs its legitimate-use checks on the new tree; verdict="BROKEN" restores the
     checkpoint.

Time follows the tested setup: with a deadline, the review needs 600 s left to start, the tester gets
min(left - 300, tester_cap), a "report now" turn at most 300 s, the recheck at most 600 s.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from . import triage as tr
from .harnesses import Harness, Session
from .workspace import DIFF_EXCLUDES, REVERT_EXCLUDES, checkpoint, load_state, revert, save_state, snapshot, tree_diff, ws


class Clock:
    def __init__(self, deadline: float | None):
        self.deadline = deadline

    def left(self) -> float:
        return math.inf if self.deadline is None else self.deadline - time.time()


def _report(s: Session) -> str:
    return next((t for t in reversed(s.texts or [s.text]) if tr.has_report(t or "")), "")


def _record(info: dict) -> None:
    (ws() / "review.json").write_text(json.dumps(info, indent=2))


def _put_back(repo: Path, source: Path, info: dict, key: str) -> None:
    """The tester must not change the patch; if it did (a harness without a hard edit-deny), restore `source`."""
    if tree_diff(source, repo, REVERT_EXCLUDES):
        info[key] = revert(repo, source)


def patched_paths(repo: Path) -> frozenset[str]:
    """The paths the patch changed or added, relative to `repo` (none before `cz init`)."""
    orig = ws() / "orig"
    return frozenset(r for _, r in tree_diff(orig, repo, DIFF_EXCLUDES)) if orig.exists() else frozenset()


def tester_phase(tester: Harness, repo: Path, clock: Clock, tester_cap: float = 1500) -> dict:
    """Steps 1-3. Returns the review record; `forward` holds the prompt for the fix round ('' = nothing forwarded)."""
    info: dict = {"stop": None, "forward": ""}
    left = clock.left()
    if left < 600:
        info["stop"] = "time"
        return info
    checkpoint(repo)
    t0 = time.time()
    tcap = min(left - 300, tester_cap)
    s = tester.tester(tr.TESTER_MSG, tcap, tag="review")
    info["retries"] = []
    if not s.sid and clock.left() > 600:
        info["retries"].append("no_session")
        s = tester.tester(tr.TESTER_MSG, min(clock.left() - 300, tcap), tag="review_retry")
    rep = _report(s)
    if s.sid and not rep and clock.left() > 300:
        info["retries"].append("report_now")
        rep = _report(tester.tester(tr.REPORT_NOW, min(clock.left() - 120, 300), sid=s.sid, tag="review_report"))
    info.update(tester_session=s.sid, tester_s=round(time.time() - t0, 1), tester_timed_out=s.timed_out)
    (ws() / "review_raw.md").write_text(rep)
    _put_back(repo, ws() / "pre_review", info, "tester_changed_tree")
    t = tr.triage(rep, tr.repo_path_checker(repo, patched_paths(repo), ws() / "orig"))
    info.update(not_run=t["not_run"], stop=t.get("stop"),
                kept=[{k: v for k, v in x.items() if k != "text"} for x in t["kept"]], dropped=t["dropped"])
    body = tr.forward_body(t)
    if not body:
        info["stop"] = info["stop"] or "nothing_forwarded"
        return info
    info["forward"] = tr.PROMPT.format(checkpoint=ws() / "pre_review", body=body)
    (ws() / "review_forwarded.md").write_text(info["forward"])
    return info


def fix_phase(agent: Harness, agent_sid: str, info: dict, clock: Clock, recheck: bool = True) -> None:
    """Step 4: the forwarded findings go once to the agent's own session. With a recheck to come, the fix round leaves
    it 300 s, so a slow fix round cannot skip the recheck that guards it."""
    left = clock.left()
    left -= 300 if recheck and left - 300 >= 120 else 0     # never skip the fix round for the reserve
    if left < 120:
        info["stop"] = "time_before_forward"
        return
    s = agent.agent(info["forward"], min(left, 1e7), sid=agent_sid, tag="review_fix")
    info.update(forwarded=True, fix_s=round(s.secs, 1), fix_timed_out=s.timed_out)


def recheck_phase(tester: Harness, repo: Path, info: dict, clock: Clock) -> None:
    """Step 5: the tester's own session re-runs its legitimate-use checks; BROKEN restores the checkpoint."""
    tsid = info.get("tester_session")
    if not tsid or clock.left() <= 240:
        info["recheck"] = {"verdict": None, "skipped": "no tester session" if not tsid else "time"}
        return
    snapshot(repo, ws() / "post_fix", skip=REVERT_EXCLUDES)
    s = tester.tester(tr.RECHECK, min(clock.left() - 60, 600), sid=tsid, tag="review_recheck")
    text = next((t for t in reversed(s.texts or [s.text]) if tr.has_recheck(t or "")), s.text)
    (ws() / "review_recheck.md").write_text(text or "")
    rc = {**tr.recheck_verdict(text), "secs": round(s.secs, 1)}
    _put_back(repo, ws() / "post_fix", rc, "tester_changed_tree")
    if rc["verdict"] == "BROKEN":
        rc["reverted"] = revert(repo)
    info["recheck"] = rc


def review_loop(agent: Harness, tester: Harness, repo: Path, agent_sid: str | None, clock: Clock,
                tester_cap: float = 1500, recheck: bool = True) -> dict:
    """The whole loop. Without `agent_sid` there is no session to continue: the forwarded prompt is returned for the
    caller to deliver, and the recheck is left to `cz recheck`."""
    info = tester_phase(tester, repo, clock, tester_cap)
    st = load_state()
    if info["forward"] and agent_sid:
        fix_phase(agent, agent_sid, info, clock, recheck)
        if recheck:
            recheck_phase(tester, repo, info, clock)
        st["stage"] = "done"
    elif info["forward"]:
        st["stage"] = "fix"
    else:
        st["stage"] = "done"
    st["tester_session"] = info.get("tester_session", "")
    save_state(st)
    _record(info)
    return info


def summary(info: dict) -> str:
    kept = [k["id"] for k in info.get("kept", [])]
    parts = [f"review: {len(kept)} finding(s) forwarded" + (f" ({', '.join(kept)})" if kept else ""),
             f"{len(info.get('dropped', []))} dropped", f"{len(info.get('not_run', []))} not-run requirement(s)"]
    if info.get("stop"):
        parts.append(f"stop: {info['stop']}")
    if info.get("fix_timed_out"):
        parts.append("fix round timed out")
    rc = info.get("recheck") or {}
    if rc.get("verdict"):
        parts.append(f"recheck {rc['verdict']}" + (", fix round reverted to the checkpoint" if rc.get("reverted") else ""))
    elif rc.get("skipped"):
        parts.append(f"recheck skipped ({rc['skipped']}): the fix round is unverified")
    return "; ".join(parts)
