#!/usr/bin/env bash
# Chevron Pro Cursor uninstaller. Removes the app, CLI, trail daemon (and its autostart), launcher entry,
# icon, Hyprland snippets (.conf/.lua) + their include lines, the top-bar button (Waybar / omarchy-shell), and all ChevronPro cursor themes (plus leftovers
# of the old "Chevron Cursor" v1/v2), then restores the cursor you had before installing.
#   uninstall.sh                 asks whether to delete your settings and saved presets
#   uninstall.sh --purge         also delete ~/.config/chevron-pro-cursor (settings + presets)
#   uninstall.sh --keep-settings keep them without asking
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE=""
for c in "$HERE/chevron_core.py" "${XDG_DATA_HOME:-$HOME/.local/share}/chevron-pro-cursor/chevron_core.py"; do
  [[ -f "$c" ]] && { CORE="$c"; break; }
done
if [[ -z "$CORE" ]]; then echo "Chevron Pro Cursor doesn't seem to be installed (chevron_core.py not found)."; exit 0; fi
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cp "$CORE" "$TMP/"
for m in reload_anim.py chevron_bar.py; do [[ -f "$(dirname "$CORE")/$m" ]] && cp "$(dirname "$CORE")/$m" "$TMP/"; done
python3 "$TMP/chevron_core.py" uninstall "$@"
