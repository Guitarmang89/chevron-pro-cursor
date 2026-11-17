"""Top-bar button for Chevron Pro Cursor.

Omarchy 3.x uses Waybar (~/.config/waybar/config.jsonc + style.css); Omarchy 4.x ("quattro") replaced
it with omarchy-shell (~/.config/omarchy/shell.json). Both are supported. The button launches the
settings app (`chevron-pro-cursor open`, an absolute path, started detached).

Positions: left | center-left | center-mid | center-right | right | none
  Waybar:        modules-left (end) | modules-center (start / middle / end) | modules-right (start)
  omarchy-shell: layout.left (end)  | centerBegin | center | centerEnd       | right (start)

The Waybar config is edited as text with a small JSONC tokenizer, so comments, formatting and the
rest of the file stay byte-for-byte as they were; removing the button restores the original bytes.
A backup is kept next to the file (<name>.chevron-pro-cursor.bak) until the button is removed.
"""
import json, os, re, shutil, subprocess

POSITIONS = ("left", "center-left", "center-mid", "center-right", "right")
MODULE = "custom/chevron-pro-cursor"
LEGACY_MODULES = ("custom/chevron" + "-cursor",)
SHELL_ID = "chevron-pro-cursor"
GLYPH = "\U000F01C0"          # nf-md-cursor_default (Nerd Font, used by Omarchy's bars)
BEGIN, END = ">>> chevron-pro-cursor", "<<< chevron-pro-cursor"
BAK = ".chevron-pro-cursor.bak"
TOOLTIP = "Chevron Pro Cursor\nClick: open the cursor settings"

HOME = os.path.expanduser("~")
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
WAYBAR_DIR = os.path.join(CONFIG, "waybar")
SHELL_JSON = os.path.join(CONFIG, "omarchy", "shell.json")


