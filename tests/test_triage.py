import unittest

from collinearzero import triage as tr

REPORT = """Requirements (numbered) ...

BYPASSES:
[B1] requirement 2 | orig: same
input: name=%2e%2e/etc/passwd via GET /download -> 200 with file contents; expected 400

REGRESSIONS:
[R1] orig: differs | backing: tests/test_download.py
input: name=reports/q1.pdf -> 400; expected 200 ("test_nested_download")
[R2] orig: differs | backing: none
input: name=a..b.txt -> 400; expected 200
[R3] orig: differs | backing: docs/missing.md
input: name=x -> 400

CHECKED:
- requirement 1: name=../x -> 400
- requirement 3: not run (needs a running server)

NOTES:
- error message text changed
"""


class TriageTest(unittest.TestCase):
    def test_structured(self):
        t = tr.triage(REPORT, lambda p: p == "tests/test_download.py")
        self.assertEqual([k["id"] for k in t["kept"]], ["B1", "R1"])
        self.assertEqual({d["id"]: d["why"] for d in t["dropped"]},
                         {"R2": "no repository backing", "R3": "no existing repository path as backing"})
        self.assertEqual(t["not_run"], ["- requirement 3: not run (needs a running server)"])
        body = tr.forward_body(t)
        self.assertIn("[B1]", body)
        self.assertIn("[R1]", body)
        self.assertNotIn("[R2]", body)
        self.assertNotIn("error message", body)
        self.assertIn("REQUIREMENTS THE TESTER DID NOT RUN", body)

    def test_no_report(self):
        t = tr.triage("I could not finish.", lambda p: True)
        self.assertEqual(t["stop"], "no_report")
        self.assertEqual(tr.forward_body(t), "")

    def test_unstructured_fallback(self):
        rep = "BYPASSES:\nthe %2e%2e form still escapes the root\n\nREGRESSIONS:\nnested names fail\n\nCHECKED:\nnone\n"
        t = tr.triage(rep, lambda p: True)
        self.assertTrue(t["fallback"])
        self.assertEqual(t["kept"][0]["id"], "BYPASSES")
        self.assertEqual(t["dropped"][0]["why"], "unstructured report")

    def test_none_found(self):
        rep = "**BYPASSES:** none found\n\n**REGRESSIONS:** none found\n\n**CHECKED:**\n- requirement 1 ok\n\nNOTES: none\n"
        t = tr.triage(rep, lambda p: True)
        self.assertEqual(t["kept"], [])
        self.assertIsNone(t.get("stop"))
        self.assertEqual(tr.forward_body(t), "")

    def test_recheck_verdict(self):
        v = tr.recheck_verdict("PASS a\nFAIL b | observed 400\nRECHECK: BROKEN")
        self.assertEqual(v["verdict"], "BROKEN")
        self.assertEqual(v["failed"], ["FAIL b | observed 400"])
        self.assertEqual(tr.recheck_verdict("**RECHECK: OK**")["verdict"], "OK")
        self.assertIsNone(tr.recheck_verdict("no verdict")["verdict"])

    def test_empty_sections_in_other_words(self):
        for empty in ("(none)", "N/A", "I found no bypasses.", "No bypasses found.", "There were no bypasses.",
                      "_None._", "Did not find any."):
            t = tr.triage(f"BYPASSES:\n{empty}\n\nREGRESSIONS:\n{empty}\n\nCHECKED:\n- 1 ok\n", lambda p: True)
            self.assertEqual((t["kept"], t["dropped"]), ([], []), empty)

    def test_prose_is_not_a_header(self):
        rep = "Checked the diff first.\nBypasses were hard to find.\n\n" + REPORT
        t = tr.triage(rep, lambda p: p == "tests/test_download.py")
        self.assertEqual([k["id"] for k in t["kept"]], ["B1", "R1"])
        self.assertFalse(t["fallback"])
        self.assertEqual(t["not_run"], ["- requirement 3: not run (needs a running server)"])

    def test_headers_with_counts_dashes_and_crlf(self):
        item = "[B1] requirement 1 | orig: same\ninput: ../x -> read\n"
        for hdr in ("## BYPASSES (1)", "BYPASSES (1):", "## BYPASSES - 1 found", "BYPASSES"):
            for nl in ("\n", "\r\n"):
                rep = (hdr + "\n" + item + "\n## CHECKED (3 runs)\n- req 2 not run\n").replace("\n", nl)
                t = tr.triage(rep, lambda p: True)
                self.assertEqual([k["id"] for k in t["kept"]], ["B1"], repr(hdr + nl))
                self.assertEqual(len(t["not_run"]), 1, repr(hdr + nl))
        t = tr.triage("BYPASSES (0):\nnone\n\nREGRESSIONS (0):\nnone\n", lambda p: True)
        self.assertEqual((t["kept"], t["dropped"]), ([], []))

    def test_title_case_headings(self):
        item = "[B1] requirement 2 | orig: same\ninput: ../x -> read\n"
        for hdr in ("## Bypasses Found", "## Bypasses found", "**Bypasses found:**", "## Bypasses 1", "Bypasses.",
                    "1. BYPASSES:"):
            t = tr.triage(f"{hdr}\n{item}\n### Checked requirements\n- req 3 not run\n", lambda p: True)
            self.assertEqual([k["id"] for k in t["kept"]], ["B1"], hdr)
            self.assertEqual(len(t["not_run"]), 1, hdr)

    def test_heading_rest_of_line(self):
        t = tr.triage("## Bypasses found\nnone\n\n## Regressions found\nnone\n", lambda p: True)
        self.assertEqual((t["kept"], t["fallback"]), ([], False))
        t = tr.triage("**BYPASSES:** the %2e%2e form still escapes the root\n", lambda p: True)
        self.assertEqual([k["id"] for k in t["kept"]], ["BYPASSES"])

    def test_nothing_found_in_other_words(self):
        for empty in ("No bypasses were found.", "none found. All 14 attack inputs were rejected (see CHECKED).",
                      "None found; every attack in CHECKED was blocked.", "none found — the patch blocks every variant",
                      "None found ✅", "No bypasses found for requirements 1-5."):
            t = tr.triage(f"BYPASSES:\n{empty}\n\nREGRESSIONS:\nnone\n", lambda p: True)
            self.assertEqual((t["kept"], t["fallback"]), ([], False), empty)

    def test_bypass_prose_is_not_empty(self):
        for real in ("Found no check on symlinks: ln -s /etc/passwd x then GET /x returns the file",
                     "There are no checks on URL-encoded input; GET /files/%2e%2e%2fetc/passwd returns 200",
                     "I could not find any guard on the second entry point: cli read ../x escapes",
                     "- Did not find validation in the batch API; POST /batch with ../ writes outside",
                     "No regression test covers it, but ..%2f reaches /etc/passwd",
                     "None of the encodings are blocked: %2e%2e reaches /etc/passwd",
                     "Nothing blocks a symlinked upload: ln -s /etc x; PUT /x/passwd writes outside"):
            t = tr.triage(f"BYPASSES:\n{real}\n\nCHECKED:\n- 1 ok\n", lambda p: True)
            self.assertEqual([k["id"] for k in t["kept"]], ["BYPASSES"], real)

    def test_recheck_last_verdict_and_fail_lines(self):
        v = tr.recheck_verdict("I will end with RECHECK: OK if all pass.\nFAIL b | observed 400\nRECHECK: BROKEN")
        self.assertEqual(v["verdict"], "BROKEN")
        v = tr.recheck_verdict("PASS a\nFAIL b | observed 400\nRECHECK: OK")
        self.assertEqual(v["verdict"], "BROKEN")
        self.assertIn("overridden", v)
        for benign in ("FAIL: test_legacy (t.T) -- also fails on orig", "- FAIL count: 0",
                       "FAIL b | observed 400 (same as orig, pre-existing)", "FAIL x | observed 404 (orig: same)",
                       "FAIL x | observed 404, unchanged from the original", "FAIL x | observed 404 (same on orig)"):
            self.assertEqual(tr.recheck_verdict(f"PASS a\n{benign}\nRECHECK: OK")["verdict"], "OK", benign)


