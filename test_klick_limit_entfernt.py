#!/usr/bin/env python3
"""test_klick_limit_entfernt.py - Verifiziert das Zwei-Loop-Design von
zustand_fischen() (siehe fish_bot.py, Modul-Docstring):

  - _mess_loop() (eigener Thread) misst kontinuierlich, klickt aber nie.
  - _klick_loop() (Hauptthread) klickt NUR bei Ring-Treffer + Stillstand,
    OHNE Vorhersage/Extrapolation bei Bewegung, und hoechstens EINMAL pro
    Stillstand-Phase (siehe test_ein_klick_pro_stillstand_phase()) - nicht
    bei jedem Poll waehrend derselbe Fisch weiter stillsteht. Zusaetzlich
    gebremst durch MIN_KLICK_ABSTAND_S als Sicherheitsnetz gegen
    Doppelklicks durch Erkennungsrauschen. Kein festes Klick-Limit pro
    Popup (MAX_KLICK_PRO_POPUP gab es fruecher, WAIT_AFTER_CLICK nie - beide
    sollen es weiterhin nicht geben) - mehrere GETRENNTE Stillstand-Phasen
    duerfen je einen Klick ausloesen, siehe
    test_mehrere_stillstand_phasen_mehrere_klicks().

Mockt fenster_finden_geprueft()/screenshot_holen()/popup_finden()/
ziel_finden(), damit der Test ohne echtes Spielfenster/Arduino laeuft. Da
zustand_fischen() jetzt einen echten Hintergrund-Thread startet (_mess_loop()
laeuft parallel zu _klick_loop() im Hauptthread), sind die Mocks anhand der
WANDUHR (time.time()) parametrisiert statt anhand eines Tick-Zaehlers - ein
fester Tick-Zaehler waere bei echter Parallelitaet nicht deterministisch
(siehe test_bewegung_kein_klick() unten).

Die Screenshot-ROI-Zuschneidung (_popup_roi(), siehe fish_bot.py) sorgt
dafuer, dass popup_finden()/ziel_finden() nach dem ersten Tick nur noch
Ausschnitte statt des ganzen (gemockten) Bilds sehen - die Fake-Funktionen
unten rechnen deshalb ihre "wahre" absolute Position anhand des zuletzt an
screenshot_holen() uebergebenen 'region' in Ausschnitts-Koordinaten um,
genau wie es die echte Bilderkennung auf einem echten Ausschnitt taete.
"""

import math
import time
import threading
from unittest import mock

import numpy as np

import fish_bot


class FakeMaus:
    def __init__(self):
        self.klick_zeiten = []
        self._lock = threading.Lock()

    def klick_links(self):
        with self._lock:
            self.klick_zeiten.append(time.time())
        return True


def _mocks(fenster, popup_abs, ziel_abs_fn, popup_schliesst_nach_s=None):
    """Baut die fuer zustand_fischen() benoetigten Mocks. ziel_abs_fn(t) gibt
    die "wahre" absolute Fischposition zum Zeitpunkt t (Sekunden seit Start)
    zurueck, oder None. popup_abs ist die feste Popup-Position/Radius, oder
    None fuer "nie ein Popup". popup_schliesst_nach_s: Popup verschwindet ab
    dieser Sekunde (None = nie)."""
    start = time.time()
    letzte_region = {"val": None}
    dummy_bild = np.zeros((10, 10, 3), dtype=np.uint8)

    def fake_screenshot_holen(_fenster, region=None):
        letzte_region["val"] = region
        return dummy_bild

    def _versatz():
        region = letzte_region["val"]
        return (region[0], region[1]) if region is not None else (0, 0)

    def fake_popup_finden(_screenshot):
        if popup_abs is None:
            return None
        t = time.time() - start
        if popup_schliesst_nach_s is not None and t > popup_schliesst_nach_s:
            return None
        ox, oy = _versatz()
        return (popup_abs[0] - ox, popup_abs[1] - oy, popup_abs[2])

    def fake_ziel_finden(_screenshot):
        t = time.time() - start
        pos = ziel_abs_fn(t)
        if pos is None:
            return None
        ox, oy = _versatz()
        return (pos[0] - ox, pos[1] - oy)

    return start, fake_screenshot_holen, fake_popup_finden, fake_ziel_finden


