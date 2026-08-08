#!/usr/bin/env python3
"""test_klick_offset.py - Misst systematisch den Versatz zwischen einer per
HID-Maus angepeilten und der tatsaechlich (per GetCursorPos) angefahrenen
Cursor-Position.

Hintergrund: Klicks landeten wiederholt ~15px (~4mm) zu weit LINKS vom
beabsichtigten Ziel, unabhaengig davon, wo im METIN2-Fenster geklickt wurde.
Die Python-seitige Koordinaten-Pipeline (fenster_finden -> screenshot_holen ->
Klickziel) ist in sich konsistent (siehe fish_bot.py); der Versatz muss also
entweder aus der Firmware-seitigen USB-HID-Skalierung oder aus Windows'
Zuordnung des HID-Absolut-Bereichs auf den Bildschirm kommen - beides von hier
aus nicht am Quellcode nachvollziehbar (Firmware-Sketch nicht im Repository).

Verwendung:
    python test_klick_offset.py

Voraussetzung: Kein anderer Prozess (z.B. Command Center) darf die HID-Maus
(COM-Port) gerade geoeffnet haben - ein serieller Port erlaubt nur eine
Verbindung gleichzeitig.
"""

import sys
import time
import ctypes
from ctypes import wintypes

from modules.fenster import fenster_finden
from hid_maus import HIDMaus, KLICK_OFFSET_X_PX, KLICK_OFFSET_Y_PX

FENSTER_TITEL = "METIN2"
user32 = ctypes.windll.user32


def _cursor_position():
    punkt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(punkt))
    return punkt.x, punkt.y


def _testpunkte(fenster):
    """Liefert benannte Testpunkte relativ zum Fenster: Mitte + je ein Punkt
    nahe links/rechts/oben/unten (mit Rand-Puffer, damit die Maus nicht am
    Fensterrand haengt)."""
    x, y, w, h = fenster["x"], fenster["y"], fenster["w"], fenster["h"]
    puffer = max(30, min(w, h) // 6)
    return [
        ("Mitte", x + w // 2, y + h // 2),
        ("Links", x + puffer, y + h // 2),
        ("Rechts", x + w - puffer, y + h // 2),
        ("Oben", x + w // 2, y + puffer),
        ("Unten", x + w // 2, y + h - puffer),
    ]


def messen(maus, ziel_x, ziel_y, versuche=3):
    """Bewegt die Maus 'versuche'-mal zum selben Ziel und liest jedes Mal die
    tatsaechliche Position aus - mehrfach, um Ausreisser (Timing/Rundung) von
    einem echten systematischen Versatz zu unterscheiden."""
    messungen = []
    for _ in range(versuche):
        ok = maus.maus_bewegen_abs(ziel_x, ziel_y)
        time.sleep(0.15)
        ist_x, ist_y = _cursor_position()
        messungen.append((ok, ist_x, ist_y))
    return messungen


def main():
    fenster = fenster_finden(FENSTER_TITEL)
    if fenster is None:
        print(f"FEHLER: Fenster '{FENSTER_TITEL}' nicht gefunden - Test abgebrochen.")
        return 1
    print(f"Fenster: {fenster}")

    maus = HIDMaus(port=None)
    if not maus.port:
        print("FEHLER: Kein Arduino gefunden (Auto-Erkennung fehlgeschlagen).")
        return 1
    if not maus.verbinden():
        print(f"FEHLER: Verbindung zu {maus.port} fehlgeschlagen (Port bereits belegt?).")
        return 1

    print(f"Verbunden mit {maus.port}. Aktive Korrektur: "
          f"KLICK_OFFSET_X_PX={KLICK_OFFSET_X_PX}, KLICK_OFFSET_Y_PX={KLICK_OFFSET_Y_PX}\n")

    zeilen = []
    for name, ziel_x, ziel_y in _testpunkte(fenster):
        messungen = messen(maus, ziel_x, ziel_y)
        # Median der Wiederholungen als robuster Ist-Wert je Punkt.
        xs = sorted(m[1] for m in messungen)
        ys = sorted(m[2] for m in messungen)
        ist_x = xs[len(xs) // 2]
        ist_y = ys[len(ys) // 2]
        dx = ist_x - ziel_x
        dy = ist_y - ziel_y
        alle_bestaetigt = all(m[0] for m in messungen)
        zeilen.append((name, ziel_x, ziel_y, ist_x, ist_y, dx, dy, alle_bestaetigt))

    maus.schliessen()

    header = f"{'Punkt':8} {'Ziel X':>7} {'Ziel Y':>7} {'Ist X':>7} {'Ist Y':>7} {'dX':>5} {'dY':>5}  ACK"
    print(header)
    print("-" * len(header))
    dxs, dys = [], []
    for name, zx, zy, ix, iy, dx, dy, ack in zeilen:
        print(f"{name:8} {zx:7d} {zy:7d} {ix:7d} {iy:7d} {dx:5d} {dy:5d}  {'ja' if ack else 'NEIN'}")
        dxs.append(dx)
        dys.append(dy)

    print()
    dx_min, dx_max = min(dxs), max(dxs)
    dy_min, dy_max = min(dys), max(dys)
    dx_konstant = (dx_max - dx_min) <= 3
    dy_konstant = (dy_max - dy_min) <= 3
    print(f"dX-Bereich: {dx_min} bis {dx_max} ({'konstant' if dx_konstant else 'NICHT konstant'})")
    print(f"dY-Bereich: {dy_min} bis {dy_max} ({'konstant' if dy_konstant else 'NICHT konstant'})")

    if dx_konstant and dy_konstant:
        dx_avg = round(sum(dxs) / len(dxs))
        dy_avg = round(sum(dys) / len(dys))
        empfohlen_x = KLICK_OFFSET_X_PX - dx_avg
        empfohlen_y = KLICK_OFFSET_Y_PX - dy_avg
        print(f"\nOffset ist konstant. Empfohlene KLICK_OFFSET_X_PX/Y_PX in hid_maus.py: "
              f"{empfohlen_x} / {empfohlen_y} (aktuell: {KLICK_OFFSET_X_PX} / {KLICK_OFFSET_Y_PX})")
        if abs(dx_avg) <= 3 and abs(dy_avg) <= 3:
            print("Toleranz <=3px bereits erreicht - keine weitere Anpassung noetig.")
        else:
            print("Toleranz >3px - hid_maus.KLICK_OFFSET_X_PX/Y_PX auf die empfohlenen "
                  "Werte setzen und Test wiederholen.")
    else:
        print("\nOffset schwankt zwischen den Punkten - kein einfacher konstanter Versatz, "
              "eine additive Korrektur allein wird das Problem nicht vollstaendig loesen "
              "(z.B. Skalierungsfehler statt konstantem Offset moeglich).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
