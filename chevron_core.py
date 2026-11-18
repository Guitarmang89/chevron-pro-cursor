#!/usr/bin/env python3
"""
Chevron Pro Cursor engine: renders an open upside-down-V chevron (two lines, no base,
no fill) with round caps + round apex, optional neon glow, and writes an Xcursor
theme directly (pure Python + Pillow). The click point (hotspot) is the apex tip.

Used by the picker app (chevron-pro-picker) and usable from the command line:
  chevron_core.py apply --color "#FF2A2A" --glow 60 --thickness 50 --opening 116 --size 32
  chevron_core.py build --name ChevronPro-Red --color "#FF2A2A" --glow 0 --out ./themes
  chevron_core.py use ChevronPro-RedSight 32     # switch to an installed prebuilt theme
  chevron_core.py reset
  chevron_core.py uninstall [--purge]          # remove everything (same as uninstall.sh)
Installed as the `chevron-pro-cursor` command.
"""
import argparse, hashlib, io, json, math, os, re, shutil, struct, subprocess, zipfile
import sys
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
except ImportError:          # uninstall / reset / trail commands work without Pillow
    Image = ImageDraw = ImageFilter = ImageChops = None
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import reload_anim   # noqa: E402  (animated reload busy cursor)

PRESETS = {
    "White": "#FFFFFF", "Black": "#000000", "Red": "#FF2A2A", "NeonGreen": "#39FF14",
    "Cyan": "#00F0FF", "Orange": "#FF8C00", "Pink": "#FF2BD6", "Yellow": "#FFE600",
}
SIZES = [24, 32, 48, 64, 96, 128]   # every theme carries all of these (HiDPI scaling picks the right one)
DEFAULTS = {"color": "#39FF14", "glow": 50, "glow_color": None,  # None = match the line color
            "thickness": 50, "angle": 58, "size": 32,
            "outline_color": None,      # None = auto: black, or white when the main color is dark
            "outline_opacity": 60,      # 0 = invisible .. 100 = solid crisp edge
            "outline_width": 25,        # 0 = none .. 100 = as wide as the line itself (per side)
            "heartbeat": False,         # pulse the glow of the main cursor (lub-dub) on top of the steady glow
            "heartbeat_intensity": 50,  # 0 = no pulse (static) .. 100 = about 2.25x the glow at the beat (v3.1: 25 % stronger)
            "heartbeat_bpm": 60,        # 50..120 beats per minute (loop = 60000 / bpm ms)
            "heartbeat_color_custom": False,  # False: the pulse is the glow color
            "heartbeat_color": None}    # the pulse color (#RRGGBB) when heartbeat_color_custom is on
APP_NAME = "Chevron Pro Cursor"
AUTHOR = "Sir Render"


def _read_version(default="3.2.0"):
    """The version comes from the VERSION file next to this module (installed alongside it)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "VERSION")) as f:
            return f.read().strip() or default
    except OSError:
        return default


VERSION = _read_version()
WIN_W_FRAC = 0.38          # settings window: 38 % of the monitor width (compact) ...
WIN_H_FRAC = 0.50          # ... and half its height
THEME_NAME = "ChevronPro"
LOOK_KEYS = ("color", "glow", "glow_color", "thickness", "angle", "outline_color", "outline_opacity", "outline_width",
             "heartbeat", "heartbeat_intensity", "heartbeat_bpm", "heartbeat_color_custom", "heartbeat_color")
# Closest thing to an "inverted" cursor (Hyprland can't invert): white line, solid black outline, no glow.
FULL_KEYS = LOOK_KEYS + ("size",)
PRESET_TRAIL_KEYS = ("trail_color_custom", "trail_color")   # presets also remember the trail color choice


def _p(color, glow, glow_color, thickness, opening, outline_color, outline_opacity, outline_width, size=32,
       heartbeat=False, heartbeat_intensity=50, heartbeat_bpm=60):
    return {"color": color, "glow": glow, "glow_color": glow_color, "thickness": thickness, "angle": opening / 2,
            "outline_color": outline_color, "outline_opacity": outline_opacity, "outline_width": outline_width, "size": size,
            "heartbeat": heartbeat, "heartbeat_intensity": heartbeat_intensity, "heartbeat_bpm": heartbeat_bpm,
            "trail_color_custom": False,      # built-ins: the trail follows the cursor's own colors
            "heartbeat_color_custom": False, "heartbeat_color": None}


# Built-in presets (read-only). opening is the full angle between the legs.
BUILTIN_PRESETS = {
    "Default":              _p("#39FF14", 50, None,      50, 116, None,      60, 25),
    "High Contrast":        _p("#FFFFFF", 0,  None,      55, 116, "#000000", 100, 55),
    "Neon Cyan":            _p("#00F0FF", 80, None,      45, 116, None,      50, 20),
    "Red Sight":            _p("#FF2A2A", 60, "#FF2A2A", 55, 110, "#000000", 60, 25),
    "White / Cyan Glow":    _p("#FFFFFF", 70, "#00F0FF", 50, 116, None,      50, 20),
    "Night Vision":         _p("#7CFF4F", 65, "#1FAA00", 45, 124, "#000000", 40, 20),
    "Gold / Orange Glow":   _p("#FFD700", 65, "#FF8C00", 55, 116, "#000000", 55, 25),
    "Pink / Purple Glow":   _p("#FF2BD6", 75, "#9D00FF", 50, 120, None,      50, 20),
    "Stealth Black":        _p("#000000", 0,  None,      55, 116, "#FFFFFF", 100, 45),
    "Wide Scope":           _p("#FFFFFF", 35, "#FF2A2A", 40, 150, "#000000", 70, 30),
    "Sharp Arrow":          _p("#FFE600", 45, None,      60, 80,  "#000000", 80, 30),
}
HIGH_CONTRAST = BUILTIN_PRESETS["High Contrast"]
PRESETS_FILE = None  # set below once CFG_DIR is known

# Geometry, as fractions of the cursor size
ANGLE_MIN, ANGLE_MAX = 30, 75   # leg angle from vertical -> opening 60..150 degrees
MARGIN = 0.15          # canvas fraction kept free outside the line edges for the glow
LEG_MAX = 0.40         # longest leg (centre-line), fraction of size
SS = 4                 # supersampling factor (render 4x, downsample)

CURSOR_NAMES = """
default left_ptr arrow top_left_arrow right_ptr pointer hand hand1 hand2 pointing_hand
crosshair cross tcross cross_reverse diamond_cross target dotbox draped_box icon
text xterm ibeam vertical-text context-menu help question_arrow whats_this left_ptr_help
progress left_ptr_watch half-busy wait watch clock
copy dnd-copy alias link dnd-link dnd-none dnd-ask dnd-move dnd-no-drop no-drop not-allowed
forbidden crossed_circle circle pirate X_cursor cell plus all-scroll fleur move size_all grab grabbing
openhand closedhand pencil color-picker zoom-in zoom-out
col-resize row-resize sb_h_double_arrow sb_v_double_arrow h_double_arrow v_double_arrow
split_h split_v size_hor size_ver size-hor size-ver
n-resize s-resize e-resize w-resize ne-resize nw-resize se-resize sw-resize
ew-resize ns-resize nesw-resize nwse-resize size_bdiag size_fdiag size-bdiag size-fdiag
top_side bottom_side left_side right_side top_left_corner top_right_corner
bottom_left_corner bottom_right_corner ul_angle ur_angle ll_angle lr_angle
sb_up_arrow sb_down_arrow sb_left_arrow sb_right_arrow up-arrow down-arrow based_arrow_up based_arrow_down
center_ptr right_tee left_tee top_tee bottom_tee
00000000000000020006000e7e9ffc3f 08e8e1c95fe2fc01f976f1e063a24ccd 1081e37283d90000800003c07f3ef6bf
3085a0e285430894940527032f8b26df 3ecb610c1bf2410f44200f48c40d3599 4498f0e0c1937ffe01fd06f973665830
5c6cd98b3f3ebcb1f9c7f1c204630408 6407b0e94181790501fd1e167b474872 640fb0e74195791501fd1ed57b41487f
9081237383d90e509aa00f00170e968f 9d800788f1b08800ae810202380a0822 a2a266d0498c3104214a47bd64ab0fc8
b66166c04f8c3109214a4fbd64a50fc8 d9ce0ab605698f320427677b458ad60b e29285e634086352946a0e7090d73106
fcf21c00b30f7e3f83fe0dfd12e71cff 14fef782d02440884392942c11205230 2870a09082c103050810ffdffffe0204
c7088f0f3e6c8088236ef8e1e3e70000 fcf1c3c7cd4491d801f1e1c78f100000 028006030e0e7ebffc7f7070c0600140
00008160000006810000408080010102 03b6e0fcb3499374a867c041f52298f0 1e1e3e00000000000000000000000000
""".split()
CURSOR_NAMES = list(dict.fromkeys(CURSOR_NAMES))
MAIN = "left_ptr"

HOME = os.path.expanduser("~")
ICONS = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")), "icons")
CFG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "chevron-pro-cursor")
SETTINGS = os.path.join(CFG_DIR, "settings.json")
HYPR_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "hypr")
SNIPPET = os.path.join(HYPR_DIR, "chevron-pro-cursor.conf")
PRESETS_FILE = os.path.join(CFG_DIR, "presets.json")
DATA_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")), "chevron-pro-cursor")
ORIGINAL_FILE = os.path.join(DATA_DIR, "original-cursor.json")
BIN_DIR = os.path.join(HOME, ".local", "bin")
APPS_DIR = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(HOME, ".local/share")), "applications")
ICON_FILE = os.path.join(ICONS, "hicolor", "128x128", "apps", "chevron-pro-cursor.png")
DESKTOP_FILE = os.path.join(APPS_DIR, "chevron-pro-cursor.desktop")
WAYBAR_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config")), "waybar")
FALLBACK_CURSOR = ("Adwaita", 24)   # Omarchy's stock cursor

OWNED_MANIFEST = os.path.join(DATA_DIR, "installed-files")
THEME_OWNED_MARKER = ".chevron-pro-cursor"
THEME_OWNED_COMMENT = "Comment=Chevron Pro Cursor"
LEGACY_THEME_COMMENT = "Comment=Chevron sight cursor"      # themes of the old "Chevron Cursor" (v1/v2)

# sha256 of every file a released installer (v1 .. v3.2.x) put in a shared location, by installed name.
# Only used to recognise installs from before the identity manifest; anything else is left alone.
# .desktop entries are hashed as the template, i.e. with the Exec path normalised back to @BIN@.
KNOWN_SHA256 = {
    "chevron-pro-picker": {"ca65cf14bae07f8358a04623d24fd04cf7b9d570d7f1f0bcc02cfabc4abd1419",    # v3.0
                           "f03e1f7d7200264f17935877710687f415eb7ab89bc59f872a6c64b5ac8c4641",    # v3.1, v3.1.1
                           "98b9694c3c4329b993a37c229642a7b6589bbd8c5190cdea7fdfc2759bd788df"},   # v3.2.0
    "chevron-pro-trail": {"b8a9937b2f3aeec3aee7b3a7ad48d936fd340bd5038d31dc373a4abc458cedc3",     # v3.0
                          "be548c45a3af0676cbf5fc1e57f07c1f43e7e397cb41b51caeebd6b0860e1ba9"},    # v3.1 .. v3.2.0
    "chevron-pro-cursor.png": {"f9c96a2928ababf20e555d9a7f0b45815a293b1773d30a47b1e86773c6455aa2"},
    "chevron-pro-cursor.desktop": {"fc4682a88ff31420e4f30e25f61bbbd8bc3440e3453cd421082ba72e8a14e19c"},
    # the old "Chevron Cursor" (v1/v2), incl. the files of its install dir
    "chevron" "-picker": {"c6e7d76b8dd228e18c08b74576ee522c837a0ee4dc05ff55ea114f7edb4ce605"},
    "chevron" "-trail": {"ee86fb8218441d62162b93f58333071388318fada55ede3e77abc50121509ccf"},
    "chevron" "-cursor.png": {"f9c96a2928ababf20e555d9a7f0b45815a293b1773d30a47b1e86773c6455aa2"},
    "chevron" "-cursor.desktop": {"55c6f0f0079924f603b524779a772cd66c4091b1d39c0538ed55211409cbe610"},
    "chevron_core.py": {"6f5f4152b2707adc2b7682706766c1f046a98ac0ba005d29574cba0354567e46"},
    "reload_anim.py": {"270050c66f8ccbdc4ca3f64b10cd60fd552a17160c35f1472b284e2818f3b3c7"},
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _identity(path):
    """What is at path right now: 'link:<exact target>' for a symlink, 'sha256:<hex>' for a regular
    file, None for anything else (missing, folder, device...)."""
    try:
        if os.path.islink(path):
            return "link:" + os.readlink(path)
        if os.path.isfile(path):
            return "sha256:" + _sha256(path)
    except OSError:
        pass
    return None


def _read_manifest():
    """{path: recorded identity} from the ownership manifest, or None if there is none (install from
    before v3.2.1). Entries written by the first manifest version carry no identity (value '')."""
    try:
        with open(OWNED_MANIFEST) as f:
            lines = [l.rstrip("\n") for l in f]
    except OSError:
        return None
    out = {}
    for ln in lines:
        if not ln:
            continue
        path, _tab, ident = ln.partition("\t")
        out[path] = ident
    return out


def write_manifest(paths):
    """Record the identity of every shared path this install placed (used by install.sh)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    rows = [f"{p}\t{_identity(p)}" for p in dict.fromkeys(paths) if p and _identity(p)]
    tmp = OWNED_MANIFEST + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(r + "\n" for r in rows))
    os.replace(tmp, OWNED_MANIFEST)
    return rows