# ------------------------------------------------------------------ JSONC tokenizer
def tokens(text):
    """Yield (kind, start, end) for significant tokens: '{' '}' '[' ']' ':' ',' 'str' 'lit'.
    Comments (// and /* */) and whitespace are skipped."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i); i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j < 0 else j + 2
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            yield ("str", i, j + 1); i = j + 1
        elif c in "{}[]:,":
            yield (c, i, i + 1); i += 1
        else:
            j = i
            while j < n and text[j] not in " \t\r\n{}[]:,/\"":
                j += 1
            yield ("lit", i, max(j, i + 1)); i = max(j, i + 1)


def parse_jsonc(text):
    """Parse JSONC (comments + trailing commas) - used to validate every edit."""
    out, last = [], 0
    toks = list(tokens(text))
    for k, (kind, s, e) in enumerate(toks):
        if kind == "," and k + 1 < len(toks) and toks[k + 1][0] in "]}":
            continue                                  # trailing comma
        out.append(text[s:e])
    return json.loads(" ".join(out))


def _top_object(toks):
    """-> (index of the '{' of the bar object, index of its matching '}') ; the first bar if a list."""
    if not toks:
        raise ValueError("empty config")
    k = 0
    if toks[0][0] == "[":
        k = 1
    if toks[k][0] != "{":
        raise ValueError("unexpected Waybar config layout")
    depth = 0
    for j in range(k, len(toks)):
        if toks[j][0] in "{[":
            depth += 1
        elif toks[j][0] in "}]":
            depth -= 1
            if depth == 0:
                return k, j
    raise ValueError("unbalanced Waybar config")


def _find_key(text, toks, key):
    """-> (index of '[' , index of ']') of a top-level array property, or None."""
    a, b = _top_object(toks)
    depth = 0
    for j in range(a, b):
        kind = toks[j][0]
        if kind in "{[":
            depth += 1
        elif kind in "}]":
            depth -= 1
        elif depth == 1 and kind == "str" and text[toks[j][1]:toks[j][2]] == json.dumps(key) \
                and toks[j + 1][0] == ":" and toks[j + 2][0] == "[":
            lb = j + 2; d = 0
            for m in range(lb, b):
                if toks[m][0] in "{[":
                    d += 1
                elif toks[m][0] in "}]":
                    d -= 1
                    if d == 0:
                        return lb, m
    return None


def _line_indent(text, pos):
    ls = text.rfind("\n", 0, pos) + 1
    m = re.match(r"[ \t]*", text[ls:])
    return m.group(0)


def _module_block(text, toks, cmd):
    a, _b = _top_object(toks)
    brace = toks[a][1]
    nxt = toks[a + 1][1]
    ind = _line_indent(text, nxt) if "\n" in text[brace:nxt] else "  "
    body = {"format": GLYPH, "tooltip-format": TOOLTIP, "on-click": cmd}
    inner = json.dumps(body, indent=2, ensure_ascii=False).replace("\n", "\n" + ind)
    # the end marker is a line comment: if the bar object continues on the same line, end it with a newline
    tail = "" if "\n" in text[brace:nxt] else ":nl\n"
    return brace + 1, (f"\n{ind}// {BEGIN} (added by Chevron Pro Cursor; its installer/uninstaller manage this block)"
                       f"\n{ind}{json.dumps(MODULE)}: {inner},\n{ind}// {END}{tail}")


def waybar_add(text, position, cmd):
    """Return the config text with the button added at position (text unchanged if already there)."""
    if MODULE in [v for v in _array_values(text)]:
        return text
    section, where = {"left": ("modules-left", "end"), "center-left": ("modules-center", "start"),
                      "center-mid": ("modules-center", "mid"), "center-right": ("modules-center", "end"),
                      "right": ("modules-right", "start")}[position]
    toks = list(tokens(text))
    edits = []                                       # (pos, insert text); applied from the back
    span = _find_key(text, toks, section)
    entry = json.dumps(MODULE)
    if span is None:
        # no such list yet: create it inside our marked block
        pos, block = _module_block(text, toks, cmd)
        a0 = _top_object(toks)[0]
        ind = _line_indent(text, toks[a0 + 1][1]) if "\n" in text[toks[a0][1]:toks[a0 + 1][1]] else "  "
        block = block.replace(f"\n{ind}// {END}", f"\n{ind}{json.dumps(section)}: [{entry}],\n{ind}// {END}")
        edits.append((pos, block))
    else:
        lb, rb = span
        elems = [toks[m] for m in range(lb + 1, rb) if toks[m][0] == "str" and _depth_ok(toks, lb, m)]
        multiline = "\n" in text[toks[lb][1]:toks[rb][1]]
        if not elems:
            edits.append((toks[lb][2], entry))
        else:
            if where == "start":
                k = 0
            elif where == "end":
                k = len(elems)
            else:
                k = (len(elems) + 1) // 2
            if k < len(elems):                      # insert before element k
                e = elems[k]
                if multiline:
                    edits.append((e[1], entry + ",\n" + _line_indent(text, e[1])))
                else:
                    edits.append((e[1], entry + ", "))
            else:                                   # after the last element
                e = elems[-1]
                if multiline:
                    edits.append((e[2], ",\n" + _line_indent(text, e[1]) + entry))
                else:
                    edits.append((e[2], ", " + entry))
        edits.append(_module_block(text, toks, cmd))
    out = text
    for pos, ins in sorted(edits, key=lambda x: -x[0]):
        out = out[:pos] + ins + out[pos:]
    parse_jsonc(out)                                 # must still be valid
    return out


def _depth_ok(toks, lb, m):
    d = 0
    for j in range(lb + 1, m):
        if toks[j][0] in "{[":
            d += 1
        elif toks[j][0] in "}]":
            d -= 1
    return d == 0


def _array_values(text):
    try:
        toks = list(tokens(text))
        vals = []
        for sec in ("modules-left", "modules-center", "modules-right"):
            span = _find_key(text, toks, sec)
            if span:
                vals += [json.loads(text[toks[m][1]:toks[m][2]]) for m in range(span[0] + 1, span[1]) if toks[m][0] == "str"]
        return vals
    except ValueError:
        return []


def waybar_remove(text):
    """Remove our marked block(s) and our entries from the module lists, restoring the original bytes."""
    names = (MODULE,) + LEGACY_MODULES
    # 1) marked blocks (each starts with a newline we added)
    out = re.sub(r"\n[ \t]*// " + re.escape(BEGIN) + r".*?\n[ \t]*// " + re.escape(END) + r"(?::nl\n)?", "", text, flags=re.S)
    legacy = "chevron" + "-cursor"
    out = re.sub(r"\n[ \t]*// >>> " + legacy + r".*?\n[ \t]*// <<< " + legacy + r"[^\n]*", "", out, flags=re.S)
    # 2) list entries
    while True:
        toks = list(tokens(out))
        hit = next((k for k, t in enumerate(toks) if t[0] == "str" and out[t[1]:t[2]] in [json.dumps(n) for n in names]
                    and (k + 1 >= len(toks) or toks[k + 1][0] != ":")), None)
        if hit is None:
            break
        s, e = toks[hit][1], toks[hit][2]
        nxt = toks[hit + 1] if hit + 1 < len(toks) else None
        prv = toks[hit - 1]
        if nxt and nxt[0] == ",":
            j = nxt[2]
            while j < len(out) and out[j] in " \t\r\n":
                j += 1
            out = out[:s] + out[j:]
        elif prv[0] == ",":
            i = s
            while i > prv[2] and out[i - 1] in " \t\r\n":
                i -= 1
            out = out[:prv[1]] + out[prv[2]:i] + out[e:]
        else:
            out = out[:s] + out[e:]
    return out


CSS = ("\n/* " + BEGIN + " */\n#custom-chevron-pro-cursor {\n  margin: 0 10px;\n  min-width: 12px;\n}\n/* " + END + " */\n")


def css_add(text):
    if BEGIN in text:
        return text
    return text + ("" if text.endswith("\n") or not text else "\n") + CSS


def css_remove(text):
    return re.sub(r"\n?/\* " + re.escape(BEGIN) + r" \*/.*?/\* " + re.escape(END) + r" \*/\n?", "", text, flags=re.S)


# ------------------------------------------------------------------ omarchy-shell (Omarchy 4.x)
SHELL_SECTIONS = {"left": ("left", "end"), "center-left": ("centerBegin", "end"), "center-mid": ("center", "end"),
                  "center-right": ("centerEnd", "start"), "right": ("right", "start")}


def shell_defaults_path():
    for base in (os.environ.get("OMARCHY_PATH"), os.path.join(HOME, ".local/share/omarchy"), "/usr/share/omarchy"):
        if base and os.path.isfile(os.path.join(base, "config/omarchy/shell.json")):
            return os.path.join(base, "config/omarchy/shell.json")
    return None


def shell_add(d, position, cmd):
    d = json.loads(json.dumps(d))
    lay = d.setdefault("bar", {}).setdefault("layout", {})
    for sec in ("left", "centerBegin", "center", "centerEnd", "right"):
        lay.setdefault(sec, [])
    if any(isinstance(e, dict) and e.get("id") == SHELL_ID for sec in lay.values() if isinstance(sec, list) for e in sec):
        return d
    sec, where = SHELL_SECTIONS[position]
    entry = {"id": SHELL_ID, "type": "command", "text": GLYPH, "tooltip": TOOLTIP, "onClick": cmd, "horizontalMargin": 10}
    (lay[sec].append if where == "end" else lambda x: lay[sec].insert(0, x))(entry)
    return d


def shell_remove(d):
    d = json.loads(json.dumps(d))
    lay = (d.get("bar") or {}).get("layout") or {}
    for sec, items in lay.items():
        if isinstance(items, list):
            lay[sec] = [e for e in items if not (isinstance(e, dict) and e.get("id") == SHELL_ID)]
    return d


def _dump_shell(d):
    return json.dumps(d, indent=2) + "\n"


# ------------------------------------------------------------------ install / remove on this machine
def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect():
    """-> 'shell' (Omarchy 4.x omarchy-shell), 'waybar', or None."""
    has_shell_cfg = os.path.isfile(SHELL_JSON) or shell_defaults_path() is not None
    if has_shell_cfg and (shutil.which("omarchy-shell") or not _waybar_config()):
        return "shell"
    if os.path.isfile(os.path.join(WAYBAR_DIR, "config.jsonc")) or os.path.isfile(os.path.join(WAYBAR_DIR, "config")) \
            or shutil.which("waybar"):
        return "waybar"
    return None


def _waybar_config():
    for n in ("config.jsonc", "config"):
        p = os.path.join(WAYBAR_DIR, n)
        if os.path.isfile(p):
            return p
    return None


def _write(path, text):
    tmp = path + ".chevron-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def restart(kind, log):
    if kind == "waybar":
        if shutil.which("omarchy-restart-waybar") and _run(["omarchy-restart-waybar"]):
            log.append("restarted Waybar")
        elif _run(["pgrep", "-x", "waybar"]):
            _run(["pkill", "-SIGUSR2", "-x", "waybar"]); log.append("reloaded Waybar")
    elif kind == "shell" and shutil.which("omarchy-shell"):
        if _run(["omarchy-shell", "shell", "reloadConfig"]) or _run(["omarchy-shell", "-q", "shell", "rescanPlugins"]):
            log.append("reloaded omarchy-shell")


def add(position, cmd, state_file, kind=None, do_restart=True):
    """Add the button. Returns log lines. Records what was done in state_file (JSON)."""
    log = []
    if position == "none":
        return remove(state_file, do_restart=do_restart)
    if position not in POSITIONS:
        raise ValueError(f"position must be one of: {', '.join(POSITIONS)}, none")
    kind = kind or detect()
    remove(state_file, do_restart=False, quiet=True)          # moving it: take the old one out first
    state = {"kind": kind, "position": position}
    if kind == "waybar":
        cfg = _waybar_config()
        if not cfg:
            log.append("Waybar config not found (~/.config/waybar/config.jsonc): no bar button added"); return log
        txt = open(cfg, encoding="utf-8").read()
        if not os.path.exists(cfg + BAK):
            shutil.copy2(cfg, cfg + BAK)
        _write(cfg, waybar_add(txt, position, cmd))
        state.update(config=cfg)
        css = os.path.join(os.path.dirname(cfg), "style.css")
        if os.path.isfile(css):
            ctxt = open(css, encoding="utf-8").read()
            if not os.path.exists(css + BAK):
                shutil.copy2(css, css + BAK)
            _write(css, css_add(ctxt)); state.update(css=css)
        log.append(f"added the Chevron Pro Cursor button to Waybar ({position}) in {cfg} (backup: {cfg + BAK})")
    elif kind == "shell":
        created = not os.path.isfile(SHELL_JSON)
        if created:
            src = shell_defaults_path()
            if not src:
                log.append("omarchy-shell defaults not found: no bar button added"); return log
            d = json.load(open(src, encoding="utf-8"))
            os.makedirs(os.path.dirname(SHELL_JSON), exist_ok=True)
        else:
            d = json.load(open(SHELL_JSON, encoding="utf-8"))
            if not os.path.exists(SHELL_JSON + BAK):
                shutil.copy2(SHELL_JSON, SHELL_JSON + BAK)
        _write(SHELL_JSON, _dump_shell(shell_add(d, position, cmd)))
        state.update(config=SHELL_JSON, created=created)
        log.append(f"added the Chevron Pro Cursor button to the Omarchy bar ({position}) in {SHELL_JSON}")
    else:
        log.append("no Waybar or omarchy-shell found: no bar button added"); return log
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    if do_restart:
        restart(kind, log)
    return log


def remove(state_file=None, do_restart=True, quiet=False):
    """Remove the button from Waybar and/or omarchy-shell (whatever is there) and delete our backups."""
    log, kinds = [], set()
    cfgs = [p for p in (os.path.join(WAYBAR_DIR, n) for n in sorted(os.listdir(WAYBAR_DIR))) if os.path.isfile(p)] \
        if os.path.isdir(WAYBAR_DIR) else []
    for p in cfgs:
        fn = os.path.basename(p)
        if fn.endswith(BAK) or fn.endswith("." + "chevron" + "-cursor.bak"):
            if not quiet:
                os.remove(p); log.append(f"removed Waybar backup {p}")
            continue
        if not (fn.startswith("config") or fn.endswith(".css")):
            continue
        txt = open(p, encoding="utf-8").read()
        new = css_remove(txt) if fn.endswith(".css") else waybar_remove(txt)
        if new != txt:
            if not fn.endswith(".css"):
                parse_jsonc(new)
            _write(p, new); kinds.add("waybar")
            log.append(f"removed the Chevron Pro Cursor button from {p}")
    state = {}
    try:
        state = json.load(open(state_file)) if state_file else {}
    except (OSError, ValueError):
        pass
    if os.path.isfile(SHELL_JSON):
        try:
            d = json.load(open(SHELL_JSON, encoding="utf-8"))
            nd = shell_remove(d)
            if nd != d:
                kinds.add("shell")
                src = shell_defaults_path()
                if state.get("created") and src and json.load(open(src, encoding="utf-8")) == nd:
                    os.remove(SHELL_JSON); log.append(f"removed {SHELL_JSON} (we created it; it was the defaults)")
                else:
                    _write(SHELL_JSON, _dump_shell(nd)); log.append(f"removed the Chevron Pro Cursor button from {SHELL_JSON}")
        except (OSError, ValueError):
            pass
        if not quiet and os.path.exists(SHELL_JSON + BAK):
            os.remove(SHELL_JSON + BAK)
    if state_file and os.path.exists(state_file) and not quiet:
        os.remove(state_file)
    if do_restart:
        for k in kinds:
            restart(k, log)
    return log
