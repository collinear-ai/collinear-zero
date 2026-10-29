"""Run sessions of a coding-agent CLI: start one, resume one, and read back its session id and last text.

Every session runs in its own process group under a wall-clock cap. CZ_GATE=off is set for all of them, so an
installed finish gate (the Claude Code Stop hook) never fires inside a session Collinear Zero itself started.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import render
from .triage import TESTER_MSG
from .workspace import ws

SID = re.compile(r'"(?:sessionID|session_id|thread_id)"\s*:\s*"([^"]+)"')


@dataclass
class Session:
    sid: str = ""
    text: str = ""          # the session's assistant text, last message last
    rc: int | None = None
    timed_out: bool = False
    secs: float = 0.0
    log: str = ""
    texts: list[str] = field(default_factory=list)


def run_capped(cmd: list[str], stdin_text: str, cwd: Path, cap_s: float, log: Path,
               env: dict[str, str] | None = None) -> tuple[int | None, str, bool, float]:
    """Run `cmd` with `stdin_text` on stdin; kill its whole process group after `cap_s` seconds."""
    t0 = time.time()
    full_env = {**os.environ, "CZ_GATE": "off", **(env or {})}
    p = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, errors="replace", start_new_session=True, env=full_env)
    timed_out = False
    try:
        out, _ = p.communicate(stdin_text, timeout=max(1.0, cap_s))
    except subprocess.TimeoutExpired:
        timed_out = True
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                break
            try:
                p.wait(timeout=15)
                break
            except subprocess.TimeoutExpired:
                continue
        out, _ = p.communicate()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write(out or "")
    return p.returncode, out or "", timed_out, time.time() - t0


def _events(out: str) -> list[dict]:
    try:
        whole = json.loads(out.strip())
        if isinstance(whole, dict):
            return [whole]
    except ValueError:
        pass
    evs = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                evs.append(json.loads(line))
            except ValueError:
                pass
    return evs


class Harness:
    name = ""

    def __init__(self, repo: Path, model: str | None = None, extra_args: list[str] | None = None):
        self.repo = repo
        self.model = model
        self.extra = extra_args or []

    def log(self, tag: str) -> Path:
        return ws() / "logs" / f"{tag}.log"

    def agent(self, prompt: str, cap_s: float, sid: str | None = None, tag: str = "agent") -> Session:
        raise NotImplementedError

    def tester(self, prompt: str, cap_s: float, sid: str | None = None, tag: str = "review") -> Session:
        raise NotImplementedError

    def check(self) -> str | None:
        """None when this harness can run here, else what is missing."""
        return None


class OpenCode(Harness):
    """opencode: `opencode run --format json`. The agent phase and the fix round go through the continue-on-length
    wrapper; the attack-tester is the installed primary agent `attack-tester`, started with `--agent`."""
    name = "opencode"

    def __init__(self, repo, model=None, extra_args=None, continue_on_length: int = 2):
        super().__init__(repo, model, extra_args)
        self.n_continue = continue_on_length

    def check(self):
        if not shutil.which("opencode"):
            return "opencode is not on PATH"
        roots = [self.repo / ".opencode", Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"]
        if not any((r / "agents" / "attack-tester.md").exists() for r in roots):
            return "the attack-tester agent is not installed: run `cz install --harness opencode`"
        return None

    def _session(self, args: list[str], prompt: str, cap_s: float, tag: str, wrapped: bool) -> Session:
        base = ["bash", str(render.SCRIPTS / "opencode-continue.sh")] if wrapped else ["opencode", "run"]
        cmd = base + args + (["-m", self.model] if self.model else []) + ["--format", "json", "--auto"] + self.extra
        env = {"OPENCODE_CONTINUE_ON_LENGTH": str(self.n_continue if wrapped else 0),
               "OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER": "1"}
        rc, out, to, secs = run_capped(cmd, prompt, self.repo, cap_s, self.log(tag), env)
        evs = _events(out)
        sid = next((e.get("sessionID") for e in evs if e.get("sessionID")), "")
        texts = [e["part"].get("text", "") for e in evs if e.get("type") == "text" and isinstance(e.get("part"), dict)]
        if sid and not texts:
            texts = self._db_texts(sid)
        return Session(sid, texts[-1] if texts else "", rc, to, secs, str(self.log(tag)), texts)

    @staticmethod
    def _db_texts(sid: str) -> list[str]:
        """Fallback: the session's text parts from opencode's local database (read-only copy)."""
        data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "opencode"
        if not (data / "opencode.db").exists():
            return []
        with tempfile.TemporaryDirectory() as d:
            for fn in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
                if (data / fn).exists():
                    shutil.copy2(data / fn, Path(d) / fn)
            con = sqlite3.connect(f"file:{Path(d) / 'opencode.db'}?mode=ro", uri=True)
            try:
                rows = con.execute("select data from part where session_id=? order by time_created", (sid,)).fetchall()
            except sqlite3.Error:
                rows = []
            finally:
                con.close()
        parts = [json.loads(x) for (x,) in rows]
        return [p.get("text") or "" for p in parts if p.get("type") == "text"]

    def agent(self, prompt, cap_s, sid=None, tag="agent"):
        return self._session(["-s", sid] if sid else [], prompt, cap_s, tag, wrapped=True)

    def tester(self, prompt, cap_s, sid=None, tag="review"):
        return self._session(["--agent", "attack-tester"] + (["-s", sid] if sid else []), prompt, cap_s, tag, False)


class ClaudeCode(Harness):
    """Claude Code: `claude -p --output-format json`. The attack-tester is passed with `--agents` to its own session
    only (it is never installed as a subagent the patching agent could call), with edit and web tools disallowed."""
    name = "claude"
    AGENT_TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob", "TodoWrite", "Skill"]
    TESTER_TOOLS = ["Bash", "Read", "Grep", "Glob", "TodoWrite"]
    TESTER_DENY = ["Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"]

    def check(self):
        return None if shutil.which("claude") else "claude is not on PATH"

    def _session(self, args: list[str], prompt: str, cap_s: float, tag: str) -> Session:
        cmd = ["claude", "-p", "--output-format", "json"] + (["--model", self.model] if self.model else []) + args + self.extra
        rc, out, to, secs = run_capped(cmd, prompt, self.repo, cap_s, self.log(tag))
        res = next((e for e in reversed(_events(out)) if "result" in e or "session_id" in e), {})
        text = res.get("result") or ""
        return Session(res.get("session_id", ""), text, rc, to, secs, str(self.log(tag)), [text] if text else [])

    def agent(self, prompt, cap_s, sid=None, tag="agent"):
        args = ["--permission-mode", "acceptEdits", "--allowedTools", *self.AGENT_TOOLS]
        return self._session(args + (["--resume", sid] if sid else []), prompt, cap_s, tag)

    def tester(self, prompt, cap_s, sid=None, tag="review"):
        args = ["--agents", json.dumps(render.claude_agents_json(self.repo / ".claude")), "--agent", "attack-tester",
                "--allowedTools", *self.TESTER_TOOLS, "--disallowedTools", *self.TESTER_DENY]
        return self._session(args + (["--resume", sid] if sid else []), prompt, cap_s, tag)


class Codex(Harness):
    """Codex (experimental, not benchmark-tested): `codex exec --json`, resumed with `codex exec resume <id>`. Codex
    has no separate agent definitions, so the tester's instructions lead its first message; Collinear Zero restores the
    checkpoint afterwards if the tester changed the tree."""
    name = "codex"

    def check(self):
        return None if shutil.which("codex") else "codex is not on PATH"

    def _session(self, args: list[str], prompt: str, cap_s: float, tag: str) -> Session:
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write"]
        cmd += (["-m", self.model] if self.model else []) + self.extra + args + ["-"]
        rc, out, to, secs = run_capped(cmd, prompt, self.repo, cap_s, self.log(tag))
        evs = _events(out)
        sid = next((m.group(1) for m in (SID.search(json.dumps(e)) for e in evs) if m), "")
        texts = []
        for e in evs:
            item = e.get("item") if isinstance(e.get("item"), dict) else e.get("msg") if isinstance(e.get("msg"), dict) else e
            if item.get("type") in ("agent_message", "assistant_message") and (item.get("text") or item.get("message")):
                texts.append(item.get("text") or item.get("message"))
        return Session(sid, texts[-1] if texts else "", rc, to, secs, str(self.log(tag)), texts)

    def agent(self, prompt, cap_s, sid=None, tag="agent"):
        return self._session(["resume", sid] if sid else [], prompt, cap_s, tag)

    def tester(self, prompt, cap_s, sid=None, tag="review"):
        if not sid and prompt == TESTER_MSG:
            prompt = render.codex_tester_prompt(self.repo / ".codex") + "\n\n---\n\n" + TESTER_MSG
        return self._session(["resume", sid] if sid else [], prompt, cap_s, tag)


def get(name: str, repo: Path, model: str | None = None, extra_args: list[str] | None = None, **kw) -> Harness:
    cls = {"opencode": OpenCode, "claude": ClaudeCode, "codex": Codex}[name]
    return cls(repo, model, extra_args, **kw) if kw else cls(repo, model, extra_args)
