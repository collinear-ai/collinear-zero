---
name: collinearzero
description: Workflow for fixing a described security vulnerability or weakness (CVE, CWE, advisory, audit finding, scanner result, or threat description) in a code repository. Locate every affected path, fix at the right boundary, prove the fix with a variant-driven check, and review the patch against a snapshot of the original code.
---

<!-- Adapted from codex-security (Apache-2.0, Copyright 2025 OpenAI) and deepsec (Apache-2.0, Copyright 2026
Vercel, Inc. and contributors); see NOTICE in the Collinear Zero repository for sources and changes. -->

# Security patch workflow

Keep every step short and driven by tool calls. Track the lists below with {{TODO}}.

The helper `{{CZ}}` keeps the workspace `{{WS}}`: the finding verbatim (`task.md`) and an untouched snapshot of the
original repository (`orig/`). Run `{{CZ}} init` before your first edit if it has not run yet (see the rules).

## Priorities, in order
1. The described attack is blocked on every path and for every variant, including the default and
   unconfigured setup. Fail closed. Behavior the task calls vulnerable is not legitimate, even if a default
   or an existing test relies on it.
2. Legitimate behavior keeps working, including safe alternatives the code already offers.
3. Repository conventions, then the smallest change that achieves 1 and 2. "Smallest" never means skipping the
   shared primitive: a guard in one caller is not a fix while the vulnerable function stays reachable.

## 1. Map the description to code
- Take each concrete phrase (component, input, option, protocol, file type, consequence) and grep for it.
- Write the tuple: attacker-controlled source, the missing or wrong control, the dangerous sink and its impact.
- List candidate sinks. If the obvious sink already handles the classic attack, the weakness is elsewhere, or
  it bypasses that guard. Local changelogs and version notes can reveal an earlier, incomplete fix.
- Write down every invariant or guarantee the task states, and every "must still work" example. Each must hold
  after your fix.
- `{{WS}}/orig` is an untouched copy of the original repository. Never modify or delete it, and do not commit or
  `git add`: you and the attack-tester both compare the working tree with `{{WS}}/orig`.

## 2. Inventory every path ({{TODO}})
List every way input reaches the sink or the protected action:
- public entry points and wrappers, high- and low-level APIs;
- fallback, owner, admin, and self branches;
- modes, backends, and storage variants;
- sibling operations of the same family (read/write/delete, the load and parse variants);
- input that arrives through paths, headers, configuration, or stored state.

A shared check protects only the callers that actually call it.

Sweep for siblings by the contract's data type and the bug's idiom (the type or struct name, the unsafe call)
across the whole module directory, not by the first site's variable names. If the task or the repository mentions
several strategies, backends, or entry points, open every one before you call the fix complete.

## 3. Variant matrix ({{TODO}})
From the task's wording and the class file for this weakness, list inputs that must be blocked and inputs that
must keep working:
- type and shape: missing, null, empty, wrong type, list vs string;
- case, whitespace, and encodings: percent, double, unicode, backslash, trailing dot;
- aliases and equivalent forms;
- what the consuming component does with the value (browser, shell, filesystem, parser, resolver);
- boundary sizes, including a nested or combined input just under any cap you set.

Cross every attack family with every input form and every supply path the task names (a grid, not a list): inline
and reference forms of the same markup; a value, a buffer, a callback, and an async supplier of the same key.

## 4. Fix
- Fix at the shared primitive or where untrusted input enters. Also guard the dangerous operation if other paths
  reach it. Validate after decoding and normalizing, just before use.
- Reject unsafe input explicitly, in the error style the surrounding code already uses. Do not silently truncate
  or reinterpret it. Reject only the unsafe forms: the legitimate forms the original accepted keep working.
- An error must reach the caller as an error: no fallthrough, no swallowed failure, and no default value that
  lets execution continue to the consequence.
- Prefer helpers and APIs already used nearby. Add no dependencies.
- If a feature is inherently dangerous, make it opt-in instead of relying on callers to configure a filter.

## 5. Prove it
- Write a small table-driven check in `/tmp` that calls the real entry points, not a reimplementation. Every path
  and variant from steps 2–3 must be blocked; legitimate controls taken from existing tests or docs must still
  pass. Assert the described impact itself, under the default configuration.
