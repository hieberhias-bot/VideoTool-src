#!/usr/bin/env python3
"""test_makro_fenster_isolation.py - Tests fuer die Fenster-ISOLATION eines
einzelnen Makros auf genau EIN METIN2-Fenster (siehe Aufgabenstellung
"FENSTER-ISOLATION"): aktion_skript.py bekommt dafuer einen optionalen
'fenster_provider'-Parameter, der bei jedem Bild-/Fokus-/Wurm-/MAUS_ABS-
Schritt neu nach der aktuellen Fensterposition gefragt wird (siehe
modules.fenster.fenster_von_hwnd()), statt (wie bisher ohne fenster_provider)
immer das erste METIN2-Fenster per Titel zu suchen.

Alle Tests laufen OHNE echte HID-Maus/echtes METIN2-Fenster (FakeMaus +
gemockte fish_bot/win32gui-Aufrufe).

Verwendung:
    python -m unittest test_makro_fenster_isolation
"""

import unittest
from unittest import mock

import numpy as np

import aktion_skript
import bild_erkennung


class FakeMaus:
    """Zeichnet alle Aufrufe auf und bestaetigt sie immer (True) - fuer
    Schritte, die keine echte HID-Verbindung brauchen."""

    def __init__(self):
        self.aufrufe = []

    def klick_links(self):
        self.aufrufe.append(("klick_links",))
        return True

    def klick_rechts(self):
        self.aufrufe.append(("klick_rechts",))
        return True

    def maus_bewegen(self, x, y):
        self.aufrufe.append(("maus_bewegen", x, y))
        return True

    def maus_ziehen(self, x, y):
        self.aufrufe.append(("maus_ziehen", x, y))
        return True


def _schritt(aktion, **parameter):
    return {"aktion": aktion, "parameter": parameter}


class TestMausAbsFensterIsolation(unittest.TestCase):
    """MAUS_ABS: x/y sind ohne fenster_provider (Standard, "Alle Fenster")
    absolute Bildschirmkoordinaten (bisheriges Verhalten) - MIT
    fenster_provider dagegen relativ zum isolierten Fenster gemeint, die
    aktuelle Fensterposition wird addiert (siehe Aufgabenstellung Punkt 3:
    "Klicks: Koordinaten relativ zu Fenster X")."""

    def test_ohne_fenster_provider_bleibt_absolut(self):
        maus = FakeMaus()
        aktion_skript.schritt_ausfuehren(_schritt("MAUS_ABS", x=50, y=30), maus)
        self.assertEqual(maus.aufrufe, [("maus_ziehen", 50, 30)])

    def test_mit_fenster_provider_addiert_fensterposition(self):
        maus = FakeMaus()
        provider = lambda: {"hwnd": 1, "x": 1000, "y": 200, "w": 800, "h": 600}
        aktion_skript.schritt_ausfuehren(_schritt("MAUS_ABS", x=50, y=30), maus,
                                          fenster_provider=provider)
        self.assertEqual(maus.aufrufe, [("maus_ziehen", 1050, 230)])

    def test_fenster_provider_liefert_none_wirft_fehler(self):
        maus = FakeMaus()
        provider = lambda: None
        with self.assertRaises(aktion_skript.SchrittFehler):
            aktion_skript.schritt_ausfuehren(_schritt("MAUS_ABS", x=50, y=30), maus,
                                              fenster_provider=provider)
        self.assertEqual(maus.aufrufe, [])  # gar nicht erst geklickt/bewegt

    def test_fensterposition_wird_bei_jedem_schritt_neu_geholt(self):
        """Bewegt sich das Fenster zwischen zwei Schritten, muss der zweite
        Schritt die NEUE Position verwenden (kein gecachter fenster_provider-
        Wert) - Grundlage fuer 'Fensterposition wird bei jedem Zyklus neu
        geholt' aus der Aufgabenstellung."""
        positionen = [{"hwnd": 1, "x": 0, "y": 0, "w": 800, "h": 600},
                      {"hwnd": 1, "x": 300, "y": 300, "w": 800, "h": 600}]
        provider = mock.Mock(side_effect=positionen)
        maus = FakeMaus()
        aktion_skript.schritt_ausfuehren(_schritt("MAUS_ABS", x=10, y=10), maus, fenster_provider=provider)
        aktion_skript.schritt_ausfuehren(_schritt("MAUS_ABS", x=10, y=10), maus, fenster_provider=provider)
        self.assertEqual(maus.aufrufe, [("maus_ziehen", 10, 10), ("maus_ziehen", 310, 310)])


