#!/usr/bin/env python3
"""test_multi_fenster_erkennung.py - Tests fuer die Mehrfenster-Erkennung in
modules/fenster.py (alle_spielfenster_finden()/fenster_von_hwnd()) -
Grundlage der Mehrfach-Fenster-Unterstuetzung im Makro-Skript-System (siehe
aktion_skript.py/makro_manager.py/command_center.py MAKRO TOOLS-Reiter).

_alle_fenster() (roher EnumWindows-Scan) wird per unittest.mock gepatcht,
damit die Tests unabhaengig von tatsaechlich offenen Fenstern deterministisch
laufen. fenster_von_hwnd() wird stattdessen auf Ebene von user32 gepatcht
(GetWindowRect() erwartet ein ctypes.byref()-Ziel - siehe FakeUser32 unten).

Verwendung:
    python -m unittest test_multi_fenster_erkennung
"""

import ctypes
import unittest
from unittest import mock

import modules.fenster as fenster_modul


class TestAlleSpielfensterFinden(unittest.TestCase):

    def _mock_fenster(self, treffer):
        """treffer: Liste von (hwnd, titel, x, y, w, h)-Tupeln, wie sie
        _alle_fenster() liefert (bereits ohne ignorierte Systemfenster)."""
        return mock.patch.object(fenster_modul, "_alle_fenster", return_value=treffer)

    def test_filtert_nach_titel(self):
        rohdaten = [
            (1, "METIN2", 0, 0, 800, 600),
            (2, "Notepad", 0, 0, 400, 300),
            (3, "metin2 - zweiter Client", 900, 0, 800, 600),
        ]
        with self._mock_fenster(rohdaten):
            ergebnis = fenster_modul.alle_spielfenster_finden("METIN2")
        self.assertEqual(len(ergebnis), 2)
        self.assertTrue(all("metin2" in f["titel"].lower() for f in ergebnis))

    def test_nummerierung_oben_links_zuerst(self):
        # Absichtlich NICHT in Positions-Reihenfolge uebergeben - die
        # Nummerierung muss trotzdem nach Position sortieren (y, dann x).
        rohdaten = [
            (10, "METIN2", 900, 500, 800, 600),   # unten rechts
            (20, "METIN2", 0, 0, 800, 600),        # oben links
            (30, "METIN2", 900, 0, 800, 600),      # oben rechts (gleiche y wie hwnd 20)
        ]
        with self._mock_fenster(rohdaten):
            ergebnis = fenster_modul.alle_spielfenster_finden()
        self.assertEqual([f["hwnd"] for f in ergebnis], [20, 30, 10])
        self.assertEqual([f["nummer"] for f in ergebnis], [1, 2, 3])

    def test_leere_liste_ohne_treffer(self):
        with self._mock_fenster([]):
            self.assertEqual(fenster_modul.alle_spielfenster_finden(), [])

    def test_dict_form_entspricht_aufgabenstellung(self):
        rohdaten = [(42, "METIN2", 5, 6, 800, 600)]
        with self._mock_fenster(rohdaten):
            ergebnis = fenster_modul.alle_spielfenster_finden()
        self.assertEqual(ergebnis, [{
            "hwnd": 42, "titel": "METIN2", "x": 5, "y": 6,
            "breite": 800, "hoehe": 600, "nummer": 1,
        }])


class FakeUser32:
    """Ersetzt modules.fenster.user32 fuer fenster_von_hwnd()-Tests - simuliert
    genau die vier dort verwendeten WinAPI-Aufrufe fuer EIN bekanntes hwnd.

    GetWindowRect() erwartet als zweites Argument ctypes.byref(rect) - der
    private (aber stabile) '_obj'-Zugriff auf das darunterliegende Objekt
    erlaubt es, das RECT wie die echte WinAPI zu befuellen, ohne einen
    tatsaechlichen Foreign-Function-Call zu brauchen."""

    def __init__(self, existiert=True, sichtbar=True, titel="METIN2", rect=(10, 20, 826, 656)):
        self.existiert = existiert
        self.sichtbar = sichtbar
        self.titel = titel
        self.rect = rect  # (left, top, right, bottom)

    def IsWindow(self, hwnd):
        return self.existiert

    def IsWindowVisible(self, hwnd):
        return self.sichtbar

    def GetWindowTextLengthW(self, hwnd):
        return len(self.titel)

    def GetWindowTextW(self, hwnd, buf, size):
        buf.value = self.titel
        return len(self.titel)

    def GetWindowRect(self, hwnd, rect_ref):
        rect = rect_ref._obj
        rect.left, rect.top, rect.right, rect.bottom = self.rect
        return 1


class TestFensterVonHwnd(unittest.TestCase):

    def test_liefert_aktuelle_position(self):
        fake = FakeUser32(rect=(100, 50, 916, 686))
        with mock.patch.object(fenster_modul, "user32", fake):
            ergebnis = fenster_modul.fenster_von_hwnd(12345)
        self.assertEqual(ergebnis, {
            "hwnd": 12345, "titel": "METIN2", "x": 100, "y": 50, "w": 816, "h": 636,
        })

    def test_none_bei_geschlossenem_fenster(self):
        fake = FakeUser32(existiert=False)
        with mock.patch.object(fenster_modul, "user32", fake):
            self.assertIsNone(fenster_modul.fenster_von_hwnd(12345))

    def test_none_bei_unsichtbarem_fenster(self):
        fake = FakeUser32(sichtbar=False)
        with mock.patch.object(fenster_modul, "user32", fake):
            self.assertIsNone(fenster_modul.fenster_von_hwnd(12345))

    def test_none_ohne_hwnd(self):
        self.assertIsNone(fenster_modul.fenster_von_hwnd(None))
        self.assertIsNone(fenster_modul.fenster_von_hwnd(0))

    def test_neue_position_nach_verschieben(self):
        """Zwei aufeinanderfolgende Aufrufe muessen die JEWEILS aktuelle
        Position liefern (kein Caching) - Grundlage fuer 'Fensterposition
        wird bei jedem Zyklus neu geholt' (siehe Aufgabenstellung)."""
        fake = FakeUser32(rect=(0, 0, 816, 636))
        with mock.patch.object(fenster_modul, "user32", fake):
            erste = fenster_modul.fenster_von_hwnd(1)
            fake.rect = (500, 300, 1316, 936)
            zweite = fenster_modul.fenster_von_hwnd(1)
        self.assertEqual((erste["x"], erste["y"]), (0, 0))
        self.assertEqual((zweite["x"], zweite["y"]), (500, 300))


if __name__ == "__main__":
    unittest.main()
