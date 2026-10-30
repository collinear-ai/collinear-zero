import json
import re
import unittest
from pathlib import Path

from collinearzero import blindtests, install, regress, render, workspace as w
from tests.helpers import TempWS

JUNIT = """<testsuite>
<testcase classname="t" name="a"/>
<testcase classname="t" name="b">{b}</testcase>
<testcase classname="t" name="c"><skipped/></testcase>
</testsuite>"""


class RegressTest(TempWS):
    def test_junit_compare(self):
        o, p = self.tmp / "o.xml", self.tmp / "p.xml"
        o.write_text(JUNIT.format(b=""))
        p.write_text(JUNIT.format(b="<failure/>"))
        c = regress.compare(regress.junit_results(o), regress.junit_results(p))
        self.assertEqual(c["newly_failing"], ["t::b"])
        self.assertNotIn("t::c", regress.junit_results(o))

    def test_exit_codes(self):
        self.write("ok.flag", "1")
        w.init(self.repo, "t")
        (self.repo / "ok.flag").unlink()
        rc, out = regress.regress(self.repo, "test -f ok.flag")
        self.assertEqual(rc, 1)
        self.assertIn("REGRESSION", out)
        self.assertTrue((w.ws() / "orig" / "ok.flag").exists())       # the snapshot is never touched

    def test_junit_command(self):
        self.write("mode", "pass")
        w.init(self.repo, "t")
        self.write("mode", "fail")
        cmd = ("if [ $(cat mode) = pass ]; then b=''; else b='<failure/>'; fi; "
               "printf '<testsuite><testcase classname=\"t\" name=\"x\">%s</testcase></testsuite>' \"$b\" > {junit}")
        rc, out = regress.regress(self.repo, cmd)
        self.assertEqual(rc, 1)
        self.assertIn("NEWLY FAILING", out)


class BlindTestsTest(TempWS):
    def test_validate_then_run(self):
        self.write("guard.sh", "exit 0\n")                     # the original: no guard
        w.init(self.repo, "t")
        tdir = w.ws() / "bt" / "tests"
        tdir.mkdir(parents=True)
        (tdir / "exploit_guard.sh").write_text("grep -q blocked guard.sh && exit 0; echo 'VIOLATION: no guard'; exit 1\n")
        (tdir / "legit_runs.sh").write_text("bash guard.sh >/dev/null; exit 0\n")
        (tdir / "legit_wrong.sh").write_text("exit 1\n")       # fails on the original: dropped
        self.write("guard.sh", "# blocked\nexit 0\n")
        rc, out = blindtests.tests(self.repo)
        self.assertEqual(rc, 0, out)
        self.assertIn("legit_wrong.sh: original exit 1 (want 0) -> dropped", out)
        self.assertIn("2 valid test(s), 0 failing", out)


class InstallTest(TempWS):
    def test_project_round_trip(self):
        self.write("AGENTS.md", "# project notes\n")
        for h in ("opencode", "claude", "codex"):
            install.install(h, "project", self.repo, blind_tests=True)
        agents = (self.repo / "AGENTS.md").read_text()
        self.assertEqual(agents.count(install.BEGIN), 1)           # opencode and codex share one block
        self.assertTrue((self.repo / ".opencode/agents/attack-tester.md").exists())
        self.assertFalse((self.repo / ".claude/agents/attack-tester.md").exists())   # never a callable subagent
        self.assertTrue((self.repo / ".claude/agents/blind-test-writer.md").exists())
        hooks = json.loads((self.repo / ".claude/settings.json").read_text())["hooks"]["Stop"]
        self.assertTrue(hooks[0]["hooks"][0]["command"].endswith(" gate"))
        self.assertTrue(install.installed("claude", self.repo))
        for h in ("opencode", "claude", "codex"):
            install.uninstall(h, "project", self.repo)
        self.assertEqual((self.repo / "AGENTS.md").read_text(), "# project notes\n")
        self.assertFalse((self.repo / ".claude/settings.json").exists())
        self.assertFalse(install.installed("claude", self.repo))

    def test_user_scope_config_dirs(self):
        import os
        os.environ.update(XDG_CONFIG_HOME=str(self.tmp / "xdg"), CODEX_HOME=str(self.tmp / "codex"),
                          CLAUDE_CONFIG_DIR=str(self.tmp / "claude"))
        for h in ("opencode", "claude", "codex"):
            install.install(h, "user", self.repo)
        self.assertTrue((self.tmp / "xdg/opencode/AGENTS.md").exists())
        self.assertTrue((self.tmp / "claude/CLAUDE.md").exists())
        self.assertTrue((self.tmp / "codex/AGENTS.md").exists())
        self.assertFalse((self.tmp / "home/.claude").exists())


class RenderTest(unittest.TestCase):
    # Model pins, plus the experiment labels from the untracked .lint-labels if present (as in scripts/lint.py).
    _labels = Path(__file__).resolve().parent.parent / ".lint-labels"
    LABELS = re.compile("|".join([r"\bmodel:\s*\S+/", *(
        [ln.strip() for ln in _labels.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        if _labels.exists() else [])]), re.I)

    def test_rendered_texts(self):
        root = Path("/cfg")
        for h in render.HARNESSES:
            for blind in (False, True):
                text = render.rules(h, root, blind)
                self.assertNotIn("{{", text)
                self.assertIsNone(self.LABELS.search(text), h)
                self.assertEqual("Independent tests" in text, blind and h != "codex")
            for src, _ in render.skill_files():
                self.assertNotIn("{{", render.skill_text(src, h, root))
        self.assertIn("mode: primary", render.opencode_agent("attack-tester", root))
        self.assertIn("mode: subagent", render.opencode_agent("blind-test-writer", root))
        self.assertNotIn("{{", render.codex_tester_prompt(root))


if __name__ == "__main__":
    unittest.main()
