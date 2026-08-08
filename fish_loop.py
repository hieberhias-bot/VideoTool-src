#!/usr/bin/env python3
"""fish_loop.py - Vereinfachter Fisch-Bot ohne Zustandsautomat.

Im Gegensatz zu fish_bot.py (Zustandsautomat mit WURM_KLICKEN, PRUEFE_POPUP_1-4,
Inventar-Logik) macht FishLoop nur EINE Sache in einer Endlosschleife:

    auf Popup warten -> Fisch im Ring suchen -> bei Stillstand+klickbar klicken
    -> Popup weg -> von vorn

Kein Wurm-Nachlegen, kein Inventar, keine Wiederherstellungs-Kette - dafuer
deutlich weniger Code.

Popup-Erkennung: Template-Matching (popup_matchtemplate()) statt der
bisherigen HSV-Box-Erkennung (popup_erkennung.popup_finden()) - portiert aus
der Original-Methode von DownD/MetinFishingCV (FishingDetection.py), die
unabhaengig von der Ring-Farbe/-Animation ist und daher deutlich weniger
Fehlerkennungen liefert (die alte HSV-Box-Erkennung fand u.a. andere runde
UI-Elemente faelschlich als "Popup").

Fisch-/Klickbarkeits-Erkennung: fisch_hsv()/kreis_klickbar(), ebenfalls
1:1 aus demselben Original-Projekt portiert (exakte Parameter, siehe
FISH_COLOR_*/GRAB_COLOR_*/GRAB_THRESHOLD_SUM unten) - anstelle der bisherigen
Fisch-Ring-Geometrie (fisch_im_ring()) entscheidet jetzt der farbliche
"klickbar"-Zustand des Rings selbst (kreis_klickbar()) ueber den Klick.

fish_bot.py wird von dieser Datei nicht veraendert; nur FischGlaetter (reiner
Rauschfilter, keine Zustandsmaschine) wird von dort wiederverwendet.
"""

import os
import time
import math
import logging

import cv2
import numpy as np
from PIL import ImageGrab

try:
    import dxcam
except ImportError:
    dxcam = None

from modules.fenster import fenster_finden
from hid_maus import HIDMaus
from fish_bot import FischGlaetter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_logger = logging.getLogger("FishLoop")

FENSTER_TITEL = "METIN2"

STILLSTAND_SCHWELLE_PX = 5   # Pixel
STILLSTAND_FRAMES = 3        # Anzahl verglichener GEFILTERTER (nicht roher) Positionen
MIN_KLICK_ABSTAND_S = 0.1    # Sekunden zwischen zwei Klicks
WARTE_INTERVALL_S = 0.08     # Sekunden zwischen zwei Loop-Durchlaeufen

# Rohe Fisch-Erkennungen springen durch Glitzer/Schatten im Wasser bis zu
# ~100px zwischen zwei Messungen (siehe fish_bot.py) - ohne Ausreisser-Filter
# wuerde fisch_steht_still() praktisch nie True liefern. Deshalb laeuft jede
# neue Position zuerst durch FischGlaetter (Ausreisser-Filter + Median,
# siehe fish_bot.py) - dieselbe, dort bereits gegen echte Aufnahmen getestete
# Filterlogik, hier wiederverwendet statt dupliziert.
MAX_SPRUNG_PX = 40

# ---------- Original-Parameter aus DownD/MetinFishingCV/FishingDetection.py ----------
# (unveraendert uebernommen, siehe Aufgabenstellung - NICHT verandern ohne
# das Original erneut zu pruefen)

GAME_TEMPLATE_PFAD = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "resources", "template_fish_game_border.png")
GAME_THRESHOLD = 0.7
GAME_RESIZE_FACTOR = 0.3

# Rand des Popup-Templates, der beim Zuschneiden auf die Ring-Innenflaeche
# abgezogen wird - oben BORDER_OFFSET+BORDER_OFFSET_TITLE (Rahmen + "Fish
# Game"-Titelleiste), an den anderen drei Seiten je BORDER_OFFSET (exakt wie
# get_game_template_crop() im Original).
BORDER_OFFSET = 10
BORDER_OFFSET_TITLE = 28