def _legacy_symlinks():
    """The exact symlinks released installers created (path -> target)."""
    return {os.path.join(BIN_DIR, "chevron-pro-cursor"): os.path.join(DATA_DIR, "chevron_core.py"),
            LEGACY["bins"][1]: os.path.join(LEGACY["data_dir"], "chevron_core.py")}


def _legacy_verified(path):
    """No identity on record: ours only if what is there now is exactly what a released Chevron
    installer put at that path (the same symlink target, or a known file hash)."""
    if os.path.islink(path):
        want = _legacy_symlinks().get(path)
        return want is not None and os.readlink(path) == want
    if not os.path.isfile(path):
        return False
    name = os.path.basename(path)
    known = KNOWN_SHA256.get(name)
    if not known:
        return False
    try:
        if name.endswith(".desktop"):
            txt = open(path, "rb").read().decode("utf-8", "surrogateescape")
            txt = txt.replace(os.path.join(DATA_DIR, "chevron-pro-picker"), "@BIN@/chevron-pro-picker")
            txt = txt.replace(BIN_DIR + "/", "@BIN@/")
            digest = hashlib.sha256(txt.encode("utf-8", "surrogateescape")).hexdigest()
        else:
            digest = _sha256(path)
    except OSError:
        return False
    return digest in known


def ownership(path):
    """'absent', 'ours' (verified: what is there now is what Chevron recorded or a release installed),
    'changed' (Chevron installed it, but it has been replaced or edited since) or 'foreign'."""
    if not os.path.lexists(path):
        return "absent"
    m = _read_manifest()
    if m is not None and path not in m:
        return "foreign"                      # the installer skipped it: never ours
    rec = m.get(path) if m is not None else ""
    if rec:
        return "ours" if _identity(path) == rec else "changed"
    # no identity on record (legacy install, or a path-only manifest): only a positive match counts
    return "ours" if _legacy_verified(path) else ("changed" if m is not None else "foreign")


_WHY = {"changed": "changed since Chevron Pro Cursor installed it",
        "foreign": "not verified as installed by Chevron Pro Cursor"}


def _rm_if_ours(path, log, legacy=False):
    """Remove path only if its current identity is verified as ours; otherwise leave it and say so.
    legacy: a path of the old "Chevron Cursor", never in our manifest (verified by known identity only)."""
    if not os.path.lexists(path):
        return
    st = ("ours" if _legacy_verified(path) else "foreign") if legacy else ownership(path)
    if st == "ours":
        _rm(path, log)
    else:
        log.append(f"left {path} in place ({_WHY.get(st, st)})")


def _theme_is_ours(path):
    """True if this theme folder was installed or built by Chevron Pro Cursor (or the old Chevron Cursor)."""
    if not os.path.isdir(path) or os.path.islink(path):
        return False
    if os.path.isfile(os.path.join(path, THEME_OWNED_MARKER)):
        return True
    try:
        with open(os.path.join(path, "index.theme")) as f:
            for line in f:
                if line.startswith((THEME_OWNED_COMMENT, LEGACY_THEME_COMMENT)):
                    return True
    except OSError:
        pass
    return False


# Everything Chevron starts runs from its own install dir (~/.local/share/chevron-pro-cursor), never
# from ~/.local/bin: a shared path can be replaced by anyone after install.
def _bundled(name):
    p = os.path.join(DATA_DIR, name)
    if os.path.isfile(p):
        return p
    here = os.path.join(os.path.dirname(os.path.realpath(__file__)), name)   # running from a checkout
    return here if os.path.isfile(here) else None


def picker_bin():
    return _bundled("chevron-pro-picker")


def cli_bin():
    return os.path.join(DATA_DIR, "chevron_core.py") if os.path.isfile(os.path.join(DATA_DIR, "chevron_core.py")) \
        else os.path.realpath(__file__)


def trail_bin():
    """Trail executable for launch and the Hyprland autostart line (our install dir, even before it exists)."""
    return _bundled("chevron-pro-trail") or os.path.join(DATA_DIR, "chevron-pro-trail")


# ---------------------------------------------------------------- presets
def load_user_presets():
    try:
        with open(PRESETS_FILE) as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {}
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):   # presets saved before v3 have no heartbeat keys: heartbeat off
                v = dict(v)
                for hk in ("heartbeat", "heartbeat_intensity", "heartbeat_bpm", "heartbeat_color_custom", "heartbeat_color"):
                    v.setdefault(hk, DEFAULTS[hk])
                v.setdefault("trail_color_custom", False)   # older presets: trail follows the cursor colors
                out[k] = v
        return out
    except (OSError, ValueError):
        return {}


def save_user_presets(d):
    os.makedirs(CFG_DIR, exist_ok=True)
    tmp = PRESETS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, PRESETS_FILE)


def all_presets():
    """[(name, settings, is_builtin)] built-ins first, then the user's own."""
    return [(n, dict(v), True) for n, v in BUILTIN_PRESETS.items()] + \
           [(n, dict(v), False) for n, v in load_user_presets().items()]


def _norm(n):
    return " ".join(n.lower().replace("/", " ").replace("-", " ").replace("_", " ").split())


def find_preset(name):
    for n, v, b in all_presets():
        if _norm(n) == _norm(name):
            return n, v, b
    return None


def _check_new_name(name, exclude=None):
    name = name.strip()
    if not name:
        raise ValueError("preset name can't be empty")
    if any(name.lower() == n.lower() for n in BUILTIN_PRESETS):
        raise ValueError(f"'{name}' is a built-in preset name")
    if any(name.lower() == n.lower() and n != exclude for n in load_user_presets()):
        raise ValueError(f"a preset called '{name}' already exists")
    return name


def save_preset(name, settings, overwrite=False):
    d = load_user_presets()
    name = name.strip()
    if not (overwrite and name in d):
        name = _check_new_name(name)
    d[name] = {k: settings.get(k, DEFAULTS.get(k)) for k in FULL_KEYS}
    d[name]["trail_color_custom"] = bool(settings.get("trail_color_custom"))
    d[name]["trail_color"] = settings.get("trail_color")
    save_user_presets(d)
    return name


def rename_preset(old, new):
    d = load_user_presets()
    if old not in d:
        raise ValueError(f"'{old}' is not one of your presets (built-ins can't be renamed)")
    new = _check_new_name(new, exclude=old)
    d = {(new if k == old else k): v for k, v in d.items()}   # keep order
    save_user_presets(d)
    return new


def delete_preset(name):
    d = load_user_presets()
    if name not in d:
        raise ValueError(f"'{name}' is not one of your presets (built-ins can't be deleted)")
    del d[name]
    save_user_presets(d)


