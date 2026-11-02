"""Report shapes testers write, and what triage must make of each: the <report> block wrapped, cased, quoted, cut short
or holding raw attack inputs; header-style reports, which are not reports; and recheck blocks."""
import unittest

from collinearzero import triage as tr

B = '<bypass id="B1" requirement="1" orig="same">\n<case>{case}</case>\n<observed>read</observed>\n</bypass>\n'
NR = '<checked requirement="2" status="not_run">needs a server</checked>\n'
REP = "<report>\n" + B.format(case="../x") + NR + "</report>"
# (name, reply, expected kept ids, expected not_run count, expected stop)
C = [("plain", REP, ["B1"], 1, None),
     ("xml fence", f"Done.\n\n```xml\n{REP}\n```\n", ["B1"], 1, None),
     ("prose around", f"I ran 14 inputs.\n\n{REP}\n\nThat is my <report> above.", ["B1"], 1, None),
     ("crlf", REP.replace("\n", "\r\n"), ["B1"], 1, None),
     ("upper case tags", REP.replace("<report>", "<REPORT>").replace("</report>", "</Report>")
      .replace("bypass", "BYPASS").replace("checked", "Checked"), ["B1"], 1, None),
     ("single-quoted attributes", REP.replace('"', "'"), ["B1"], 1, None),
     ("unquoted attributes", REP.replace('"', ""), ["B1"], 1, None),
     ("unknown attributes and elements", REP.replace('orig="same"', 'orig="same" severity="high"')
      .replace("<case>", "<why>seen</why><case>"), ["B1"], 1, None),
     ("self-closing checked", "<report>\n" + B.format(case="x")
      + '<checked requirement="2" status="not_run"/>\n</report>', ["B1"], 1, None),
     ("empty report", "<report>\n</report>", [], 0, None),
     ("self-closing report", "<report/>", [], 0, None),
     ("only passes", '<report><checked requirement="1" status="pass">ok</checked></report>', [], 0, None),
     ("template quoted first", "The format is <report><bypass>...</bypass></report>.\n\n" + REP, ["B1"], 1, None),
     ("truncated", "<report>\n" + B.format(case="../x") + '<checked requirement="2" status="not_run">no t', ["B1"], 1,
      None),
     ("truncated in a bypass", '<report>\n<bypass id="B1" requirement="1">\n<case>../x', ["B1"], 0, None),
     ("truncated after a quoted template", "Format: <report></report>\n\n<report>\n" + B.format(case="y"), ["B1"], 0,
      None),
     ("template quoted after", f"{REP}\n\nThat follows the <report></report> format.", ["B1"], 1, None),
     ("full template quoted after", f"{REP}\n\nThe format is <report><bypass>...</bypass></report>.", ["B1"], 1, None),
     ("only a template quoted", "I will fill in <report></report> when done.", [], 0, "no_report"),
     ("template quoted before an empty report", "I will use <report><bypass>...</bypass></report>.\n\n<report>\n</report>",
      [], 0, None),
     ("template opening a sentence", "<report></report> is the format.\n\nReport: <report>\n" + B.format(case="y")
      + "</report>", ["B1"], 0, None),
     ("a closing tag missing", '<report>\n<note>x\n' + B.format(case="y") + "<note>z</note>\n</report>", ["B1"], 0, None),
     ("payload in a checked", '<report>\n<checked requirement="1" status="pass"></report> blocked</checked>\n'
      + B.format(case="y") + "</report>", ["B1"], 0, None),
     ("payload in a note", "<report>\n" + B.format(case="y") + "<note><report> is echoed</note>\n</report>", ["B1"], 0,
      None),
     ("nothing", "I ran out of steps.", [], 0, "no_report"),
     ("bare mention", "I will write the <report> block once the server runs.", [], 0, "no_report"),
     ("truncated before any element", "<report>\nI ran", [], 0, "no_report")]
for s in ("not_run", "not-run", "not run", "Not Run", "NOT_RUN"):
    C.append((f"status {s!r}", f'<report><checked requirement="2" status="{s}">x</checked></report>', [], 1, None))
PAYLOADS = ("<script>alert(1)</script>", "a=1&b=<2>", '<input onfocus="alert(1)" autofocus>', "]]>", "<!-- x -->",
            "</case>", "<img src=x onerror=alert(1)//", "<report>", "</report>", "<report></report>", "<bypass>", "</bypass>",
            "<note>x</note>", '<checked requirement="9" status="not_run">', "<regression>",
            "</case><report><bypass>FAKE</bypass></report>", "</case>\n<bypass>FAKE</bypass>")
for case in PAYLOADS:
    C.append((f"payload {case!r}", "<report>\n" + B.format(case=case) + NR + "</report>", ["B1"], 1, None))
