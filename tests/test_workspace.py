import os
import unittest

from collinearzero import workspace as w
from tests.helpers import TempWS


class WorkspaceTest(TempWS):
    def test_init_snapshot_diff_revert(self):
        self.write("app.py", "v1\n")
        self.write("lib/util.py", "u1\n")
        self.write("old.txt", "gone soon\n")
        self.write(".git/HEAD", "ref\n")
        ext = self.tmp / "external"
        self.write("vendored.c", "x\n", root=ext)
        os.symlink(ext, self.repo / "vendor")
        os.symlink("app.py", self.repo / "alias.py")
        msg = w.init(self.repo, "the finding, verbatim\n")
        self.assertIn("snapshotted", msg)
        orig = w.ws() / "orig"
        self.assertEqual((w.ws() / "task.md").read_text(), "the finding, verbatim\n")
        self.assertFalse((orig / ".git").exists())
        self.assertTrue((orig / "vendor").is_dir() and not (orig / "vendor").is_symlink())   # top-level dir link: copied
        self.assertTrue((orig / "alias.py").is_symlink())                                     # file link: kept
        self.assertTrue(w.active_for(self.repo))

        self.write("app.py", "v2\n")
        (self.repo / "old.txt").unlink()
        self.write("new/added.py", "n\n")
        d = w.tree_diff(orig, self.repo)
        # like `diff -rq`, links are followed: alias.py -> app.py differs too; the linked vendor/ dir does not
        self.assertEqual(sorted(d), [("changed", "alias.py"), ("changed", "app.py"), ("only_a", "old.txt"),
                                     ("only_b", "new")])
        self.assertIn("Only in", w.format_diff(orig, self.repo, d))

        w.checkpoint(self.repo)
        self.write("app.py", "v3\n")
        self.write("lib/util.py", "u2\n")
        self.write("scratch.txt", "tester junk\n")
        r = w.revert(self.repo)
        self.assertEqual(r["residual"], 0)
        self.assertEqual((self.repo / "app.py").read_text(), "v2\n")
        self.assertEqual((self.repo / "lib/util.py").read_text(), "u1\n")
        self.assertFalse((self.repo / "scratch.txt").exists())
        self.assertTrue((self.repo / ".git/HEAD").exists())

    def test_special_files_and_light_checkpoint(self):
        self.write("app.py", "v1\n")
        self.write("node_modules/dep/index.js", "dep\n")
        self.write("pkg/node_modules/dep/index.js", "dep\n")
        os.symlink("/dev/null", self.repo / "null")
        w.init(self.repo, "t")
        self.assertEqual(w.tree_diff(w.ws() / "orig", self.repo), [])     # a link to /dev/null is not a change
        w.checkpoint(self.repo)
        self.assertFalse((w.ws() / "pre_review/node_modules").exists())
        self.write("app.py", "v2\n")
        import shutil
        shutil.rmtree(self.repo / "pkg")                                # the fix round deleted a directory
        self.assertEqual(w.revert(self.repo)["residual"], 0)
        self.assertEqual((self.repo / "app.py").read_text(), "v1\n")
        self.assertTrue((self.repo / "pkg/node_modules/dep/index.js").exists())   # restored whole
        self.assertTrue((self.repo / "node_modules/dep/index.js").exists())       # never touched by a revert

    def test_init_refuses_other_repo(self):
        w.init(self.repo, "t")
        other = self.tmp / "other"
        other.mkdir()
        with self.assertRaises(SystemExit):
            w.init(other, "t")
        self.assertIn("already initialised", w.init(self.repo, "t"))


if __name__ == "__main__":
    unittest.main()
