"""The shared default cursor (~/.local/share/icons/default/index.theme), in a throwaway $HOME.

Apply moves what was there to a backup and records the identity of the override and of that backup;
reset / uninstall only restore (or remove the override) while the override is still exactly what Chevron
wrote and the backup still exactly what it saved. Anything changed later, or without a recorded identity
(installs from before it was recorded), is left in place."""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ownership as own  # noqa: E402  (only its throwaway-$HOME helpers)

ORIGINAL = "[Icon Theme]\nInherits=Bibata-Modern-Classic\n"
OTHER = "[Icon Theme]\nInherits=Breeze_Light\n# written by another theme\n"


class DefaultIndex(own.Home):
    def setUp(self):
        super().setUp()
        self.idx = os.path.join(self.home, ".local/share/icons/default/index.theme")
        self.bak = self.idx + ".bak"
        self.cbak = self.idx + ".chevron-pro-cursor.bak"
        self.state = os.path.join(self.lib, "default-index-theme.json")

    def apply(self, theme="ChevronPro-Test"):
        return self.core("print('\\n'.join(core.activate(%r, 24)))" % theme)

    def reset(self):
        return self.core("print('\\n'.join(core.reset({'previous': {'theme': 'Adwaita', 'size': 24}})))")

    def uninst(self):
        return self.core("print('\\n'.join(core.uninstall(purge=False, interactive=False)))")

    def read(self, p):
        return open(p).read()

    # ------------------------------------------------------------------ tests
    locals().update({n: None for n in dir(own.Home) if n.startswith("test_")})   # don't re-run the ownership tests

    def test_unchanged_override_is_restored_by_reset_and_uninstall(self):
        self.write(self.idx, ORIGINAL, 0o644)
        self.run_sh()
        out = self.apply()
        self.assertIn(f"backed up {self.idx} to {self.bak}", out)
        self.assertIn("Inherits=ChevronPro-Test", self.read(self.idx))
        st = json.load(open(self.state))
        self.assertTrue(st["override"].startswith("sha256:") and st["backup"].startswith("sha256:"))
        self.assertEqual(st["backup_path"], self.bak)
        self.apply()                                            # re-apply: our own override is not backed up again
        self.assertEqual(self.read(self.bak), ORIGINAL)
        out = self.reset()
        self.assertEqual(self.read(self.idx), ORIGINAL)
        self.assertFalse(os.path.lexists(self.bak))
        self.assertFalse(os.path.exists(self.state))
        self.apply()
        out = self.uninst()
        self.assertIn(f"restored your original {self.idx}", out)
        self.assertEqual(self.read(self.idx), ORIGINAL)
        self.assertFalse(os.path.lexists(self.bak))

    def test_no_original_override_is_removed(self):
        self.run_sh()
        self.apply()
        self.assertFalse(os.path.lexists(self.bak))
        self.reset()
        self.assertFalse(os.path.lexists(self.idx))
        self.apply()
        self.assertIn(f"removed {self.idx}", self.uninst())
        self.assertFalse(os.path.lexists(self.idx))

    def test_edited_override_is_left_alone(self):
        self.write(self.idx, ORIGINAL, 0o644)
        self.run_sh()
        self.apply()
        with open(self.idx, "a") as f:                          # the user edits Chevron's override
            f.write("# my edit\n")
        edited = self.read(self.idx)
        out = self.reset()
        self.assertIn(f"left {self.idx} in place (changed since", out)
        self.assertEqual(self.read(self.idx), edited)
        self.assertEqual(self.read(self.bak), ORIGINAL)         # the backup is kept, not put over the edit
        self.write(self.idx, OTHER, 0o644)                      # another theme replaces it entirely
        out = self.uninst()
        self.assertEqual(self.read(self.idx), OTHER)
        self.assertEqual(self.read(self.bak), ORIGINAL)
        self.assertIn(f"left Chevron's backup of your original at {self.bak}", out)

    def test_reapply_after_another_theme_changed_it(self):
        self.write(self.idx, ORIGINAL, 0o644)
        self.run_sh()
        self.apply()
        self.write(self.idx, OTHER, 0o644)                      # another theme takes over, then Chevron is applied again
        self.apply()
        self.assertIn("Inherits=ChevronPro-Test", self.read(self.idx))
        self.assertEqual(self.read(self.bak), OTHER)            # the newest non-Chevron file is what reset goes back to
        self.reset()
        self.assertEqual(self.read(self.idx), OTHER)

    def test_missing_identity_from_older_install_is_not_restored(self):
        """v3.2.x wrote the override and index.theme.bak but recorded no identity: the backup can't be
        proven to be Chevron's, so it is never put back; an override in exactly Chevron's format is removed."""
        self.simulate_v320()
        self.write(self.idx, "[Icon Theme]\n# chevron-pro-cursor\nInherits=ChevronPro-Default\n", 0o644)
        self.write(self.bak, ORIGINAL, 0o644)
        out = self.uninst()
        self.assertNotIn("restored", out)
        self.assertIn(f"removed {self.idx}", out)
        self.assertEqual(self.read(self.bak), ORIGINAL)
        self.assertIn(f"left {self.bak} in place (not verified", out)

    def test_missing_identity_edited_override_is_left_alone(self):
        self.simulate_v320()
        edited = "[Icon Theme]\n# chevron-pro-cursor\nInherits=Bibata-Modern-Ice\n"   # marker kept, theme changed
        self.write(self.idx, edited, 0o644)
        self.write(self.bak, ORIGINAL, 0o644)
        out = self.reset()
        self.assertEqual(self.read(self.idx), edited)
        self.assertEqual(self.read(self.bak), ORIGINAL)
        self.assertIn(f"left {self.idx} in place", out)

    def test_backup_must_still_be_chevrons(self):
        self.write(self.idx, ORIGINAL, 0o644)
        self.run_sh()
        self.apply()
        self.write(self.bak, OTHER, 0o644)                      # the backup was replaced after Chevron made it
        out = self.reset()
        self.assertNotIn("restored", out)
        self.assertEqual(self.read(self.bak), OTHER)
        self.assertFalse(os.path.lexists(self.idx))             # our unchanged override is still removed
        self.assertIn(f"left {self.bak} in place (not verified", out)

    def test_foreign_bak_is_never_overwritten(self):
        self.write(self.idx, ORIGINAL, 0o644)
        self.write(self.bak, OTHER, 0o644)                      # someone else's .bak was already there
        self.run_sh()
        self.assertIn(f"backed up {self.idx} to {self.cbak}", self.apply())
        self.assertEqual(self.read(self.bak), OTHER)
        self.reset()
        self.assertEqual(self.read(self.idx), ORIGINAL)
        self.assertEqual(self.read(self.bak), OTHER)
        self.assertFalse(os.path.lexists(self.cbak))

    def test_symlinked_index_is_moved_not_written_through(self):
        target = os.path.join(self.tmp, "shared-index.theme")
        with open(target, "w") as f:
            f.write(ORIGINAL)
        os.makedirs(os.path.dirname(self.idx))
        os.symlink(target, self.idx)
        self.run_sh()
        self.apply()
        self.assertEqual(open(target).read(), ORIGINAL)         # the link target is untouched
        self.assertTrue(os.path.islink(self.bak))
        self.uninst()
        self.assertTrue(os.path.islink(self.idx))
        self.assertEqual(os.readlink(self.idx), target)


if __name__ == "__main__":
    unittest.main()