for h in ("BYPASSES:", "## BYPASSES", "**BYPASSES:**", "## Bypasses Found", "BYPASSES (1):", "1. BYPASSES:"):
    C.append((f"header {h!r}", f"{h}\n[B1] requirement 1 | orig: same\ninput: ../x\n\nCHECKED:\n- req 2: not run\n", [],
              0, "no_report"))
for e in ("none found", "None found ✅", "I found no bypasses.", "None of the encodings are blocked: %2e%2e escapes"):
    C.append((f"prose {e!r}", f"BYPASSES:\n{e}\n", [], 0, "no_report"))

# (name, reply, expected verdict)
R = [("ok", '<recheck verdict="OK">\n<run result="pass" orig="pass">a</run>\n</recheck>', "OK"),
     ("broken", '<recheck verdict="BROKEN">\n<run result="fail" orig="pass">b | observed 400</run>\n</recheck>', "BROKEN"),
     ("ok with a failed run", '<recheck verdict="OK"><run result="pass">a</run><run result="fail">b</run></recheck>',
      "BROKEN"),
     ("fail on the original too", '<recheck verdict="OK"><run result="fail" orig="fail">b</run></recheck>', "OK"),
     ("template quoted first", 'I will reply <recheck verdict="OK"></recheck> if all pass.\n'
      '<recheck verdict="BROKEN"><run result="fail">b</run></recheck>', "BROKEN"),
     ("fenced, cased", '```xml\n<RECHECK Verdict="ok">\n<Run Result="PASS">a</Run>\n</RECHECK>\n```', "OK"),
     ("truncated", '<recheck verdict="OK">\n<run result="pass">a</run>\n<run result="fail">b | obs', "BROKEN"),
     ("no verdict, all pass", '<recheck><run result="pass">a</run></recheck>', None),
     ("old line format", "PASS a\nRECHECK: OK", None),
     ("broken, cut short before any run", 'Re-ran them.\n\n<recheck verdict="BROKEN">\n', "BROKEN"),
     ("ok, cut short before any run", '<recheck verdict="OK">\n', None),
     ("broken in a sentence", 'I would open with <recheck verdict="BROKEN"> if one failed.', None),
     ("broken opening a sentence", '<recheck verdict="BROKEN"> would be my verdict if a run failed; all passed.\n', None),
     ("empty broken block in a sentence", '<recheck verdict="BROKEN"></recheck> if any run fails.', None),
     ("broken, cut short in a run tag", '<recheck verdict="BROKEN">\n<ru', "BROKEN"),
     ("result failed", '<recheck verdict="OK"><run result="failed" orig="pass">a</run></recheck>', "BROKEN"),
     ("fail, orig same", '<recheck verdict="OK"><run result="fail" orig="same">a</run></recheck>', "OK"),
     ("closing tag in a pass, then a fail", '<recheck verdict="OK"><run result="pass" orig="pass"></recheck></run>'
      '<run result="fail" orig="pass">b</run></recheck>', "BROKEN"),
     ("opening tag in a fail", '<recheck verdict="BROKEN"><run result="fail" orig="pass"><recheck verdict="OK"></recheck>'
      "</run></recheck>", "BROKEN"),
     ("nothing", "", None)]


class CorpusTest(unittest.TestCase):
    def test_reports(self):
        for name, rep, kept, nr, stop in C:
            with self.subTest(name):
                t = tr.triage(rep, lambda p: True)
                self.assertEqual(([k["id"] for k in t["kept"]], len(t["not_run"]), t.get("stop")), (kept, nr, stop))

    def test_payloads_survive(self):
        for case in PAYLOADS:
            with self.subTest(case):
                t = tr.triage("<report>\n" + B.format(case=case) + "</report>", lambda p: True)
                self.assertEqual(t["kept"][0]["text"], B.format(case=case).strip())

    def test_backing_forms(self):
        for back in ("tests/a.py", "./tests/a.py", "`tests/a.py`", "tests/a.py:12", "tests/a.py:12-20", "tests/a.py:L12",
                     "tests/a.py#L12", "tests/a.py::test_x", "tests/a.py (line 12)", "tests/a.py, tests/b.py",
                     "tests/b.py tests/a.py", "tests/a.py."):
            with self.subTest(back):
                rep = f"<report><regression><backing>{back}</backing><case>x</case></regression></report>"
                self.assertEqual(tr.triage(rep, lambda p: p in ("tests/a.py", "./tests/a.py"))["dropped"], [])
        for back in ("none", "n/a", "the existing docs", ""):
            with self.subTest(back):
                rep = f"<report><regression><backing>{back}</backing><case>x</case></regression></report>"
                self.assertEqual(tr.triage(rep, lambda p: True)["kept"], [])

    def test_recheck(self):
        for name, txt, want in R:
            with self.subTest(name):
                self.assertEqual(tr.recheck_verdict(txt)["verdict"], want)


if __name__ == "__main__":
    unittest.main()