# ---------------------------------------------------------------- rendering
def hex_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise ValueError(f"bad color {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def edge_rgb(rgb):
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return (255, 255, 255) if lum < 60 else (0, 0, 0)


def clamp_angle(angle):
    return max(ANGLE_MIN, min(ANGLE_MAX, angle))


def geometry(angle, w_frac=0.0):
    """(leg length, tip y) as fractions of size, for line width w_frac (fraction of size).
    Legs shrink so the outer edge of the line (incl. round caps) stays MARGIN away from
    every canvas edge at any opening/thickness; the tip moves down for flat chevrons so
    the shape stays roughly centred (60deg: tall/narrow, 150deg: flat/wide)."""
    a = math.radians(clamp_angle(angle))
    h = w_frac / 2
    L = min(LEG_MAX, (0.5 - MARGIN - h) / math.sin(a), (1 - 2 * MARGIN - 2 * h) / math.cos(a))
    tip_y = max(MARGIN, 0.45 - L * math.cos(a) / 2)
    return L, tip_y


def opts_of(o):
    """Normalise a settings dict (fills defaults, maps the old 'edge' flag)."""
    r = dict(DEFAULTS); r.update({k: v for k, v in (o or {}).items() if v is not None})
    if "edge" in (o or {}) and not o["edge"] and "outline_opacity" not in o:
        r["outline_opacity"] = 0
    r["angle"] = clamp_angle(r["angle"])
    return r


def outline_px(size, o):
    """outline_width 0..100 -> outline px per side, 0 .. one full line width."""
    if o["outline_opacity"] <= 0 or o["outline_width"] <= 0:
        return 0.0
    return max(0.5, o["outline_width"] / 100.0 * stroke_px(size, o["thickness"]))


def outline_rgb(o):
    c = o.get("outline_color")
    return hex_rgb(c) if c else edge_rgb(hex_rgb(o["color"]))


def glow_rgb(o):
    c = o.get("glow_color")
    return hex_rgb(c) if c else hex_rgb(o["color"])


def _dims(size, o):
    w = stroke_px(size, o["thickness"])
    e = outline_px(size, o)
    return w, e


def hotspot(size, o=None):
    o = opts_of(o)
    w, e = _dims(size, o)
    return size // 2, round(geometry(o["angle"], (w + 2 * e) / size)[1] * size)


def stroke_px(size, thickness):
    """thickness 0..100 -> line width in px (about 1.3px .. 13% of size)."""
    t = max(0, min(100, thickness)) / 100.0
    return max(1.3, (0.035 + 0.095 * t) * size)


def glow_layers(glow):
    """glow 0..100 -> neon gaussian layers [(sigma_frac, strength)]. 0 = none."""
    a = max(0, min(100, glow)) / 100.0
    if a <= 0:
        return []
    return [(0.012 + 0.010 * a, 0.6 + 1.2 * a),     # tight bright halo
            (0.025 + 0.030 * a, 0.25 + 1.15 * a),   # body of the bloom
            (0.040 + 0.045 * a, 1.0 * a * a)]       # wide soft haze (only at high settings)


def chevron_mask(size, width_px, angle, core_w, total_w, ss=SS):
    """Antialiased L mask of the two open legs (round caps + round apex), drawn at width_px.
    core_w = main line width (its outer tip sits on the hotspot); total_w = widest stroke
    drawn (line + outline), used so legs are sized to never clip."""
    S = size * ss
    L_frac, tip_y = geometry(angle, total_w / size)
    hx, hy = size // 2, round(tip_y * size)
    ax, ay = (hx + 0.5) * ss, (hy + 0.5) * ss              # centre of the hotspot pixel
    # shift apex centre-line down by core_w/2 so the outer tip of the main line is the hotspot
    ay += core_w * ss / 2 - 0.5 * ss
    w = width_px * ss
    L = L_frac * size * ss
    a = math.radians(clamp_angle(angle))
    pts = [(ax - L * math.sin(a), ay + L * math.cos(a)), (ax, ay), (ax + L * math.sin(a), ay + L * math.cos(a))]
    img = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(img)
    d.line(pts, fill=255, width=max(1, round(w)), joint="curve")
    r = w / 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    # Mirror the left half onto the right so both legs are pixel-identical.
    axis = int(round(ax))
    left = img.crop((0, 0, axis, S))
    img.paste(left.transpose(Image.Transpose.FLIP_LEFT_RIGHT), (axis, 0))
    return img.resize((size, size), Image.LANCZOS)


def _fade(size):
    m = Image.new("L", (size, size))
    data = []
    for y in range(size):
        for x in range(size):
            # distance to the nearest canvas edge, in fractions of size
            dist = min(x + 0.5, y + 0.5, size - x - 0.5, size - y - 0.5) / size
            t = min(1.0, max(0.0, dist * size / max(3.0, 0.08 * size)))
            data.append(int(255 * t * t * (3 - 2 * t)))
    m.putdata(data)
    return m


_FADE_CACHE = {}


# Detailed shapes use thinner strokes so their parts stay readable.
SHAPE_WSCALE = {"default": 1.0, "ew": 0.8, "ns": 0.8, "nwse": 0.8, "nesw": 0.8, "pointer": 0.85, "not-allowed": 0.8,
                "crosshair": 0.75, "cell": 0.85, "move": 0.75, "wait": reload_anim.WSCALE}
DETAIL_WSCALE = 0.62


def shape_dims(size, o, shape="default"):
    w, e = _dims(size, o)
    k = SHAPE_WSCALE.get(shape, DETAIL_WSCALE)
    return max(1.2, w * k), e * k


HB_BOOST_RADIUS = 0.25   # glow radius grows by up to 25 % at the strongest beat
HB_MIN_GLOW = 30         # with the steady glow at 0, the beat still flashes a glow of this strength
HB_GAIN = 1.25           # v3.1: the beat is 25 % stronger at the same intensity setting


def heartbeat_rgb(o):
    """Color of the heartbeat pulse: the custom one when switched on, else the glow color."""
    c = o.get("heartbeat_color")
    return hex_rgb(c) if o.get("heartbeat_color_custom") and c else glow_rgb(o)


def _glow_alpha(size, core, layers, radius=1.0):
    acc = [0.0] * (size * size)
    for sigma, k in layers:
        b = core.filter(ImageFilter.GaussianBlur(max(0.5, sigma * radius * size)))
        for i, v in enumerate(b.tobytes()):
            acc[i] += v * k
    return [255 * (1 - math.exp(-v / 255.0 * 1.4)) for v in acc]


def _compose(size, o, mask_fn, shape="default", pulse=0.0):
    """Shared look: glow (bottom) -> outline -> main line. mask_fn(width_px, total_w) -> L mask.
    pulse 0..1 adds a heartbeat boost ON TOP of the steady glow (0 = exactly the steady glow)."""
    rgb = hex_rgb(o["color"])
    w, e = shape_dims(size, o, shape)
    tw = w + 2 * e
    core = mask_fn(w, tw)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    solid = lambda c, a: Image.merge("RGBA", (*[Image.new("L", (size, size), v) for v in c], a))
    layers = glow_layers(o["glow"])
    if layers or pulse > 0:  # 1) neon glow, bottom layer, from the main line
        vals = _glow_alpha(size, core, layers) if layers else [0.0] * (size * size)
        extra = None
        if pulse > 0:        # boost: + up to 1.25 more full glows, slightly wider
            extra = _glow_alpha(size, core, layers or glow_layers(HB_MIN_GLOW), 1.0 + HB_BOOST_RADIUS * pulse)
            extra = [HB_GAIN * pulse * x for x in extra]
        own = extra is not None and heartbeat_rgb(o) != glow_rgb(o)
        if extra is not None and not own:
            vals = [v + x for v, x in zip(vals, extra)]
        if size not in _FADE_CACHE:
            _FADE_CACHE[size] = _fade(size)

        def layer(vs, rgb):
            g = Image.new("L", (size, size))
            g.putdata([min(255, int(v + 0.5)) for v in vs])
            out.alpha_composite(solid(rgb, ImageChops.multiply(g, _FADE_CACHE[size])))
        layer(vals, glow_rgb(o))
        if own:              # pulse in its own color, blended over the steady glow
            layer(extra, heartbeat_rgb(o))
    if e > 0:   # 2) outline: a clean anti-aliased stroke e px wider on every side, under the line
        ring = ImageChops.subtract(mask_fn(tw, tw), core)
        op = max(0, min(100, o["outline_opacity"])) / 100.0
        out.alpha_composite(solid(outline_rgb(o), ring.point(lambda v: int(v * op + 0.5))))
    out.alpha_composite(solid(rgb, core))   # 3) main line on top
    return out


# ---------------------------------------------------------------- heartbeat glow
HB_BPM_MIN, HB_BPM_MAX = 50, 120
HB_STEP = 30             # ms per frame while a beat is moving
HB_DUB = 0.55            # the 'dub' is ~55 % of the 'lub'


def heartbeat_timing(bpm):
    """-> (loop_ms, lub_to_dub_gap_ms, beat_duration_ms)."""
    bpm = max(HB_BPM_MIN, min(HB_BPM_MAX, int(round(float(bpm)))))
    loop = 60000.0 / bpm
    gap = 230.0 if bpm <= 70 else 230.0 - 30.0 * (bpm - 70) / 50.0     # 230 ms, down to 200 ms at 120 BPM
    dur = min(330.0, loop - gap - 40.0)                                  # each beat fully decays before the rest
    return loop, gap, dur


def _beat(t, dur):
    """One beat: quick rise (20 %), smooth decay to exactly 0 at dur."""
    if t <= 0 or t >= dur:
        return 0.0
    r = 0.2 * dur
    if t < r:
        u = t / r
        return u * u * (3 - 2 * u)
    u = (t - r) / (dur - r)
    return (1 - u * u * (3 - 2 * u)) ** 1.5


def heartbeat_frames(o):
    """-> [(pulse 0..1, delay_ms)] for the main cursor; [] when the heartbeat is off or 0 %.
    Delays sum to round(60000 / bpm) ms."""
    o = opts_of(o)
    k = max(0, min(100, float(o.get("heartbeat_intensity", 50)))) / 100.0
    if not o.get("heartbeat") or k <= 0:
        return []
    loop, gap, dur = heartbeat_timing(o.get("heartbeat_bpm", 60))
    total = int(round(loop))
    end = int(round(gap + dur))
    n = max(1, int(math.ceil(end / float(HB_STEP))))
    times = [round(end * i / n) for i in range(n + 1)]          # frame start times, last = start of rest
    frames = []
    for i in range(n):
        t = times[i]
        level = _beat(t, dur) + HB_DUB * _beat(t - gap, dur)
        frames.append((k * min(1.0, level), times[i + 1] - times[i]))
    frames.append((0.0, total - end))                           # rest: exactly the steady glow
    return frames


# The reload busy cursor (wait/watch/clock) is drawn 25 % bigger on a 25 % bigger canvas (centre hotspot);
# every other cursor keeps the nominal size x size canvas.
SHAPE_CANVAS = {"wait": 1.25}


def shape_canvas(size, shape):
    """Canvas edge (px) of a shape at a nominal cursor size."""
    k = SHAPE_CANVAS.get(shape, 1.0)
    return size if k == 1.0 else int(2 * round(size * k / 2))     # even, so the centre stays exact


def render(size, o=None, shape="default", frame=0, pulse=0.0):
    """Render one cursor shape at a nominal size. o: settings dict.
    Returns an RGBA image of shape_canvas(size, shape) px (size x size except the enlarged reload cursor)."""
    o = opts_of(o)
    size = shape_canvas(size, shape)
    if shape == "default":
        w, _e = _dims(size, o)
        return _compose(size, o, lambda wp, tw: chevron_mask(size, wp, o["angle"], w, tw), pulse=pulse)
    strokes = shape_strokes(shape, o, frame)
    return _compose(size, o, lambda wp, tw: stroke_mask(size, strokes, wp, tw), shape)


# ---------------------------------------------------------------- the full cursor set
# Shapes are drawn as open rounded strokes in unit coordinates (-1..1, y down) that map onto
# the safe area of the canvas (inside MARGIN + half the widest stroke), so nothing clips.
def _arc(cx, cy, r, a0, a1, n=None):
    n = n or max(8, int(abs(a1 - a0) / 8))
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _rot(strokes, deg):
    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[(x * c - y * s_, x * s_ + y * c) for x, y in st] for st in strokes]


def _shift(strokes, dx, dy, k=1.0):
    return [[(x * k + dx, y * k + dy) for x, y in st] for st in strokes]


def _head(tip, dx, dy, ln=0.38, spread=42):
    """Open arrow head (two legs) at tip, pointing along (dx, dy)."""
    a = math.atan2(dy, dx)
    legs = []
    for sgn in (-1, 1):
        b = a + math.pi + sgn * math.radians(spread)
        legs.append((tip[0] + ln * math.cos(b), tip[1] + ln * math.sin(b)))
    return [legs[0], tip, legs[1]]


