#!/usr/bin/env bash
# Chevron Pro Cursor installer for Omarchy / Arch + Hyprland.
#   ./install.sh               install (or upgrade) the app, CLI, trail daemon and prebuilt themes, then open the app
#   ./install.sh --no-launch   same, without opening the app
#   ./install.sh --bar-position left|center-left|center-mid|center-right|right|none
#                              where to put the top-bar button (Waybar on Omarchy 3.x, the Omarchy bar on 4.x);
#                              without it you're asked (1-5, 0 = none) when running in a terminal
#   ./install.sh --force       replace existing launcher/CLI/theme files even if Chevron didn't create them
#   ./install.sh --uninstall   remove everything (alias for ./uninstall.sh; add --purge to delete settings too)
# Upgrading from the old "Chevron Cursor" (v1/v2) is automatic: settings and saved presets are migrated
# and the old files, themes, autostart line and daemon are removed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(cat "$HERE/VERSION" 2>/dev/null || echo 3)"

if [[ "${1:-}" == "--uninstall" ]]; then
  shift; exec "$HERE/uninstall.sh" "$@"
fi
NO_LAUNCH=0; BAR_POS=""; FORCE=0
while (($#)); do
  case "$1" in
    --no-launch) NO_LAUNCH=1 ;;
    --force) FORCE=1 ;;
    --bar-position) BAR_POS="${2:-}"; shift ;;
    --bar-position=*) BAR_POS="${1#*=}" ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)"; exit 2 ;;
  esac
  shift
done
case "$BAR_POS" in
  ""|left|center-left|center-mid|center-right|right|none) ;;
  *) echo "--bar-position must be left, center-left, center-mid, center-right, right or none"; exit 2 ;;
esac

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"
LIB="$DATA/chevron-pro-cursor"
APPS="$DATA/applications"
THEMES="$DATA/icons"
ICONDIR="$THEMES/hicolor/128x128/apps"
echo "Installing Chevron Pro Cursor v$VERSION"

