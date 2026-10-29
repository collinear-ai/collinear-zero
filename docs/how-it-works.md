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
or harmful **by running code**, not by opinion. It reports structured findings:

- `[B<n>] requirement <n> | orig: same|differs`: a bypass of a numbered requirement, with the exact input, the entry
point, the observed and expected result, and what the same input does on the original.
- `[R<n>] orig: same|differs | backing: <path>`: a regression, where the backing is a repository file (test, doc
or example) that uses the input as legitimate.
- `CHECKED:` runs that passed, and requirements it did not run (`not run`).
- `NOTES:` other changed results.

The agent acts on whatever it is shown. Collinear Zero runs the tester itself, after the agent stops, and filters
the report before the agent sees it.

## 3. Deterministic triage

- **Forwarded:**
  - every bypass;
  - a regression, only if its `backing:` path exists in the repository;
  - requirements the tester did not run, as checks for the agent to do.
- **Dropped:** everything else.

The filter does not use a model. It keeps a regression only when the cited repository path exists.

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