def _double_arrow():
    return [[(-0.95, 0), (0.95, 0)], _head((-0.95, 0), -1, 0), _head((0.95, 0), 1, 0)]


def _mini_chevron(o):
    """Small chevron (top-left) used by combo cursors; tip at (-0.55, -0.85)."""
    a = math.radians(clamp_angle(o["angle"]))
    L = 0.62
    tip = (-0.55, -0.85)
    return [[(tip[0] - L * math.sin(a), tip[1] + L * math.cos(a)), tip, (tip[0] + L * math.sin(a), tip[1] + L * math.cos(a))]], tip


SPIN_FRAMES = 24   # progress spinner: constant-speed turn, 24 x 33 ms = ~0.8 s per turn
SPIN_DELAY = 33   # ms per frame


def shape_strokes(shape, o, frame=0):
    """Return ([stroke polylines], ...) for a named shape in unit coordinates."""
    if shape == "pointer":      # upward arrow: chevron head + stem, tip = click point
        return [_head((0, -0.95), 0, -1, ln=0.62, spread=38), [(0, -0.95), (0, 0.95)]]
    if shape == "ew":
        return _double_arrow()
    if shape == "ns":
        return _rot(_double_arrow(), 90)
    if shape == "nwse":
        return _shift(_rot(_double_arrow(), 45), 0, 0, 0.92)
    if shape == "nesw":
        return _shift(_rot(_double_arrow(), -45), 0, 0, 0.92)
    if shape == "move":         # 4-way
        st = [[(-0.95, 0), (0.95, 0)], [(0, -0.95), (0, 0.95)]]
        return st + [_head((-0.95, 0), -1, 0, 0.32), _head((0.95, 0), 1, 0, 0.32), _head((0, -0.95), 0, -1, 0.32), _head((0, 0.95), 0, 1, 0.32)]
    if shape == "text":         # I-beam with gently curved serifs (symmetric)
        top = [(-0.4, -0.95), (-0.2, -0.86), (0, -0.82), (0.2, -0.86), (0.4, -0.95)]
        return [[(0, -0.82), (0, 0.82)], top, [(x, -y) for x, y in top]]
    if shape == "vtext":
        return _rot(shape_strokes("text", o), 90)
    if shape == "wait":         # reload loop: mag out, empty hold, new mag, rack, settle, rest
        return [pts for pts, _a in reload_anim.reload_strokes(frame)]
    if shape == "progress":     # mini chevron + small spinner
        ch, _ = _mini_chevron(o)
        a0 = frame * 360.0 / SPIN_FRAMES
        return ch + [_arc(0.48, 0.48, 0.42, a0, a0 + 270, 40)]
    if shape == "not-allowed":
        return [_arc(0, 0, 0.82, 0, 360, 48), [(-0.58, 0.58), (0.58, -0.58)]]
    if shape == "crosshair":
        g = 0.24
        return [[(-0.95, 0), (-g, 0)], [(g, 0), (0.95, 0)], [(0, -0.95), (0, -g)], [(0, g), (0, 0.95)]]
    if shape == "cell":
        return [[(-0.75, 0), (0.75, 0)], [(0, -0.75), (0, 0.75)]]
    if shape == "help":         # mini chevron + question mark
        ch, _ = _mini_chevron(o)
        q = _arc(0.45, 0.12, 0.3, 180, 360 + 45, 20) + [(0.45, 0.62)]
        return ch + [q, [(0.45, 0.92), (0.45, 0.92)]]
    if shape == "copy":         # mini chevron + plus badge
        ch, _ = _mini_chevron(o)
        return ch + [[(0.15, 0.5), (0.85, 0.5)], [(0.5, 0.15), (0.5, 0.85)]]
    if shape == "alias":        # mini chevron + curved link arrow
        ch, _ = _mini_chevron(o)
        arc = _arc(0.55, 0.85, 0.55, 180, 270, 12)
        return ch + [arc, _head(arc[-1], 1, 0, 0.26)]
    if shape == "context-menu":  # mini chevron + menu lines
        ch, _ = _mini_chevron(o)
        return ch + [[(0.15, y), (0.85, y)] for y in (0.1, 0.5, 0.9)]
    if shape in ("zoom-in", "zoom-out"):
        st = [_arc(-0.2, -0.2, 0.62, 0, 360, 44), [(0.24, 0.24), (0.88, 0.88)], [(-0.5, -0.2), (0.1, -0.2)]]
        if shape == "zoom-in":
            st.append([(-0.2, -0.5), (-0.2, 0.1)])
        return st
    if shape == "grab":         # open hand: four fingers over a palm curve
        st = [_arc(0, 0.25, 0.62, 0, 180, 20)]
        for x, top in ((-0.62, -0.25), (-0.21, -0.75), (0.21, -0.75), (0.62, -0.25)):
            st.append([(x, top), (x, 0.25)])
        return st
    if shape == "grabbing":     # closed hand: short knuckles over palm
        st = [_arc(0, 0.1, 0.62, 0, 180, 20)]
        for x in (-0.62, -0.21, 0.21, 0.62):
            st.append([(x, -0.2), (x, 0.1)])
        return st
    if shape == "pencil":       # pencil outline, tip at bottom-left
        body = [(-0.9, 0.9), (-0.65, 0.25), (0.55, -0.95), (0.95, -0.55), (-0.25, 0.65), (-0.9, 0.9)]
        return [body, [(-0.65, 0.25), (-0.25, 0.65)]]
    raise KeyError(shape)


# hotspot (unit coords) per shape; default handled by the chevron geometry
SHAPE_HOT = {"pointer": (0, -0.95), "progress": None, "help": None, "copy": None, "alias": None,
             "context-menu": None, "pencil": (-0.9, 0.9), "zoom-in": (-0.2, -0.2), "zoom-out": (-0.2, -0.2)}
SHAPE_KIND = {"default": "tip", "pointer": "tip", "progress": "tip", "help": "tip", "copy": "tip", "alias": "tip",
              "context-menu": "tip", "pencil": "tip"}   # others: "center"
ANIMATED = {"wait", "progress"}


def anim_delays(shape):
    """Per-frame delays (ms) for an animated shape; the frame count is len() of this list."""
    if shape == "wait":
        return reload_anim.frame_delays()
    return [SPIN_DELAY] * SPIN_FRAMES


def _unit_scale(size, total_w):
    return (0.5 - MARGIN) * size - total_w / 2.0


