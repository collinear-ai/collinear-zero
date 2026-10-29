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


if __name__ == "__main__":
    unittest.main()
