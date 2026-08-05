import pygetwindow as gw
import time

# Fenster finden
fenster = gw.getWindowsWithTitle('METIN2')
print("Gefunden:", len(fenster))
if fenster:
    w = fenster[0]
    print("Titel:", w.title)
    print("Position:", w.left, w.top)
    print("Groesse:", w.width, w.height)
    print("Sichtbar:", w.visible)
    print("Aktiv:", w.isActive)