def stroke_mask(size, strokes, width_px, total_w, ss=SS):
    S = size * ss
    c = (size // 2 + 0.5) * ss
    k = _unit_scale(size, total_w) * ss
    img = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(img)
    w = width_px * ss
    r = w / 2
    for st in strokes:
        pts = [(c + x * k, c + y * k) for x, y in st]
        if len(pts) > 1:
            d.line(pts, fill=255, width=max(1, round(w)), joint="curve")
        for x, y in pts:
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    return img.resize((size, size), Image.LANCZOS)


def shape_hotspot(size, o, shape):
    o = opts_of(o)
    if shape == "default":
        return hotspot(size, o)
    size = shape_canvas(size, shape)
    w, e = shape_dims(size, o, shape)
    u = SHAPE_HOT.get(shape, (0.0, 0.0))
    if u is None:
        u = _mini_chevron(o)[1]
    k = _unit_scale(size, w + 2 * e)
    c = size // 2 + 0.5
    return int(math.floor(c + u[0] * k)), int(math.floor(c + u[1] * k))


# cursor name -> shape (X11 names, CSS / cursor-shape-v1 names, KDE/GNOME aliases, legacy hashes)
NAME_MAP = {
    "default": ["default", "left_ptr", "arrow", "top_left_arrow", "right_ptr", "center_ptr", "dnd-none", "draft_large", "draft_small"],
    "pointer": ["pointer", "hand", "hand1", "hand2", "pointing_hand", "9d800788f1b08800ae810202380a0822", "e29285e634086352946a0e7090d73106"],
    "text": ["text", "xterm", "ibeam"],
    "vtext": ["vertical-text"],
    "wait": ["wait", "watch", "clock"],
    "progress": ["progress", "left_ptr_watch", "half-busy", "08e8e1c95fe2fc01f976f1e063a24ccd", "3ecb610c1bf2410f44200f48c40d3599", "00000000000000020006000e7e9ffc3f"],
    "help": ["help", "question_arrow", "whats_this", "left_ptr_help", "gumby", "5c6cd98b3f3ebcb1f9c7f1c204630408", "d9ce0ab605698f320427677b458ad60b"],
    "context-menu": ["context-menu", "dnd-ask"],
    "copy": ["copy", "dnd-copy", "1081e37283d90000800003c07f3ef6bf", "6407b0e94181790501fd1e167b474872", "b66166c04f8c3109214a4fbd64a50fc8"],
    "alias": ["alias", "link", "dnd-link", "3085a0e285430894940527032f8b26df", "640fb0e74195791501fd1ed57b41487f", "a2a266d0498c3104214a47bd64ab0fc8"],
    "not-allowed": ["not-allowed", "no-drop", "dnd-no-drop", "forbidden", "crossed_circle", "circle", "pirate", "X_cursor", "03b6e0fcb3499374a867c041f52298f0"],
    "crosshair": ["crosshair", "cross", "tcross", "cross_reverse", "diamond_cross", "target", "dotbox", "draped_box", "icon", "color-picker"],
    "cell": ["cell", "plus"],
    "move": ["move", "all-scroll", "fleur", "size_all", "dnd-move", "4498f0e0c1937ffe01fd06f973665830", "9081237383d90e509aa00f00170e968f", "fcf21c00b30f7e3f83fe0dfd12e71cff"],
    "grab": ["grab", "openhand"],
    "grabbing": ["grabbing", "closedhand", "dragging"],
    "ew": ["ew-resize", "col-resize", "e-resize", "w-resize", "left_side", "right_side", "sb_h_double_arrow", "h_double_arrow",
           "size_hor", "size-hor", "split_h", "left_tee", "right_tee", "sb_left_arrow", "sb_right_arrow",
           "028006030e0e7ebffc7f7070c0600140", "14fef782d02440884392942c11205230"],
    "ns": ["ns-resize", "row-resize", "n-resize", "s-resize", "top_side", "bottom_side", "sb_v_double_arrow", "v_double_arrow",
           "size_ver", "size-ver", "split_v", "top_tee", "bottom_tee", "sb_up_arrow", "sb_down_arrow", "up-arrow", "down-arrow",
           "based_arrow_up", "based_arrow_down", "double_arrow", "00008160000006810000408080010102", "2870a09082c103050810ffdffffe0204"],
    "nwse": ["nwse-resize", "nw-resize", "se-resize", "top_left_corner", "bottom_right_corner", "ul_angle", "lr_angle",
             "size_fdiag", "size-fdiag", "bd_double_arrow", "c7088f0f3e6c8088236ef8e1e3e70000"],
    "nesw": ["nesw-resize", "ne-resize", "sw-resize", "top_right_corner", "bottom_left_corner", "ur_angle", "ll_angle",
             "size_bdiag", "size-bdiag", "fd_double_arrow", "fcf1c3c7cd4491d801f1e1c78f100000"],
    "zoom-in": ["zoom-in"],
    "zoom-out": ["zoom-out"],
    "pencil": ["pencil"],
}
SHAPES = list(NAME_MAP)


# ---------------------------------------------------------------- writers
def _premul(img):
    raw = img.tobytes()
    buf = bytearray()
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i:i + 4]
        buf += struct.pack("<I", (a << 24) | ((r * a + 127) // 255 << 16) | ((g * a + 127) // 255 << 8) | ((b * a + 127) // 255))
    return bytes(buf)


def write_xcursor(path, frames):
    n = len(frames)
    toc, chunks, pos = b"", b"", 16 + 12 * n
    for fr in frames:
        size, img, xh, yh = fr[:4]
        delay = fr[4] if len(fr) > 4 else 0
        c = struct.pack("<9I", 36, 0xFFFD0002, size, 1, img.width, img.height, xh, yh, delay) + _premul(img)
        toc += struct.pack("<3I", 0xFFFD0002, size, pos)
        chunks += c
        pos += len(c)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(struct.pack("<4s3I", b"Xcur", 16, 0x10000, n) + toc + chunks)
    os.replace(tmp, path)


def build_theme(outdir, name, o, sizes=SIZES):
    o = opts_of(o)
    tdir = os.path.join(outdir, name)
    stage = tdir + ".building"
    shutil.rmtree(stage, ignore_errors=True)
    cdir = os.path.join(stage, "cursors")
    os.makedirs(cdir)
    hb = heartbeat_frames(o)
    for shape, names in NAME_MAP.items():
        frames = []
        for sz in sizes:
            hx, hy = shape_hotspot(sz, o, shape)
            if shape == "default" and hb:
                for pulse, delay in hb:
                    frames.append((sz, render(sz, o, shape, pulse=pulse), hx, hy, delay))
            elif shape in ANIMATED:
                for f, delay in enumerate(anim_delays(shape)):
                    frames.append((sz, render(sz, o, shape, f), hx, hy, delay))
            else:
                frames.append((sz, render(sz, o, shape), hx, hy))
        main = names[0] if shape != "default" else MAIN
        write_xcursor(os.path.join(cdir, main), frames)
        for n in names:
            if n != main and not os.path.lexists(os.path.join(cdir, n)):
                os.symlink(main, os.path.join(cdir, n))
    with open(os.path.join(stage, "index.theme"), "w") as f:
        f.write(f"[Icon Theme]\nName={name}\nComment={APP_NAME} (click point = chevron tip)\nInherits=Adwaita\n")
        if hb:
            f.write(f"X-ChevronPro-Heartbeat-Loop-ms={sum(d for _p_, d in hb)}\n")
    shutil.rmtree(tdir, ignore_errors=True)
    os.replace(stage, tdir)
    return tdir


# ---------------------------------------------------------------- settings / apply / reset
def load_settings():
    s = dict(DEFAULTS); s.update(TRAIL_DEFAULTS)
    raw = {}
    try:
        with open(SETTINGS) as f:
            raw = json.load(f)
        s.update(raw)
    except (OSError, ValueError):
        pass
    if raw and "trail_sens_v" not in raw:
        s["trail_sens_v"] = 1          # written by v1/v2: migrated just below
    s.pop("hyprcursor", None)
    if s.pop("edge", True) is False and "outline_opacity" not in s:
        s["outline_opacity"] = 0
    if s.get("trail_sens_v", 1) < 2:        # settings from v1/v2: 120 Hz sampling -> 240 Hz; slider position kept
        s["trail_rate"] = max(240, s.get("trail_rate", 240)); s["trail_sens_v"] = 2
    return s


def save_settings(s):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(SETTINGS, "w") as f:
        json.dump(s, f, indent=2)


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def _gsettings_get(key):
    ok, out = _run(["gsettings", "get", "org.gnome.desktop.interface", key])
    return out.strip("'") if ok else None


SNIPPET_LUA = os.path.join(HYPR_DIR, "chevron-pro-cursor.lua")
APP_ID = "com.chevronpro.Cursor"
LUA_BEGIN = "-- >>> chevron-pro-cursor (added by Chevron Pro Cursor; its uninstaller removes this block)"
LUA_END = "-- <<< chevron-pro-cursor"
BAR_STATE = os.path.join(DATA_DIR, "bar.json")


def _hypr_conf():
    return os.path.join(HYPR_DIR, "hyprland.conf")


def _hypr_lua():
    """Omarchy 4.x ('quattro') configures Hyprland in Lua: ~/.config/hypr/hyprland.lua."""
    return os.path.join(HYPR_DIR, "hyprland.lua")


def _lua_include():
    return f"{LUA_BEGIN}\npcall(dofile, {json.dumps(SNIPPET_LUA)})\n{LUA_END}"


def _set_include(enabled):
    """Load our snippet from the user's Hyprland config: `source = ...` in hyprland.conf and/or a
    guarded dofile() block in hyprland.lua (whichever exist). enabled=False removes them."""
    conf = _hypr_conf()
    line = f"source = {SNIPPET}"
    if os.path.exists(conf):
        with open(conf) as f:
            lines = f.read().splitlines()
        has = line in lines
        if enabled and not has:
            with open(conf, "w") as f:
                f.write("\n".join(lines + ["", line]) + "\n")
        elif not enabled and has:
            _remove_source_line(SNIPPET, [])
    lua = _hypr_lua()
    if os.path.exists(lua):
        txt = open(lua).read()
        has = LUA_BEGIN in txt
        if enabled and not has:
            with open(lua, "w") as f:
                f.write(txt + ("" if txt.endswith("\n") or not txt else "\n") + "\n" + _lua_include() + "\n")
        elif not enabled and has:
            _remove_lua_include([])


def _remove_lua_include(log):
    lua = _hypr_lua()
    if not os.path.exists(lua):
        return
    txt = open(lua).read()
    new = re.sub(r"\n?" + re.escape(LUA_BEGIN) + r".*?" + re.escape(LUA_END) + r"\n?", "", txt, flags=re.S)
    if new != txt:
        if txt.endswith("\n") and not new.endswith("\n") and new:
            new += "\n"
        with open(lua, "w") as f:
            f.write(new)
        log.append(f"removed the Chevron Pro Cursor block from {lua}")


def _hypr_version():
    """(major, minor) of the running/installed Hyprland, or None."""
    for cmd in (["hyprctl", "version", "-j"], ["hyprctl", "version"], ["Hyprland", "--version"]):
        if not shutil.which(cmd[0]):
            continue
        ok, out = _run(cmd)
        m = re.search(r"\bv?(\d+)\.(\d+)\.\d+", out or "") if ok else None
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def _rule_lines():
    """Settings window: floating, centred, compact (it otherwise fills the screen when tiled)."""
    cls = r"^(com\.chevronpro\.Cursor)$"
    v = _hypr_version()
    head = "# Chevron Pro Cursor settings window: floating, centred, %d%% of the monitor width, %d%% of its height" % (
        round(WIN_W_FRAC * 100), round(WIN_H_FRAC * 100))
    pw, ph = round(WIN_W_FRAC * 100), round(WIN_H_FRAC * 100)
    if v is not None and v < (0, 53):          # Hyprland before 0.53: windowrulev2 syntax
        return [head, f"windowrulev2 = float, class:{cls}", f"windowrulev2 = size {pw}% {ph}%, class:{cls}",
                f"windowrulev2 = center, class:{cls}"]
    return [head, f"windowrule = float on, match:class {cls}", f"windowrule = size (monitor_w*{WIN_W_FRAC:g}) (monitor_h*{WIN_H_FRAC:g}), match:class {cls}",
            f"windowrule = center on, match:class {cls}"]


def _hypr_state():
    """-> (theme, size, trail) currently written in our snippet (theme None = no cursor override)."""
    theme = size = None
    trail = False
    for path in (SNIPPET, SNIPPET_LUA):
        if not os.path.exists(path):
            continue
        txt = open(path).read()
        m = re.search(r"^env = XCURSOR_THEME,(.+)$", txt, re.M) or re.search(r'hl\.env\("XCURSOR_THEME", "([^"]+)"\)', txt)
        n = re.search(r"^env = XCURSOR_SIZE,(\d+)", txt, re.M) or re.search(r'hl\.env\("XCURSOR_SIZE", "(\d+)"\)', txt)
        if m and n:
            theme, size = m.group(1).strip(), int(n.group(1))
        trail = trail or "chevron-pro-trail" in txt
        break
    return theme, size, trail


def _write_hypr(theme, size, trail):
    """(Re)write ~/.config/hypr/chevron-pro-cursor.conf (and .lua on Omarchy 4.x / Lua configs) and make
    sure the user's Hyprland config loads it. The window rule is always there while the app is installed."""
    os.makedirs(HYPR_DIR, exist_ok=True)
    lines = ["# Written by Chevron Pro Cursor (regenerated by the app; changes here are overwritten)"]
    if theme:
        lines += [f"env = XCURSOR_THEME,{theme}", f"env = XCURSOR_SIZE,{size}", f"exec-once = hyprctl setcursor {theme} {size}"]
    if trail:
        lines.append(f"exec-once = {trail_bin()}")
    lines += [""] + _rule_lines()
    with open(SNIPPET, "w") as f:
        f.write("\n".join(lines) + "\n")
    if os.path.exists(_hypr_lua()):
        q = json.dumps
        L = ["-- Written by Chevron Pro Cursor (regenerated by the app; changes here are overwritten)"]
        if theme:
            L += [f"hl.env(\"XCURSOR_THEME\", {q(theme)})", f"hl.env(\"XCURSOR_SIZE\", {q(str(size))})"]
        start = []
        if theme:   # Omarchy 4.x restores the cursor itself after its startup cursor (from XCURSOR_THEME above)
            start.append(f"  if omarchy_startup_cursor == nil then hl.exec_cmd({q(f'hyprctl setcursor {theme} {size}')}) end")
        if trail:
            start.append(f"  hl.exec_cmd({q(trail_bin())})")
        if start:
            L += ["hl.on(\"hyprland.start\", function()"] + start + ["end)"]
        L += [f"-- settings window: floating, centred, compact ({WIN_W_FRAC:g} x monitor width, {WIN_H_FRAC:g} x height)",
              "hl.window_rule({ match = { class = " + q(r"^(com\.chevronpro\.Cursor)$") + " }, float = true, center = true, "
              f"size = \"monitor_w*{WIN_W_FRAC:g} monitor_h*{WIN_H_FRAC:g}\" }})"]
        with open(SNIPPET_LUA, "w") as f:
            f.write("\n".join(L) + "\n")
    _set_include(True)


def _set_default_inherit(theme):
    d = os.path.join(ICONS, "default")
    p = os.path.join(d, "index.theme")
    os.makedirs(d, exist_ok=True)
    if os.path.exists(p):
        txt = open(p).read()
        if NEW_MARKER not in txt and LEGACY["marker"] not in txt and not os.path.exists(p + ".bak"):
            shutil.copy(p, p + ".bak")
    with open(p, "w") as f:
        f.write(f"[Icon Theme]\n{NEW_MARKER}\nInherits={theme}\n")


def apply(settings, theme=THEME_NAME):
    """Build + install + activate. Returns a list of log lines."""
    log = []
    s = settings
    if "previous" not in s:   # remember what to go back to on Reset
        s["previous"] = {"theme": _gsettings_get("cursor-theme") or os.environ.get("XCURSOR_THEME") or "Adwaita",
                         "size": int(_gsettings_get("cursor-size") or os.environ.get("XCURSOR_SIZE") or 24)}
    s.pop("hyprcursor", None)
    cleanup_hyprcursor_leftovers()
    build_theme(ICONS, theme, s)
    log.append(f"Installed {theme} -> {os.path.join(ICONS, theme)}")
    log += activate(theme, int(s["size"]), s["previous"]["theme"])
    save_settings(s)
    return log


def cleanup_hyprcursor_leftovers():
    """Remove files/settings left by the old experimental Hyprcursor option (XCursor only now)."""
    removed = []
    if os.path.isdir(ICONS):
        for t in os.listdir(ICONS):
            if t.startswith("ChevronPro"):
                for leftover in ("hyprcursors", "manifest.hl", "manifest.toml"):
                    p = os.path.join(ICONS, t, leftover)
                    if os.path.isdir(p):
                        shutil.rmtree(p); removed.append(p)
                    elif os.path.exists(p):
                        os.remove(p); removed.append(p)
    if os.path.exists(SNIPPET):
        lines = open(SNIPPET).read().splitlines()
        keep = [l for l in lines if "HYPRCURSOR_" not in l]
        if keep != lines:
            with open(SNIPPET, "w") as f:
                f.write("\n".join(keep) + "\n")
            removed.append(SNIPPET + " (HYPRCURSOR_* lines)")
    if os.path.exists(SETTINGS):
        try:
            d = json.load(open(SETTINGS))
            if "hyprcursor" in d:
                d.pop("hyprcursor"); save_settings(d); removed.append(SETTINGS + " (hyprcursor flag)")
        except ValueError:
            pass
    return removed


TRAIL_DEFAULTS = {"trail_enabled": False, "trail_length": 200, "trail_fade": 160, "trail_width": 6,
                  "trail_softness": 75, "trail_opacity": 35, "trail_sensitivity": 60, "trail_color": None, "trail_rate": 240,
                  "trail_sens_v": 2, "trail_color_custom": False}
# trail_color_custom False (and in every settings file written before it existed): the trail is a motion
# blur of the cursor itself, in the cursor's own colors. True: tinted with trail_color.
TRAIL_KEYS = tuple(TRAIL_DEFAULTS)


def trail_threshold(sens):
    """Same curve as chevron-pro-trail: sensitivity 0..100 -> px/s (0 -> 3800, 60 -> ~1750, 100 -> 0)."""
    x = 1.0 - max(0.0, min(100.0, float(sens))) / 100.0
    return 3800.0 * (math.exp(-0.5 * x) - 1.0) / (math.exp(-0.5) - 1.0)


def set_trail_autostart(enabled):
    """Start the trail at login (or not): rewrites our Hyprland snippet, keeping the cursor part."""
    theme, size, _trail = _hypr_state()
    _write_hypr(theme, size, enabled)


def save_trail_settings(values):
    """Merge only trail_* keys into settings.json (the trail daemon live-reloads them)."""
    d = {}
    try:
        d = json.load(open(SETTINGS))
    except (OSError, ValueError):
        pass
    d.update({k: v for k, v in values.items() if k in TRAIL_KEYS})
    save_settings(d)


def trail_running():
    ok, out = _run(["pgrep", "-f", "chevron-pro-trail"])
    return ok and bool(out.strip())


def start_trail():
    bin_ = trail_bin()
    if bin_ and not trail_running() and os.path.exists(bin_):
        subprocess.Popen([bin_], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def stop_trail():
    # the daemon exits by itself when trail_enabled becomes false; this is the fallback
    _run(["pkill", "-f", "chevron-pro-trail"])


# ---------------------------------------------------------------- migration from the old name (v1/v2)
# Versions before 3.0 were called "Chevron Cursor". These paths are only used to migrate and clean up.
_OLD_SLUG = "chevron" + "-cursor"
LEGACY = {
    "cfg_dir": os.path.join(os.path.dirname(CFG_DIR), "sight" + "-cursor"),
    "data_dir": os.path.join(os.path.dirname(DATA_DIR), _OLD_SLUG),
    "bins": [os.path.join(BIN_DIR, n) for n in ("chevron" + "-picker", _OLD_SLUG, "chevron" + "-trail")],
    "desktop": os.path.join(APPS_DIR, _OLD_SLUG + ".desktop"),
    "icon": os.path.join(os.path.dirname(ICON_FILE), _OLD_SLUG + ".png"),
    "snippet": os.path.join(HYPR_DIR, "sight" + "-cursor.conf"),
    "theme_prefix": "Sight" + "-Chevron",
    "marker": "# sight" + "-cursor",
    "process": "chevron" + "-trail",
    "waybar_module": "custom/" + _OLD_SLUG,
}
NEW_MARKER = "# chevron-pro-cursor"


def _rm(path, log, label=None):
    if os.path.islink(path) or os.path.isfile(path):
        os.remove(path); log.append(f"removed {label or path}")
    elif os.path.isdir(path):
        shutil.rmtree(path); log.append(f"removed {label or path}")


def _remove_source_line(snippet_path, log):
    conf = os.path.join(HYPR_DIR, "hyprland.conf")
    if not os.path.exists(conf):
        return
    lines = open(conf).read().splitlines()
    out = []
    for l in lines:
        if l.strip() == f"source = {snippet_path}":
            if out and not out[-1].strip():
                out.pop()                    # the blank line we added before it
            continue
        out.append(l)
    if out != lines:
        with open(conf, "w") as f:
            f.write("\n".join(out) + ("\n" if out else ""))
        log.append(f"removed 'source = {snippet_path}' from {conf}")


def _bar():
    import chevron_bar
    chevron_bar.WAYBAR_DIR = WAYBAR_DIR
    return chevron_bar


def bar_remove(log, do_restart=True):
    """Remove the top-bar button (Waybar and/or omarchy-shell), incl. the old v2 module. Idempotent."""
    try:
        log += _bar().remove(BAR_STATE, do_restart=do_restart)
    except ImportError:
        pass


def bar_launch_cmd():
    cli = cli_bin() or os.path.join(DATA_DIR, "chevron_core.py")
    return f"{cli} open"


def open_app():
    """Start the settings app detached (used by the bar button): uwsm app in a uwsm session, else setsid."""
    picker = picker_bin()
    if not picker or not os.path.isfile(picker):
        raise SystemExit(f"can't open the settings: {os.path.join(DATA_DIR, 'chevron-pro-picker')} is missing (reinstall with ./install.sh)")
    cmd = [picker]
    if shutil.which("uwsm") and _run(["uwsm", "check", "is-active"])[0]:
        cmd = ["uwsm", "app", "--", picker]
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)
    return cmd


def _merge_presets(src, dst):
    try:
        old = json.load(open(src))
    except (OSError, ValueError):
        return 0
    try:
        cur = json.load(open(dst))
    except (OSError, ValueError):
        cur = {}
    n = 0
    for k, v in old.items():
        if k not in cur:
            cur[k] = v; n += 1
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w") as f:
        json.dump(cur, f, indent=2)
    return n


def _rm_legacy_data_dir(log, notes):
    """The old install dir (~/.local/share/chevron-cursor): remove only the files the old installer
    put there (known hashes) and Python's caches of them; keep the folder if anything else is inside."""
    d = LEGACY["data_dir"]
    if os.path.islink(d) or not os.path.isdir(d):
        if os.path.lexists(d):
            notes.append(f"left {d} in place ({_WHY['foreign']})")
        return
    for n in ("chevron_core.py", "reload_anim.py"):
        f = os.path.join(d, n)
        if os.path.lexists(f) and _legacy_verified(f):
            os.remove(f)
    cache = os.path.join(d, "__pycache__")
    if os.path.isdir(cache) and not os.path.islink(cache):
        for n in os.listdir(cache):
            if re.fullmatch(r"(chevron_core|reload_anim)\.[\w-]+(\.opt-\d)?\.pyc", n):
                os.remove(os.path.join(cache, n))
        if not os.listdir(cache):
            os.rmdir(cache)
    if os.listdir(d):
        notes.append(f"left {d} in place (holds files not installed by Chevron Cursor)")
    else:
        os.rmdir(d); log.append(f"removed {d}")


def migrate_legacy():
    """Move an old "Chevron Cursor" (v1/v2) install over to Chevron Pro Cursor. Idempotent.
    Returns (log lines, whether the old cursor was active)."""
    log, was_active = [], False
    L = LEGACY
    # 1) settings + presets (never lose custom presets)
    if os.path.isdir(L["cfg_dir"]):
        os.makedirs(CFG_DIR, exist_ok=True)
        old_s = os.path.join(L["cfg_dir"], "settings.json")
        if os.path.exists(old_s) and not os.path.exists(SETTINGS):
            d = json.load(open(old_s))
            prev = d.get("previous", {})
            if str(prev.get("theme", "")).startswith((L["theme_prefix"], THEME_NAME)):
                d["previous"] = {"theme": FALLBACK_CURSOR[0], "size": FALLBACK_CURSOR[1]}
            save_settings(d); log.append(f"migrated settings {old_s} -> {SETTINGS}")
        n = _merge_presets(os.path.join(L["cfg_dir"], "presets.json"), PRESETS_FILE)
        if n:
            log.append(f"migrated {n} saved preset(s) -> {PRESETS_FILE}")
        keep = os.path.join(CFG_DIR, "migrated-from-v2")
        if not os.path.exists(keep):
            shutil.copytree(L["cfg_dir"], keep)
        shutil.rmtree(L["cfg_dir"]); log.append(f"moved {L['cfg_dir']} (a copy is in {keep})")
    # 2) old daemon + autostart + Hyprland include
    if _run(["pgrep", "-f", L["process"]])[0]:
        _run(["pkill", "-f", L["process"]]); log.append("stopped the old trail daemon")
    if os.path.exists(L["snippet"]):
        was_active = "XCURSOR_THEME" in open(L["snippet"]).read()
        _rm(L["snippet"], log)
    _remove_source_line(L["snippet"], log)
    # 3) old app files: only ones still exactly as the old installer left them
    notes = []
    for b in L["bins"] + [L["desktop"], L["icon"]]:
        if os.path.lexists(b) and not _legacy_verified(b):
            notes.append(f"left {b} in place ({_WHY['foreign']})")
        elif os.path.lexists(b):
            _rm(b, log)
    _rm_legacy_data_dir(log, notes)
    # 4) old themes (the new ChevronPro themes replace them), only folders the old version made
    if os.path.isdir(ICONS):
        for t in sorted(os.listdir(ICONS)):
            if t.startswith(L["theme_prefix"]):
                if _theme_is_ours(os.path.join(ICONS, t)):
                    _rm(os.path.join(ICONS, t), log, f"old theme {t}")
                else:
                    notes.append(f"left {os.path.join(ICONS, t)} in place ({_WHY['foreign']})")
    p = os.path.join(ICONS, "default", "index.theme")
    if os.path.exists(p) and L["marker"] in open(p).read():
        with open(p, "w") as f:          # re-pointed at ChevronPro below if the cursor was active
            f.write(f"[Icon Theme]\n{NEW_MARKER}\nInherits={FALLBACK_CURSOR[0]}\n")
    if log:                              # only when an old v1/v2 install was found; a Chevron Pro
        bar_remove(log)                  # upgrade (e.g. v3 -> v3.1) keeps the bar button
    return log + notes, was_active


# ---------------------------------------------------------------- install state / uninstall
def record_original(created_dirs=()):
    """At first install: remember the user's cursor (to restore on uninstall) and which folders we create."""
    if os.path.exists(ORIGINAL_FILE):
        return False
    theme = _gsettings_get("cursor-theme") or os.environ.get("XCURSOR_THEME") or FALLBACK_CURSOR[0]
    try:
        size = int(_gsettings_get("cursor-size") or os.environ.get("XCURSOR_SIZE") or FALLBACK_CURSOR[1])
    except ValueError:
        size = FALLBACK_CURSOR[1]
    if theme.startswith((THEME_NAME, LEGACY["theme_prefix"])):   # an older install is active: use what it recorded
        theme, size = FALLBACK_CURSOR
        for f in (SETTINGS, os.path.join(LEGACY["cfg_dir"], "settings.json")):
            try:
                prev = json.load(open(f)).get("previous")
                if prev and not str(prev["theme"]).startswith((THEME_NAME, LEGACY["theme_prefix"])):
                    theme, size = prev["theme"], int(prev["size"]); break
            except (OSError, ValueError, KeyError):
                pass
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ORIGINAL_FILE, "w") as f:
        json.dump({"theme": theme, "size": size, "created_dirs": [d for d in created_dirs if d]}, f, indent=2)
    return True


def uninstall(purge=None, interactive=True):
    """Remove everything Chevron Pro Cursor (and the old Chevron Cursor) installed. Idempotent.
    purge: True = also delete settings + presets, False = keep them, None = ask (when interactive)."""
    log = []
    try:
        orig = json.load(open(ORIGINAL_FILE))
    except (OSError, ValueError):
        orig = {}
    s = load_settings() if os.path.exists(SETTINGS) else {}
    theme, size = orig.get("theme"), orig.get("size")
    if not theme:
        prev = s.get("previous") or {}
        theme, size = prev.get("theme"), prev.get("size")
    if not theme or str(theme).startswith((THEME_NAME, LEGACY["theme_prefix"])):
        theme, size = FALLBACK_CURSOR
    size = int(size or FALLBACK_CURSOR[1])
    # trail
    for proc in ("chevron-pro-trail", LEGACY["process"]):
        if _run(["pgrep", "-f", proc])[0]:
            _run(["pkill", "-f", proc]); log.append(f"stopped {proc}")
    # Hyprland: snippet (env, exec-once autostart, trail) + the source line, new and old names
    for snip in (SNIPPET, LEGACY["snippet"]):
        _rm(snip, log)
        _remove_source_line(snip, log)
    _rm(SNIPPET_LUA, log)
    _remove_lua_include(log)
    # restore the original cursor everywhere (only if ours is or was in use: a second run changes nothing)
    cur = _gsettings_get("cursor-theme") or ""
    ours_active = bool(orig) or any("restored" in l or os.path.basename(SNIPPET) in l or os.path.basename(LEGACY["snippet"]) in l for l in log) \
        or cur.startswith((THEME_NAME, LEGACY["theme_prefix"]))
    if ours_active and shutil.which("hyprctl"):
        _run(["hyprctl", "setcursor", theme, str(size)]); log.append(f"hyprctl setcursor {theme} {size}")
    if ours_active and shutil.which("gsettings"):
        _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme])
        _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(size)])
        log.append(f"GTK cursor set back to {theme} {size} (gsettings)")
    p = os.path.join(ICONS, "default", "index.theme")
    if os.path.exists(p + ".bak"):
        os.replace(p + ".bak", p); log.append(f"restored your original {p}")
    elif os.path.exists(p) and (NEW_MARKER in open(p).read() or LEGACY["marker"] in open(p).read()):
        os.remove(p); log.append(f"removed {p}")
    # top-bar button (Waybar on Omarchy 3.x, omarchy-shell on 4.x)
    bar_remove(log)
    # cursor themes (incl. any Hyprcursor leftovers inside them): only folders we marked, or
    # whose index.theme still carries our comment (legacy v3.2.0-style installs, and themes we built)
    if os.path.isdir(ICONS):
        for name in sorted(os.listdir(ICONS)):
            if name == THEME_NAME or name.startswith(THEME_NAME + "-") or name.startswith(LEGACY["theme_prefix"]):
                dest = os.path.join(ICONS, name)
                if _theme_is_ours(dest):
                    _rm(dest, log, f"cursor theme {name}")
    # app, CLI, daemon, launcher entry, icon: only paths whose current identity matches what this
    # install recorded (sha256 / symlink target), or, for installs from before the manifest, what a
    # released installer put there. Replaced, edited or skipped paths are left alone.
    for f in [os.path.join(BIN_DIR, n) for n in ("chevron-pro-picker", "chevron-pro-cursor", "chevron-pro-trail")] + \
             [DESKTOP_FILE, ICON_FILE]:
        _rm_if_ours(f, log)
    for f in LEGACY["bins"] + [LEGACY["desktop"], LEGACY["icon"]]:
        _rm_if_ours(f, log, legacy=True)
    if shutil.which("update-desktop-database") and os.path.isdir(APPS_DIR):
        _run(["update-desktop-database", APPS_DIR])
    _rm(DATA_DIR, log)
    _rm_legacy_data_dir(log, log)
    # settings
    if purge is None:
        purge = False
        if interactive and sys.stdin.isatty():
            try:
                purge = input(f"Also delete your settings and saved presets ({CFG_DIR})? [y/N] ").strip().lower() in ("y", "yes")
            except EOFError:
                purge = False
    if purge:
        for d in (CFG_DIR, LEGACY["cfg_dir"]):
            _rm(d, log)
    elif os.path.isdir(CFG_DIR):
        log.append(f"kept your settings and presets in {CFG_DIR}")
    # empty folders we created at install time
    hic = os.path.join(ICONS, "hicolor")
    # folders recorded at install time, plus the ones an older version may have created (only if left empty)
    cand = set(orig.get("created_dirs", [])) | {os.path.dirname(ICON_FILE), os.path.dirname(os.path.dirname(ICON_FILE)), hic, APPS_DIR, BIN_DIR,
                                                os.path.join(ICONS, "default")}
    for d in sorted(cand, key=len, reverse=True):
        if d == APPS_DIR and os.path.isdir(d) and os.listdir(d) == ["mimeinfo.cache"]:
            os.remove(os.path.join(d, "mimeinfo.cache"))   # made by update-desktop-database for our entry only
        if d == hic and os.path.isdir(d):
            cache = os.path.join(d, "icon-theme.cache")
            others = [f for r, _ds, fs in os.walk(d) for f in fs if os.path.join(r, f) != cache]
            if os.path.exists(cache) and not others:
                os.remove(cache)            # the icon cache gtk-update-icon-cache made for our icon only
        try:
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d); log.append(f"removed empty folder {d}")
        except OSError:
            pass
    return log


