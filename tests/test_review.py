import json
import unittest

from collinearzero import cli, gate, review, triage as tr, workspace as w
from collinearzero.harnesses import Harness, Session
from tests.helpers import TempWS

REPORT = ('<report>\n<bypass id="B1" requirement="1" orig="same">\n<case>../x</case>\n<observed>read</observed>\n'
          '<expected>refused</expected>\n</bypass>\n<checked requirement="2" status="not_run">no time</checked>\n</report>\n')
EMPTY = '<report>\n<checked requirement="1" status="pass">ok</checked>\n</report>\n'
OK = '<recheck verdict="OK">\n<run result="pass">a</run>\n</recheck>'
BROKEN = '<recheck verdict="BROKEN">\n<run result="fail">nested | observed 400</run>\n</recheck>'


class FakeHarness(Harness):
    """Scripted sessions: `tester_texts` are returned in order; the fix round edits app.py."""

    def __init__(self, repo, tester_texts=(), fix_text="v-fixed\n", tester_edits=False):
        super().__init__(repo)
        self.calls = []
        self.tester_texts = list(tester_texts)
        self.fix_text = fix_text
        self.tester_edits = tester_edits

    def agent(self, prompt, cap_s, sid=None, tag="agent"):
        self.calls.append(("agent", sid, prompt[:40], cap_s))
        (self.repo / "app.py").write_text(self.fix_text)
        return Session(sid or "agent-1", "done", 0, False, 1.0)

    def tester(self, prompt, cap_s, sid=None, tag="review"):
        self.calls.append(("tester", sid, prompt[:40], cap_s))
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
        h = FakeHarness(self.repo, [REPORT, OK])
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
        h = FakeHarness(self.repo, [REPORT, BROKEN])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["recheck"]["verdict"], "BROKEN")
        self.assertEqual((self.repo / "app.py").read_text(), "v-patched\n")   # back to the checkpoint

    def test_nothing_forwarded(self):
        h = FakeHarness(self.repo, [EMPTY])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["stop"], "nothing_forwarded")
        self.assertEqual([c[0] for c in h.calls], ["tester"])

    def test_report_now_turn(self):
        h = FakeHarness(self.repo, ["still testing...", REPORT, OK])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["retries"], ["report_now"])
        self.assertTrue(info["forwarded"])

    def test_tester_edits_are_put_back(self):
        h = FakeHarness(self.repo, [EMPTY], tester_edits=True)
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

    def test_fix_round_leaves_time_for_the_recheck(self):
        import time
        h = FakeHarness(self.repo, [REPORT, OK])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(time.time() + 1000))
        self.assertLessEqual(h.calls[1][3], 700)
        self.assertEqual(info["recheck"]["verdict"], "OK")

    def test_reserve_never_skips_the_fix_round(self):
        import time
        h = FakeHarness(self.repo, [REPORT, OK])
        info = {"forward": "findings"}
        review.fix_phase(h, "agent-1", info, review.Clock(time.time() + 330))
        self.assertTrue(info.get("forwarded"))                 # too little for both: the fix round still runs

    def test_patched_file_is_no_backing(self):
        rep = '<report>\n<regression id="R1" orig="differs"><backing>app.py</backing></regression>\n</report>\n'
        h = FakeHarness(self.repo, [rep])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual(info["stop"], "nothing_forwarded")
        self.assertEqual([d["id"] for d in info["dropped"]], ["R1"])

    def test_header_report_forwards_nothing(self):
        h = FakeHarness(self.repo, ["BYPASSES:\n[B1] requirement 1 | orig: same\n", "BYPASSES:\nstill none\n"])
        info = review.review_loop(h, h, self.repo, "agent-1", review.Clock(None))
        self.assertEqual((info["retries"], info["stop"]), (["report_now"], "no_report"))
        self.assertEqual([c[0] for c in h.calls], ["tester", "tester"])

    def test_manual_review_without_session(self):
        h = FakeHarness(self.repo, [REPORT])
        info = review.review_loop(h, h, self.repo, None, review.Clock(None))
        self.assertIn("FINDINGS TO ACT ON", info["forward"])
        self.assertEqual(w.load_state()["stage"], "fix")


class TriageCommandTest(TempWS):
    def test_cli_excludes_patched_files(self):
        import contextlib
        import io
        self.write("app.py", "v1\n")
        w.init(self.repo, "t")
        self.write("app.py", "v2\n")
        rep = self.write("../report.md", '<report><regression><backing>app.py</backing></regression></report>\n',
                         root=self.repo)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--repo", str(self.repo), "triage", str(rep)])
        self.assertEqual(out.getvalue().strip(), "nothing forwarded")


class RecheckCommandTest(TempWS):
    def setUp(self):
        super().setUp()
        self.write("app.py", "v-orig\n")
        w.init(self.repo, "task\n")
        self.write("app.py", "v-patched\n")
        self._get = cli.harnesses.get

    def tearDown(self):
        cli.harnesses.get = self._get
        super().tearDown()

    def recheck(self, fake):
        cli.harnesses.get = lambda *a, **k: fake
        cli.main(["--repo", str(self.repo), "recheck"])

    def test_refused_without_a_fix_round(self):
        fake = FakeHarness(self.repo, [EMPTY, BROKEN])
        review.review_loop(fake, fake, self.repo, None, review.Clock(None))     # nothing forwarded: stage done
        self.write("app.py", "v-later-work\n")
        with self.assertRaises(SystemExit):
            self.recheck(fake)
        self.assertEqual((self.repo / "app.py").read_text(), "v-later-work\n")  # not reverted
        self.assertEqual([c[0] for c in fake.calls], ["tester"])

    def test_after_forwarded_review(self):
        fake = FakeHarness(self.repo, [REPORT, BROKEN])
        review.review_loop(fake, fake, self.repo, None, review.Clock(None))     # forwarded: stage fix
        self.write("app.py", "v-overfixed\n")
        self.recheck(fake)
        self.assertEqual((self.repo / "app.py").read_text(), "v-patched\n")    # the fix round is reverted
        self.assertEqual(w.load_state()["stage"], "done")
        with self.assertRaises(SystemExit):                                     # and only once
            self.recheck(fake)


class GateTest(TempWS):
    def setUp(self):
        super().setUp()
        self.write("app.py", "v-orig\n")
        w.init(self.repo, "task\n")
        self.write("app.py", "v-patched\n")
        self.fake = FakeHarness(self.repo, [REPORT, BROKEN])
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

    def test_stop_before_any_edit_passes(self):
        self.write("app.py", "v-orig\n")                         # the agent asked a question before editing
        self.assertEqual(gate.gate(self.event()), {})
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(w.load_state()["stage"], "agent")
        self.write("app.py", "v-patched\n")
        self.assertEqual(gate.gate(self.event())["decision"], "block")
        self.assertLessEqual(self.fake.calls[0][3], gate.REVIEW_BUDGET - 300)   # inside the hook's timeout

    def test_inactive(self):
        import os
        os.environ["CZ_GATE"] = "off"
        self.assertEqual(gate.gate(self.event()), {})
        os.environ.pop("CZ_GATE")
        other = json.dumps({"cwd": str(self.tmp)})
        self.assertEqual(gate.gate(other), {})


if __name__ == "__main__":
    unittest.main()
