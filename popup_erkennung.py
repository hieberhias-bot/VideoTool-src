#!/usr/bin/env python3
"""popup_erkennung.py - Erkennt den weissen Fischkreis-Ring im Angeln-Popup.

Fruehere Version suchte die duenne, nahezu weisse/entsaettigte RING-LINIE
per Kontur-Rundheit (Flaeche nahe pi*r^2) - das flackerte haeufig und
verfehlte den Ring oft komplett, weil eine nur wenige Pixel breite Linie
sehr anfaellig fuer Kompression/Antialiasing/Beleuchtung ist.

Naechste Version suchte stattdessen die groesste zusammenhaengende helle
FLAECHE (gleiche HSV-Schwelle, aber als Flaeche statt Linien-Kontur). Das
ergab jedoch regelmaessig Fehlerkennungen: im normalen Spielbild (KEIN
Popup offen) ist die groesste helle Flaeche fast immer der Himmel/die
obere UI-Leiste - eine breite, flache Flaeche ueber (fast) die gesamte
Bildbreite -, NICHT der Fischkreis. Per Diagnose an popup_debug.png
(Screenshot ohne Popup) wurde so faelschlich eine Box x=0 y=0 w=808 h=185
als "Popup" gemeldet.

Aktueller Ansatz: Nach derselben HSV-Schwelle (helle, kaum gesaettigte
Flaeche) wird NICHT mehr einfach die groesste Kontur genommen, sondern
die groesste Kontur, deren Form zu einem ausgefuellten KREIS passt:
  - Bounding-Box nahezu quadratisch (Breite ~= Hoehe)
  - Fuellgrad (Kontur-Flaeche / Box-Flaeche) nahe pi/4 (~0.785), wie bei
    einer ausgefuellten Kreisflaeche (die Ring-Linie wird durch das
    Closing zu einer fast vollstaendig gefuellten Scheibe verschmolzen)
Getestet an drei echten Popup-Screenshots (test_screenshot.png,
_live_check.png, bilder_szenen/Poop Up.png): der Ring-Kontur liefert dort
uebereinstimmend aspect~1.00, fill~0.79. Die falschen Himmel/UI-Flaechen
liegen dagegen bei aspect 4-33 und fill 0.07-0.58 - werden also zuverlaessig
per Form ausgeschlossen (deutlich robuster als eine feste Bildbereichs-
Grenze, die je nach Fensterlayout unterschiedlich waere).
"""

import cv2
import numpy as np

# Popup-Ring: kaum gesaettigt (S niedrig) und sehr hell (V hoch), Farbton
# beliebig - gleiche Kalibrierung wie zuvor fuer die Ring-Linie, da es
# dieselbe helle Flaeche ist, jetzt nur als Flaeche statt Linien-Kontur
# ausgewertet.
BOX_HSV_UNTERGRENZE = np.array([0, 0, 150], dtype=np.uint8)
BOX_HSV_OBERGRENZE = np.array([179, 90, 255], dtype=np.uint8)

MIN_KONTUR_FLAECHE = 300   # Pixel - filtert kleine helle Streuflecken raus

# Formfilter, um die kreisrunde Ring-Flaeche von flachen Himmel-/UI-Flaechen
# zu unterscheiden (siehe Modul-Docstring fuer die Messwerte, die diese
# Grenzen begruenden).
ASPECT_MIN = 0.75          # Breite/Hoehe der Box, untere Grenze (Kreis ~1.0)
ASPECT_MAX = 1.33          # Breite/Hoehe der Box, obere Grenze
FUELLGRAD_MIN = 0.55       # Kontur-Flaeche / Box-Flaeche, untere Grenze (Kreis ~0.785)
FUELLGRAD_MAX = 0.95       # obere Grenze
MAX_BOX_ANTEIL = 0.6       # Box darf hoechstens 60% der Bildbreite/-hoehe einnehmen
                           # (schliesst grossflaechige Fehltreffer wie eine
                           # bildfuellende Kontur aus)