# --- dependencies (Arch) ---
need=()
if command -v pacman >/dev/null; then
  for p in python python-gobject python-cairo gtk4 gtk4-layer-shell python-pillow; do pacman -Qi "$p" >/dev/null 2>&1 || need+=("$p"); done
  if ((${#need[@]})); then
    echo "Missing packages: ${need[*]}"
    read -rp "Install them now with 'sudo pacman -S --needed ${need[*]}'? [Y/n] " ans
    if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then sudo pacman -S --needed "${need[@]}"; else echo "Skipping; the app won't start until they're installed."; fi
  fi
else
  python3 -c 'import gi; gi.require_version("Gtk","4.0"); from gi.repository import Gtk; import PIL, cairo' 2>/dev/null \
    || echo "Note: needs Python GObject + GTK4 + Pillow + pycairo, and gtk4-layer-shell for the trail (install them with your package manager)."
fi

# --- folders we create (so the uninstaller can remove them again if they end up empty) ---
created=()
for d in "$BIN" "$APPS" "$THEMES" "$THEMES/hicolor" "$THEMES/hicolor/128x128" "$ICONDIR" "$THEMES/default"; do
  [[ -e "$d" ]] || created+=("$d")
done

# --- stop running trail daemons (new and old name); restart the new one at the end ---
restart_trail=0
for proc in chevron-pro-trail "chevron""-trail"; do
  if pgrep -f "$proc" >/dev/null 2>&1; then restart_trail=1; pkill -f "$proc" || true; fi
done

# --- ownership guard: only replace files and folders Chevron Pro Cursor put there ---
# A target is ours if it doesn't exist yet, is identical to what we'd install, is listed in the
# manifest a previous install wrote, or (for installs from before the manifest) carries our marker.
# Anything else is left alone unless the user agrees (interactive) or passes --force.
MANIFEST="$LIB/installed-files"
is_ours() {  # $1 = target path, $2 = marker regex (optional)
  local t="$1" marker="${2:-}"
  [[ -e "$t" || -L "$t" ]] || return 0
  if [[ -L "$t" ]]; then [[ "$(readlink "$t")" == "$LIB/"* ]] && return 0; fi
  [[ -f "$MANIFEST" ]] && grep -qxF "$t" "$MANIFEST" && return 0
  [[ -n "$marker" && -f "$t" ]] && grep -qiE "$marker" "$t" 2>/dev/null && return 0
  return 1
}
may_replace() {  # $1 = target, $2 = marker regex; returns 0 if we may overwrite
  is_ours "$1" "${2:-}" && return 0
  if ((FORCE)); then echo "  replacing $1 (--force)"; return 0; fi
  if [[ -t 0 ]]; then
    read -rp "$1 already exists and wasn't installed by Chevron Pro Cursor. Replace it? [y/N] " a
    [[ "${a:-N}" =~ ^[Yy]$ ]] && return 0
  fi
  echo "  skipped $1 (exists and isn't ours; rerun with --force to replace)"; return 1
}
placed=()
put() {  # put MODE SRC DEST MARKER
  if may_replace "$3" "$4"; then install -m "$1" "$2" "$3"; placed+=("$3"); fi
}

# --- app files (upgrades our own previous version; never clobbers someone else's files) ---
mkdir -p "$BIN" "$LIB" "$APPS" "$ICONDIR" "$THEMES"
install -m 755 "$HERE/chevron_core.py" "$LIB/chevron_core.py"
install -m 644 "$HERE/reload_anim.py" "$LIB/reload_anim.py"
install -m 644 "$HERE/chevron_bar.py" "$LIB/chevron_bar.py"
install -m 755 "$HERE/uninstall.sh" "$LIB/uninstall.sh"
install -m 644 "$HERE/VERSION" "$LIB/VERSION"
put 755 "$HERE/chevron-pro-picker" "$BIN/chevron-pro-picker" 'chevron'
put 755 "$HERE/chevron-pro-trail" "$BIN/chevron-pro-trail" 'chevron'
if may_replace "$BIN/chevron-pro-cursor"; then ln -sfn "$LIB/chevron_core.py" "$BIN/chevron-pro-cursor"; placed+=("$BIN/chevron-pro-cursor"); fi
if cmp -s "$HERE/data/chevron-pro-cursor.png" "$ICONDIR/chevron-pro-cursor.png"; then placed+=("$ICONDIR/chevron-pro-cursor.png")
else put 644 "$HERE/data/chevron-pro-cursor.png" "$ICONDIR/chevron-pro-cursor.png" ''; fi
tmp_desktop="$(mktemp)"; sed "s|@BIN@|$BIN|" "$HERE/data/chevron-pro-cursor.desktop" > "$tmp_desktop"
put 644 "$tmp_desktop" "$APPS/chevron-pro-cursor.desktop" 'com\.chevronpro\.Cursor'; rm -f "$tmp_desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$THEMES/hicolor" 2>/dev/null || true
python3 "$LIB/chevron_core.py" record-original "${created[@]}"
echo "Installed app: $BIN/chevron-pro-picker  (launcher entry: 'Chevron Pro Cursor'), command: chevron-pro-cursor"

# --- migrate an old "Chevron Cursor" install ---
mig="$(python3 "$LIB/chevron_core.py" migrate)"
if [[ "$mig" != "no old install found" ]]; then
  echo "Upgraded from the old Chevron Cursor:"; grep -v OLD_CURSOR_ACTIVE <<<"$mig" | sed 's/^/  /'
fi

# --- prebuilt themes (shipped in the release tarball; built here for a git clone) ---
if ! ls -d "$HERE"/themes/*/ >/dev/null 2>&1; then
  echo "Building the 11 prebuilt themes (first install from a git clone, about 30 s)..."
  python3 "$HERE/build-prebuilt.py" >/dev/null
fi
for d in "$HERE"/themes/*/; do
  n="$(basename "$d")"; dest="${THEMES:?}/$n"
  # only remove an existing theme folder we created (marker file, or our index.theme from older installs)
  if [[ -e "$dest" ]]; then
    if [[ -f "$dest/.chevron-pro-cursor" ]] || grep -qs '^Comment=Chevron Pro Cursor' "$dest/index.theme" || ((FORCE)); then
      rm -rf "$dest"
    elif [[ -t 0 ]] && { read -rp "$dest already exists and wasn't installed by Chevron Pro Cursor. Replace it? [y/N] " a; [[ "${a:-N}" =~ ^[Yy]$ ]]; }; then
      rm -rf "$dest"
    else
      echo "  skipped theme $n ($dest exists and isn't ours; rerun with --force to replace)"; continue
    fi
  fi
  cp -a "$d" "$THEMES/"; touch "$dest/.chevron-pro-cursor"
done
printf '%s\n' "${placed[@]}" > "$MANIFEST"
python3 "$LIB/chevron_core.py" cleanup 2>/dev/null | grep -v "nothing to clean" | sed 's/^/  removed /' || true
echo "Installed $(ls -d "$HERE"/themes/*/ | wc -l) prebuilt themes to $THEMES (ChevronPro-<Preset>)"

if grep -q OLD_CURSOR_ACTIVE <<<"$mig"; then
  echo "Rebuilding your cursor with your migrated settings…"
  python3 "$LIB/chevron_core.py" apply | sed 's/^/  /'
else
  SNIP="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/chevron-pro-cursor.conf"
  if command -v hyprctl >/dev/null && [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && [[ -f "$SNIP" ]]; then
    t="$(sed -n 's/^env = XCURSOR_THEME,//p' "$SNIP")"; z="$(sed -n 's/^env = XCURSOR_SIZE,//p' "$SNIP")"
    [[ -n "$t" && -n "$z" ]] && hyprctl setcursor "$t" "$z" >/dev/null 2>&1 || true
  fi
fi

# --- Hyprland snippet: settings-window rule (floating, centred, half the monitor) + cursor/trail lines ---
python3 "$LIB/chevron_core.py" refresh-hypr | sed 's/^/  /'

# --- top-bar button ---
CUR_BAR="$(python3 "$LIB/chevron_core.py" bar 2>/dev/null | sed -n 's/^[a-z]*: //p')"
BAR_KIND=""
BAR_KIND="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import chevron_bar as b; print({"shell": "the Omarchy bar", "waybar": "Waybar"}.get(b.detect(), ""))' "$LIB" 2>/dev/null || true)"
if [[ -z "$BAR_POS" && -n "$BAR_KIND" && -t 0 ]]; then
  opts=(none left center-left center-mid center-right right)
  def=5; for i in "${!opts[@]}"; do [[ "${opts[$i]}" == "${CUR_BAR:-}" ]] && def=$i; done
  echo "Add a Chevron Pro Cursor button to $BAR_KIND (opens the settings)?"
  echo "  1) left   2) center-left   3) center-mid   4) center-right   5) right   0) no button"
  read -rp "Choose 0-5 [$def]: " ans
  ans="${ans:-$def}"
  if [[ "$ans" =~ ^[0-5]$ ]]; then BAR_POS="${opts[$ans]}"; else echo "  not a choice; leaving the bar as it is"; fi
fi
if [[ -n "$BAR_POS" ]]; then
  python3 "$LIB/chevron_core.py" bar --position "$BAR_POS" | sed 's/^/  /'
fi

# --- restart the trail with the new version if it was running (or is enabled) ---
if [[ $restart_trail == 1 ]] && grep -q '"trail_enabled": true' "${XDG_CONFIG_HOME:-$HOME/.config}/chevron-pro-cursor/settings.json" 2>/dev/null; then
  (setsid "$BIN/chevron-pro-trail" >/dev/null 2>&1 &); echo "Restarted the cursor trail (new version)."
fi
echo "Uninstall any time with: $LIB/uninstall.sh  (or: chevron-pro-cursor uninstall)"

if [[ $NO_LAUNCH == 0 ]] && [[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then
  "$BIN/chevron-pro-cursor" open; echo "Launching Chevron Pro Cursor…"
fi
