#!/usr/bin/env bash
# Install Collinear Zero: the `cz` tool, then the rules, skill and agents for the harnesses you name.
#   curl -fsSL https://raw.githubusercontent.com/collinear-ai/collinear-zero/main/install.sh | bash
#   curl -fsSL …/install.sh | bash -s -- claude                 # only Claude Code
#   curl -fsSL …/install.sh | SCOPE=project bash -s -- claude   # into the current repository's .claude/
# From a checkout, `./install.sh [harness…]` installs that checkout instead. CZ_SOURCE overrides the source: a
# directory, or a tarball URL (for example a release tag's archive).
set -euo pipefail
self=${BASH_SOURCE[0]:-}
TARBALL=https://github.com/collinear-ai/collinear-zero/archive/refs/heads/main.tar.gz

# Everything runs from main, so a truncated download runs nothing.
main() {
  local src spec cz
  if [ -n "${CZ_SOURCE:-}" ]; then
    src=$CZ_SOURCE
  elif [ -f "$self" ] && [ -f "$(dirname "$self")/pyproject.toml" ]; then
    src=$(cd "$(dirname "$self")" && pwd)
  else
    src=$TARBALL
  fi
  case $src in *://*) spec="collinearzero @ $src";; *) spec=$src;; esac
  echo "Installing Collinear Zero from $src"
  if command -v uv >/dev/null; then
    uv tool install --quiet --force --reinstall "$spec"
  else
    python3 -m pip install --user --quiet --force-reinstall "$spec" 2>/dev/null ||
      python3 -m pip install --quiet --force-reinstall "$spec"
  fi
  # A fresh install may not be on PATH yet: look where uv and pip --user put it.
  cz=$(command -v cz || true)
  if [ -z "$cz" ] && command -v uv >/dev/null && [ -x "$(uv tool dir --bin 2>/dev/null)/cz" ]; then
    cz="$(uv tool dir --bin)/cz"
  fi
  if [ -z "$cz" ] && [ -x "$(python3 -m site --user-base)/bin/cz" ]; then
    cz="$(python3 -m site --user-base)/bin/cz"
  fi
  local harnesses=("$@")
  [ ${#harnesses[@]} -gt 0 ] || harnesses=(claude opencode codex)
  if [ -n "$cz" ]; then
    "$cz" install --harness "${harnesses[@]}" --scope "${SCOPE:-user}"
  else
    python3 -m collinearzero install --harness "${harnesses[@]}" --scope "${SCOPE:-user}"
  fi
  command -v cz >/dev/null || echo "note: add $(dirname "${cz:-$(python3 -m site --user-base)/bin/cz}") to PATH to get the cz command"
}

main "$@"
