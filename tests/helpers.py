import os
import shutil
import tempfile
import unittest
from pathlib import Path


class TempWS(unittest.TestCase):
    """Each test gets its own workspace (CZ_WS), HOME and repository directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cz-test-"))
        self._env = {k: os.environ.get(k) for k in ("CZ_WS", "HOME", "XDG_CONFIG_HOME", "CODEX_HOME", "CZ_GATE")}
        os.environ["CZ_WS"] = str(self.tmp / "ws")
        os.environ["HOME"] = str(self.tmp / "home")
        for k in ("XDG_CONFIG_HOME", "CODEX_HOME", "CZ_GATE"):
            os.environ.pop(k, None)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, text, root=None):
        p = (root or self.repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p
