"""Report shapes testers actually write, and what triage must make of each: headers in every common markdown form, the
ways testers say a section is empty, bypass descriptions that start with "None"/"No"/"Nothing", and recheck lines."""
import unittest

from collinearzero import triage as tr

B1 = "[B1] requirement 1 | orig: same\ninput: ../x -> read\n"
# (name, report, expected kept ids, expected not_run count)
C = []
for h in ("BYPASSES:", "## BYPASSES", "**BYPASSES:**", "### Bypasses", "## BYPASSES (1)", "BYPASSES (1):",
          "## BYPASSES - 1 found", "## Bypasses Found", "**Bypasses found:**", "## Bypasses 1", "Bypasses.", "- BYPASSES:",
          "`BYPASSES:`", "1. BYPASSES:"):
    for nl in ("\n", "\r\n"):
        C.append((f"hdr {h!r}{' crlf' if nl != chr(10) else ''}", (f"{h}\n{B1}\nCHECKED:\n- req 2: not run\n").replace("\n", nl), ["B1"], 1))
for h in ("## CHECKED (3 runs)", "## Checked runs", "### Checked requirements", "## Checked / passed", "**CHECKED:**"):
    C.append((f"checked {h!r}", f"BYPASSES:\nnone\n\n{h}\n- req 2 not run\n", [], 1))
for e in ("none", "none found", "None.", "(none)", "N/A", "_None._", "I found no bypasses.", "No bypasses found.",
          "There were no bypasses.", "Did not find any.", "No bypasses were found.",
          "none found. All 14 attack inputs were rejected (see CHECKED).", "None found; every attack in CHECKED was blocked.",
          "none found — the patch blocks every variant tried.", "None found ✅", "No bypasses found for requirements 1-5.",
          "Nothing found.", "no new bypasses"):
    C.append((f"empty {e!r}", f"BYPASSES:\n{e}\n\nREGRESSIONS:\nnone\n\nCHECKED:\n- 1 ok\n", [], 0))
for r in ("the %2e%2e form still escapes the root", "Found no check on symlinks: ln -s /etc/passwd x then GET /x returns it",
          "There are no checks on URL-encoded input; GET /files/%2e%2e%2fetc/passwd returns 200",
          "I could not find any guard on the second entry point: cli read ../x escapes",
          "- Did not find validation in the batch API; POST /batch with ../ writes outside",
          "No regression test covers it, but ..%2f reaches /etc/passwd", "None of the encodings are blocked: %2e%2e reaches /etc/passwd",
          "Nothing blocks a symlinked upload: PUT /x/passwd writes outside", "Bypass via double encoding: %252e%252e"):
    C.append((f"real {r[:40]!r}", f"BYPASSES:\n{r}\n\nCHECKED:\n- 1 ok\n", ["BYPASSES"], 0))
C.append(("inline bold real", "**BYPASSES:** the %2e%2e form escapes\n", ["BYPASSES"], 0))
C.append(("prose before", "Checked the diff first.\nBypasses were hard to find.\n\nBYPASSES:\n" + B1 + "\nCHECKED:\n- req 2: not run\n", ["B1"], 1))
R = [("verdict last", "I will end with RECHECK: OK if all pass.\nRECHECK: BROKEN", "BROKEN"),
     ("fail run", "PASS a\nFAIL b | observed 400\nRECHECK: OK", "BROKEN")]
for b in ("FAIL: test_legacy (t.T) -- also fails on orig", "- FAIL count: 0", "FAIL b | observed 400 (same as orig, pre-existing)",
          "FAIL x | observed 404 (orig: same)", "FAIL x | observed 404, unchanged from the original", "FAIL x | observed 404 (same on orig)"):
    R.append((f"benign {b[:30]!r}", f"PASS a\n{b}\nRECHECK: OK", "OK"))


class CorpusTest(unittest.TestCase):
    def test_reports(self):
        for name, rep, kept, nr in C:
            with self.subTest(name):
                t = tr.triage(rep, lambda p: True)
                self.assertEqual(([k["id"] for k in t["kept"]], len(t["not_run"])), (kept, nr))

    def test_recheck_lines(self):
        for name, txt, want in R:
            with self.subTest(name):
                self.assertEqual(tr.recheck_verdict(txt)["verdict"], want)


if __name__ == "__main__":
    unittest.main()
