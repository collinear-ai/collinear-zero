"""Deterministic triage of an attack-tester report, and the fixed messages of the review loop.

The agent acts on whatever it is shown, so filtering happens here, before the agent sees the report:
    [B<n>] bypass lines                   forwarded;
    [R<n>] regression lines               forwarded only when `backing:` names a path that exists in the repository
                                          (a test, doc or example), else dropped;
    CHECKED lines marked `not run`        forwarded as requirements for the agent to run;
    NOTES                                 dropped.
A report with the section headers but no [B<n>]/[R<n>] items forwards its BYPASSES section verbatim; a reply with no
BYPASSES header forwards nothing. No model takes part in this decision.
"""
from __future__ import annotations

import re
from typing import Callable

HDR = lambda h: re.compile(r"(?im)^[#*`\s-]*\**`?%s`?\**\s*:?" % h)   # noqa: E731
ITEM = re.compile(r"(?m)^[\s>*`-]*\[(B|R)(\d+)\]")
BACKING = re.compile(r"(?i)backing\s*:\s*`?([^`|\n]+?)`?\s*(?:\||$)", re.M)
VERDICT = re.compile(r"RECHECK:\s*\**\s*(OK|BROKEN)", re.I)

TESTER_MSG = "Review the current patch. Follow your instructions."
REPORT_NOW = ("Stop testing. Write your final report now from the runs you have done, with the four headers BYPASSES:, "
              "REGRESSIONS:, CHECKED: and NOTES:, each finding as a [B<n>] or [R<n>] item as your instructions say. "
              "Mark every requirement you did not run as `not run`.")
RECHECK = ("The other agent changed the patch after your report. Re-run now, on the current tree, every run from your report "
           "that checked a legitimate input: each `must still` case, each legitimate twin and each benign input you listed. "
           "Do not run new attacks. Reply with one line per run, `PASS <input>` or `FAIL <input> | observed <result>`, and end "
           "with exactly `RECHECK: OK` if every legitimate run still behaves as before, or `RECHECK: BROKEN` if any now fails.")
PROMPT = """Review. An independent tester reviewed your patch after you stopped. Below are the findings Collinear Zero
forwards to you: bypasses of numbered task sentences, regressions that a repository test, doc or example backs, and
requirements the tester did not run. Other findings were dropped. Act on these as the "Acting on forwarded findings"
rule says, then stop. Your patch as it stood when you stopped is saved at {checkpoint}.

{body}
"""


def sections(rep: str) -> dict[str, str]:
    marks = []
    for h in ("BYPASSES", "REGRESSIONS", "CHECKED", "NOTES"):
        m = HDR(h).search(rep)
        if m:
            marks.append((m.start(), h))
    marks.sort()
    return {h: rep[s:(marks[i + 1][0] if i + 1 < len(marks) else len(rep))] for i, (s, h) in enumerate(marks)}


def items(section: str) -> list[tuple[str, str]]:
    """[(id, text)] of the [B<n>] / [R<n>] items in a section; an item runs to the next item or the section end."""
    ms = list(ITEM.finditer(section))
    return [(f"{m.group(1)}{m.group(2)}", section[m.start():(ms[i + 1].start() if i + 1 < len(ms) else len(section))].strip())
            for i, m in enumerate(ms)]


def triage(rep: str, path_exists: Callable[[str], bool]) -> dict:
    """Triage a tester report. `path_exists(p)` says whether a backing path exists in the repository."""
    sec = sections(rep)
    out: dict = {"headers": sorted(sec), "kept": [], "dropped": [], "not_run": [], "fallback": False}
    if "BYPASSES" not in sec:
        out["stop"] = "no_report"
        return out
    found = [(i, t) for i, t in items(sec.get("BYPASSES", ""))] + [(i, t) for i, t in items(sec.get("REGRESSIONS", ""))]
    if not found:
        body = re.sub(r"(?m)^\s*(-{3,}|\*{3,}|_{3,})\s*$", "", HDR("BYPASSES").sub("", sec["BYPASSES"], count=1))
        body = body.strip(" \n\t*`:#-")
        if body and not re.match(r"(?i)^(none|no bypass|nothing)", body):
            out["fallback"] = True
            out["kept"].append({"id": "BYPASSES", "kind": "bypass", "text": sec["BYPASSES"].strip()})
        rb = HDR("REGRESSIONS").sub("", sec.get("REGRESSIONS", ""), count=1).strip(" \n\t*`:#-")
        if rb and not re.match(r"(?i)^(none|no regression|nothing)", rb):
            out["dropped"].append({"id": "REGRESSIONS", "kind": "regression", "why": "unstructured report"})
    for iid, text in found:
        if iid.startswith("B"):
            out["kept"].append({"id": iid, "kind": "bypass", "text": text})
            continue
        m = BACKING.search(text)
        back = m.group(1).strip() if m else ""
        paths = [p.strip(" .,;:'\"") for p in re.split(r"[,\s]+", back) if "/" in p or "." in p]
        paths = [p.split(":")[0] for p in paths if p and p.lower() not in ("none", "n/a")]
        ok = [p for p in paths if path_exists(p)]
        rec = {"id": iid, "kind": "regression", "backing": back[:200], "paths_found": ok}
        if ok:
            out["kept"].append({**rec, "text": text})
        else:
            out["dropped"].append({**rec, "why": "no existing repository path as backing" if paths else "no repository backing"})
    for line in sec.get("CHECKED", "").splitlines():
        if re.search(r"(?i)\bnot run\b", line):
            out["not_run"].append(line.strip())
    return out


def forward_body(t: dict) -> str:
    parts = []
    if t["kept"]:
        parts.append("FINDINGS TO ACT ON:\n\n" + "\n\n".join(k["text"] for k in t["kept"]))
    if t["not_run"]:
        parts.append("REQUIREMENTS THE TESTER DID NOT RUN (run each yourself through the public entry point):\n"
                     + "\n".join(t["not_run"]))
    return "\n\n".join(parts)


def repo_path_checker(repo) -> Callable[[str], bool]:
    """A `path_exists` for `triage`: relative paths resolve inside `repo`; nothing may escape it with `..`."""
    from pathlib import Path
    root = Path(repo).resolve()

    def exists(p: str) -> bool:
        q = Path(p) if p.startswith("/") else root / (p[2:] if p.startswith("./") else p)
        if ".." in q.parts or not (q == root or root in q.parents):
            return False
        return q.exists()
    return exists


def recheck_verdict(text: str) -> dict:
    m = VERDICT.search(text or "")
    return {"verdict": m.group(1).upper() if m else None,
            "failed": [ln.strip()[:200] for ln in (text or "").splitlines() if re.match(r"\s*[-*]?\s*FAIL\b", ln)][:20]}
