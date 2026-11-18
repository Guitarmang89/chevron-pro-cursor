"""Top-bar button (Waybar JSONC / omarchy-shell), Hyprland snippet (.conf + .lua), angle range and the
trail-color preset keys. Each test runs chevron_core in a fake $HOME (a subprocess, since paths are
computed at import)."""
import json, os, shutil, subprocess, sys, tempfile, textwrap, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
sys.path.insert(0, ROOT)
import chevron_bar as B  # noqa: E402
import warnings  # noqa: E402
warnings.simplefilter("ignore", ResourceWarning)

CMD = "/home/me/.local/share/chevron-pro-cursor/chevron_core.py open"


def in_home(home, code, env=None):
    e = dict(os.environ, HOME=home, PATH="/usr/bin:/bin", XDG_CONFIG_HOME=os.path.join(home, ".config"),
             XDG_DATA_HOME=os.path.join(home, ".local/share"), **(env or {}))
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r)\nimport chevron_core as core\n" % ROOT
                        + textwrap.dedent(code)], env=e, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(r.stderr)
    return r.stdout


class Waybar(unittest.TestCase):
    def test_add_remove_is_byte_identical(self):
        for fn in ("omarchy-3.8-waybar-config.jsonc", "omarchy-3.3-waybar-config.jsonc"):
            src = open(os.path.join(DATA, fn), encoding="utf-8").read()
            for pos in B.POSITIONS:
                new = B.waybar_add(src, pos, CMD)
                d = B.parse_jsonc(new)
                self.assertEqual(d[B.MODULE]["on-click"], CMD)
                self.assertEqual(B.parse_jsonc(B.waybar_remove(new)), B.parse_jsonc(src))
                self.assertEqual(B.waybar_remove(new), src, f"{fn} {pos}")
                self.assertEqual(B.waybar_add(new, pos, CMD), new)          # idempotent

    def test_positions(self):
        src = open(os.path.join(DATA, "omarchy-3.8-waybar-config.jsonc"), encoding="utf-8").read()
        orig = B.parse_jsonc(src)
        want = {"left": ("modules-left", len(orig["modules-left"])), "center-left": ("modules-center", 0),
                "center-mid": ("modules-center", (len(orig["modules-center"]) + 1) // 2),
                "center-right": ("modules-center", len(orig["modules-center"])), "right": ("modules-right", 0)}
        for pos, (sec, idx) in want.items():
            d = B.parse_jsonc(B.waybar_add(src, pos, CMD))
            self.assertEqual(d[sec].index(B.MODULE), idx, pos)
            for other in ("modules-left", "modules-center", "modules-right"):
                if other != sec:
                    self.assertEqual(d[other], orig[other])

    def test_odd_layouts(self):
        for src in ('{"layer":"top"}', '[{"modules-right": ["x" /* c */, "y" // tail\n ]}]',
                    '{\n  // c\n  "modules-left": [],\n  "a": 1, /* x */\n}\n', '{\n\t"modules-center": [\n\t\t"a"\n\t]\n}'):
            for pos in B.POSITIONS:
                new = B.waybar_add(src, pos, CMD)
                B.parse_jsonc(new)
                self.assertEqual(B.waybar_remove(new), src)

    def test_css(self):
        css = open(os.path.join(DATA, "omarchy-3.8-waybar-style.css")).read()
        new = B.css_add(css)
        self.assertIn("#custom-chevron-pro-cursor", new)
        self.assertIn("margin: 0 10px", new)
        self.assertEqual(B.css_remove(new), css)


class OmarchyShell(unittest.TestCase):
    def test_sections_and_restore(self):
        src = open(os.path.join(DATA, "omarchy-4.5-shell.json")).read()
        d = json.loads(src)
        want = {"left": "left", "center-left": "centerBegin", "center-mid": "center", "center-right": "centerEnd", "right": "right"}
        for pos, sec in want.items():
            n = B.shell_add(d, pos, CMD)
            ids = [e.get("id") for e in n["bar"]["layout"][sec]]
            self.assertIn(B.SHELL_ID, ids)
            e = n["bar"]["layout"][sec][ids.index(B.SHELL_ID)]
            self.assertEqual((e["type"], e["onClick"]), ("command", CMD))
            self.assertEqual(B._dump_shell(B.shell_remove(n)), src)


class FakeHome(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="chevron-it-")
        os.makedirs(os.path.join(self.home, ".config/hypr"))
        os.makedirs(os.path.join(self.home, ".local/share/chevron-pro-cursor"))

    def tearDown(self):
        shutil.rmtree(self.home)

    def test_waybar_install_uninstall(self):
        wb = os.path.join(self.home, ".config/waybar")
        os.makedirs(wb)
        shutil.copy(os.path.join(DATA, "omarchy-3.8-waybar-config.jsonc"), os.path.join(wb, "config.jsonc"))
        shutil.copy(os.path.join(DATA, "omarchy-3.8-waybar-style.css"), os.path.join(wb, "style.css"))
        before = {f: open(os.path.join(wb, f), "rb").read() for f in os.listdir(wb)}
        in_home(self.home, 'print(core.main.__name__); import sys; sys.argv=["x","bar","--position","center-right","--no-restart"]; core.main()')
        cfg = B.parse_jsonc(open(os.path.join(wb, "config.jsonc")).read())
        self.assertEqual(cfg["modules-center"][-1], B.MODULE)
        self.assertTrue(os.path.exists(os.path.join(wb, "config.jsonc" + B.BAK)))
        out = in_home(self.home, 'import sys; sys.argv=["x","bar","--position","left","--no-restart"]; core.main()')
        cfg = B.parse_jsonc(open(os.path.join(wb, "config.jsonc")).read())
        self.assertEqual(cfg["modules-left"][-1], B.MODULE)
        self.assertNotIn(B.MODULE, cfg["modules-center"])
        in_home(self.home, 'log=[]; core.bar_remove(log, do_restart=False); print(log)')
        after = {f: open(os.path.join(wb, f), "rb").read() for f in os.listdir(wb)}
        self.assertEqual(after, before)

    def test_shell_created_from_defaults_and_removed(self):
        om = os.path.join(self.home, "omarchy")
        os.makedirs(os.path.join(om, "config/omarchy"))
        shutil.copy(os.path.join(DATA, "omarchy-4.5-shell.json"), os.path.join(om, "config/omarchy/shell.json"))
        os.makedirs(os.path.join(self.home, ".config/omarchy"))
        env = {"OMARCHY_PATH": om}
        in_home(self.home, 'import chevron_bar as B\nprint(B.add("right", core.bar_launch_cmd(), core.BAR_STATE, kind="shell", do_restart=False))', env)
        p = os.path.join(self.home, ".config/omarchy/shell.json")
        d = json.load(open(p))
        self.assertEqual(d["bar"]["layout"]["right"][0]["id"], B.SHELL_ID)
        in_home(self.home, 'log=[]; core.bar_remove(log, do_restart=False); print(log)', env)
        self.assertFalse(os.path.exists(p))        # we created it from the defaults: gone again

    def test_hypr_conf_and_lua(self):
        hy = os.path.join(self.home, ".config/hypr")
        shutil.copy(os.path.join(DATA, "omarchy-3.8-hyprland.conf"), os.path.join(hy, "hyprland.conf"))
        shutil.copy(os.path.join(DATA, "omarchy-4.5-hyprland.lua"), os.path.join(hy, "hyprland.lua"))
        conf0 = open(os.path.join(hy, "hyprland.conf")).read(); lua0 = open(os.path.join(hy, "hyprland.lua")).read()
        in_home(self.home, 'core._write_hypr("ChevronPro", 48, True)')
        snip = open(os.path.join(hy, "chevron-pro-cursor.conf")).read()
        self.assertIn("env = XCURSOR_THEME,ChevronPro", snip)
        self.assertIn("windowrule = float on, match:class ^(com\\.chevronpro\\.Cursor)$", snip)
        self.assertIn("windowrule = size (monitor_w*0.38) (monitor_h*0.5)", snip)
        self.assertIn("chevron-pro-trail", snip)
        lua = open(os.path.join(hy, "chevron-pro-cursor.lua")).read()
        self.assertIn('hl.env("XCURSOR_THEME", "ChevronPro")', lua)
        self.assertIn('hl.window_rule({ match = { class = "^(com\\\\.chevronpro\\\\.Cursor)$" }, float = true, center = true', lua)
        self.assertIn("source = " + os.path.join(hy, "chevron-pro-cursor.conf"), open(os.path.join(hy, "hyprland.conf")).read())
        self.assertIn('pcall(dofile, "%s")' % os.path.join(hy, "chevron-pro-cursor.lua"), open(os.path.join(hy, "hyprland.lua")).read())
        out = in_home(self.home, 'print(core._hypr_state())')
        self.assertEqual(out.strip(), "('ChevronPro', 48, True)")
        in_home(self.home, 'core.set_trail_autostart(False); print(core._hypr_state())')
        self.assertNotIn("chevron-pro-trail", open(os.path.join(hy, "chevron-pro-cursor.conf")).read())
        in_home(self.home, 'core.uninstall(purge=True, interactive=False)')
        self.assertEqual(open(os.path.join(hy, "hyprland.conf")).read(), conf0)
        self.assertEqual(open(os.path.join(hy, "hyprland.lua")).read(), lua0)
        self.assertFalse(os.path.exists(os.path.join(hy, "chevron-pro-cursor.conf")))
        self.assertFalse(os.path.exists(os.path.join(hy, "chevron-pro-cursor.lua")))


class Settings(unittest.TestCase):
    def test_angle_range(self):
        import chevron_core as core
        self.assertEqual((2 * core.ANGLE_MIN, 2 * core.ANGLE_MAX), (60, 150))
        self.assertEqual(core.clamp_angle(10), 30)
        L, tip = core.geometry(30, 0.39)
        self.assertGreater(L, 0.2)

    def test_trail_color_in_presets(self):
        home = tempfile.mkdtemp(prefix="chevron-it-")
        try:
            out = in_home(home, '''
                s = core.load_settings(); print(s["trail_color_custom"])
                s.update(trail_color_custom=True, trail_color="#FF00AA")
                core.save_preset("Pink trail", s)
                p = core.find_preset("Pink trail")[1]; print(p["trail_color_custom"], p["trail_color"])
                print(core.find_preset("Neon Cyan")[1]["trail_color_custom"])
                import json, os
                os.makedirs(core.CFG_DIR, exist_ok=True)
                json.dump({"trail_color": "#123456"}, open(core.SETTINGS, "w"))      # file from before the switch
                print(core.load_settings()["trail_color_custom"])
                import sys; sys.argv = ["x", "trail-color", "Red"]; core.main()
                d = json.load(open(core.SETTINGS)); print(d["trail_color_custom"], d["trail_color"])
                sys.argv = ["x", "trail-color", "cursor"]; core.main()
                print(json.load(open(core.SETTINGS))["trail_color_custom"])
            ''')
            lines = out.split("\n")
            self.assertEqual(lines[0], "False")
            self.assertEqual(lines[1], "True #FF00AA")
            self.assertEqual(lines[2], "False")
            self.assertEqual(lines[3], "False")
            self.assertTrue(lines[5].startswith("True #"))
            self.assertEqual(lines[7], "False")
        finally:
            shutil.rmtree(home)


if __name__ == "__main__":
    unittest.main()
