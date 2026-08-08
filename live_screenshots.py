import cv2
import numpy as np
import time

# Live-Screenshots vom Metin2-Fenster speichern, wenn Popup offen ist
# Nutze dxcam für schnelle Screenshots
import dxcam
import win32gui

def fenster_finden(titel):
    """Finde Fenster per Titel (case-insensitive)."""
    def callback(hwnd, ergebnis):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if titel.lower() in t.lower():
                ergebnis.append((hwnd, t))
        return True
    ergebnis = []
    win32gui.EnumWindows(callback, ergebnis)
    return ergebnis

fenster = fenster_finden("METIN2")
print(f"Gefundene Fenster: {fenster}")
if not fenster:
    print("Kein METIN2-Fenster gefunden!")
    exit()

hwnd, titel = fenster[0]
links, oben, rechts, unten = win32gui.GetWindowRect(hwnd)
breite = rechts - links
hoehe = unten - oben
print(f"Fenster: {titel} bei ({links},{oben}) {breite}x{hoehe}")

# dxcam für schnelle Screenshots
cam = dxcam.create(output_idx=0, output_color="BGR")
cam.start(region=(links, oben, rechts, unten))

print("\nSammle Screenshots... (öffne jetzt das Fisch-Popup im Spiel!)")
print("Drücke STRG+C zum Beenden")
print("Es werden Screenshots gespeichert, wenn ein heller Kreis (Ring) erkannt wird.\n")

zähler = 0
try:
    while True:
        frame = cam.get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        
        # Popup-Erkennung: heller Kreis (Ring) im Fenster
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Ring = heller Bereich (Wasser) umgeben von mittelgrau
        wasser = gray > 180
        if wasser.sum() > 5000:  # großes helles Wasser = Popup offen
            zähler += 1
            datei = f"live_popup_{zähler:03d}.png"
            cv2.imwrite(datei, frame)
            print(f"Popup erkannt! Screenshot {zähler} gespeichert: {datei}")
            time.sleep(0.5)  # kurz warten, nicht zu viele speichern
        else:
            time.sleep(0.1)
except KeyboardInterrupt:
    print(f"\nFertig! {zähler} Screenshots gespeichert.")
    cam.stop()
