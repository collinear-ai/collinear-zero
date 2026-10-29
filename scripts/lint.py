"""Repository checks: rendered texts are complete, no experiment labels or model pins leak, no large files."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from collinearzero import render  # noqa: E402

# Model pins are checked everywhere. Experiment labels come from the untracked .lint-labels (one regex per line), so
# the repository never names them; without that file only model pins are checked.
labels_file = ROOT / ".lint-labels"
extra = [ln.strip() for ln in labels_file.read_text().splitlines()
         if ln.strip() and not ln.startswith("#")] if labels_file.exists() else []
LABELS = re.compile("|".join([r"\bmodel:\s*\S+/", *extra]), re.I)
problems = []
for p in sorted(ROOT.rglob("*")):
    if ".git" in p.parts or not p.is_file() or p.suffix in (".pyc",) or p.name == "lint.py":
        continue
    if p.stat().st_size > 1_000_000:
        problems.append(f"{p}: larger than 1 MB")
    if p.suffix in (".md", ".py", ".sh", ".toml", ".yml", ".json", ".txt") or p.name in ("NOTICE", "LICENSE"):
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if LABELS.search(line):
                problems.append(f"{p.relative_to(ROOT)}:{i}: experiment label or model pin: {line.strip()[:100]}")
for h in render.HARNESSES:
    for blind in (False, True):
        if "{{" in render.rules(h, Path("/cfg"), blind):
            problems.append(f"rules for {h}: unfilled placeholder")
print("\n".join(problems) or "lint: ok")
sys.exit(1 if problems else 0)
