#!/usr/bin/env python3
"""test_fischbot_multi_fenster.py - Tests fuer die Mehrfach-Fenster-
Unterstuetzung des FISCH-BOTS (fish_bot.py/makro_manager.py) - dieselbe
Unterstuetzung wie fuer Bot-Skripte (siehe test_makro_fenster_isolation.py/
test_makro_manager_fenster.py), hier auf fish_bot.py angewendet:

  - fish_bot.FischBotKontext buendelt den kompletten pro-Instanz-Zustand
    (Stop-Flag, Fenstergroessen-Cache, Popup-Haltezeit, CSV-Logger), damit
    MEHRERE Fisch-Bot-Instanzen parallel (je auf ein eigenes Fenster
    isoliert) laufen koennen, ohne sich gegenseitig zu stoeren.
  - makro_manager.MakroManager.fischbot_starten_alle_fenster() startet bei
    N offenen Fenstern automatisch N isolierte Instanzen (Fan-out).

Verwendung:
    python -m unittest test_fischbot_multi_fenster
"""

import functools
import time
import unittest
from unittest import mock

import fish_bot
import makro_manager
from makro_manager import MakroManager, FISCHBOT_NAME


# ---------- fish_bot.py: FischBotKontext-Isolation ----------

class TestFischBotKontextIsolation(unittest.TestCase):

    def test_stop_events_unabhaengig(self):
        k1 = fish_bot.FischBotKontext()
        k2 = fish_bot.FischBotKontext()
        fish_bot.bot_anhalten(k1)
        self.assertTrue(fish_bot._gestoppt(k1))
        self.assertFalse(fish_bot._gestoppt(k2))

    def test_fenstergroessen_cache_unabhaengig_pro_kontext(self):
        """Zwei PARALLELE Instanzen auf unterschiedlich grossen Fenstern
        duerfen sich NICHT gegenseitig als 'Fenstergroesse hat sich
        geaendert' auffallen (siehe _fenster_plausibel()-Docstring)."""
        k1 = fish_bot.FischBotKontext()
        k2 = fish_bot.FischBotKontext()
        fenster_klein = {"w": 816, "h": 639}
        fenster_gross = {"w": 850, "h": 660}

        self.assertTrue(fish_bot._fenster_plausibel(fenster_klein, kontext=k1))
        self.assertTrue(fish_bot._fenster_plausibel(fenster_gross, kontext=k2))
        # Erneute, IDENTISCHE Groesse pro Kontext bleibt gueltig.
        self.assertTrue(fish_bot._fenster_plausibel(fenster_klein, kontext=k1))
        self.assertTrue(fish_bot._fenster_plausibel(fenster_gross, kontext=k2))
        # Ein Groessenwechsel INNERHALB desselben Kontexts wird weiterhin abgelehnt.
        self.assertFalse(fish_bot._fenster_plausibel(fenster_gross, kontext=k1))

    def test_popup_haltezeit_unabhaengig_pro_kontext(self):
        k1 = fish_bot.FischBotKontext()
        k2 = fish_bot.FischBotKontext()
        popup = (10, 10, 50)

        self.assertEqual(fish_bot._popup_mit_haltezeit(popup, kontext=k1), popup)
        # k2 hat KEINE eigene Historie - kein Popup, keine Haltezeit.
        self.assertIsNone(fish_bot._popup_mit_haltezeit(None, kontext=k2))
        # k1 haelt seine eigene Position weiterhin (innerhalb POPUP_HALTEZEIT).
        self.assertEqual(fish_bot._popup_mit_haltezeit(None, kontext=k1), popup)

    def test_ohne_kontext_faellt_auf_standard_zurueck(self):
        fish_bot._STANDARD_KONTEXT.stop_event.clear()
        self.assertFalse(fish_bot._gestoppt())
        fish_bot.bot_anhalten()
        self.assertTrue(fish_bot._gestoppt())
        fish_bot._STANDARD_KONTEXT.stop_event.clear()  # fuer andere Tests aufraeumen

    def test_csv_pfad_pro_label_getrennt(self):
        self.assertEqual(fish_bot._csv_pfad_fuer_label(None), fish_bot.CSV_LOG_PFAD)
        pfad_a = fish_bot._csv_pfad_fuer_label("Fenster 1")
        pfad_b = fish_bot._csv_pfad_fuer_label("Fenster 2")
        self.assertNotEqual(pfad_a, fish_bot.CSV_LOG_PFAD)
        self.assertNotEqual(pfad_a, pfad_b)