class PathCheckerTest(unittest.TestCase):
    def test_inside_only(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "tests").mkdir()
            (Path(d) / "tests" / "t.py").write_text("")
            ok = tr.repo_path_checker(d)
            self.assertTrue(ok("tests/t.py"))
            self.assertTrue(ok("./tests/t.py"))
            self.assertTrue(ok(str(Path(d) / "tests" / "t.py")))
            self.assertFalse(ok("../etc/passwd"))
            self.assertFalse(ok("/etc/passwd"))
            self.assertFalse(ok("tests/none.py"))

    def test_patched_paths_and_plain_names(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            repo, orig = Path(d) / "repo", Path(d) / "orig"
            for root in (repo, orig):
                for f in ("app.py", "README", "tests/test_app.py"):
                    (root / f).parent.mkdir(parents=True, exist_ok=True)
                    (root / f).write_text("")
                (root / "Tests").mkdir()
            (repo / "new").mkdir()
            (repo / "new/t.py").write_text("")
            ok = tr.repo_path_checker(repo, frozenset({"app.py", "tests/test_app.py", "new"}), orig)
            self.assertFalse(ok("app.py"))                     # the patched source itself is no backing
            self.assertTrue(ok("tests/test_app.py"))           # a test the patch edited is: it existed before
            self.assertFalse(ok("new/t.py"))                   # a file the patch added is not
            self.assertTrue(ok("README"))
            self.assertFalse(ok("Tests"))                      # a directory is no backing: cite the file
            rep = ("BYPASSES:\nnone\n\nREGRESSIONS:\n[R1] orig: differs | backing: README\n"
                   "[R2] orig: differs | backing: app.py\n[R3] orig: differs | backing: Tests show it\n")
            t = tr.triage(rep, ok)
            self.assertEqual([k["id"] for k in t["kept"]], ["R1"])
            self.assertEqual([x["id"] for x in t["dropped"]], ["R2", "R3"])


if __name__ == "__main__":
    unittest.main()
