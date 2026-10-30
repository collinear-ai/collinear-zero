import unittest

from collinearzero import triage as tr

REPORT = """Requirements (numbered) ...

<report>
<bypass id="B1" requirement="2" orig="same">
<case>name=%2e%2e/etc/passwd</case>
<entry_point>GET /download</entry_point>
<observed>200 with file contents</observed>
<expected>400</expected>
</bypass>
<regression id="R1" orig="differs">
<backing>tests/test_download.py</backing>
<case>name=reports/q1.pdf</case>
<observed>400</observed>
<expected>200</expected>
<quote>test_nested_download</quote>
</regression>
<regression id="R2" orig="differs">
<backing>none</backing>
<case>name=a..b.txt</case>
</regression>
<regression id="R3" orig="differs">
<backing>docs/missing.md</backing>
<case>name=x</case>
</regression>
<checked requirement="1" status="pass">name=../x -> 400</checked>
<checked requirement="3" status="not_run">needs a running server</checked>
<note>error message text changed</note>
</report>
"""


class TriageTest(unittest.TestCase):
    def test_structured(self):
        t = tr.triage(REPORT, lambda p: p == "tests/test_download.py")
        self.assertEqual([k["id"] for k in t["kept"]], ["B1", "R1"])
        self.assertEqual({d["id"]: d["why"] for d in t["dropped"]},
                         {"R2": "no repository backing", "R3": "no existing repository path as backing"})
        self.assertEqual(t["not_run"], ["requirement 3: not run (needs a running server)"])
        body = tr.forward_body(t)
        self.assertIn('<bypass id="B1"', body)
        self.assertIn('<regression id="R1"', body)
        self.assertNotIn('"R2"', body)
        self.assertNotIn("error message", body)
        self.assertIn("REQUIREMENTS THE TESTER DID NOT RUN", body)

    def test_no_report(self):
        t = tr.triage("I could not finish.", lambda p: True)
        self.assertEqual(t["stop"], "no_report")
        self.assertEqual(tr.forward_body(t), "")

    def test_headers_are_no_report(self):
        rep = "BYPASSES:\n[B1] requirement 1 | orig: same\ninput: ../x\n\nCHECKED:\n- requirement 2: not run\n"
        t = tr.triage(rep, lambda p: True)
        self.assertEqual((t.get("stop"), t["kept"], t["not_run"]), ("no_report", [], []))

    def test_empty_report(self):
        for rep in ("<report>\n<checked requirement=\"1\" status=\"pass\">ok</checked>\n</report>", "<report></report>",
                    "<report/>"):
            t = tr.triage(rep, lambda p: True)
            self.assertIsNone(t.get("stop"), rep)
            self.assertEqual(tr.forward_body(t), "", rep)

    def test_payloads_are_kept_verbatim(self):
        case = "<script>alert(1)</script>&x=<input onfocus=alert(1) autofocus>"
        t = tr.triage(f"<report>\n<bypass requirement=\"1\">\n<case>{case}</case>\n</bypass>\n</report>", lambda p: True)
        self.assertEqual([k["id"] for k in t["kept"]], ["B1"])
        self.assertIn(case, t["kept"][0]["text"])

    def test_truncated_report(self):
        rep = ("<report>\n<bypass id=\"B1\" requirement=\"1\">\n<case>../x</case>\n"
               "<checked requirement=\"2\" status=\"not_run\">no server")
        t = tr.triage(rep, lambda p: True)
        self.assertEqual([k["id"] for k in t["kept"]], ["B1"])
        self.assertNotIn("checked", t["kept"][0]["text"])             # the open bypass ends at the next element
        self.assertEqual(t["not_run"], ["requirement 2: not run (no server)"])

    def test_ids_missing_or_duplicated(self):
        rep = "<report>" + "".join(f"<bypass {a}><case>{i}</case></bypass>" for i, a in
                                   enumerate(('id="B2"', "", 'id="B5"', 'id="B5"', 'id="X"'))) + "</report>"
        self.assertEqual([k["id"] for k in tr.triage(rep, lambda p: True)["kept"]], ["B2", "B1", "B3", "B4", "B5"])

    def test_backing_paths(self):
        rep = ("<report><regression><backing>`docs/a.md:12`</backing><backing>tests/t.py:3-9</backing>"
               "<case>x</case></regression><regression backing=\"README, tests/t.py\"><case>y</case></regression>"
               "</report>")
        t = tr.triage(rep, lambda p: p == "tests/t.py")
        self.assertEqual([(k["id"], k["paths_found"]) for k in t["kept"]], [("R1", ["tests/t.py"]), ("R2", ["tests/t.py"])])
        self.assertEqual(t["kept"][0]["backing"], "docs/a.md, tests/t.py")

    def test_recheck_verdict(self):
        v = tr.recheck_verdict('<recheck verdict="BROKEN">\n<run result="pass">a</run>\n'
                               '<run result="fail" orig="pass">b | observed 400</run>\n</recheck>')
        self.assertEqual(v["verdict"], "BROKEN")
        self.assertEqual(v["failed"], ["b | observed 400"])
        self.assertEqual(tr.recheck_verdict('**<recheck verdict="OK"></recheck>**')["verdict"], "OK")
        self.assertIsNone(tr.recheck_verdict("RECHECK: OK")["verdict"])

    def test_recheck_failed_run_overrides_ok(self):
        v = tr.recheck_verdict('<recheck verdict="OK"><run result="fail">b | observed 400</run></recheck>')
        self.assertEqual(v["verdict"], "BROKEN")
        self.assertIn("overridden", v)
        v = tr.recheck_verdict('<recheck verdict="OK"><run result="fail" orig="fail">b | observed 404</run></recheck>')
        self.assertEqual((v["verdict"], v["failed"]), ("OK", []))   # it failed on the original too


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
                (root / "fixtures").mkdir()
            (repo / "new").mkdir()
            (repo / "new/t.py").write_text("")
            ok = tr.repo_path_checker(repo, frozenset({"app.py", "tests/test_app.py", "new"}), orig)
            self.assertFalse(ok("app.py"))                     # the patched source itself is no backing
            self.assertTrue(ok("tests/test_app.py"))           # a test the patch edited is: it existed before
            self.assertFalse(ok("new/t.py"))                   # a file the patch added is not
            self.assertTrue(ok("README"))
            self.assertFalse(ok("fixtures"))                      # a directory is no backing: cite the file
            rep = ("<report><regression><backing>README</backing></regression>"
                   "<regression><backing>app.py</backing></regression>"
                   "<regression><backing>fixtures</backing></regression></report>")
            t = tr.triage(rep, ok)
            self.assertEqual([k["id"] for k in t["kept"]], ["R1"])
            self.assertEqual([x["id"] for x in t["dropped"]], ["R2", "R3"])


if __name__ == "__main__":
    unittest.main()