class TestFensterFindenGeprueftProvider(unittest.TestCase):

    def test_nutzt_fenster_provider_statt_titelsuche(self):
        eigenes_fenster = {"hwnd": 42, "x": 100, "y": 50, "w": 816, "h": 639}
        provider = mock.Mock(return_value=eigenes_fenster)
        with mock.patch("fish_bot.fenster_finden") as m_suche:
            ergebnis = fish_bot.fenster_finden_geprueft(fenster_provider=provider)
        m_suche.assert_not_called()
        provider.assert_called_once()
        self.assertEqual(ergebnis, eigenes_fenster)

    def test_ohne_provider_bisheriges_verhalten(self):
        gefunden = {"hwnd": 1, "x": 0, "y": 0, "w": 816, "h": 639}
        with mock.patch("fish_bot.fenster_finden", return_value=gefunden) as m_suche:
            ergebnis = fish_bot.fenster_finden_geprueft()
        m_suche.assert_called_once()
        self.assertEqual(ergebnis, gefunden)

    def test_fenster_provider_liefert_none(self):
        provider = mock.Mock(return_value=None)
        self.assertIsNone(fish_bot.fenster_finden_geprueft(fenster_provider=provider))


class TestLeertasteFokussierung(unittest.TestCase):
    """TASTE-Aequivalent des Fisch-Bots (Leertaste zum Auswerfen): bei
    MEHREREN offenen Fenstern muss VOR dem Tastendruck genau das isolierte
    Fenster fokussiert werden (SendInput liefert sonst an das gerade
    fokussierte, evtl. falsche Fenster)."""

    def test_fokussiert_hwnd_wenn_gesetzt(self):
        with mock.patch("fish_bot.win32gui.SetForegroundWindow") as m_fokus, \
             mock.patch("fish_bot.time.sleep") as m_sleep, \
             mock.patch.object(fish_bot._pynput_tastatur, "press"), \
             mock.patch.object(fish_bot._pynput_tastatur, "release"):
            fish_bot.leertaste_tippen(mock.Mock(), hwnd=777)
        m_fokus.assert_called_once_with(777)
        self.assertIn(mock.call(fish_bot.FOKUS_WARTEZEIT_S), m_sleep.call_args_list)

    def test_kein_fokuswechsel_ohne_hwnd(self):
        with mock.patch("fish_bot.win32gui.SetForegroundWindow") as m_fokus, \
             mock.patch("fish_bot.time.sleep"), \
             mock.patch.object(fish_bot._pynput_tastatur, "press"), \
             mock.patch.object(fish_bot._pynput_tastatur, "release"):
            fish_bot.leertaste_tippen(mock.Mock())
        m_fokus.assert_not_called()


# ---------- makro_manager.py: Fisch-Bot-Fan-out ----------

def _blockierender_fisch_bot(maus=None, kontext=None, fenster_provider=None):
    """Ersetzt fish_bot.bot_starten() in diesen Tests: blockiert (wie eine
    echte Ausfuehrung), bis kontext.stop_event gesetzt wird."""
    kontext.stop_event.wait(2.0)
    return "GESTOPPT"


def _fisch_manager(fenster_liste):
    manager = MakroManager(maus_getter=lambda: object(), log=lambda msg: None)
    p_bot = mock.patch.object(makro_manager.fish_bot, "bot_starten",
                               side_effect=_blockierender_fisch_bot)
    p_fenster = mock.patch.object(makro_manager.fenster_modul, "alle_spielfenster_finden",
                                   return_value=fenster_liste)
    return manager, p_bot, p_fenster


