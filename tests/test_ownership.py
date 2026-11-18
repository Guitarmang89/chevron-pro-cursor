"""Ownership of shared paths: install.sh / uninstall in a throwaway $HOME.

Launchers only ever run the bundled copies in ~/.local/share/chevron-pro-cursor; a shared path
(~/.local/bin, the .desktop entry, the icon) is only replaced or removed while its current identity
(sha256 / exact symlink target) matches what the manifest recorded, or, for installs from before the
manifest, what a released installer put there."""
import os, shutil, subprocess, sys, tempfile, textwrap, unittest
import warnings
warnings.simplefilter("ignore", ResourceWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FOREIGN = "#!/bin/sh\n# some other tool that happens to be called chevron, not ours\necho foreign\n"


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="chevron-own-")
        self.home = os.path.join(self.tmp, "home")
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.home)
        shutil.copytree(ROOT, self.src, ignore=shutil.ignore_patterns(".git", "themes", "__pycache__", "tests", "*.png"))
        os.makedirs(os.path.join(self.src, "data"), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "data", "chevron-pro-cursor.png"), os.path.join(self.src, "data"))
        t = os.path.join(self.src, "themes", "ChevronPro-Test", "cursors")      # one tiny prebuilt theme
        os.makedirs(t)
        with open(os.path.join(os.path.dirname(t), "index.theme"), "w") as f:
            f.write("[Icon Theme]\nName=ChevronPro-Test\nComment=Chevron Pro Cursor (click point = chevron tip)\n")
        # stubs so the test never touches real processes, bars or cursors on this machine
        self.stub = os.path.join(self.tmp, "stub")
        os.makedirs(self.stub)
        for n in ("pgrep", "pkill", "hyprctl", "gsettings", "uwsm", "waybar", "omarchy-shell", "setsid"):
            p = os.path.join(self.stub, n)
            with open(p, "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(p, 0o755)
        self.env = {"HOME": self.home, "PATH": self.stub + ":/usr/bin:/bin", "LANG": "C.UTF-8",
                    "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_DATA_HOME": os.path.join(self.home, ".local/share")}
        self.bin = os.path.join(self.home, ".local/bin")
        self.lib = os.path.join(self.home, ".local/share/chevron-pro-cursor")
        self.desktop = os.path.join(self.home, ".local/share/applications/chevron-pro-cursor.desktop")
        self.icon = os.path.join(self.home, ".local/share/icons/hicolor/128x128/apps/chevron-pro-cursor.png")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def run_sh(self, *args):
        r = subprocess.run(["bash", os.path.join(self.src, "install.sh"), "--no-launch", "--bar-position", "none", *args],
                           env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def uninstall(self):
        r = subprocess.run(["bash", os.path.join(self.lib, "uninstall.sh"), "--keep-settings"], env=self.env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def core(self, code):
        r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\nimport chevron_core as core\n" % self.lib
                            + textwrap.dedent(code)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def write(self, path, text, mode=0o755):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.lexists(path):
            os.remove(path)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, mode)

    def launchers(self):
        return self.core("""
            print(core.picker_bin()); print(core.cli_bin()); print(core.trail_bin()); print(core.bar_launch_cmd())
        """).splitlines() + [l for l in open(self.desktop) if l.startswith("Exec=")]

    def assert_bundled_launchers(self):
        got = self.launchers()
        self.assertEqual(got[:3], [os.path.join(self.lib, n) for n in ("chevron-pro-picker", "chevron_core.py", "chevron-pro-trail")])
        self.assertEqual(got[3], os.path.join(self.lib, "chevron_core.py") + " open")
        self.assertEqual(got[4].strip(), "Exec=" + os.path.join(self.lib, "chevron-pro-picker"))
        for g in got:
            self.assertNotIn("/.local/bin/", g)

    def manifest(self):
        return dict(l.rstrip("\n").split("\t", 1) for l in open(os.path.join(self.lib, "installed-files")) if l.strip())

    def simulate_v320(self):
        """What the v3.2.0 installer left: shared files, the CLI symlink, no manifest."""
        os.makedirs(self.lib, exist_ok=True)
        shutil.copy(os.path.join(ROOT, "chevron_core.py"), os.path.join(self.lib, "chevron_core.py"))
        for n in ("chevron-pro-picker", "chevron-pro-trail"):
            os.makedirs(self.bin, exist_ok=True)
            shutil.copy(os.path.join(ROOT, n), os.path.join(self.bin, n))
        os.symlink(os.path.join(self.lib, "chevron_core.py"), os.path.join(self.bin, "chevron-pro-cursor"))
        os.makedirs(os.path.dirname(self.icon), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "data", "chevron-pro-cursor.png"), self.icon)
        tpl = open(os.path.join(ROOT, "data", "chevron-pro-cursor.desktop")).read()
        self.write(self.desktop, tpl.replace("@BIN@", self.bin), 0o644)

    # ------------------------------------------------------------------ tests
    def test_fresh_install_reinstall_and_uninstall(self):
        out = self.run_sh()
        self.assertNotIn("left ", out)
        m = self.manifest()
        self.assertEqual(set(m), {os.path.join(self.bin, n) for n in ("chevron-pro-picker", "chevron-pro-trail", "chevron-pro-cursor")}
                         | {self.desktop, self.icon})
        self.assertEqual(m[os.path.join(self.bin, "chevron-pro-cursor")], "link:" + os.path.join(self.lib, "chevron_core.py"))
        self.assertTrue(m[self.desktop].startswith("sha256:"))
        self.assert_bundled_launchers()
        out = self.run_sh()                                     # reinstall: everything still verified
        self.assertNotIn("left ", out)
        self.assertEqual(self.manifest(), m)
        self.uninstall()
        for p in list(m) + [self.lib]:
            self.assertFalse(os.path.lexists(p), p)

    def test_replaced_after_install_is_not_launched_or_removed(self):
        self.run_sh()
        picker = os.path.join(self.bin, "chevron-pro-picker")
        cli = os.path.join(self.bin, "chevron-pro-cursor")
        self.write(picker, FOREIGN)                             # another tool takes the name
        os.remove(cli); os.symlink(os.path.join(self.lib, "chevron-pro-trail"), cli)   # a link into our dir, but not ours
        with open(self.desktop, "a") as f:
            f.write("# edited by the user\n")
        self.assertEqual(self.core("print(core.ownership(%r), core.ownership(%r), core.ownership(%r))" % (picker, cli, self.desktop)),
                         "changed changed changed")
        out = self.run_sh()                                     # upgrade: leaves all three alone
        for p in (picker, cli, self.desktop):
            self.assertIn(f"left {p} alone (it has changed since Chevron Pro Cursor installed it", out)
        self.assertEqual(open(picker).read(), FOREIGN)
        self.assertEqual(os.readlink(cli), os.path.join(self.lib, "chevron-pro-trail"))
        self.assertNotIn(picker, self.manifest())
        got = self.launchers()
        self.assertEqual(got[0], os.path.join(self.lib, "chevron-pro-picker"))
        self.assertEqual(got[1], os.path.join(self.lib, "chevron_core.py"))
        self.assertNotIn("/.local/bin/", "".join(got))
        cmd = [l for l in open(os.path.join(ROOT, "ChevronProButton.qml")) if "command:" in l][0]
        self.assertNotIn(".local/bin", cmd)
        self.assertIn('.local/share}/chevron-pro-cursor/chevron_core.py', cmd)
        out = self.uninstall()
        self.assertEqual(open(picker).read(), FOREIGN)          # not deleted
        self.assertTrue(os.path.islink(cli))
        self.assertTrue(os.path.exists(self.desktop))
        self.assertIn(f"left {picker} in place", out)
        self.assertFalse(os.path.lexists(os.path.join(self.bin, "chevron-pro-trail")))   # still-verified ones go

    def test_replaced_without_reinstall_is_not_removed(self):
        self.run_sh()
        trail = os.path.join(self.bin, "chevron-pro-trail")
        self.write(trail, FOREIGN)
        out = self.uninstall()
        self.assertEqual(open(trail).read(), FOREIGN)
        self.assertIn(f"left {trail} in place (changed since", out)

    def test_force_replaces_and_takes_ownership(self):
        picker = os.path.join(self.bin, "chevron-pro-picker")
        self.write(picker, FOREIGN)
        out = self.run_sh()
        self.assertIn(f"left {picker} alone (it wasn't installed by Chevron Pro Cursor", out)
        self.assertEqual(open(picker).read(), FOREIGN)
        self.assertNotIn(picker, self.manifest())
        self.assertIn(f"left {picker} in place (not verified", self.core("import io; print('\\n'.join(core.uninstall(purge=False, interactive=False)))"))
        self.assertEqual(open(picker).read(), FOREIGN)
        out = self.run_sh("--force")
        self.assertIn(f"replacing {picker} (--force)", out)
        self.assertEqual(open(picker).read(), open(os.path.join(ROOT, "chevron-pro-picker")).read())
        self.assertIn(picker, self.manifest())
        self.uninstall()
        self.assertFalse(os.path.lexists(picker))

    def test_legacy_verified_paths_upgraded_and_removed(self):
        self.simulate_v320()
        shared = [os.path.join(self.bin, n) for n in ("chevron-pro-picker", "chevron-pro-trail", "chevron-pro-cursor")] + [self.desktop, self.icon]
        self.assertEqual(self.core("print(' '.join(core.ownership(p) for p in %r))" % shared), " ".join(["ours"] * 5))
        out = self.run_sh()                                     # upgrade from v3.2.0
        self.assertNotIn("left ", out)
        self.assertEqual(set(self.manifest()), set(shared))
        self.assert_bundled_launchers()
        self.uninstall()
        for p in shared:
            self.assertFalse(os.path.lexists(p), p)

    def test_legacy_v320_uninstall_without_upgrade(self):
        self.simulate_v320()
        out = self.core("print('\\n'.join(core.uninstall(purge=False, interactive=False)))")
        self.assertNotIn("left ", out)
        self.assertFalse(os.path.lexists(os.path.join(self.bin, "chevron-pro-picker")))
        self.assertFalse(os.path.lexists(self.icon))

    def test_legacy_unverified_paths_left_alone(self):
        self.simulate_v320()
        picker = os.path.join(self.bin, "chevron-pro-picker")
        cli = os.path.join(self.bin, "chevron-pro-cursor")
        self.write(picker, FOREIGN)                             # mentions "chevron": the old marker rule took it
        os.remove(cli); os.symlink(os.path.join(self.lib, "somewhere-else"), cli)
        self.write(self.icon, "not our icon", 0o644)
        old = os.path.join(self.bin, "chevron" "-picker")      # v1/v2 names
        old_cli = os.path.join(self.bin, "chevron" "-cursor")
        old_dir = os.path.join(self.home, ".local/share", "chevron" "-cursor")
        self.write(old, FOREIGN)
        os.makedirs(old_dir)
        self.write(os.path.join(old_dir, "notes.txt"), "user file", 0o644)
        os.symlink(os.path.join(old_dir, "chevron_core.py"), old_cli)   # exactly what v1/v2 made: verified
        out = self.run_sh()
        for p in (picker, cli, self.icon):
            self.assertIn(f"left {p} alone", out)
        self.assertIn(f"left {old} in place", out)
        self.assertIn(f"left {old_dir} in place", out)
        self.assertEqual(open(picker).read(), FOREIGN)
        self.assertEqual(open(old).read(), FOREIGN)
        self.assertFalse(os.path.lexists(old_cli))              # the verified legacy symlink was removed
        self.assertTrue(os.path.isfile(os.path.join(old_dir, "notes.txt")))
        self.assert_bundled_launchers()
        out = self.uninstall()
        for p in (picker, cli, self.icon, old):
            self.assertTrue(os.path.lexists(p), p)
        self.assertTrue(os.path.isfile(os.path.join(old_dir, "notes.txt")))

    def test_path_only_manifest_from_v321_requires_verification(self):
        """The first manifest (f4eb69f) listed paths without identities: a listed path that no longer
        matches a released file is treated as changed."""
        self.simulate_v320()
        picker = os.path.join(self.bin, "chevron-pro-picker")
        trail = os.path.join(self.bin, "chevron-pro-trail")
        with open(os.path.join(self.lib, "installed-files"), "w") as f:
            f.write(picker + "\n" + trail + "\n")
        self.write(picker, FOREIGN)
        self.assertEqual(self.core("print(core.ownership(%r), core.ownership(%r), core.ownership(%r))" % (picker, trail, self.icon)),
                         "changed ours foreign")
        out = self.core("print('\\n'.join(core.uninstall(purge=False, interactive=False)))")
        self.assertEqual(open(picker).read(), FOREIGN)
        self.assertFalse(os.path.lexists(trail))
        self.assertTrue(os.path.lexists(self.icon))             # skipped by that install (not listed): kept
        self.assertIn(f"left {self.icon} in place", out)


if __name__ == "__main__":
    unittest.main()