FISH_COLOR_LBOUND = np.array([73, 99, 116], dtype=np.uint8)
FISH_COLOR_HBOUND = np.array([144, 154, 132], dtype=np.uint8)

GRAB_COLOR_LBOUND = np.array([118, 56, 141], dtype=np.uint8)
GRAB_COLOR_HBOUND = np.array([255, 144, 255], dtype=np.uint8)
GRAB_THRESHOLD_SUM = 40000  # Vergleich gegen np.sum(maske) (0/255-Werte), NICHT Pixelanzahl

# ---------------------------------------------------------------------------

_dxcam_kamera = None   # lazy erzeugte dxcam-Kamera
_dxcam_kaputt = False  # True, sobald dxcam einmal fehlgeschlagen ist

_popup_template_grau = None  # um GAME_RESIZE_FACTOR verkleinertes Graustufen-Template
_popup_box_w = None           # volle (hochskalierte) Breite/Hoehe des Templates
_popup_box_h = None           # (siehe popup_matchtemplate()/_popup_box())


def _dxcam_holen():
    """Liefert die (einmalig erzeugte) dxcam-Kamera, oder None wenn dxcam
    nicht installiert ist oder fehlschlaegt (siehe fish_bot.py: dxcam ist um
    Groessenordnungen schneller als PIL ImageGrab, PIL bleibt Fallback)."""
    global _dxcam_kamera, _dxcam_kaputt
    if _dxcam_kamera is not None or _dxcam_kaputt:
        return _dxcam_kamera
    if dxcam is None:
        _dxcam_kaputt = True
        return None
    try:
        _dxcam_kamera = dxcam.create(output_color="BGR")
    except Exception as e:
        _logger.warning("dxcam.create() fehlgeschlagen (%s) - falle auf PIL ImageGrab zurueck", e)
        _dxcam_kaputt = True
        return None
    return _dxcam_kamera


def _popup_template_holen():
    """Laedt und verkleinert das Popup-Referenzbild einmalig (Graustufen,
    um GAME_RESIZE_FACTOR verkleinert - dieselbe Vorverarbeitung wie fuer
    jeden Suchframe in popup_matchtemplate())."""
    global _popup_template_grau, _popup_box_w, _popup_box_h
    if _popup_template_grau is not None:
        return _popup_template_grau
    bild = cv2.imread(GAME_TEMPLATE_PFAD)
    if bild is None:
        _logger.error("Popup-Template nicht gefunden: %s", GAME_TEMPLATE_PFAD)
        return None
    _popup_box_h, _popup_box_w = bild.shape[:2]
    grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    _popup_template_grau = cv2.resize(grau, None, fx=GAME_RESIZE_FACTOR, fy=GAME_RESIZE_FACTOR)
    return _popup_template_grau