- Run every "must still work" example from the task and the repository on `{{WS}}/orig` and on your patch, through
  the real entry point. The results must match unless a task sentence requires the change. Never write into
  `{{WS}}/orig`: if the project must be compiled, build a copy under `/tmp` or set the build output directory there.
- Replay every item of your inventory through the fixed code, including each field you listed as overridable.
- C and C++: build the project's own tests or your check with `-fsanitize=address,undefined` when the toolchain
  supports it; every sanitizer report is a finding.
- Run the narrowest build or type check, then the nearest existing tests with the project's own runner and
  environment (virtualenv, node_modules, module cache). Missing tooling is not evidence that the fix is wrong:
  trace the code instead, and timebox setup to a few minutes.
- A failing check means the fix is incomplete: change the fix, not the check.

## 6. Existing tests that now fail
A newly failing test is a regression: narrow the fix (add a boundary instead of removing a feature). The
exception is a test that asserts the vulnerable behavior itself: update only that expectation and say so. Never
delete, skip, or weaken tests to make them pass.

## 7. Review the patch (once it exists)
The patch is the working tree compared with `{{WS}}/orig` (git history may be missing or include unrelated work).
List it with `{{CZ}} diff` (`Only in {{WS}}/orig` is a deleted file), read each changed source file with
`diff -u {{WS}}/orig/<path> <path>`, and review it as someone who knows only the task:
- Re-walk the path inventory and variant matrix against the patched code. Try one more variant and one more path.
- Check both outcomes of every changed condition, every caller of a changed helper, and every error path.
- Look for later bypasses: values re-read, re-decoded, or re-resolved after validation; cached or derived
  authority; redirects and callbacks.
- Fix confirmed problems only, then repeat step 5.
- Act on findings the review forwards as the rules' review section says: minimally, and re-run the attack checks
  after.

## 8. Finish
Remove scratch files and debug output from the repository. Do not commit or `git add`, and never modify or delete
`{{WS}}/orig`. If the task asks for a patch or diff file, regenerate it as your last action. Summarize the paths and
variants covered, the checks run, and anything left unverified.

## Class guidance
Read only the file for the weakness you are fixing (paths are relative to this skill):
- `classes/path-file.md`: path traversal, links, archives, uploads (CWE-22, 23, 36, 59, 73, 434)
- `classes/injection.md`: command, argument, SQL, NoSQL, LDAP, XPath, header/CRLF, expression (CWE-77, 78, 88, 89, 90, 93, 113, 643, 917, 943)
- `classes/web-output.md`: XSS, output encoding, template and code injection, CSRF (CWE-79, 80, 94, 95, 116, 352, 1336)
- `classes/ssrf-redirect.md`: SSRF, open redirect, external references, cross-origin data (CWE-200, 441, 601, 610, 918)
- `classes/deserialization.md`: unsafe deserialization, reflection, dynamic code loading (CWE-470, 502, 913)
- `classes/xml.md`: XXE, entity expansion (CWE-611, 776, 827)
- `classes/access-control.md`: authorization, IDOR, missing authentication, privilege (CWE-269, 284, 285, 306, 639, 862, 863)
- `classes/authn-session.md`: authentication, sessions, tokens, brute force (CWE-287, 290, 294, 307, 384, 613, 620, 640)
- `classes/crypto-integrity.md`: TLS and certificates, weak crypto or randomness, signatures, timing (CWE-208, 295, 297, 327, 330, 345, 347)
- `classes/resource-dos.md`: limits, ReDoS, recursion, decompression (CWE-400, 409, 674, 770, 789, 834, 1333)
- `classes/memory-integer.md`: bounds, integer overflow, NULL, use-after-free (CWE-119, 125, 129, 131, 190, 191, 415, 416, 476, 787)
- `classes/defaults-errors.md`: insecure defaults, failed protection, error handling, validation (CWE-20, 703, 754, 755, 1188, 693)
- `classes/logging-exposure.md`: log injection, secrets in logs or errors, cleartext (CWE-117, 200, 209, 312, 319, 532)
- `classes/object-pollution.md`: prototype pollution, mass assignment (CWE-915, 1321)
- `classes/concurrency.md`: races, TOCTOU (CWE-362, 366, 367)
