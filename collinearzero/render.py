"""Render the harness-neutral texts in core/ for one harness: placeholders, agent frontmatter, optional blocks."""
from __future__ import annotations

import re
from pathlib import Path

from .workspace import ws

CORE = Path(__file__).parent / "core"
SCRIPTS = Path(__file__).parent / "scripts"
HARNESSES = ("opencode", "claude", "codex")
BLIND = re.compile(r"\n?<!-- blind-tests:begin -->.*?<!-- blind-tests:end -->\n?", re.S)


def skill_dir(harness: str, root: Path) -> Path:
    return root / "skills" / "collinearzero"


def placeholders(harness: str, root: Path) -> dict[str, str]:
    sk = skill_dir(harness, root) / "SKILL.md"
    todo = {"opencode": "`todowrite`", "claude": "the TodoWrite tool", "codex": "your plan (`update_plan`)"}[harness]
    load = {"opencode": f"with the `skill` tool; if it fails, read `{sk}` once",
            "claude": f"with the Skill tool; if it is unavailable, read `{sk}` once",
            "codex": f"read `{sk}` once"}[harness]
    writer = {"opencode": "call the `blind-test-writer` subagent once with the task tool",
              "claude": "call the `blind-test-writer` subagent once with the Task tool",
              "codex": ""}[harness]
    return {"WS": str(ws()), "CZ": "cz", "TODO": todo, "LOAD_SKILL": load, "CALL_WRITER": writer}


def fill(text: str, values: dict[str, str]) -> str:
    out = re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), text)
    left = re.findall(r"\{\{\w+\}\}", out)
    if left:
        raise ValueError(f"unfilled placeholders: {sorted(set(left))}")
    return out


def rules(harness: str, root: Path, blind_tests: bool = False) -> str:
    text = (CORE / "rules.md").read_text()
    if not blind_tests or harness == "codex":
        text = BLIND.sub("\n", text)
    else:
        text = text.replace("<!-- blind-tests:begin -->\n", "").replace("<!-- blind-tests:end -->\n", "")
    return fill(text, placeholders(harness, root))


def split_agent(name: str) -> tuple[dict[str, str], str]:
    """(frontmatter fields, body) of core/agents/<name>.md; the frontmatter is simple `key: value` lines."""
    raw = (CORE / "agents" / f"{name}.md").read_text()
    _, fm, body = raw.split("---\n", 2)
    meta = {}
    for line in fm.splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, body


def agent_body(name: str, harness: str, root: Path) -> tuple[dict[str, str], str]:
    meta, body = split_agent(name)
    vals = placeholders(harness, root)
    return {k: fill(v, vals) for k, v in meta.items()}, fill(body, vals)


def opencode_agent(name: str, root: Path) -> str:
    """An opencode agent file. The attack-tester is a primary agent, so the patching agent cannot call it as a
    subagent; Collinear Zero starts it in its own session."""
    meta, body = agent_body(name, "opencode", root)
    mode = "primary" if name == "attack-tester" else "subagent"
    lines = ["---", f"description: {meta['description']}", f"mode: {mode}", f"steps: {meta.get('steps', '30')}",
             "permission:", "  edit: deny", "  webfetch: deny", "  websearch: deny", "  codesearch: deny", "  task: deny",
             "---"]
    return "\n".join(lines) + "\n" + body


def claude_agent_file(name: str, root: Path) -> str:
    meta, body = agent_body(name, "claude", root)
    return (f"---\nname: {name}\ndescription: {meta['description']}\ntools: Bash, Read, Grep, Glob\n---\n" + body)


def claude_agents_json(root: Path) -> dict:
    """The attack-tester for `claude --agents`: passed only to its own session, never installed as a subagent."""
    meta, body = agent_body("attack-tester", "claude", root)
    return {"attack-tester": {"description": meta["description"], "prompt": body,
                              "tools": ["Bash", "Read", "Grep", "Glob"]}}


def codex_tester_prompt(root: Path) -> str:
    _, body = agent_body("attack-tester", "codex", root)
    return body


def skill_files() -> list[tuple[Path, Path]]:
    """[(source, path relative to the skill directory)] for the skill."""
    src = CORE / "skills" / "collinearzero"
    return [(p, p.relative_to(src)) for p in sorted(src.rglob("*")) if p.is_file()]


def skill_text(path: Path, harness: str, root: Path) -> str:
    return fill(path.read_text(), placeholders(harness, root))