def test_bewegung_kein_klick():
    """Waehrend sich der Fisch bewegt (>STILLSTAND_SCHWELLE_PX zwischen den
    letzten STILLSTAND_FRAMES rohen Messungen), darf NICHT geklickt werden -
    auch wenn er die ganze Zeit im Ring ist. Keine Vorhersage/Extrapolation
    mehr fuer bewegte Ziele.

    Wichtig: die Bewegung ist ein MONOTONER Sweep pro Aufruf (Zaehler), nicht
    zeitbasiert und nicht hin- und herspringend - fisch_steht_still()
    vergleicht nur den ERSTEN und LETZTEN Punkt der letzten STILLSTAND_FRAMES
    Messungen (siehe dort), ein hin- und herspringendes Muster koennte also
    durch reinen Zufall wieder auf der Startposition landen und so faelschlich
    als 'stillstehend' erscheinen, obwohl dazwischen klar Bewegung war."""
    fenster = {"x": 0, "y": 0, "w": 400, "h": 300}
    popup_abs = (200, 150, 65)
    BEWEGT_BIS_S = 0.6
    zaehler = {"n": 0}

    def ziel_abs(t):
        if t >= BEWEGT_BIS_S:
            return None  # Test endet, bevor der Fisch stillstehen wuerde
        # Bewegt sich bei JEDEM Aufruf monoton deutlich (>STILLSTAND_SCHWELLE_PX)
        # durch den Ring, bleibt dabei aber komplett innerhalb (Radius+Puffer=75).
        zaehler["n"] += 1
        return (130 + zaehler["n"] * 18, 150)

    _, fake_screenshot, fake_popup, fake_ziel = _mocks(
        fenster, popup_abs, ziel_abs, popup_schliesst_nach_s=BEWEGT_BIS_S)

    maus = FakeMaus()
    with mock.patch.object(fish_bot, "fenster_finden_geprueft", return_value=fenster), \
         mock.patch.object(fish_bot, "screenshot_holen", side_effect=fake_screenshot), \
         mock.patch.object(fish_bot, "popup_finden", side_effect=fake_popup), \
         mock.patch.object(fish_bot, "ziel_finden", side_effect=fake_ziel), \
         mock.patch.object(fish_bot, "maus_bewegen"), \
         mock.patch.object(fish_bot, "POPUP_SCHLIESS_DEBOUNCE", 0.1):
        ergebnis = fish_bot.zustand_fischen(maus)

    assert ergebnis == fish_bot.ZUSTAND_WARTE_EINHOLEN, ergebnis
    assert maus.klick_zeiten == [], (
        f"Sollte waehrend staendiger Bewegung NIE klicken, hat aber "
        f"{len(maus.klick_zeiten)}x geklickt!")
    print("OK: kein einziger Klick waehrend staendiger Bewegung im Ring.")


