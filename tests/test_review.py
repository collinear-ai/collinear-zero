import json
import unittest

from collinearzero import gate, review, triage as tr, workspace as w
from collinearzero.harnesses import Harness, Session
from tests.helpers import TempWS

REPORT = ("BYPASSES:\n[B1] requirement 1 | orig: same\ninput: ../x -> read; expected refused\n\n"
          "REGRESSIONS:\nnone found\n\nCHECKED:\n- requirement 2: not run\n\nNOTES:\nnone\n")


class FakeHarness(Harness):
    """Scripted sessions: `tester_texts` are returned in order; the fix round edits app.py."""

    def __init__(self, repo, tester_texts=(), fix_text="v-fixed\n", tester_edits=False):
        super().__init__(repo)
        self.calls = []
        self.tester_texts = list(tester_texts)
        self.fix_text = fix_text
        self.tester_edits = tester_edits

    def agent(self, prompt, cap_s, sid=None, tag="agent"):
        self.calls.append(("agent", sid, prompt[:40]))
        (self.repo / "app.py").write_text(self.fix_text)
        return Session(sid or "agent-1", "done", 0, False, 1.0)

    def tester(self, prompt, cap_s, sid=None, tag="review"):
        self.calls.append(("tester", sid, prompt[:40]))
        if self.tester_edits:
            (self.repo / "app.py").write_text("tester wrote here\n")
        text = self.tester_texts.pop(0) if self.tester_texts else ""
        return Session("tester-1", text, 0, False, 1.0, texts=[text])


class ReviewLoopTest(TempWS):
    def setUp(self):
        super().setUp()
        self.write("app.py", "v-orig\n")
        w.init(self.repo, "Fix the traversal. 1. Names with .. must be refused. 2. Nested names must still work.\n")
        self.write("app.py", "v-patched\n")

    def test_forward_fix_recheck_ok(self):
        h = FakeHarness(self.repo, [REPORT, "PASS a\nRECHECK: OK"])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertTrue(info["forwarded"])
        self.assertEqual(info["recheck"]["verdict"], "OK")
        self.assertEqual((self.repo / "app.py").read_text(), "v-fixed\n")
        self.assertEqual([c[0] for c in h.calls], ["tester", "agent", "tester"])
        self.assertEqual(h.calls[1][1], "agent-1")                 # the fix round continues the agent's session
        self.assertEqual(h.calls[2][1], "tester-1")                # the recheck continues the tester's session
        self.assertEqual(w.load_state()["stage"], "done")
        self.assertTrue((w.ws() / "review.json").exists())

    def test_recheck_broken_reverts(self):
        h = FakeHarness(self.repo, [REPORT, "FAIL nested | observed 400\nRECHECK: BROKEN"])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["recheck"]["verdict"], "BROKEN")
        self.assertEqual((self.repo / "app.py").read_text(), "v-patched\n")   # back to the checkpoint

    def test_nothing_forwarded(self):
        h = FakeHarness(self.repo, ["BYPASSES:\nnone found\nREGRESSIONS:\nnone found\nCHECKED:\n- 1 ok\n"])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["stop"], "nothing_forwarded")
        self.assertEqual([c[0] for c in h.calls], ["tester"])

    def test_report_now_turn(self):
        h = FakeHarness(self.repo, ["still testing...", REPORT, "RECHECK: OK"])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["retries"], ["report_now"])
        self.assertTrue(info["forwarded"])

    def test_tester_edits_are_put_back(self):
        h = FakeHarness(self.repo, ["BYPASSES:\nnone found\n"], tester_edits=True)
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertIn("tester_changed_tree", info)
        self.assertEqual((self.repo / "app.py").read_text(), "v-patched\n")

    def test_too_little_time(self):
        import time
        h = FakeHarness(self.repo, [REPORT])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(time.time() + 100))
        self.assertEqual(info["stop"], "time")
        self.assertEqual(h.calls, [])

    def test_summary_names_a_skipped_recheck(self):
        info = {"kept": [{"id": "B1"}], "dropped": [], "not_run": [], "fix_timed_out": True,
                "recheck": {"verdict": None, "skipped": "time"}}
        s = review.summary(info)
        self.assertIn("fix round timed out", s)
        self.assertIn("recheck skipped (time)", s)

    def test_manual_review_without_session(self):
        h = FakeHarness(self.repo, [REPORT])
        info = review.review_loop(h, h, self.repo, None, review.Clock(None))
        self.assertIn("FINDINGS TO ACT ON", info["forward"])
        self.assertEqual(w.load_state()["stage"], "fix")


class GateTest(TempWS):
    def setUp(self):
        super().setUp()
        self.write("app.py", "v-orig\n")
        w.init(self.repo, "task\n")
        self.write("app.py", "v-patched\n")
        self.fake = FakeHarness(self.repo, [REPORT, "RECHECK: BROKEN"])
        self._get = gate.harnesses.get
        gate.harnesses.get = lambda *a, **k: self.fake

    def tearDown(self):
        gate.harnesses.get = self._get
        super().tearDown()

    def event(self):
        return json.dumps({"hook_event_name": "Stop", "cwd": str(self.repo), "stop_hook_active": False})

    def test_block_then_recheck(self):
        r1 = gate.gate(self.event())
        self.assertEqual(r1["decision"], "block")
        self.assertIn("FINDINGS TO ACT ON", r1["reason"])
        self.write("app.py", "v-overfixed\n")                     # the agent's fix round
        r2 = gate.gate(self.event())
        self.assertIn("recheck BROKEN", r2["systemMessage"])
        self.assertEqual((self.repo / "app.py").read_text(), "v-patched\n")
        self.assertEqual(gate.gate(self.event()), {})           # done: further stops pass

    def test_inactive(self):
        import os
        os.environ["CZ_GATE"] = "off"
        self.assertEqual(gate.gate(self.event()), {})
        os.environ.pop("CZ_GATE")
        other = json.dumps({"cwd": str(self.tmp)})
        self.assertEqual(gate.gate(other), {})


if __name__ == "__main__":
    unittest.main()