class TestFischBotFanOut(unittest.TestCase):

    def test_kein_fenster_offen_eine_instanz_ohne_isolation(self):
        manager, p_bot, p_fenster = _fisch_manager([])
        with p_bot as m_bot, p_fenster:
            gestartet = manager.fischbot_starten_alle_fenster()
            time.sleep(0.05)
            manager.stoppe_alle_instanzen(FISCHBOT_NAME, timeout=1.0)

        self.assertEqual(gestartet, [FISCHBOT_NAME])
        self.assertIsNone(m_bot.call_args.kwargs["fenster_provider"])

    def test_ein_fenster_offen_eine_isolierte_instanz(self):
        fenster_liste = [{"hwnd": 111, "titel": "METIN2", "x": 0, "y": 0,
                           "breite": 800, "hoehe": 600, "nummer": 1}]
        manager, p_bot, p_fenster = _fisch_manager(fenster_liste)
        with p_bot as m_bot, p_fenster:
            gestartet = manager.fischbot_starten_alle_fenster()
            time.sleep(0.05)
            manager.stoppe_alle_instanzen(FISCHBOT_NAME, timeout=1.0)

        self.assertEqual(gestartet, [FISCHBOT_NAME])
        provider = m_bot.call_args.kwargs["fenster_provider"]
        self.assertIsInstance(provider, functools.partial)
        self.assertIs(provider.func, makro_manager.fenster_modul.fenster_von_hwnd)
        self.assertEqual(provider.args, (111,))

    def test_drei_fenster_offen_drei_parallele_isolierte_instanzen(self):
        fenster_liste = [
            {"hwnd": 1, "titel": "METIN2", "x": 0, "y": 0, "breite": 800, "hoehe": 600, "nummer": 1},
            {"hwnd": 2, "titel": "METIN2", "x": 800, "y": 0, "breite": 800, "hoehe": 600, "nummer": 2},
            {"hwnd": 3, "titel": "METIN2", "x": 0, "y": 600, "breite": 800, "hoehe": 600, "nummer": 3},
        ]
        manager, p_bot, p_fenster = _fisch_manager(fenster_liste)
        with p_bot as m_bot, p_fenster:
            gestartet = manager.fischbot_starten_alle_fenster()
            time.sleep(0.05)

            self.assertEqual(len(gestartet), 3)
            self.assertTrue(manager.makro_laeuft(FISCHBOT_NAME))
            laufende = [e for e in manager.laufende_makros() if e["laeuft"]]
            self.assertEqual(len(laufende), 3)
            self.assertTrue(all(e["basis_name"] == FISCHBOT_NAME for e in laufende))
            self.assertEqual(sorted(e["fenster_label"] for e in laufende),
                              ["Fenster 1", "Fenster 2", "Fenster 3"])

            # Jede Instanz bekam einen EIGENEN FischBotKontext mit
            # unterschiedlichem Fenster-hwnd (siehe fish_bot_starten()).
            kontexte = [c.kwargs["kontext"] for c in m_bot.call_args_list]
            self.assertEqual(len({id(k) for k in kontexte}), 3)
            hwnds = sorted(c.kwargs["fenster_provider"].args[0] for c in m_bot.call_args_list)
            self.assertEqual(hwnds, [1, 2, 3])

            manager.stoppe_alle_instanzen(FISCHBOT_NAME, timeout=1.0)

        self.assertFalse(manager.makro_laeuft(FISCHBOT_NAME))

    def test_stoppe_makro_wirkt_ueber_geteiltes_stop_event(self):
        """eintrag.stop_event UND kontext.stop_event sind DASSELBE Objekt
        (siehe fish_bot_starten()) - stoppe_makro() braucht daher KEINEN
        fish_bot-spezifischen Sonderfall mehr (im Gegensatz zum alten,
        globalen fish_bot.bot_anhalten()-Aufruf)."""
        manager, p_bot, p_fenster = _fisch_manager([])
        with p_bot as m_bot, p_fenster:
            manager.fischbot_starten_alle_fenster()
            time.sleep(0.05)
            kontext = m_bot.call_args.kwargs["kontext"]
            self.assertFalse(kontext.stop_event.is_set())

            manager.stoppe_makro(FISCHBOT_NAME, timeout=1.0)
            self.assertTrue(kontext.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
