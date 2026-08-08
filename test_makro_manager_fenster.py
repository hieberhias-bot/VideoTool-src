#!/usr/bin/env python3
"""test_makro_manager_fenster.py - Tests fuer die Mehrfenster-Zuordnung in
makro_manager.py: MakroManager.starte_makro(fenster_hwnd=...) isoliert eine
einzelne Instanz auf ein Fenster, starte_makro_alle_fenster() startet bei
mehreren offenen Spielfenstern automatisch je EINE isolierte Instanz PRO
Fenster (siehe Aufgabenstellung "VERHALTEN BEI MEHREREN FENSTERN + GLEICHEM
SKRIPT").

aktion_skript.skript_ausfuehren()/skript_laden() und
modules.fenster.alle_spielfenster_finden() werden gemockt - diese Tests
pruefen NUR die Orchestrierung in makro_manager.py (welche/wie viele
Instanzen mit welchem fenster_hwnd/instanz_key gestartet werden), nicht die
eigentliche Skript-Ausfuehrung (siehe dafuer
test_makro_fenster_isolation.py) oder Fenster-Erkennung (siehe
test_multi_fenster_erkennung.py).

Verwendung:
    python -m unittest test_makro_manager_fenster
"""

import functools
import threading
import time
import unittest
from unittest import mock

import makro_manager
from makro_manager import MakroManager, MakroManagerFehler


def _blockierende_ausfuehrung(schritte, maus, bei_fehler="ABBRECHEN", log=print, status=None,
                               dispatcher=None, prioritaet="MITTEL", stop_event=None,
                               sprung_ziel=None, fenster_provider=None, **kwargs):
    """Ersetzt aktion_skript.skript_ausfuehren() in diesen Tests: blockiert
    (wie eine echte Ausfuehrung), bis stop_event gesetzt wird - dadurch
    koennen Tests zwischen Start und Stop tatsaechlich 'LAEUFT' beobachten,
    statt einer sofort beendeten Instanz hinterherzulaufen."""
    stop_event.wait(2.0)
    return "GESTOPPT"


def _manager(fenster_liste):
    manager = MakroManager(maus_getter=lambda: object(), log=lambda msg: None)
    patch_laden = mock.patch.object(makro_manager.aktion_skript, "skript_laden",
                                     return_value=[{"aktion": "WARTEN", "parameter": {"sekunden": 0}}])
    patch_ausfuehren = mock.patch.object(makro_manager.aktion_skript, "skript_ausfuehren",
                                          side_effect=_blockierende_ausfuehrung)
    patch_fenster = mock.patch.object(makro_manager.fenster_modul, "alle_spielfenster_finden",
                                       return_value=fenster_liste)
    return manager, patch_laden, patch_ausfuehren, patch_fenster


class TestStarteMakroFensterHwnd(unittest.TestCase):
    """starte_makro(fenster_hwnd=...) baut einen fenster_provider, der an
    aktion_skript.skript_ausfuehren() durchgereicht wird."""

    def test_fenster_hwnd_ergibt_gebundenen_provider(self):
        manager, p_laden, p_ausfuehren, _p_fenster = _manager([])
        with p_laden, p_ausfuehren as m_ausfuehren:
            manager.starte_makro("mein_skript", fenster_hwnd=777)
            time.sleep(0.05)  # Thread-Start abwarten
            manager.stoppe_makro("mein_skript", timeout=1.0)

        provider = m_ausfuehren.call_args.kwargs["fenster_provider"]
        self.assertIsInstance(provider, functools.partial)
        self.assertIs(provider.func, makro_manager.fenster_modul.fenster_von_hwnd)
        self.assertEqual(provider.args, (777,))

    def test_ohne_fenster_hwnd_kein_provider(self):
        manager, p_laden, p_ausfuehren, _p_fenster = _manager([])
        with p_laden, p_ausfuehren as m_ausfuehren:
            manager.starte_makro("mein_skript")
            time.sleep(0.05)
            manager.stoppe_makro("mein_skript", timeout=1.0)
        self.assertIsNone(m_ausfuehren.call_args.kwargs["fenster_provider"])


