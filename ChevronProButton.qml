import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar button for Chevron Pro Cursor: opens the settings app (installed by ./install.sh).
// Launches the shared CLI only if Chevron owns it (symlink into our install dir, or listed
// in the ownership manifest); otherwise the bundled copy in that directory.
BarWidget {
  id: root
  moduleName: "io.github.guitarmang89.chevron-pro-cursor"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: openApp
    command: ["sh", "-c", "data=\"${XDG_DATA_HOME:-$HOME/.local/share}/chevron-pro-cursor\"; shared=\"$HOME/.local/bin/chevron-pro-cursor\"; if { [ -L \"$shared\" ] && [ \"$(readlink \"$shared\")\" = \"$data/chevron_core.py\" ]; } || { [ -f \"$data/installed-files\" ] && grep -qxF \"$shared\" \"$data/installed-files\"; }; then exec \"$shared\" open; elif [ -x \"$data/chevron_core.py\" ]; then exec \"$data/chevron_core.py\" open; else echo \"Chevron Pro Cursor is not installed\" >&2; exit 1; fi"]
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
