import json
import unittest

from collinearzero import harnesses as hz
from collinearzero.triage import TESTER_MSG
from tests.helpers import TempWS


class CommandTest(TempWS):
    """The command lines each harness builds, and how their output is read (no real CLI is started)."""

    def setUp(self):
        super().setUp()
        self.calls = []
        self.out = ""
        self._orig = hz.run_capped

        def fake(cmd, stdin_text, cwd, cap_s, log, env=None):
            self.calls.append({"cmd": cmd, "stdin": stdin_text, "cap": cap_s, "env": env or {}})
            return 0, self.out, False, 0.1
        hz.run_capped = fake

    def tearDown(self):
        hz.run_capped = self._orig
        super().tearDown()

    def test_opencode(self):
        self.out = "\n".join(json.dumps(e) for e in [
            {"type": "step_start", "sessionID": "ses_1", "part": {}},
            {"type": "text", "sessionID": "ses_1", "part": {"type": "text", "text": "BYPASSES:\nnone found"}}])
        h = hz.get("opencode", self.repo, "prov/model")
        s = h.agent("fix it", 2700)
        c = self.calls[-1]
        self.assertTrue(c["cmd"][1].endswith("opencode-continue.sh"))
        self.assertIn("-m", c["cmd"])
        self.assertEqual(c["env"]["OPENCODE_CONTINUE_ON_LENGTH"], "2")
        self.assertEqual((s.sid, s.text), ("ses_1", "BYPASSES:\nnone found"))
        h.tester(TESTER_MSG, 1500, sid="ses_1")
        c = self.calls[-1]
        self.assertEqual(c["cmd"][:2], ["opencode", "run"])
        self.assertIn("attack-tester", c["cmd"])
        self.assertEqual(c["cmd"][c["cmd"].index("-s") + 1], "ses_1")

    def test_claude(self):
        self.out = json.dumps({"type": "result", "result": "RECHECK: OK", "session_id": "abc"})
        h = hz.get("claude", self.repo)
        s = h.tester(TESTER_MSG, 1500)
        c = self.calls[-1]["cmd"]
        self.assertEqual(c[:4], ["claude", "-p", "--output-format", "json"])
        agents = json.loads(c[c.index("--agents") + 1])
        self.assertIn("attack-tester", agents)
        self.assertNotIn("{{", agents["attack-tester"]["prompt"])
        self.assertIn("Edit", c[c.index("--disallowedTools"):])
        self.assertEqual((s.sid, s.text), ("abc", "RECHECK: OK"))
        h.agent("fix", 100, sid="abc")
        c = self.calls[-1]["cmd"]
        self.assertEqual(c[c.index("--resume") + 1], "abc")

    def test_codex(self):
        self.out = "\n".join(json.dumps(e) for e in [
            {"type": "thread.started", "thread_id": "th_9"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "BYPASSES:\nnone found"}}])
        h = hz.get("codex", self.repo)
        s = h.tester(TESTER_MSG, 1500)
        c = self.calls[-1]
        self.assertEqual(c["cmd"][:2], ["codex", "exec"])
        self.assertTrue(c["stdin"].endswith(TESTER_MSG) and len(c["stdin"]) > 1000)   # the tester's instructions lead
        self.assertEqual((s.sid, s.text), ("th_9", "BYPASSES:\nnone found"))
        h.agent("fix", 100, sid="th_9")
        c = self.calls[-1]["cmd"]
        self.assertEqual(c[-3:], ["resume", "th_9", "-"])


class RunCappedTest(TempWS):
    def test_kill_on_cap(self):
        rc, out, timed_out, secs = hz.run_capped(["bash", "-c", "echo start; sleep 30"], "", self.repo, 1,
                                                 self.tmp / "log")
        self.assertTrue(timed_out)
        self.assertIn("start", out)
        self.assertLess(secs, 20)

    def test_gate_off_in_sessions(self):
        rc, out, _, _ = hz.run_capped(["bash", "-c", "echo $CZ_GATE"], "", self.repo, 10, self.tmp / "log")
        self.assertEqual(out.strip(), "off")


if __name__ == "__main__":
    unittest.main()