class TestStarteMakroAlleFenster(unittest.TestCase):

    def test_kein_fenster_offen_eine_instanz_ohne_isolation(self):
        manager, p_laden, p_ausfuehren, p_fenster = _manager([])
        with p_laden, p_ausfuehren as m_ausfuehren, p_fenster:
            gestartet = manager.starte_makro_alle_fenster("mein_skript")
            time.sleep(0.05)
            manager.stoppe_alle_instanzen("mein_skript", timeout=1.0)

        self.assertEqual(gestartet, ["mein_skript"])
        self.assertIsNone(m_ausfuehren.call_args.kwargs["fenster_provider"])

    def test_ein_fenster_offen_eine_isolierte_instanz(self):
        fenster_liste = [{"hwnd": 111, "titel": "METIN2", "x": 0, "y": 0,
                           "breite": 800, "hoehe": 600, "nummer": 1}]
        manager, p_laden, p_ausfuehren, p_fenster = _manager(fenster_liste)
        with p_laden, p_ausfuehren as m_ausfuehren, p_fenster:
            gestartet = manager.starte_makro_alle_fenster("mein_skript")
            time.sleep(0.05)
            manager.stoppe_alle_instanzen("mein_skript", timeout=1.0)

        self.assertEqual(gestartet, ["mein_skript"])
        provider = m_ausfuehren.call_args.kwargs["fenster_provider"]
        self.assertEqual(provider.args, (111,))

    def test_drei_fenster_offen_drei_parallele_isolierte_instanzen(self):
        fenster_liste = [
            {"hwnd": 1, "titel": "METIN2", "x": 0, "y": 0, "breite": 800, "hoehe": 600, "nummer": 1},
            {"hwnd": 2, "titel": "METIN2", "x": 800, "y": 0, "breite": 800, "hoehe": 600, "nummer": 2},
            {"hwnd": 3, "titel": "METIN2", "x": 0, "y": 600, "breite": 800, "hoehe": 600, "nummer": 3},
        ]
        manager, p_laden, p_ausfuehren, p_fenster = _manager(fenster_liste)
        with p_laden, p_ausfuehren as m_ausfuehren, p_fenster:
            gestartet = manager.starte_makro_alle_fenster("mein_skript", prioritaet="HOCH")
            time.sleep(0.05)

            # Alle drei Instanzen laufen PARALLEL, je auf ein eigenes Fenster
            # isoliert (jeweils eigener stop_event, siehe Aufgabenstellung
            # "Jede Instanz hat ihren eigenen Stop-Flag").
            self.assertEqual(len(gestartet), 3)
            self.assertTrue(manager.makro_laeuft("mein_skript"))
            laufende = [e for e in manager.laufende_makros() if e["laeuft"]]
            self.assertEqual(len(laufende), 3)
            self.assertTrue(all(e["basis_name"] == "mein_skript" for e in laufende))
            self.assertEqual(sorted(e["fenster_label"] for e in laufende),
                              ["Fenster 1", "Fenster 2", "Fenster 3"])

            hwnds_verwendet = sorted(c.kwargs["fenster_provider"].args[0]
                                      for c in m_ausfuehren.call_args_list)
            self.assertEqual(hwnds_verwendet, [1, 2, 3])

            manager.stoppe_alle_instanzen("mein_skript", timeout=1.0)

        self.assertFalse(manager.makro_laeuft("mein_skript"))

    def test_zweite_instanz_desselben_skripts_waehrend_erste_laeuft_erlaubt(self):
        """Kein instanz_key-Konflikt zwischen zwei Fenster-Instanzen
        desselben Skripts (im Gegensatz zur alten Ein-Instanz-pro-Name-
        Beschraenkung)."""
        fenster_liste = [
            {"hwnd": 1, "titel": "METIN2", "x": 0, "y": 0, "breite": 800, "hoehe": 600, "nummer": 1},
            {"hwnd": 2, "titel": "METIN2", "x": 800, "y": 0, "breite": 800, "hoehe": 600, "nummer": 2},
        ]
        manager, p_laden, p_ausfuehren, p_fenster = _manager(fenster_liste)
        with p_laden, p_ausfuehren, p_fenster:
            gestartet = manager.starte_makro_alle_fenster("mein_skript")
            self.assertEqual(len(set(gestartet)), 2)  # zwei EINDEUTIGE instanz_key
            time.sleep(0.05)
            manager.stoppe_alle_instanzen("mein_skript", timeout=1.0)


class TestStoppeAlleInstanzen(unittest.TestCase):

    def test_stoppt_nur_instanzen_des_angegebenen_skripts(self):
        fenster_liste = [
            {"hwnd": 1, "titel": "METIN2", "x": 0, "y": 0, "breite": 800, "hoehe": 600, "nummer": 1},
            {"hwnd": 2, "titel": "METIN2", "x": 800, "y": 0, "breite": 800, "hoehe": 600, "nummer": 2},
        ]
        manager, p_laden, p_ausfuehren, p_fenster = _manager(fenster_liste)
        with p_laden, p_ausfuehren, p_fenster:
            manager.starte_makro_alle_fenster("skript_a")
            manager.starte_makro("skript_b")
            time.sleep(0.05)

            gestoppt = manager.stoppe_alle_instanzen("skript_a", timeout=1.0)
            self.assertEqual(len(gestoppt), 2)
            self.assertFalse(manager.makro_laeuft("skript_a"))
            self.assertTrue(manager.makro_laeuft("skript_b"))

            manager.stoppe_alle_instanzen("skript_b", timeout=1.0)


if __name__ == "__main__":
    unittest.main()