def popup_finden(bild_np):
    """
    Sucht den weissen Fischkreis-Ring des Angeln-Minigames in einem BGR-
    Screenshot.

    Wertet alle hellen, kaum gesaettigten Konturen aus und behaelt nur die,
    deren Form zu einem ausgefuellten Kreis passt (siehe Modul-Docstring:
    Bounding-Box nahezu quadratisch + Fuellgrad nahe pi/4). Das filtert
    breite, flache Fehltreffer wie den Himmel/die obere UI-Leiste zuverlaessig
    heraus. Von den verbleibenden, formlich passenden Kandidaten wird der
    groesste genommen. Der Radius wird aus deren Bounding-Box geschaetzt
    (Mittel aus halber Breite und halber Hoehe).

    Args:
        bild_np (np.ndarray): BGR-Screenshot (z.B. vom METIN2-Fenster).

    Returns:
        tuple[int, int, int] | None: (cx, cy, radius) in Bildkoordinaten,
            oder None wenn kein formlich passender Fischkreis gefunden wurde.
    """
    bild_h, bild_w = bild_np.shape[:2]

    hsv = cv2.cvtColor(bild_np, cv2.COLOR_BGR2HSV)
    maske = cv2.inRange(hsv, BOX_HSV_UNTERGRENZE, BOX_HSV_OBERGRENZE)
    # Ein kleines Closing schliesst Luecken/Antialiasing-Kanten in der
    # Ring-Linie, wodurch sie zu einer fast vollstaendig gefuellten
    # Kreisflaeche verschmilzt (Fuellgrad nahe pi/4, siehe Formfilter unten).
    kernel = np.ones((5, 5), np.uint8)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, kernel)

    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not konturen:
        return None

    bester = None       # (Flaeche, cx, cy, radius) des besten Kandidaten bisher
    for kontur in konturen:
        flaeche = cv2.contourArea(kontur)
        if flaeche < MIN_KONTUR_FLAECHE:
            continue

        x, y, w, h = cv2.boundingRect(kontur)
        if w == 0 or h == 0:
            continue

        # Grossflaechige Bereiche wie Himmel/UI-Leisten ausschliessen, die
        # (fast) die gesamte Bildbreite/-hoehe einnehmen.
        if w > bild_w * MAX_BOX_ANTEIL or h > bild_h * MAX_BOX_ANTEIL:
            continue

        # Formfilter: nur (nahezu) quadratische, (nahezu) kreisfoermig
        # gefuellte Konturen sind Kandidaten fuer den Fischkreis-Ring - das
        # unterscheidet ihn von flachen, laenglichen hellen Flaechen wie dem
        # Himmel (siehe Modul-Docstring fuer die Messwerte).
        seitenverhaeltnis = w / h
        fuellgrad = flaeche / (w * h)
        if not (ASPECT_MIN <= seitenverhaeltnis <= ASPECT_MAX):
            continue
        if not (FUELLGRAD_MIN <= fuellgrad <= FUELLGRAD_MAX):
            continue

        if bester is None or flaeche > bester[0]:
            cx, cy = x + w / 2.0, y + h / 2.0
            radius = (w + h) / 4.0  # Mittel aus halber Breite und halber Hoehe
            bester = (flaeche, cx, cy, radius)

    if bester is None:
        return None

    _, cx, cy, radius = bester
    return int(round(cx)), int(round(cy)), int(round(radius))


def _debug_bild(bild_np, popup):
    """Zeichnet den erkannten Kreis auf eine Kopie des Bilds (fuer manuelle Pruefung)."""
    dbg = bild_np.copy()
    if popup is not None:
        cx, cy, r = popup
        cv2.circle(dbg, (cx, cy), r, (0, 0, 255), 2)
        cv2.circle(dbg, (cx, cy), 3, (0, 255, 0), -1)
    return dbg


if __name__ == "__main__":
    # Kleiner manueller Test gegen die beiden Referenzbilder, falls vorhanden.
    import sys

    pfade = sys.argv[1:] or [
        "C:/Users/vm1/Desktop/projekt/popup1.webp.png",
        "C:/Users/vm1/Desktop/projekt/popup2.webp.png",
    ]
    for pfad in pfade:
        bild = cv2.imread(pfad)
        if bild is None:
            print(f"{pfad}: konnte nicht geladen werden")
            continue
        ergebnis = popup_finden(bild)
        print(f"{pfad}: shape={bild.shape} -> popup_finden() = {ergebnis}")