class TestWurmKlickenFensterIsolation(unittest.TestCase):
    """WURM_KLICKEN muss bei gesetztem fenster_provider GENAU dieses Fenster
    verwenden statt (wie ohne fenster_provider) selbst per Titel zu
    suchen - sonst wuerde eine auf 'Fenster 2' isolierte Instanz versehentlich
    im FALSCHEN Fenster (dem erstbesten METIN2-Fenster) klicken."""

    def test_verwendet_fenster_provider_statt_titelsuche(self):
        eigenes_fenster = {"hwnd": 99, "x": 500, "y": 0, "w": 800, "h": 600}
        provider = mock.Mock(return_value=eigenes_fenster)
        maus = FakeMaus()

        with mock.patch("aktion_skript.fish_bot.fenster_finden_geprueft") as m_suche, \
             mock.patch("aktion_skript.fish_bot.screenshot_holen", return_value=np.zeros((1, 1, 3))) as m_shot, \
             mock.patch("aktion_skript.fish_bot.wurm_klicken", return_value=True) as m_klick:
            aktion_skript.schritt_ausfuehren(_schritt("WURM_KLICKEN"), maus, fenster_provider=provider)

        m_suche.assert_not_called()
        provider.assert_called_once()
        m_shot.assert_called_once_with(eigenes_fenster)
        m_klick.assert_called_once()
        self.assertEqual(m_klick.call_args[0][1], eigenes_fenster)

    def test_ohne_fenster_provider_bisheriges_verhalten(self):
        gefundenes_fenster = {"hwnd": 1, "x": 0, "y": 0, "w": 800, "h": 600}
        maus = FakeMaus()
        with mock.patch("aktion_skript.fish_bot.fenster_finden_geprueft",
                         return_value=gefundenes_fenster) as m_suche, \
             mock.patch("aktion_skript.fish_bot.screenshot_holen", return_value=np.zeros((1, 1, 3))), \
             mock.patch("aktion_skript.fish_bot.wurm_klicken", return_value=True):
            aktion_skript.schritt_ausfuehren(_schritt("WURM_KLICKEN"), maus)
        m_suche.assert_called_once()


class TestFokussiereMetin2(unittest.TestCase):
    """TASTE-Schritte fokussieren vor dem Senden das METIN2-Fenster (siehe
    _fokussiere_metin2()) - bei mehreren offenen Fenstern MUSS das GENAU das
    isolierte Fenster sein, nicht win32gui.FindWindow(None, 'METIN2') (liefert
    bei mehreren gleich betitelten Fenstern immer dasselbe, evtl. falsche)."""

    def test_nutzt_hwnd_aus_fenster_provider(self):
        provider = mock.Mock(return_value={"hwnd": 777, "x": 0, "y": 0, "w": 800, "h": 600})
        with mock.patch("aktion_skript.win32gui.FindWindow") as m_find, \
             mock.patch("aktion_skript.win32gui.SetForegroundWindow") as m_fokus, \
             mock.patch("aktion_skript.time.sleep"):
            aktion_skript._fokussiere_metin2(fenster_provider=provider)
        m_find.assert_not_called()
        m_fokus.assert_called_once_with(777)

    def test_fallback_auf_titelsuche_ohne_provider(self):
        with mock.patch("aktion_skript.win32gui.FindWindow", return_value=555) as m_find, \
             mock.patch("aktion_skript.win32gui.SetForegroundWindow") as m_fokus, \
             mock.patch("aktion_skript.time.sleep"):
            aktion_skript._fokussiere_metin2()
        m_find.assert_called_once()
        m_fokus.assert_called_once_with(555)


class TestBildErkennungFensterProvider(unittest.TestCase):
    """bild_erkennung._aktueller_treffer() (Basis von bild_pruefen()/
    bild_warten_bis_sichtbar()/_weg()) muss den gegebenen fenster_provider
    verwenden - dadurch bleiben Screenshots/Bilderkennung fuer BILD_*-
    Aktionen ebenfalls auf das isolierte Fenster beschraenkt (siehe
    Aufgabenstellung Punkt 3: 'Bilderkennung NUR im Screenshot von Fenster
    X')."""

    def test_bild_pruefen_nutzt_fenster_provider(self):
        eigenes_fenster = {"hwnd": 42, "x": 300, "y": 10, "w": 800, "h": 600}
        provider = mock.Mock(return_value=eigenes_fenster)
        with mock.patch("bild_erkennung.fish_bot.fenster_finden_geprueft") as m_suche, \
             mock.patch("bild_erkennung.fish_bot.screenshot_holen",
                         return_value=np.zeros((600, 800, 3), dtype=np.uint8)) as m_shot, \
             mock.patch("bild_erkennung.bild_finden", return_value=None):
            bild_erkennung.bild_pruefen("irgendein_bild.png", fenster_provider=provider)
        m_suche.assert_not_called()
        provider.assert_called_once()
        m_shot.assert_called_once_with(eigenes_fenster)

    def test_bild_pruefen_ohne_provider_bisheriges_verhalten(self):
        gefundenes_fenster = {"hwnd": 1, "x": 0, "y": 0, "w": 800, "h": 600}
        with mock.patch("bild_erkennung.fish_bot.fenster_finden_geprueft",
                         return_value=gefundenes_fenster) as m_suche, \
             mock.patch("bild_erkennung.fish_bot.screenshot_holen",
                         return_value=np.zeros((600, 800, 3), dtype=np.uint8)), \
             mock.patch("bild_erkennung.bild_finden", return_value=None):
            bild_erkennung.bild_pruefen("irgendein_bild.png")
        m_suche.assert_called_once()

    def test_kein_fenster_gefunden_liefert_none(self):
        provider = mock.Mock(return_value=None)
        ergebnis = bild_erkennung.bild_pruefen("irgendein_bild.png", fenster_provider=provider)
        self.assertIsNone(ergebnis)


if __name__ == "__main__":
    unittest.main()
