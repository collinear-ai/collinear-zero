"""`cz gate`: the finish gate for interactive Claude Code, installed as a Stop hook.

A Stop hook runs when the agent tries to end its turn. With an active Collinear Zero task for this repository:
  first stop      -> run the attack-tester and the triage; if anything is forwarded, block the stop and hand the
                     findings to the agent (that continuation is the fix round), else let it stop;
  next stop       -> recheck in the tester's session, restore the checkpoint on RECHECK: BROKEN, let it stop.
Without an active task, or inside a session Collinear Zero started itself (CZ_GATE=off), it does nothing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import harnesses
from .review import Clock, recheck_phase, summary, tester_phase
from .workspace import load_state, save_state, ws


def gate(stdin_text: str) -> dict:
    """The hook's JSON reply (empty = allow the stop)."""
    if os.environ.get("CZ_GATE", "").lower() in ("off", "0", "false"):
        return {}
    try:
        event = json.loads(stdin_text or "{}")
    except ValueError:
        event = {}
    repo = Path(event.get("cwd") or os.getcwd()).resolve()
    st = load_state()
    if not st or st.get("repo") != str(repo) or st.get("stage") not in ("agent", "fix"):
        return {}
    model = os.environ.get("CZ_TESTER_MODEL") or None
    tester = harnesses.get("claude", repo, model)
    cap = float(os.environ.get("CZ_TESTER_CAP", "1500"))
    if st["stage"] == "agent":
        info = tester_phase(tester, repo, Clock(None), cap)
        st = load_state()
        st["tester_session"] = info.get("tester_session", "")
        st["stage"] = "fix" if info["forward"] else "done"
        save_state(st)
        (ws() / "review.json").write_text(json.dumps(info, indent=2))
        if info["forward"]:
            return {"decision": "block", "reason": info["forward"]}
        return {"systemMessage": "Collinear Zero " + summary(info)}
    info = json.loads((ws() / "review.json").read_text()) if (ws() / "review.json").exists() else {}
    info["tester_session"] = st.get("tester_session") or info.get("tester_session")
    recheck_phase(tester, repo, info, Clock(None))
    st["stage"] = "done"
    save_state(st)
    (ws() / "review.json").write_text(json.dumps(info, indent=2))
    return {"systemMessage": "Collinear Zero " + summary(info)}


def main() -> int:
    reply = gate(sys.stdin.read())
    if reply:
        print(json.dumps(reply))
    return 0
