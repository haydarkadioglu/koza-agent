import { app, Menu, Tray } from "electron"
import { iconPath } from "./windows"
import { getLastFocusedWindow } from "./window-registry"

let tray: Tray | null = null

export function setupTray(quitApp: () => void) {
  if (tray) return

  tray = new Tray(iconPath())
  tray.setToolTip("Koza")
  
  const contextMenu = Menu.buildFromTemplate([
    {
      label: "Show Koza",
      click: () => {
        const win = getLastFocusedWindow()
        if (win) {
          win.show()
          win.focus()
        }
      },
    },
    { type: "separator" },
    {
      label: "Quit Koza",
      click: quitApp,
    },
  ])

  tray.setContextMenu(contextMenu)

  tray.on("click", () => {
    const win = getLastFocusedWindow()
    if (win) {
      if (win.isVisible()) {
        if (win.isFocused()) {
          win.hide()
        } else {
          win.focus()
        }
      } else {
        win.show()
        win.focus()
      }
    }
  })
}
