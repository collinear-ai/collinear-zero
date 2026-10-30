from collinearzero import cli, install, run, workspace as w
from tests.helpers import TempWS
from tests.test_review import FakeHarness


class RunTest(TempWS):
    def setUp(self):
        super().setUp()
        self.write("app.py", "v-orig\n")
        install.install("claude", "project", self.repo)
        self.fake = FakeHarness(self.repo, ["BYPASSES:\nnone found\n"])
        self._get = run.harnesses.get
        run.harnesses.get = lambda *a, **k: self.fake

    def tearDown(self):
        run.harnesses.get = self._get
        super().tearDown()

    def test_workspace_named_at_install(self):
        run.run("task\n", self.repo, "claude")
        self.assertEqual(self.fake.calls[0][2], "task\n")

    def test_other_workspace_is_named_in_the_prompt(self):
        import os
        os.environ["CZ_WS"] = str(self.tmp / "ws2")
        run.run("task\n", self.repo, "claude")
        self.assertTrue(self.fake.calls[0][2].startswith("Collinear Zero workspace"))
        self.assertIn(str(self.tmp / "ws2"), run.WS_NOTE.format(ws=w.ws()))

    def test_workspace_prefix_is_not_a_match(self):
        import os
        for other in (str(w.ws())[:-1], str(w.ws().parent)):    # a prefix of the installed path
            os.environ["CZ_WS"] = other
            self.assertFalse(install.names_workspace("claude", self.repo), other)

    def test_a_dead_runs_task_does_not_block(self):
        other = self.tmp / "other"
        other.mkdir()
        w.init(other, "t")
        st = w.load_state()
        st["pid"] = 2 ** 22 + 12345                              # no such process: a run that crashed
        w.save_state(st)
        run.run("task\n", self.repo, "claude")
        self.assertEqual(w.load_state()["repo"], str(self.repo.resolve()))

    def test_status_names_another_workspace(self):
        import contextlib, io, os
        os.environ["CZ_WS"] = str(self.tmp / "ws2")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--repo", str(self.repo), "status"])
        self.assertIn(f"workspace for this task is {self.tmp / 'ws2'}", out.getvalue())

    def test_refuses_another_repositorys_active_task(self):
        other = self.tmp / "other"
        other.mkdir()
        w.init(other, "t")
        with self.assertRaises(SystemExit):
            run.run("task\n", self.repo, "claude")
        self.assertEqual(w.load_state()["repo"], str(other.resolve()))
        self.assertEqual(self.fake.calls, [])


class RegressCommandTest(TempWS):
    def test_argv_words_keep_their_quoting(self):
        from collinearzero import regress
        seen = []
        orig = regress.regress
        regress.regress = lambda repo, cmd, timeout: (seen.append(cmd), (0, ""))[1]
        try:
            for argv in (["--", "pytest", "-k", "a and b"], ["--", "pytest -x | tee log"],
                         ["--", "JEST_JUNIT_OUTPUT_FILE={junit}", "npx", "jest", "--reporters=jest-junit"]):
                with self.assertRaises(SystemExit):
                    cli.main(["--repo", str(self.repo), "regress", *argv])
        finally:
            regress.regress = orig
        self.assertEqual(seen, ["pytest -k 'a and b'", "pytest -x | tee log",
                                "JEST_JUNIT_OUTPUT_FILE={junit} npx jest --reporters=jest-junit"])


if __name__ == "__main__":
    import unittest
    unittest.main()
