"""Deterministic triage of an attack-tester report, and the fixed messages of the review loop.

The agent acts on whatever it is shown, so filtering happens here, before the agent sees the report. The tester writes
its report as one <report> block (the last one in the reply counts):
    <bypass>                              forwarded;
    <regression>                          forwarded only when a <backing> names a file the repository had before the
                                          patch (a file the patch changed only if it is a test, doc or example), else
                                          dropped;
    <checked status="not_run">            forwarded as requirements for the agent to run;
    <checked status="pass">, <note>       dropped.
A reply with no <report> forwards nothing. No model takes part in this decision.

The blocks are read with a tolerant tag scanner, not an XML parser: attack inputs hold unescaped `<`, `&` and `>`,
and a reply cut short may lack its closing tags.
"""
from __future__ import annotations

import re
from typing import Callable

TOP = r"</?(?:report|bypass|regression|checked|note)\b"   # an element of the report ends where the next one starts
_ATTRS = r"""((?:"[^"]*"|'[^']*'|[^'">])*)"""
ATTR = re.compile(r"""([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>/]+))""")
BACKING_FILE = re.compile(r"(?i)(^|/)(tests?|spec|specs|__tests__|docs?|examples?)(/|$)|(^|/)(test_|readme)|"
                          r"[._-](test|spec)s?\.|\.(md|rst|txt|adoc)$")

TESTER_MSG = "Review the current patch. Follow your instructions."
REPORT_NOW = ("Stop testing. Write your final report now from the runs you have done: one <report> block as your "
              "instructions say, each finding as a <bypass> or <regression> element, and every requirement you did not "
              "run as <checked requirement=\"<n>\" status=\"not_run\">.")
RECHECK = ("The other agent changed the patch after your report. Re-run now, on the current tree, every run from your report "
           "that checked a legitimate input: each `must still` case, each legitimate twin and each benign input you listed. "
           "Do not run new attacks. Reply with one <recheck> block holding one line per run, "
           "`<run result=\"pass\" orig=\"pass\">input</run>` or `<run result=\"fail\" orig=\"pass\">input | observed "
           "result</run>`, where `orig` is that input's result on the original from your earlier runs (leave it out if "
           "you did not run it there). Open the block with <recheck verdict=\"OK\"> if every legitimate run still "
           "behaves as before, or <recheck verdict=\"BROKEN\"> if any now fails, and close it with </recheck>.")
PROMPT = """Review. An independent tester reviewed your patch after you stopped. Below are the findings Collinear Zero
forwards to you: bypasses of numbered task sentences, regressions that a repository test, doc or example backs, and
requirements the tester did not run. Other findings were dropped. Act on these as the "Acting on forwarded findings"
rule says, then stop. Your patch as it stood when you stopped is saved at {checkpoint}.

{body}
"""


def _attrs(s: str) -> dict[str, str]:
    return {m.group(1).lower(): next(g for g in m.groups()[1:] if g is not None).strip() for m in ATTR.finditer(s)}


def _enum(v: str) -> str:
    """`Not Run`, `not-run` and `not_run` alike."""
    return re.sub(r"[\s-]+", "_", v.strip().lower())


def block(tag: str, text: str, inner: str = TOP) -> tuple[dict[str, str], str] | None:
    """(attributes, body) of the last <tag> in `text` that is closed or holds an `inner` element: an earlier block may
    quote the instruction, and a bare mention ("my <report> above") is no block. Without its closing tag the body runs
    to the end."""
    text = text or ""
    found = []
    for m in re.finditer(r"(?i)<%s\b%s>" % (tag, _ATTRS), text):
        a = m.group(1).rstrip()
        if a.endswith("/"):
            found.append((_attrs(a[:-1]), "", True))
            continue
        end = re.compile(r"(?i)</%s\s*>" % tag).search(text, m.end())
        body = text[m.end():end.start() if end else len(text)]
        found.append((_attrs(a), body, bool(end) or bool(re.search(r"(?i)" + inner, body))))
    return next(((a, b) for a, b, ok in reversed(found) if ok), None)


def elems(tag: str, body: str, stop: str = TOP) -> list[tuple[dict[str, str], str, str]]:
    """[(attributes, inner text, raw element)] of each <tag> in `body`. An element without its closing tag ends where
    `stop` next matches. Self-closing elements have no inner text."""
    out = []
    for m in re.finditer(r"(?is)<%s\b%s>(?:(?<=/>)|(.*?)(?:</%s\s*>|(?=%s)|\Z))" % (tag, _ATTRS, tag, stop), body):
        a = m.group(1).rstrip()
        out.append((_attrs(a[:-1] if a.endswith("/") else a), (m.group(2) or "").strip(), m.group(0).strip()))
    return out


def has_report(text: str) -> bool:
    return block("report", text) is not None


def has_recheck(text: str) -> bool:
    return block("recheck", text, inner=r"<run\b") is not None


