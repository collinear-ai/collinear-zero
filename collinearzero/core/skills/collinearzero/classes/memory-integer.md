# Memory safety and integer errors (CWE-119, 125, 129, 131, 190, 191, 415, 416, 476, 787)

**Tuple.** Attacker-controlled lengths, indexes, counts, or error paths lead to out-of-bounds access,
arithmetic overflow, NULL dereference, or use of freed memory.

## Complete fix
- **Bounds:** check every index or length against the actual buffer size before each read or write, including
  loop bounds and off-by-one cases (`<` vs `<=`). Use sized APIs (`snprintf`, `memcpy` with checked lengths,
  `strnlen`), never unbounded copies.
- **Integer overflow:** validate before computing sizes: `a + b` and `a * b` can wrap, so check against the
  maximum first or use checked arithmetic (`__builtin_mul_overflow`, `checked_add`, `Math.addExact`). Watch
  signed/unsigned mixing and narrowing casts.
- **Reinterpreted bytes:** pointer, offset, index, and length fields read from bytes another party can write
  (shared memory, mapped files, packed buffers, unions, messages) are attacker-chosen. Validate them before every
  use, not once at load; if a field cannot be validated, remove the dereference.
- **Error paths:** on every failure branch, do not dereference or advance pointers that were never populated.
  Initialize outputs, check return values, and return early.
- **Lifetime:** NULL a pointer after `free`, avoid double free and use-after-free across error paths and callbacks,
  and match allocation to ownership.
- **The pattern often repeats:** grep for the same idiom across the module (same macro, helper, or parse loop)
  and fix every instance that is reachable from input.
- **Rust:** audit `unsafe` blocks, `get_unchecked`, and length arithmetic. Use `checked_*` and `saturating_*`.
  Treat a panic on attacker input as denial of service.
- **Go and Java:** check slice and array indexes from input; prevent `int` overflow before `make` or `new`;
  avoid nil dereferences on error returns.
- **Validate:** compile with warnings, and build the project's own tests with ASan/UBSan if available; every
  sanitizer report is a finding. Feed the crashing or boundary inputs: 0, max, max+1, negative, and truncated data.
  Code that matches an upstream release is not proof it is safe.

## Incomplete fixes
- Checking one copy while the sibling read path is unchecked.
- A check placed after the arithmetic that overflows.
- Fixing the reported crash but not the other branch with the same pattern.