def activate(theme, size, bounce_via=None):
    """Point Hyprland, GTK and X11 apps at an installed theme."""
    log = []
    trail = False
    try:
        trail = bool(json.load(open(SETTINGS)).get("trail_enabled"))
    except (OSError, ValueError):
        pass
    _write_hypr(theme, size, trail)
    log.append(f"Hyprland settings written to {SNIPPET}" + (f" and {SNIPPET_LUA}" if os.path.exists(SNIPPET_LUA) else ""))
    if shutil.which("hyprctl"):
        # Hyprland caches cursor images by theme name; bounce through another theme so a
        # regenerated theme with the same name is actually reloaded.
        if bounce_via and bounce_via != theme:
            _run(["hyprctl", "setcursor", bounce_via, str(size)])
        ok, out = _run(["hyprctl", "setcursor", theme, str(size)])
        log.append(f"hyprctl setcursor {theme} {size}: {'ok' if ok else out}")
    if shutil.which("gsettings"):
        _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme])
        _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(size)])
        log.append("GTK cursor updated (gsettings)")
    _set_default_inherit(theme)
    return log


def reset(settings=None):
    s = settings or load_settings()
    prev = s.get("previous", {"theme": "Adwaita", "size": 24})
    log = []
    _write_hypr(None, None, False)       # keeps only the settings-window rule
    log.append("Removed Hyprland cursor override")
    if s.get("trail_enabled"):
        s["trail_enabled"] = False
        save_trail_settings({"trail_enabled": False})
        stop_trail()
        log.append("Cursor trail turned off")
    if shutil.which("hyprctl"):
        ok, out = _run(["hyprctl", "setcursor", prev["theme"], str(prev["size"])])
        log.append(f"hyprctl setcursor {prev['theme']} {prev['size']}: {'ok' if ok else out}")
    if shutil.which("gsettings"):
        _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", prev["theme"]])
        _run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(prev["size"])])
    p = os.path.join(ICONS, "default", "index.theme")
    if os.path.exists(p + ".bak"):
        os.replace(p + ".bak", p)
    elif os.path.exists(p) and (NEW_MARKER in open(p).read() or LEGACY["marker"] in open(p).read()):
        os.remove(p)
    log.append(f"Back to {prev['theme']} {prev['size']}")
    return log


