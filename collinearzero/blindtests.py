"""`cz tests` (opt-in): validate the blind test-writer's tests on the original, then run the valid ones on the patch.

Contract (core/agents/blind-test-writer.md): WS/bt/tests/exploit_*.sh must exit 1 on the original (the weakness is
there), legit_*.sh must exit 0 on it. Each test runs as `bash <file>` from a scratch copy of the tree, so a test that
writes files cannot change the original or the patch. Exit code 2 means the test could not run.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .workspace import snapshot, ws


def _run(test: Path, tree: Path, timeout: float) -> int | None:
    with tempfile.TemporaryDirectory(prefix="cz-bt-") as d:
        scratch = Path(d) / "tree"
        snapshot(tree, scratch)
        try:
            return subprocess.run(["bash", str(test)], cwd=str(scratch), capture_output=True, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return None


def expected(test: Path) -> int | None:
    return 1 if test.name.startswith("exploit_") else 0 if test.name.startswith("legit_") else None


def tests(repo: Path, timeout: float = 180) -> tuple[int, str]:
    tdir = ws() / "bt" / "tests"
    files = sorted(tdir.glob("*.sh")) if tdir.exists() else []
    if not files:
        return 2, f"cz tests: no tests in {tdir}"
    lines, valid = [], []
    for t in files:
        want = expected(t)
        got = _run(t, ws() / "orig", timeout)
        ok = want is not None and got == want
        lines.append(f"{t.name}: original exit {got} (want {want}) -> {'valid' if ok else 'dropped'}")
        if ok:
            valid.append(t)
    failed = []
    for t in valid:
        got = _run(t, repo, timeout)
        if got != 0:
            failed.append(t.name)
        lines.append(f"{t.name}: patch exit {got} -> {'PASS' if got == 0 else 'FAIL'}")
    lines.append(f"{len(valid)} valid test(s), {len(failed)} failing on the patch" + (f": {', '.join(failed)}" if failed else ""))
    return (1 if failed else 0), "\n".join(lines)
