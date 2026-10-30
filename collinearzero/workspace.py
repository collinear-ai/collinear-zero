"""The workspace: the finding verbatim, an untouched snapshot of the original tree, and the review checkpoint.

Layout of the workspace directory (``CZ_WS``, default ``/tmp/collinearzero``):
    task.md        the finding, exactly as given
    orig/          the repository before any change (the attack-tester diffs against it)
    pre_review/    the patched tree when the agent first stopped (the review's revert target)
    state.json     which repository the task belongs to and how far the review got
    logs/          raw output of every agent, tester and recheck session
"""
from __future__ import annotations

import filecmp
import json
import os
import shutil
import stat
import time
from pathlib import Path

DIFF_EXCLUDES = ("node_modules", "target", ".git", "__pycache__")   # what the attack-tester's own diff skips
REVERT_EXCLUDES = ("node_modules", ".git", "__pycache__")           # what a revert leaves alone
SNAPSHOT_SKIP = (".git",)


def ws() -> Path:
    return Path(os.environ.get("CZ_WS", "/tmp/collinearzero"))


def load_state() -> dict:
    p = ws() / "state.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    ws().mkdir(parents=True, exist_ok=True)
    tmp = ws() / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(ws() / "state.json")


def active_for(repo: Path) -> bool:
    st = load_state()
    return bool(st) and st.get("repo") == str(repo.resolve()) and st.get("stage") != "done"


def snapshot(src: Path, dest: Path, skip: tuple[str, ...] = SNAPSHOT_SKIP) -> None:
    """Copy `src` into a fresh `dest`. A top-level symlink to a directory is copied as its target's contents (so the
    copy is usable on its own); every other symlink is kept as a link."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for entry in sorted(os.listdir(src)):
        if entry in skip:
            continue
        s, d = src / entry, dest / entry
        if s.is_symlink() and s.is_dir():
            shutil.copytree(s.resolve(), d, symlinks=True)
        elif s.is_dir() and not s.is_symlink():
            shutil.copytree(s, d, symlinks=True)
        else:
            shutil.copy2(s, d, follow_symlinks=False)


def init(repo: Path, task: str, force: bool = False) -> str:
    repo = repo.resolve()
    st = load_state()
    if st and st.get("stage") != "done" and not force:
        if st.get("repo") == str(repo):
            return f"already initialised for {repo} (stage: {st.get('stage')}); use --force to start over"
        raise SystemExit(f"cz: the workspace {ws()} holds an active task for {st.get('repo')}; "
                         "finish it, run `cz reset`, or set CZ_WS to another directory")
    if ws().exists():
        shutil.rmtree(ws())
    ws().mkdir(parents=True)
    (ws() / "task.md").write_text(task)
    snapshot(repo, ws() / "orig")
    save_state({"repo": str(repo), "stage": "agent", "created": time.time()})
    return f"recorded the task in {ws() / 'task.md'} and snapshotted {repo} to {ws() / 'orig'}"


def _same(a: Path, b: Path) -> bool:
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:   # a dangling link on either side
        return a.is_symlink() and b.is_symlink() and os.readlink(a) == os.readlink(b)
    if not (stat.S_ISREG(sa.st_mode) and stat.S_ISREG(sb.st_mode)):
        # filecmp calls any non-regular file different; a link to /dev/null on both sides is the same file
        return stat.S_IFMT(sa.st_mode) == stat.S_IFMT(sb.st_mode) and sa.st_rdev == sb.st_rdev
    return filecmp.cmp(a, b, shallow=False)


def tree_diff(a: Path, b: Path, excludes: tuple[str, ...] = DIFF_EXCLUDES) -> list[tuple[str, str]]:
    """Differences between trees `a` and `b`, like `diff -rq -x …` (which follows symlinks): ("changed", rel),
    ("only_a", rel), ("only_b", rel). A directory present on one side only is reported once, not file by file."""
    out: list[tuple[str, str]] = []

    def walk(rel: str) -> None:
        da, db = a / rel if rel else a, b / rel if rel else b
        na = {n for n in os.listdir(da) if n not in excludes}
        nb = {n for n in os.listdir(db) if n not in excludes}
        for n in sorted(na | nb):
            r = f"{rel}/{n}" if rel else n
            pa, pb = a / r, b / r
            if n not in nb:
                out.append(("only_a", r))
            elif n not in na:
                out.append(("only_b", r))
            elif pa.is_dir() and pb.is_dir():
                walk(r)
            elif pa.is_dir() != pb.is_dir():
                out.append(("changed", r))
            elif not _same(pa, pb):
                out.append(("changed", r))

    walk("")
    return out


def format_diff(a: Path, b: Path, diffs: list[tuple[str, str]]) -> str:
    """`diff -rq` style lines, so the output reads like the command the skill and the tester use."""
    lines = []
    for kind, rel in diffs:
        if kind == "changed":
            lines.append(f"Files {a / rel} and {b / rel} differ")
        else:
            root = a if kind == "only_a" else b
            parent = (root / rel).parent
            lines.append(f"Only in {parent}: {Path(rel).name}")
    return "\n".join(lines)


def checkpoint(repo: Path) -> None:
    """The revert target. A revert leaves REVERT_EXCLUDES alone, so the checkpoint need not copy them at the top level
    (node_modules alone can be most of a JavaScript repository). Nested ones stay: a revert that restores a deleted
    directory copies it whole from here."""
    snapshot(repo, ws() / "pre_review", skip=REVERT_EXCLUDES)


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink()


def _copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        _remove(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not src.is_symlink():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def revert(repo: Path, source: Path | None = None) -> dict:
    """Make `repo` match `source` (default: the review checkpoint) file by file, leaving excluded directories alone."""
    source = source or ws() / "pre_review"
    diffs = tree_diff(source, repo, REVERT_EXCLUDES)
    for kind, rel in diffs:
        if kind in ("changed", "only_a"):
            _copy(source / rel, repo / rel)
        else:
            _remove(repo / rel)
    return {"reverted": len(diffs), "residual": len(tree_diff(source, repo, REVERT_EXCLUDES))}