def _ids(found: list[tuple[dict[str, str], str, str]], prefix: str) -> list[str]:
    """The tester's ids where they are `<prefix><n>` and unique, else the next unused number."""
    given = [a.get("id", "").upper() for a, _, _ in found]
    taken = {g for g in given if re.fullmatch(prefix + r"\d+", g) and given.count(g) == 1}
    out, n = [], 0
    for g in given:
        if g in taken:
            out.append(g)
            continue
        n += 1
        while f"{prefix}{n}" in taken:
            n += 1
        out.append(f"{prefix}{n}")
    return out


def _backing(a: dict[str, str], inner: str) -> list[str]:
    """Each <backing> element is one path (a `backing="a, b"` attribute is read too), without a `:line` suffix."""
    raw = [i for _, i, _ in elems("backing", inner, stop="<")] + re.split(r"\s*,\s*", a.get("backing", ""))
    paths = [re.sub(r":\d+(?:[-:]\d+)*$", "", p.strip(" \n\t`'\"")) for p in raw]
    return [p for p in paths if p and p.lower() not in ("none", "n/a")]


def triage(rep: str, path_exists: Callable[[str], bool]) -> dict:
    """Triage a tester report. `path_exists(p)` says whether `p` is a repository file a regression may cite."""
    out: dict = {"kept": [], "dropped": [], "not_run": []}
    rb = block("report", rep)
    if rb is None:
        out["stop"] = "no_report"
        return out
    body = rb[1]
    bypasses = elems("bypass", body)
    for iid, (_, _, raw) in zip(_ids(bypasses, "B"), bypasses):
        out["kept"].append({"id": iid, "kind": "bypass", "text": raw})
    regressions = elems("regression", body)
    for iid, (a, inner, raw) in zip(_ids(regressions, "R"), regressions):
        paths = _backing(a, inner)
        ok = [p for p in paths if path_exists(p)]
        rec = {"id": iid, "kind": "regression", "backing": ", ".join(paths)[:200], "paths_found": ok}
        if ok:
            out["kept"].append({**rec, "text": raw})
        else:
            out["dropped"].append({**rec, "why": "no existing repository path as backing" if paths else "no repository backing"})
    for a, inner, _ in elems("checked", body):
        if _enum(a.get("status", "")) == "not_run":
            why = " ".join(inner.split())
            out["not_run"].append(f"requirement {a.get('requirement', '?')}: not run" + (f" ({why})" if why else ""))
    return out


def forward_body(t: dict) -> str:
    parts = []
    if t["kept"]:
        parts.append("FINDINGS TO ACT ON:\n\n" + "\n\n".join(k["text"] for k in t["kept"]))
    if t["not_run"]:
        parts.append("REQUIREMENTS THE TESTER DID NOT RUN (run each yourself through the public entry point):\n"
                     + "\n".join(t["not_run"]))
    return "\n\n".join(parts)


def repo_path_checker(repo, patched: frozenset[str] = frozenset(), orig=None) -> Callable[[str], bool]:
    """A `path_exists` for `triage`: a file in `repo` (relative paths resolve inside it; nothing may escape it with
    `..`) that the repository had before the patch (`orig`, the snapshot). A file the patch changed (`patched`,
    relative to `repo`) counts only if it is a test, doc or example: a test the patch edited is the strongest evidence
    of a regression, but the patched source shows only what the patch does."""
    from pathlib import Path
    root = Path(repo).resolve()
    before = Path(orig) if orig else None

    def exists(p: str) -> bool:
        q = Path(p).resolve() if p.startswith("/") else root / (p[2:] if p.startswith("./") else p)
        if ".." in Path(p).parts or not (q == root or root in q.parents):
            return False
        rel = q.relative_to(root)
        if not q.is_file() or (before is not None and not (before / rel).is_file()):
            return False      # a directory is too vague; a file the patch added is not the repository's
        if any(r.as_posix() in patched for r in (rel, *rel.parents)):
            return bool(BACKING_FILE.search(rel.as_posix()))
        return True
    return exists


def recheck_verdict(text: str) -> dict:
    """From the last <recheck> block (an earlier one may quote the instruction). A failed run that did not also fail on
    the original makes the verdict BROKEN whatever the block says."""
    rb = block("recheck", text or "", inner=r"<run\b")
    if rb is None:
        return {"verdict": None, "failed": []}
    a, body = rb
    failed = [" ".join(inner.split())[:200] for ra, inner, _ in elems("run", body, stop=r"</?(?:run|recheck)\b")
              if _enum(ra.get("result", "")) == "fail" and _enum(ra.get("orig", "")) != "fail"]
    said = _enum(a.get("verdict", "")).upper()
    out = {"verdict": "BROKEN" if said == "BROKEN" or failed else "OK" if said == "OK" else None, "failed": failed[:20]}
    if failed and said == "OK":
        out["overridden"] = "verdict OK with a failed run"
    return out