def test_ein_klick_pro_stillstand_phase():
    """Steht der Fisch durchgehend (eine einzige, ununterbrochene Phase) im
    Ring still, darf trotzdem nur EIN EINZIGER Klick ausgeloest werden -
    nicht mehr bei jedem Poll/jeder Messung, waehrend die Stillstand-Phase
    andauert."""
    fenster = {"x": 0, "y": 0, "w": 400, "h": 300}
    popup_abs = (200, 150, 65)
    LAUFZEIT_S = 1.0

    def ziel_abs(t):
        return (200, 150)  # steht die ganze Zeit exakt still, EINE Phase

    _, fake_screenshot, fake_popup, fake_ziel = _mocks(
        fenster, popup_abs, ziel_abs, popup_schliesst_nach_s=LAUFZEIT_S)

    maus = FakeMaus()
    with mock.patch.object(fish_bot, "fenster_finden_geprueft", return_value=fenster), \
         mock.patch.object(fish_bot, "screenshot_holen", side_effect=fake_screenshot), \
         mock.patch.object(fish_bot, "popup_finden", side_effect=fake_popup), \
         mock.patch.object(fish_bot, "ziel_finden", side_effect=fake_ziel), \
         mock.patch.object(fish_bot, "maus_bewegen"), \
         mock.patch.object(fish_bot, "POPUP_SCHLIESS_DEBOUNCE", 0.1):
        ergebnis = fish_bot.zustand_fischen(maus)

    assert ergebnis == fish_bot.ZUSTAND_WARTE_EINHOLEN, ergebnis
    n = len(maus.klick_zeiten)
    print(f"Anzahl Klicks bei EINER durchgehenden Stillstand-Phase ueber ~{LAUFZEIT_S}s: {n}")
    assert n == 1, f"Erwartet genau 1 Klick pro Stillstand-Phase, bekommen {n}!"
    print("OK: durchgehender Stillstand -> genau 1 Klick, kein Nachklicken auf denselben Fisch.")


def test_mehrere_stillstand_phasen_mehrere_klicks():
    """Kein festes Klick-Limit pro Popup: mehrere GETRENNTE Stillstand-Phasen
    (jeweils durch eine echte Bewegungsphase voneinander getrennt) innerhalb
    desselben Popups duerfen jede fuer sich genau einen Klick ausloesen -
    still -> Klick -> bewegt -> Reset -> still -> Klick -> bewegt -> Reset
    -> still -> Klick."""
    fenster = {"x": 0, "y": 0, "w": 400, "h": 300}
    popup_abs = (200, 150, 65)

    # Zeitfenster in Sekunden seit Start: 3 Stillstand-Phasen, getrennt durch
    # 2 echte Bewegungsphasen (lang genug, um STILLSTAND_FRAMES=3 rohe
    # Messungen bei MESS_INTERVALL_S=0.08s sicher durchzuspuelen).
    PHASEN = [
        (0.00, 0.35, "still"),
        (0.35, 0.65, "bewegt"),
        (0.65, 1.00, "still"),
        (1.00, 1.30, "bewegt"),
        (1.30, 1.65, "still"),
    ]
    SCHLIESST_NACH_S = 1.65
    zaehler = {"n": 0}

    def ziel_abs(t):
        for start, ende, art in PHASEN:
            if start <= t < ende:
                if art == "still":
                    return (200, 150)
                # Monotoner Sweep (kein Hin-und-Her) - vermeidet, dass
                # fisch_steht_still() (vergleicht nur ersten/letzten Punkt
                # des Fensters) eine Bewegung faelschlich als Stillstand
                # liest, siehe test_bewegung_kein_klick().
                zaehler["n"] += 1
                return (130 + zaehler["n"] * 18, 150)
        return (200, 150)

    _, fake_screenshot, fake_popup, fake_ziel = _mocks(
        fenster, popup_abs, ziel_abs, popup_schliesst_nach_s=SCHLIESST_NACH_S)

    maus = FakeMaus()
    with mock.patch.object(fish_bot, "fenster_finden_geprueft", return_value=fenster), \
         mock.patch.object(fish_bot, "screenshot_holen", side_effect=fake_screenshot), \
         mock.patch.object(fish_bot, "popup_finden", side_effect=fake_popup), \
         mock.patch.object(fish_bot, "ziel_finden", side_effect=fake_ziel), \
         mock.patch.object(fish_bot, "maus_bewegen"), \
         mock.patch.object(fish_bot, "POPUP_SCHLIESS_DEBOUNCE", 0.1):
        ergebnis = fish_bot.zustand_fischen(maus)

    assert ergebnis == fish_bot.ZUSTAND_WARTE_EINHOLEN, ergebnis
    n = len(maus.klick_zeiten)
    print(f"Anzahl Klicks ueber 3 getrennte Stillstand-Phasen: {n}")
    assert n == 3, f"Erwartet genau 3 Klicks (1 pro Stillstand-Phase), bekommen {n}!"
    print("OK: 3 getrennte Stillstand-Phasen -> genau 3 Klicks (kein Klick-Limit pro "
          "Popup, aber genau 1 Klick pro Phase).")


