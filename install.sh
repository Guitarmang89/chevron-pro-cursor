#!/usr/bin/env bash
# Chevron Pro Cursor installer for Omarchy / Arch + Hyprland.
#   ./install.sh               install (or upgrade) the app, CLI, trail daemon and prebuilt themes, then open the app
#   ./install.sh --no-launch   same, without opening the app
#   ./install.sh --bar-position left|center-left|center-mid|center-right|right|none
#                              where to put the top-bar button (Waybar on Omarchy 3.x, the Omarchy bar on 4.x);
#                              without it you're asked (1-5, 0 = none) when running in a terminal
#   ./install.sh --force       replace existing launcher/CLI/theme files even if Chevron didn't create them
#                              (or they changed since it did)
#   ./install.sh --uninstall   remove everything (alias for ./uninstall.sh; add --purge to delete settings too)
# Upgrading from the old "Chevron Cursor" (v1/v2) is automatic: settings and saved presets are migrated
# and the old files (only if still exactly as the old version left them), themes, autostart line and daemon are removed.
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
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
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

# --- ownership guard: only replace shared files Chevron Pro Cursor put there and nobody changed since ---
# Every shared path an install places is recorded in the manifest with its identity (sha256 for a file,
# the exact target for a symlink). A path may be replaced if it doesn't exist, already is exactly what
# we'd install, or its current identity matches that record (installs from before the manifest: a
# known release's file hash or symlink target). Anything else, including a file swapped or edited
# after install, is left alone unless the user agrees (interactive) or passes --force.
CORE="$LIB/chevron_core.py"
may_replace() {  # $1 = target, $2 = file we'd install there, or link:TARGET for a symlink
  local t="$1" want="${2:-}" st why
  [[ -e "$t" || -L "$t" ]] || return 0
  if [[ "$want" == link:* ]]; then
    [[ -L "$t" && "$(readlink "$t")" == "${want#link:}" ]] && return 0
  elif [[ -n "$want" && -f "$t" && ! -L "$t" ]] && cmp -s "$want" "$t"; then
    return 0
  fi
  st="$(python3 "$CORE" owns "$t" 2>/dev/null || echo foreign)"
  [[ "$st" == ours ]] && return 0
  if [[ "$st" == changed ]]; then why="has changed since Chevron Pro Cursor installed it"
  else why="wasn't installed by Chevron Pro Cursor"; fi
  if ((FORCE)); then echo "  replacing $t (--force)"; return 0; fi
  if [[ -t 0 ]]; then
    read -rp "$t already exists and $why. Replace it? [y/N] " a
    [[ "${a:-N}" =~ ^[Yy]$ ]] && return 0
  fi
  echo "  left $t alone (it $why; rerun with --force to replace it)"; return 1
}
placed=()
put() {  # put MODE SRC DEST
  if may_replace "$3" "$2"; then rm -f "$3"; install -m "$1" "$2" "$3"; placed+=("$3"); fi
}

# --- app files (upgrades our own previous version; never clobbers someone else's files) ---
mkdir -p "$BIN" "$LIB" "$APPS" "$ICONDIR" "$THEMES"
install -m 755 "$HERE/chevron_core.py" "$LIB/chevron_core.py"
install -m 644 "$HERE/reload_anim.py" "$LIB/reload_anim.py"
install -m 644 "$HERE/chevron_bar.py" "$LIB/chevron_bar.py"
install -m 755 "$HERE/uninstall.sh" "$LIB/uninstall.sh"
install -m 644 "$HERE/VERSION" "$LIB/VERSION"
# everything Chevron launches (desktop entry, bar button, trail autostart, post-install open) runs these
# copies inside our install dir; the ~/.local/bin commands are only a convenience for the terminal
install -m 755 "$HERE/chevron-pro-picker" "$LIB/chevron-pro-picker"
install -m 755 "$HERE/chevron-pro-trail" "$LIB/chevron-pro-trail"
PICKER_EXEC="$LIB/chevron-pro-picker"
CLI_EXEC="$LIB/chevron_core.py"
TRAIL_EXEC="$LIB/chevron-pro-trail"
put 755 "$HERE/chevron-pro-picker" "$BIN/chevron-pro-picker"
put 755 "$HERE/chevron-pro-trail" "$BIN/chevron-pro-trail"
if may_replace "$BIN/chevron-pro-cursor" "link:$LIB/chevron_core.py"; then
  rm -f "$BIN/chevron-pro-cursor"; ln -s "$LIB/chevron_core.py" "$BIN/chevron-pro-cursor"; placed+=("$BIN/chevron-pro-cursor")
fi
put 644 "$HERE/data/chevron-pro-cursor.png" "$ICONDIR/chevron-pro-cursor.png"
tmp_desktop="$(mktemp)"
sed "s#@BIN@/chevron-pro-picker#${PICKER_EXEC}#" "$HERE/data/chevron-pro-cursor.desktop" > "$tmp_desktop"
put 644 "$tmp_desktop" "$APPS/chevron-pro-cursor.desktop"; rm -f "$tmp_desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$THEMES/hicolor" 2>/dev/null || true
python3 "$LIB/chevron_core.py" record-original "${created[@]}"
echo "Installed app: $PICKER_EXEC  (launcher entry: 'Chevron Pro Cursor'), command: $CLI_EXEC"

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
python3 "$CORE" record-manifest "${placed[@]+"${placed[@]}"}"
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
# an existing button is re-added in place, so it launches the bundled copy (older versions used ~/.local/bin)
if [[ -z "$BAR_POS" && -n "${CUR_BAR:-}" && "$CUR_BAR" != none ]]; then BAR_POS="$CUR_BAR"; fi
if [[ -n "$BAR_POS" ]]; then
  python3 "$LIB/chevron_core.py" bar --position "$BAR_POS" | sed 's/^/  /'
fi

# --- restart the trail with the new version if it was running (or is enabled) ---
if [[ $restart_trail == 1 ]] && grep -q '"trail_enabled": true' "${XDG_CONFIG_HOME:-$HOME/.config}/chevron-pro-cursor/settings.json" 2>/dev/null; then
  (setsid "$TRAIL_EXEC" >/dev/null 2>&1 &); echo "Restarted the cursor trail (new version)."
fi
if [[ " ${placed[*]+"${placed[*]}"} " == *" $BIN/chevron-pro-cursor "* ]]; then
  echo "Uninstall any time with: $LIB/uninstall.sh  (or: chevron-pro-cursor uninstall)"
else
  echo "Uninstall any time with: $LIB/uninstall.sh  (or: $CLI_EXEC uninstall)"
fi

if [[ $NO_LAUNCH == 0 ]] && [[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then
  "$CLI_EXEC" open; echo "Launching Chevron Pro Cursor…"
fi
