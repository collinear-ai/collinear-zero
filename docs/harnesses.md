# Harness details

`cz install --harness <h> [--scope user|project]` writes these files. `<root>` is the user config directory, or
the repository's `.opencode/`, `.claude/` or `.codex/` with `--scope project`.

## opencode (benchmarked)
**Files:**
- **Rules:** a marked block in `<root>/AGENTS.md` (project scope: the repository's `AGENTS.md`).
- **Skill:** `<root>/skills/collinearzero/`.
- **Attack-tester:** `<root>/agents/attack-tester.md`. It is a **primary** agent, so the patching agent cannot call
  it as a subagent. Edit, web and task tools are denied; 45 steps.

**Sessions:**
- **Agent phase:** `opencode run --format json --auto`, through `opencode-continue.sh`. That wrapper resumes the
  session (up to twice) when a response hit the output-token limit before calling a tool.
- **Tester:** `opencode run --agent attack-tester`.
- **Fix round and recheck:** they continue the agent's and the tester's sessions with `-s <id>`.
- **Report text:** read from the JSON events, with opencode's local database as a fallback.
- **File watcher:** Collinear Zero sets `OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER=1` for these sessions. `opencode run`
  doesn't need the watcher, and it hangs at startup when the host runs out of inotify instances.

**Interactive:** run `cz review --harness opencode`, then `cz recheck --harness opencode`.

## Claude Code
**Files:**
- **Rules:** a marked block in `<root>/CLAUDE.md`.
- **Skill:** `<root>/skills/collinearzero/`.
- **Finish gate:** a Stop hook in `<root>/settings.json` (`cz gate`, 2,000 s timeout).

**The tester is never installed as a subagent.** `cz` passes it with `--agents` to its own `claude -p` session,
with `Edit`, `Write`, `NotebookEdit`, web and `Task` tools disallowed.

**Interactive (the gate):**
- **First stop:** the gate runs the tester and the triage. If findings are forwarded, it blocks the stop and hands
  them to Claude.
- **Next stop:** it runs the recheck and reverts the fix round on `RECHECK: BROKEN`.
- **Without an active task for this repository,** it does nothing.

**Non-interactive (`cz run`):**
- **Agent:** `claude -p --output-format json --permission-mode acceptEdits` with Bash, Read, Edit, Write, Grep, Glob,
  TodoWrite and Skill allowed.
- **Fix round and recheck:** `--resume <session>`.
- **Extra flags:** `--harness-arg` adds flags.
- **The gate inside these sessions:** `CZ_GATE=off` is set for every session `cz` starts, so the gate never fires
  inside them.

## Codex (experimental)
**Files:**
- **Rules:** a marked block in `<root>/AGENTS.md` (project scope: the repository's `AGENTS.md`).
- **Skill:** `<root>/skills/collinearzero/`. The rules point at its `SKILL.md` path directly.

**Sessions:**
- **Command:** `codex exec --json --sandbox workspace-write -`.
- **Fix round and recheck:** `codex exec … resume <id> -`.
- **The tester:** Codex has no separate agent definitions, so the tester's instructions lead its first message.
  Because the sandbox cannot make the repository read-only for one session, Collinear Zero restores the checkpoint if
  the tree changed while the tester ran.

**Not supported:** the blind test-writer.

**Not yet verified:** the CLI flags and the JSON event format against a current Codex release.

## Workspace (`CZ_WS`, default `/tmp/collinearzero`)
| Path | Contents |
|---|---|
| `task.md` | the finding, verbatim |
| `orig/` | the repository before any change (`.git` skipped) |
| `pre_review/`, `post_fix/` | the checkpoints before the fix round and before the recheck |
| `state.json` | the repository, the stage (`agent` → `fix` → `done`), the session ids |
| `review.json` | every finding's triage decision, the retries, the times and the recheck verdict |
| `review_raw.md` | the tester's report |
| `review_forwarded.md` | what the agent was sent |
| `review_recheck.md` | the tester's recheck reply |
| `run.json`, `logs/` | `cz run`'s record, and the raw output of every session |