def preview_image(settings, bg_light=(236, 236, 236), bg_dark=(22, 22, 26)):
    """Light/dark preview: a zoomed view on top and the cursor at real size underneath."""
    size = int(settings["size"])
    zs = max(144, min(256, size * 4))
    big = render(zs, settings)
    big = big.crop((0, int(zs * 0.06), zs, int(zs * 0.80)))          # trim empty space below the legs
    real = render(size, settings)
    real = real.crop((0, int(size * 0.06), size, int(size * 0.80)))
    tw, th = big.width + 40, big.height + real.height + 50
    img = Image.new("RGB", (tw * 2, th))
    for i, bg in enumerate((bg_light, bg_dark)):
        tile = Image.new("RGBA", (tw, th), bg + (255,))
        tile.alpha_composite(big, (20, 15))
        tile.alpha_composite(real, ((tw - real.width) // 2, big.height + 30))
        img.paste(tile.convert("RGB"), (i * tw, 0))
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("apply", "build"):
        p = sub.add_parser(name)
        p.add_argument("--color", help="#RRGGBB or preset name (" + ", ".join(PRESETS) + ")")
        p.add_argument("--glow", type=int, help="0 (none) .. 100 (strong neon)")
        p.add_argument("--glow-color", help="#RRGGBB, preset name, or 'match' (same as the line; default)")
        p.add_argument("--thickness", type=int, help="0 (thin) .. 100 (thick)")
        p.add_argument("--angle", type=int, help="leg angle from vertical, degrees, 30-75 (= 60-150 deg opening)")
        p.add_argument("--opening", type=int, help="full opening angle between the legs, 60-150 degrees")
        p.add_argument("--size", type=int, help="cursor size, e.g. 24 32 48 64 96")
        p.add_argument("--outline-color", help="#RRGGBB, preset name, or 'auto' (black; white for dark main colors)")
        p.add_argument("--outline-opacity", type=int, help="0 (invisible) .. 100 (solid crisp edge)")
        p.add_argument("--outline-width", type=int, help="0 (none) .. 100 (as wide as the line, per side)")
        p.add_argument("--no-edge", action="store_true", help="same as --outline-opacity 0")
        p.add_argument("--heartbeat", choices=["on", "off"], help="pulse the glow like a heartbeat (main cursor)")
        p.add_argument("--heartbeat-intensity", type=int, help="0 (no pulse) .. 100 (about 2.25x the glow at the beat)")
        p.add_argument("--heartbeat-bpm", type=int, help=f"heart rate, {50}-{120} BPM")
        p.add_argument("--heartbeat-color", help="#RRGGBB, preset name, or 'glow' (pulse in the glow color; default)")
        if name == "build":
            p.add_argument("--name", required=True)
            p.add_argument("--out", default="themes")
    for p in (sub.choices["apply"], sub.choices["build"]):
        p.add_argument("--preset", help="start from a built-in or saved preset (see: chevron-pro-cursor presets); other flags override it")
    sub.add_parser("reset")
    tp = sub.add_parser("trail", help="turn the cursor trail on/off: chevron-pro-cursor trail on|off")
    tp.add_argument("state", choices=["on", "off"])
    tc = sub.add_parser("trail-color", help="trail color: 'cursor' (follow the cursor's own colors, default) or a custom #RRGGBB / color name")
    tc.add_argument("color")
    sub.add_parser("presets", help="list built-in and saved presets")
    sp = sub.add_parser("save-preset", help="save the current settings as a preset"); sp.add_argument("name")
    rp = sub.add_parser("rename-preset"); rp.add_argument("old"); rp.add_argument("new")
    dp = sub.add_parser("delete-preset"); dp.add_argument("name")
    sub.add_parser("cleanup", help="remove leftovers of the old experimental Hyprcursor option")
    un = sub.add_parser("uninstall", help="remove Chevron Pro Cursor completely and restore your previous cursor")
    un.add_argument("--purge", action="store_true", help="also delete your settings and saved presets")
    un.add_argument("--keep-settings", action="store_true", help="keep settings and presets without asking")
    sub.add_parser("migrate", help="(used by install.sh) move an old Chevron Cursor install over")
    ro = sub.add_parser("record-original", help="(used by install.sh) remember your cursor before installing")
    ro.add_argument("created", nargs="*")
    ow = sub.add_parser("owns", help="(used by install.sh) print ours / changed / foreign / absent for each path")
    ow.add_argument("paths", nargs="+")
    rm_ = sub.add_parser("record-manifest", help="(used by install.sh) record the identity of the shared paths it placed")
    rm_.add_argument("paths", nargs="*")
    sub.add_parser("version")
    sub.add_parser("open", help="open the settings app (detached; used by the top-bar button)")
    bp = sub.add_parser("bar", help="top-bar button: chevron-pro-cursor bar --position left|center-left|center-mid|center-right|right|none")
    bp.add_argument("--position", choices=["left", "center-left", "center-mid", "center-right", "right", "none"])
    bp.add_argument("--no-restart", action="store_true", help="don't restart Waybar / reload omarchy-shell")
    sub.add_parser("refresh-hypr", help="(used by install.sh) rewrite the Hyprland snippet (window rule, cursor, trail)")
    u = sub.add_parser("use", help="switch to an already-installed theme (e.g. a prebuilt one)")
    u.add_argument("theme"); u.add_argument("size", type=int, nargs="?", default=32)
    a = ap.parse_args()
    if a.cmd == "version":
        print(f"{APP_NAME} {VERSION}"); return
    if a.cmd == "uninstall":
        log = uninstall(purge=True if a.purge else (False if a.keep_settings else None))
        print(f"{APP_NAME} uninstalled. Summary:")
        print("\n".join("  - " + l for l in log) or "  - nothing was installed")
        print("Log out and back in so every app picks up your original cursor.")
        return
    if a.cmd == "migrate":
        log, active = migrate_legacy()
        print("\n".join(log) or "no old install found")
        if active:
            print("OLD_CURSOR_ACTIVE")
        return
    if a.cmd == "record-original":
        record_original(a.created); return
    if a.cmd == "owns":
        print("\n".join(ownership(x) for x in a.paths)); return
    if a.cmd == "record-manifest":
        write_manifest(a.paths); return
    if a.cmd == "reset":
        print("\n".join(reset())); return
    if a.cmd == "trail":
        on = a.state == "on"
        save_trail_settings({"trail_enabled": on})
        set_trail_autostart(on)
        (start_trail if on else stop_trail)()
        print("trail", a.state); return
    if a.cmd == "presets":
        for n, v, b in all_presets():
            gc = v.get("glow_color") or "match"; oc = v.get("outline_color") or "auto"
            print(f"{'built-in' if b else 'saved   '}  {n:22s} line {v['color']}  glow {v['glow']:>3} {gc:8s} thick {v['thickness']:>3}  "
                  f"opening {int(round(2 * v['angle']))}deg  outline {oc} {v['outline_opacity']}%/{v['outline_width']}  size {v.get('size', 32)}"
                  + (f"  heartbeat {v.get('heartbeat_intensity', 50)}% {v.get('heartbeat_bpm', 60)}bpm" if v.get("heartbeat") else "")
                  + (f"  trail {v.get('trail_color')}" if v.get("trail_color_custom") and v.get("trail_color") else ""))
        return
    if a.cmd == "save-preset":
        print("saved", save_preset(a.name, load_settings())); return
    if a.cmd == "rename-preset":
        print("renamed to", rename_preset(a.old, a.new)); return
    if a.cmd == "open":
        open_app(); return
    if a.cmd == "bar":
        if not a.position:
            try:
                st = json.load(open(BAR_STATE)); print(f"{st.get('kind')}: {st.get('position')}")
            except (OSError, ValueError):
                print("none")
            return
        log = _bar().add(a.position, bar_launch_cmd(), BAR_STATE, do_restart=not a.no_restart)
        print("\n".join(log) or "no bar button"); return
    if a.cmd == "refresh-hypr":
        if os.path.isdir(HYPR_DIR):
            _write_hypr(*_hypr_state()); print(f"Hyprland snippet updated: {SNIPPET}" + (f" + {SNIPPET_LUA}" if os.path.exists(SNIPPET_LUA) else ""))
        else:
            print("no ~/.config/hypr: skipped")
        return
    if a.cmd == "trail-color":
        if a.color.lower() in ("cursor", "auto", "match", "follow"):
            save_trail_settings({"trail_color_custom": False}); print("trail follows the cursor's colors"); return
        hx = PRESETS.get(a.color, a.color)
        hx = hx if hx.startswith("#") else "#" + hx
        hex_rgb(hx)
        save_trail_settings({"trail_color_custom": True, "trail_color": hx.upper()}); print("trail color", hx.upper()); return
    if a.cmd == "delete-preset":
        delete_preset(a.name); print("deleted", a.name); return
    if a.cmd == "cleanup":
        print("\n".join(cleanup_hyprcursor_leftovers()) or "nothing to clean"); return
    if a.cmd == "use":
        if not os.path.isdir(os.path.join(ICONS, a.theme, "cursors")):
            raise SystemExit(f"{a.theme} is not installed in {ICONS}")
        s = load_settings()
        if "previous" not in s:
            s["previous"] = {"theme": _gsettings_get("cursor-theme") or "Adwaita", "size": int(_gsettings_get("cursor-size") or 24)}
            save_settings(s)
        cleanup_hyprcursor_leftovers()
        print("\n".join(activate(a.theme, a.size, s["previous"]["theme"])))
        return
    s = load_settings() if a.cmd == "apply" else dict(DEFAULTS)
    if a.preset:
        hit = find_preset(a.preset)
        if not hit:
            raise SystemExit(f"no preset called '{a.preset}'. Run: chevron-pro-cursor presets")
        s.update(hit[1]); s["preset"] = hit[0]
    for k in ("glow", "thickness", "angle", "size"):
        if getattr(a, k) is not None:
            s[k] = getattr(a, k)
    if a.opening is not None:
        s["angle"] = a.opening / 2
    if not ANGLE_MIN <= s["angle"] <= ANGLE_MAX:
        raise SystemExit(f"opening must be {2*ANGLE_MIN}-{2*ANGLE_MAX} degrees (--angle {ANGLE_MIN}-{ANGLE_MAX})")
    if a.color:
        s["color"] = PRESETS.get(a.color, a.color)
        hex_rgb(s["color"])
    if a.glow_color:
        s["glow_color"] = None if a.glow_color.lower() == "match" else PRESETS.get(a.glow_color, a.glow_color)
        if s["glow_color"]:
            hex_rgb(s["glow_color"])
    if a.outline_color:
        s["outline_color"] = None if a.outline_color.lower() == "auto" else PRESETS.get(a.outline_color, a.outline_color)
        if s["outline_color"]:
            hex_rgb(s["outline_color"])
    for k in ("outline_opacity", "outline_width"):
        v = getattr(a, k)
        if v is not None:
            if not 0 <= v <= 100:
                raise SystemExit(f"--{k.replace('_', '-')} must be 0-100")
            s[k] = v
    if a.no_edge:
        s["outline_opacity"] = 0
    if a.heartbeat:
        s["heartbeat"] = a.heartbeat == "on"
    if a.heartbeat_intensity is not None:
        if not 0 <= a.heartbeat_intensity <= 100:
            raise SystemExit("--heartbeat-intensity must be 0-100")
        s["heartbeat_intensity"] = a.heartbeat_intensity
    if a.heartbeat_bpm is not None:
        if not HB_BPM_MIN <= a.heartbeat_bpm <= HB_BPM_MAX:
            raise SystemExit(f"--heartbeat-bpm must be {HB_BPM_MIN}-{HB_BPM_MAX}")
        s["heartbeat_bpm"] = a.heartbeat_bpm
    if a.heartbeat_color:
        if a.heartbeat_color.lower() in ("glow", "match", "auto"):
            s["heartbeat_color_custom"] = False
        else:
            hx = PRESETS.get(a.heartbeat_color, a.heartbeat_color)
            hx = (hx if hx.startswith("#") else "#" + hx).upper()
            hex_rgb(hx)
            s["heartbeat_color_custom"], s["heartbeat_color"] = True, hx
    if a.preset and any(s.get(k) != hit[1].get(k) for k in FULL_KEYS if k in hit[1]):
        s.pop("preset", None)              # flags changed it: it's no longer exactly that preset
    if a.cmd == "apply":
        print("\n".join(apply(s)))
    else:
        print(build_theme(a.out, a.name, s))


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        raise SystemExit(f"error: {e}")