def test_kein_klick_ausserhalb_ring():
    """Steht der Fisch ausserhalb des Rings (aber sonst still), darf trotz
    Stillstand nicht geklickt werden."""
    fenster = {"x": 0, "y": 0, "w": 400, "h": 300}
    popup_abs = (200, 150, 65)
    LAUFZEIT_S = 0.6

    def ziel_abs(t):
        return (200 + 200, 150)  # weit ausserhalb von Radius 65+Puffer

    _, fake_screenshot, fake_popup, fake_ziel = _mocks(
        fenster, popup_abs, ziel_abs, popup_schliesst_nach_s=LAUFZEIT_S)

    maus = FakeMaus()
    with mock.patch.object(fish_bot, "fenster_finden_geprueft", return_value=fenster), \
         mock.patch.object(fish_bot, "screenshot_holen", side_effect=fake_screenshot), \
         mock.patch.object(fish_bot, "popup_finden", side_effect=fake_popup), \
         mock.patch.object(fish_bot, "ziel_finden", side_effect=fake_ziel), \
         mock.patch.object(fish_bot, "maus_bewegen"), \
         mock.patch.object(fish_bot, "POPUP_SCHLIESS_DEBOUNCE", 0.1):
        ergebnis = fish_bot.zustand_fischen(maus)

    assert ergebnis == fish_bot.ZUSTAND_WARTE_EINHOLEN, ergebnis
    assert maus.klick_zeiten == [], (
        f"Sollte ausserhalb des Rings nie klicken, hat aber "
        f"{len(maus.klick_zeiten)}x geklickt!")
    print("OK: kein Klick, wenn der (stillstehende) Fisch ausserhalb des Rings ist.")


def test_fisch_steht_still_pur():
    """Reiner Funktionstest fuer fisch_steht_still() (keine Threads noetig)."""
    assert fish_bot.fisch_steht_still([]) is False
    assert fish_bot.fisch_steht_still([(0, 0), (1, 0)]) is False  # zu wenig Historie
    bewegt = [(0, 0), (50, 0), (100, 0)]
    assert fish_bot.fisch_steht_still(bewegt) is False
    still = [(100, 100), (101, 100), (102, 101)]
    assert fish_bot.fisch_steht_still(still) is True
    print("OK: fisch_steht_still() erkennt Bewegung/Stillstand korrekt.")


def test_kein_max_klick_limit():
    assert not hasattr(fish_bot, "MAX_KLICK_PRO_POPUP"), \
        "MAX_KLICK_PRO_POPUP sollte komplett entfernt sein!"
    assert not hasattr(fish_bot, "WAIT_AFTER_CLICK"), \
        "WAIT_AFTER_CLICK sollte komplett entfernt sein (kein Extra-Delay mehr)!"
    print("OK: kein MAX_KLICK_PRO_POPUP/WAIT_AFTER_CLICK mehr vorhanden.")


def main():
    test_kein_max_klick_limit()
    test_fisch_steht_still_pur()
    test_kein_klick_ausserhalb_ring()
    test_bewegung_kein_klick()
    test_ein_klick_pro_stillstand_phase()
    test_mehrere_stillstand_phasen_mehrere_klicks()
    print("\nAlle Tests OK.")


if __name__ == "__main__":
    main()
