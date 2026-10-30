# How Collinear Zero works, and why

## 1. The agent cannot check itself

A failing patch often ends with the agent reporting a successful self-check, at the same rate as a passing one. Its
checks encode its own reading of the finding, so they miss the variants its fix misses. Approaches that kept the
checking inside the agent's own process did not move results:

- a requirement checklist enforced at finish;
- validation tools;
- a test-writer that saw only the finding.

## 2. An independent tester, but not one the agent controls

A tester in a fresh session sees only the finding and the original code. It is told to prove the patch incomplete
or harmful **by running code**, not by opinion. It ends with one `<report>` block of tagged elements:

- `<bypass id="B<n>" requirement="<n>" orig="same|differs">`: a bypass of a numbered requirement, with the exact
input, the entry point, the observed and expected result, and what the same input does on the original.
- `<regression id="R<n>" orig="same|differs">`: a regression, with one `<backing>` per repository file (test, doc or
example) that uses the input as legitimate.
- `<checked status="pass|not_run">`: runs that passed, and requirements it did not run.
- `<note>`: other changed results.

An empty section is the absence of elements, not a sentence, so triage never has to read prose. Inputs are written
verbatim (attack inputs hold `<`, `&` and `>`), so the block is read with a tolerant tag scanner rather than an XML
parser: the last `<report>` counts, and a reply cut short before its closing tags still parses.

The agent acts on whatever it is shown. Collinear Zero runs the tester itself, after the agent stops, and filters
the report before the agent sees it.

## 3. Deterministic triage

- **Forwarded:**
  - every bypass;
  - a regression, only if a `<backing>` path is a file the repository had before the patch; a file the patch changed
    counts only if it is a test, doc or example, since the patched source shows only what the patch does;
  - requirements the tester did not run, as checks for the agent to do.
- **Dropped:** everything else. A reply with no `<report>` gets one "report now" turn; if that has none either,
  nothing is forwarded.

The filter does not use a model. It keeps a regression only when the cited repository file existed before the patch.

## 4. One fix round, minimal, with a checkpoint

- **One fix round:** the agent gets the filtered findings once, in its own session.
- **How it is told to fix:**
  - fix a bypass in the function it names;
  - keep public signatures and existing mechanisms;
  - re-run its checks after every fix;
  - revert any fix that makes a check fail which passed at the checkpoint.
- **Why:** a change made for a finding is what most often breaks a correct patch, usually because a correct finding
was fixed so broadly that legitimate behavior is refused.

## 5. Recheck and revert

After the fix round, the tester's session re-runs its legitimate-use checks on the new tree. If any now fails, the
fix round is reverted to the checkpoint. This guards against the over-broad fixes above.
