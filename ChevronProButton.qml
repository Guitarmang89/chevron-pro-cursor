import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar button for Chevron Pro Cursor: opens the settings app (installed by ./install.sh).
// Always runs the bundled copy inside Chevron's install dir, never a shared ~/.local/bin path
// (anyone can replace those after install).
BarWidget {
  id: root
  moduleName: "io.github.guitarmang89.chevron-pro-cursor"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: openApp
    command: ["sh", "-c", "core=\"${XDG_DATA_HOME:-$HOME/.local/share}/chevron-pro-cursor/chevron_core.py\"; if [ -f \"$core\" ]; then exec python3 \"$core\" open; else echo \"Chevron Pro Cursor is not installed\" >&2; exit 1; fi"]
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\udb80\uddc0"          // nf-md-chevron_up (same glyph as the Waybar button)
    slotSize: Style.bar.statusSlot
    tooltipText: "Chevron Pro Cursor"
    onPressed: openApp.running = true
  }
}
