#!/usr/bin/env bash
# Install Collinear Zero: the `cz` tool, then the rules, skill and agents for the harnesses you name.
#   ./install.sh                       # claude, opencode and codex, user scope
#   ./install.sh claude                # only Claude Code
#   SCOPE=project ./install.sh claude  # into the current repository's .claude/ instead of ~/.claude/
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
if command -v uv >/dev/null; then
  uv tool install --quiet --force "$here"
else
  python3 -m pip install --user --quiet "$here" 2>/dev/null || python3 -m pip install --quiet "$here"
fi
cz=$(command -v cz || echo "python3 -m collinearzero")
harnesses=("$@")
[ ${#harnesses[@]} -gt 0 ] || harnesses=(claude opencode codex)
$cz install --harness "${harnesses[@]}" --scope "${SCOPE:-user}"
command -v cz >/dev/null || echo "note: add $(python3 -m site --user-base)/bin to PATH to get the cz command"