def popup_matchtemplate(frame):
    """Erkennt das Angel-Popup per Template-Matching (Original-Methode aus
    DownD/MetinFishingCV/FishingDetection.py) statt per HSV-Box-Erkennung.

    Ablauf (exakt wie im Original): BilateralFilter(7,85,85) -> Graustufen ->
    um GAME_RESIZE_FACTOR (0.3) verkleinern -> cv2.matchTemplate gegen das
    (gleich vorverarbeitete) Referenzbild. Korrelation < GAME_THRESHOLD (0.7)
    => kein Popup.

    Returns:
        (int, int, int) | None: (cx, cy, radius) in Vollbild-Koordinaten -
            radius ist die halbe Hoehe des gefundenen Bereichs in
            ORIGINALGROESSE (nicht verkleinert), oder None wenn kein Popup
            gefunden wurde.
    """
    vorlage = _popup_template_holen()
    if vorlage is None:
        return None

    gefiltert = cv2.bilateralFilter(frame, 7, 85, 85)
    grau = cv2.cvtColor(gefiltert, cv2.COLOR_BGR2GRAY)
    klein = cv2.resize(grau, None, fx=GAME_RESIZE_FACTOR, fy=GAME_RESIZE_FACTOR)

    if klein.shape[0] < vorlage.shape[0] or klein.shape[1] < vorlage.shape[1]:
        return None

    ergebnis = cv2.matchTemplate(klein, vorlage, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(ergebnis)
    if max_val < GAME_THRESHOLD:
        return None

    x0 = int(max_loc[0] / GAME_RESIZE_FACTOR)
    y0 = int(max_loc[1] / GAME_RESIZE_FACTOR)
    cx = x0 + _popup_box_w // 2
    cy = y0 + _popup_box_h // 2
    radius = _popup_box_h // 2
    return cx, cy, radius


def _popup_box(popup, frame_w, frame_h):
    """Rekonstruiert die volle Match-Box aus (cx, cy, radius) und schneidet
    dann BORDER_OFFSET/BORDER_OFFSET_TITLE ab (exakt wie
    get_game_template_crop() im Original), um die Ring-Innenflaeche (ohne
    Rahmen/Titelleiste) zu erhalten. Auf die Frame-Grenzen begrenzt."""
    cx, cy, _ = popup
    x0 = cx - _popup_box_w // 2
    y0 = cy - _popup_box_h // 2
    x1 = x0 + _popup_box_w
    y1 = y0 + _popup_box_h

    x0 = max(0, x0 + BORDER_OFFSET)
    y0 = max(0, y0 + BORDER_OFFSET + BORDER_OFFSET_TITLE)
    x1 = min(frame_w, x1 - BORDER_OFFSET)
    y1 = min(frame_h, y1 - BORDER_OFFSET)
    return x0, y0, x1, y1


def fisch_hsv(frame, popup):
    """Sucht die groesste Kontur im FISH_COLOR-HSV-Bereich innerhalb der
    Ring-Innenflaeche (Original-Methode: groesste Kontur -> Momente ->
    Zentrum). Gibt (x, y) in Vollbild-Koordinaten zurueck, oder None."""
    x0, y0, x1, y1 = _popup_box(popup, frame.shape[1], frame.shape[0])
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    maske = cv2.inRange(hsv, FISH_COLOR_LBOUND, FISH_COLOR_HBOUND)
    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not konturen:
        return None

    groesste = max(konturen, key=cv2.contourArea)
    momente = cv2.moments(groesste)
    if momente["m00"] == 0:
        return None

    fisch_x = int(momente["m10"] / momente["m00"]) + x0
    fisch_y = int(momente["m01"] / momente["m00"]) + y0
    return fisch_x, fisch_y


def kreis_klickbar(frame, popup):
    """True, wenn die Summe der GRAB_COLOR-Maske innerhalb der Ring-
    Innenflaeche GRAB_THRESHOLD_SUM uebersteigt (Original-Methode:
    np.sum(maske) einer 0/255-Maske, NICHT Pixel-Anzahl)."""
    x0, y0, x1, y1 = _popup_box(popup, frame.shape[1], frame.shape[0])
    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return False

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    maske = cv2.inRange(hsv, GRAB_COLOR_LBOUND, GRAB_COLOR_HBOUND)
    return int(np.sum(maske)) > GRAB_THRESHOLD_SUM


class FishLoop:
    """Reiner Popup-Fisch-Loop (siehe Modul-Docstring)."""

    def __init__(self, maus):
        self.maus = maus
        self._glaetter = FischGlaetter(max_sprung_px=MAX_SPRUNG_PX)
        self._historie = []      # letzte STILLSTAND_FRAMES GEFILTERTEN (nicht rohen) Fischpositionen
        self._letzter_klick = 0.0
        self.fisch_glatt = None  # median-geglaettete Position, siehe fisch_steht_still()

    def screenshot_holen(self):
        """Screenshot des METIN2-Fensters (dxcam bevorzugt, PIL-Fallback).

        Returns:
            (np.ndarray, dict) | (None, None): BGR-Bild + Fenster-Dict
                {"x","y","w","h"}, oder (None, None) wenn das Fenster gerade
                nicht gefunden wurde.
        """
        fenster = fenster_finden(FENSTER_TITEL)
        if fenster is None:
            return None, None

        box = (fenster["x"], fenster["y"],
               fenster["x"] + fenster["w"], fenster["y"] + fenster["h"])

        frame = None
        kamera = _dxcam_holen()
        if kamera is not None:
            try:
                frame = kamera.grab(region=box, new_frame_only=False)
            except Exception as e:
                _logger.warning("dxcam.grab() fehlgeschlagen (%s) - PIL-Fallback", e)
                frame = None
        if frame is None:
            bild = ImageGrab.grab(bbox=box)
            frame = cv2.cvtColor(np.array(bild), cv2.COLOR_RGB2BGR)

        return frame, fenster

    def fisch_steht_still(self, pos):
        """Verarbeitet eine neue ROHE Fisch-Position durch den Ausreisser-
        Filter (siehe FischGlaetter/MAX_SPRUNG_PX-Kommentar oben) und gibt
        True zurueck, wenn die letzten STILLSTAND_FRAMES GEFILTERTEN (nicht
        rohen, aber auch nicht median-geglaetteten) Positionen sich um
        weniger als STILLSTAND_SCHWELLE_PX bewegt haben.

        Die median-geglaettete Position fuer den Klickpunkt selbst steht
        danach in self.fisch_glatt (siehe laufe())."""
        self.fisch_glatt = self._glaetter.position(pos[0], pos[1])
        gefiltert = self._glaetter.gefilterte_position()

        self._historie.append(gefiltert)
        if len(self._historie) > STILLSTAND_FRAMES:
            self._historie.pop(0)
        if len(self._historie) < STILLSTAND_FRAMES:
            return False
        return math.dist(self._historie[0], self._historie[-1]) < STILLSTAND_SCHWELLE_PX

    def fisch_im_ring(self, fisch_pos, popup_center, radius):
        """True, wenn 'fisch_pos' innerhalb von 'radius' um 'popup_center'
        liegt. Nicht mehr Teil der Klick-Entscheidung (siehe laufe() -
        kreis_klickbar() ersetzt die geometrische Ring-Pruefung durch den
        farblichen "klickbar"-Zustand des Original-Projekts), bleibt aber
        als eigenstaendige Hilfsfunktion verfuegbar."""
        dx = fisch_pos[0] - popup_center[0]
        dy = fisch_pos[1] - popup_center[1]
        return (dx * dx + dy * dy) <= (radius * radius)

    def laufe(self):
        """Haupt-Loop: Endlosschleife bis KeyboardInterrupt (Strg+C).

        Klick-Gate (siehe Aufgabenstellung): Popup gefunden UND Ring laut
        kreis_klickbar() farblich klickbar UND Fisch steht still.
        """
        _logger.info("FishLoop gestartet - Strg+C zum Beenden.")
        try:
            while True:
                frame, fenster = self.screenshot_holen()
                if frame is None:
                    time.sleep(WARTE_INTERVALL_S)
                    continue

                popup = popup_matchtemplate(frame)
                if popup is None:
                    self._glaetter.reset()
                    self._historie.clear()
                    time.sleep(WARTE_INTERVALL_S)
                    continue

                cx, cy, r = popup
                _logger.info("Popup erkannt: (%d, %d) r=%d", cx, cy, r)

                ziel = fisch_hsv(frame, popup)
                if ziel is None:
                    time.sleep(WARTE_INTERVALL_S)
                    continue

                still = self.fisch_steht_still(ziel)
                klickbar = kreis_klickbar(frame, popup)

                jetzt = time.time()
                sperre_abgelaufen = (jetzt - self._letzter_klick) >= MIN_KLICK_ABSTAND_S

                if klickbar and still and sperre_abgelaufen:
                    glatt_x, glatt_y = self.fisch_glatt
                    ziel_x = fenster["x"] + glatt_x
                    ziel_y = fenster["y"] + glatt_y
                    self.maus.maus_bewegen_abs(ziel_x, ziel_y)
                    time.sleep(0.05)
                    self.maus.klick_links()
                    self._letzter_klick = jetzt
                    _logger.info("Klick auf (%d, %d)", ziel_x, ziel_y)

                time.sleep(WARTE_INTERVALL_S)
        except KeyboardInterrupt:
            _logger.info("FishLoop gestoppt (Strg+C).")


def main():
    maus = HIDMaus("COM9")
    if not maus.verbinden():
        _logger.error("Keine Verbindung zur HID-Maus auf COM9.")
        return
    try:
        FishLoop(maus).laufe()
    finally:
        maus.schliessen()


if __name__ == "__main__":
    main()
