"""`cz regress -- <test command>`: run the repository's own tests on the original snapshot and on the patch.

The command runs in a scratch copy of WS/orig and in the working tree. If it contains `{junit}`, that is replaced by
a JUnit XML path for each run and the per-test results are compared (pytest --junitxml={junit}, go-junit-report,
jest-junit, gradle/maven reports copied there, ...); otherwise only the two exit codes and output tails are compared.
Exit status 1 when the patch newly fails something the original passed.
"""
from __future__ import annotations

import shlex
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .workspace import snapshot, ws


def junit_results(path: Path) -> dict[str, bool]:
    """{test id: passed} from a JUnit XML file (testsuite or testsuites root)."""
    out: dict[str, bool] = {}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return out
    for tc in root.iter("testcase"):
        tid = f"{tc.get('classname', '')}::{tc.get('name', '')}".strip(":")
        bad = any(ch.tag in ("failure", "error") for ch in tc)
        skipped = any(ch.tag == "skipped" for ch in tc)
        if not skipped:
            out[tid] = not bad
    return out


def _run(cmd: str, cwd: Path, junit: Path, timeout: float) -> tuple[int | None, str]:
    full = cmd.replace("{junit}", shlex.quote(str(junit)))
    try:
        p = subprocess.run(full, shell=True, cwd=str(cwd), capture_output=True, text=True, errors="replace",
                           timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        return None, f"timed out after {timeout:.0f} s\n{e.stdout or ''}"


def compare(orig: dict[str, bool], patch: dict[str, bool]) -> dict[str, list[str]]:
    return {"newly_failing": sorted(t for t, ok in patch.items() if not ok and orig.get(t) is True),
            "missing": sorted(t for t, ok in orig.items() if ok and t not in patch),
            "newly_passing": sorted(t for t, ok in patch.items() if ok and orig.get(t) is False)}


def regress(repo: Path, cmd: str, timeout: float = 1800) -> tuple[int, str]:
    orig = ws() / "orig"
    if not orig.exists():
        return 2, "cz regress: no snapshot of the original; run `cz init` first"
    with tempfile.TemporaryDirectory(prefix="cz-regress-") as d:
        scratch = Path(d) / "orig"
        snapshot(orig, scratch, skip=())
        jo, jp = Path(d) / "junit_orig.xml", Path(d) / "junit_patch.xml"
        rc_o, out_o = _run(cmd, scratch, jo, timeout)
        rc_p, out_p = _run(cmd, repo, jp, timeout)
        lines = [f"original: exit {rc_o}", f"patch:    exit {rc_p}"]
        if "{junit}" in cmd:
            ro, rp = junit_results(jo), junit_results(jp)
            c = compare(ro, rp)
            lines.append(f"tests: {len(ro)} on the original, {len(rp)} on the patch")
            for k, label in (("newly_failing", "NEWLY FAILING"), ("missing", "MISSING (passed on the original)"),
                             ("newly_passing", "newly passing")):
                if c[k]:
                    lines.append(f"{label}:\n  " + "\n  ".join(c[k][:50]))
            bad = bool(c["newly_failing"] or c["missing"]) or (not ro and not rp and rc_o == 0 and rc_p != 0)
        else:
            bad = rc_o == 0 and rc_p != 0
            if bad:
                lines.append("the test command passes on the original and fails on the patch. Last lines of the patch run:")
                lines.append("\n".join(out_p.splitlines()[-30:]))
        lines.append("REGRESSION" if bad else "no regression found")
        return (1 if bad else 0), "\n".join(lines)
