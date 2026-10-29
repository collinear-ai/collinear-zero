"""`cz install` / `cz uninstall`: put the rules, the skill and the agents where each harness reads them.

               rules (marked block)          skill                          agents / hooks
  opencode     <root>/AGENTS.md              <root>/skills/collinearzero/     <root>/agents/attack-tester.md (primary)
  claude       <root>/CLAUDE.md              <root>/skills/collinearzero/     Stop hook `cz gate` in <root>/settings.json
  codex        <root>/AGENTS.md              <root>/skills/collinearzero/     (none: Collinear Zero runs the tester itself)

<root> is the user config directory (~/.config/opencode, ~/.claude, ~/.codex) or, with --scope project, the repository's
.opencode/, .claude/ or .codex/ (opencode and codex then read the rules from the repository's AGENTS.md). The Claude
Code attack-tester is never installed: `cz` passes it to its own session only. Every edited file is backed up once
(`<file>.cz-bak`), and <root>/collinearzero.manifest.json lists what was added so `cz uninstall` can remove it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import render

BEGIN, END = "<!-- collinearzero:begin -->", "<!-- collinearzero:end -->"
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.S)


def root_dir(harness: str, scope: str, repo: Path) -> Path:
    if scope == "project":
        return repo / {"opencode": ".opencode", "claude": ".claude", "codex": ".codex"}[harness]
    if harness == "opencode":
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"
    if harness == "claude":
        return Path.home() / ".claude"
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def rules_file(harness: str, scope: str, repo: Path) -> Path:
    if scope == "project" and harness in ("opencode", "codex"):
        return repo / "AGENTS.md"
    return root_dir(harness, scope, repo) / ("CLAUDE.md" if harness == "claude" else "AGENTS.md")


def cz_command() -> str:
    exe = shutil.which("cz")
    return exe or f"{sys.executable} -m collinearzero"


def _backup(p: Path) -> None:
    b = p.with_name(p.name + ".cz-bak")
    if p.exists() and not b.exists():
        shutil.copy2(p, b)


def _write(p: Path, text: str, added: list[str], ours: set[str]) -> None:
    """Write a file Collinear Zero owns; a pre-existing file that is not ours is backed up first."""
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and str(p) not in ours:
        _backup(p)
    if not p.exists() or str(p) in ours:
        added.append(str(p))
    p.write_text(text)


def _set_block(p: Path, body: str, added: list[str]) -> None:
    old = p.read_text() if p.exists() else ""
    if p.exists() and BEGIN not in old:
        _backup(p)
    elif not p.exists():
        added.append(str(p))
    block = f"{BEGIN}\n{body.rstrip()}\n{END}\n"
    new = BLOCK.sub(lambda _: block, old) if BEGIN in old else (old.rstrip() + "\n\n" + block if old.strip() else block)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new)


def _hook_entry() -> dict:
    return {"hooks": [{"type": "command", "command": f"{cz_command()} gate", "timeout": 2000}]}


def _is_ours(entry: dict) -> bool:
    def ours(cmd: str) -> bool:
        exe = cmd[:-len(" gate")]
        return cmd.endswith(" gate") and (Path(exe).name == "cz" or exe.endswith(" -m collinearzero"))
    return any(ours(str(h.get("command", ""))) for h in entry.get("hooks", []))


def _settings_hook(p: Path, add: bool, added: list[str] | None = None) -> None:
    data = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
    stop = [e for e in data.get("hooks", {}).get("Stop", []) if not _is_ours(e)]
    if add:
        stop.append(_hook_entry())
        if p.exists() and not any(_is_ours(e) for e in data.get("hooks", {}).get("Stop", [])):
            _backup(p)
        elif not p.exists() and added is not None:
            added.append(str(p))
    hooks = data.setdefault("hooks", {})
    if stop:
        hooks["Stop"] = stop
    else:
        hooks.pop("Stop", None)
    if not hooks:
        data.pop("hooks")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def install(harness: str, scope: str, repo: Path, blind_tests: bool = False, gate: bool = True) -> list[str]:
    root = root_dir(harness, scope, repo)
    manifest = root / "collinearzero.manifest.json"
    prev = json.loads(manifest.read_text()) if manifest.exists() else {"added": []}
    ours = set(prev["added"])
    added: list[str] = []
    _set_block(rules_file(harness, scope, repo), render.rules(harness, root, blind_tests), added)
    skill = render.skill_dir(harness, root)
    for src, rel in render.skill_files():
        _write(skill / rel, render.skill_text(src, harness, root), added, ours)
    if harness == "opencode":
        _write(root / "agents" / "attack-tester.md", render.opencode_agent("attack-tester", root), added, ours)
        if blind_tests:
            _write(root / "agents" / "blind-test-writer.md", render.opencode_agent("blind-test-writer", root), added, ours)
    if harness == "claude":
        if blind_tests:
            _write(root / "agents" / "blind-test-writer.md", render.claude_agent_file("blind-test-writer", root), added, ours)
        if gate:
            _settings_hook(root / "settings.json", add=True, added=added)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"harness": harness, "scope": scope, "rules": str(rules_file(harness, scope, repo)),
                                    "gate": harness == "claude" and gate,
                                    "added": sorted(set(prev["added"]) | set(added))}, indent=2))
    shown = [str(rules_file(harness, scope, repo)), str(skill)] + [a for a in added if "/skills/" not in a]
    return list(dict.fromkeys(shown))


def uninstall(harness: str, scope: str, repo: Path) -> list[str]:
    root = root_dir(harness, scope, repo)
    manifest = root / "collinearzero.manifest.json"
    removed = []
    added = json.loads(manifest.read_text()).get("added", []) if manifest.exists() else []
    shared = {str(rules_file(harness, scope, repo)), str(root / "settings.json")}
    for f in added:
        p = Path(f)
        if p.exists() and f not in shared:
            p.unlink()
            removed.append(f)
    skill = render.skill_dir(harness, root)
    if skill.exists():
        shutil.rmtree(skill)
        removed.append(str(skill))
    rf = rules_file(harness, scope, repo)
    if rf.exists() and BEGIN in rf.read_text():
        rest = BLOCK.sub("", rf.read_text()).strip()
        if not rest and str(rf) in added:
            rf.unlink()
        else:
            rf.write_text(rest + "\n")
        removed.append(f"{rf} (Collinear Zero block)")
    sp = root / "settings.json"
    if harness == "claude" and sp.exists():
        _settings_hook(sp, add=False)
        if str(sp) in added and json.loads(sp.read_text() or "{}") == {}:
            sp.unlink()
        removed.append(f"{sp} (Stop hook)")
    if manifest.exists():
        manifest.unlink()
    return removed


def installed(harness: str, repo: Path) -> bool:
    """The rules are in place for this harness, at user or project scope."""
    return any(rules_file(harness, s, repo).exists() and BEGIN in rules_file(harness, s, repo).read_text()
               for s in ("user", "project"))
