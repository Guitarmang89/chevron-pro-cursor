import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar button for Chevron Pro Cursor: opens the settings app (installed by ./install.sh).
BarWidget {
  id: root
  moduleName: "io.github.guitarmang89.chevron-pro-cursor"

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: openApp
    command: ["sh", "-c", "exec \"$HOME/.local/bin/chevron-pro-cursor\" open"]
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
