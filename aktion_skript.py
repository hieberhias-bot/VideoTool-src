#!/usr/bin/env python3
"""aktion_skript.py - Aktionsbasierte Bot-Skripte (nicht zu verwechseln mit dem
aelteren, koordinatenbasierten "ablauf_*.json"/AblaufEditor-System, das
weiterhin unabhaengig davon existiert).

Ein Skript ist eine Liste von Schritten. Jeder Schritt hat eine Aktion (siehe
AKTIONEN) und aktions-spezifische Parameter. Skripte werden als
aktion_<name>.json im Projektverzeichnis gespeichert/geladen.

Die Ausfuehrung (skript_ausfuehren()) ist synchron/blockierend und dafuer
gedacht, von einem Aufrufer in einem eigenen Thread gestartet zu werden (z.B.
aktion_editor.py) - ausfuehrung_stoppen() signalisiert einen sauberen,
zuverlaessig schnellen Abbruch (auch waehrend eines langen WARTEN-Schritts).
"""

import os
import json
import time
import random
import threading
import ctypes
from ctypes import wintypes

import win32gui
from pynput.keyboard import Controller as _PynputController, Key as _PynputKey

import fish_bot
import bild_erkennung

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STANDARD_SKRIPT_NAME = "standard"
METIN2_FENSTER_TITEL = "METIN2"

# Abstand zwischen den beiden Einzelklicks eines Doppelklicks (siehe
# _klicken()) - deutlich unter der Windows-Standard-Doppelklickzeit
# (typisch ~500ms), aber nicht "gleichzeitig", damit die HID-Firmware beide
# Klicks sicher als zwei getrennte Ereignisse verarbeitet.
DOPPELKLICK_ABSTAND_S = 0.05

# Kurze Wartezeit NACH einer Mausbewegung, BEVOR geklickt wird (siehe
# _bild_klicken_schritt()/_bild_klicken_wenn_weg_schritt()/
# _bild_klicken_bis_schritt()) - maus_bewegen() blockiert zwar schon bis zur
# MOVED-Bestaetigung der HID-Firmware, aber der Spiel-Client braucht
# zusaetzlich eine kurze (unbekannte, nicht messbare) Latenz, um den neuen
# Cursor INTERN zu registrieren, bevor ein Klick an dieser Position ankommt -
# ohne diese Marge geht der Klick sonst ins Leere/an die vorherige Position
# (derselbe Effekt wie im FISCHEN-Klick-Loop, siehe fish_bot._klick_loop()
# und fish_bot.wurm_klicken() - dort bereits mit demselben Wert behoben).
KLICK_VORSICHTSMARGE_S = 0.02

# Verfuegbare Aktionen und ihre Parameter (Reihenfolge = Anzeige-Reihenfolge
# im Editor). Leere Parameterliste = die Aktion braucht keine Eingabefelder.
# Die BILD_*-Aktionen suchen ein PNG aus bilder_szenen/ per Template-Matching
# (siehe bild_erkennung.py) im METIN2-Fenster.
AKTIONEN = ["WARTEN", "WARTEN_MIN_MAX", "RECHTSKLICK", "LINKSKLICK", "DOPPELKLICK", "TASTE", "FOKUS",
            "MAUS_BEWEGEN", "MAUS_ABS", "WURM_KLICKEN",
            "BILD_WARTEN_BIS", "BILD_WARTEN_BIS_WEG",
            "BILD_KLICKEN", "BILD_KLICKEN_WENN_WEG", "BILD_KLICKEN_BIS",
            "SCHLEIFE_START", "SCHLEIFE_ENDE", "GEWICHTET"]

# Maximale Verschachtelungstiefe fuer GEWICHTET-Pfade (ein Pfad kann selbst
# wieder GEWICHTET-Schritte enthalten) - verhindert versehentliche/absichtliche
# Endlosrekursion (z.B. ein Pfad, der sich selbst als Unter-Schritt enthaelt).
GEWICHTET_MAX_TIEFE = 5

# klick_typ: "L" (links), "R" (rechts) oder "D" (doppelt - siehe _klicken():
# zwei rasche Linksklicks hintereinander, die HID-Firmware kennt keinen
# eigenen Doppelklick-Befehl). zufall: 1 = Klickpunkt zufaellig innerhalb der
# Hitbox waehlen (Standard, siehe bild_erkennung.zufallspunkt_in_treffer()),
# 0 = immer exakt Bildmitte + Offset (altes, deterministisches Verhalten).
AKTION_PARAMETER = {
    "WARTEN": ["sekunden", "bonus_prozent"],
    "WARTEN_MIN_MAX": ["min", "max"],
    "RECHTSKLICK": [],
    "LINKSKLICK": [],
    "DOPPELKLICK": [],
    "TASTE": ["taste"],
    # Holt das (bei Fenster-Isolation: EIGENE) METIN2-Fenster in den
    # Vordergrund (siehe _fokussiere_metin2()) - manuell einfuegbar an
    # beliebiger Stelle im Ablauf, VOR Maus-Aktionen ohne eigene
    # TASTE/BILD_*-Fokussierung (siehe deren fenster_provider-Doku): ein
    # Klick auf ein nicht fokussiertes Fenster wird von Metin2 i.d.R.
    # ignoriert (bestaetigter Regressions-Fall bei Fenster-Isolation auf
    # mehrere parallele Instanzen, siehe fish_bot._fenster_fokussiert_sicherstellen()).
    "FOKUS": [],
    "MAUS_BEWEGEN": ["dx", "dy"],
    "MAUS_ABS": ["x", "y"],
    "WURM_KLICKEN": [],
    # "endlos": 1 lasst timeout ignorieren und unbegrenzt suchen/warten (nur
    # per Stopp/ausfuehrung_stoppen() unterbrechbar) - siehe
    # bild_erkennung.bild_warten_bis_sichtbar()/_weg() (timeout<=0 = endlos).
    # "suchbereich": optionaler fensterrelativer Ausschnitt (siehe
    # modules.fenster.fenster_bereich_markieren()/aktion_editor.py's
    # "Zielbereich..."-Button), auf den die Bild-Suche eingeschraenkt wird
    # statt das GANZE Fenster zu durchsuchen - None (Standard) = ganzes
    # Fenster, bisheriges Verhalten.
    "BILD_WARTEN_BIS": ["bild", "variante", "timeout", "endlos", "schwelle", "suchbereich"],
    "BILD_WARTEN_BIS_WEG": ["bild", "variante", "timeout", "endlos", "schwelle", "suchbereich"],
    "BILD_KLICKEN": ["bild", "variante", "klick_typ", "zufall", "offset_x", "offset_y", "timeout", "endlos",
                     "schwelle", "suchbereich"],
    "BILD_KLICKEN_WENN_WEG": ["bild", "variante", "klick_typ", "zufall", "offset_x", "offset_y", "timeout",
                              "endlos", "schwelle", "suchbereich"],
    # Klickt wiederholt auf 'bild' (mit 'klickabstand' Sekunden Pause
    # zwischen den Klicks), bis 'ziel_bild' erscheint - z.B. ein Icon
    # anklicken, bis sich der Spielzustand aendert und ein anderes Bild
    # sichtbar wird.
    # modus: "ZIEL_DA" (Standard) = klicken bis 'ziel_bild' erscheint,
    # "BILD_WEG" = klicken bis 'bild' selbst verschwindet (ziel_bild/
    # ziel_variante dann irrelevant) - siehe _bild_klicken_bis_schritt().
    "BILD_KLICKEN_BIS": ["bild", "variante", "modus", "ziel_bild", "ziel_variante", "klick_typ",
                         "zufall", "offset_x", "offset_y", "klickabstand", "timeout", "endlos", "schwelle",
                         "suchbereich", "ziel_suchbereich"],
    # SCHLEIFE_START/SCHLEIFE_ENDE sind Marker-Schritte, kein verschachteltes
    # Objekt wie GEWICHTET: alle Schritte ZWISCHEN einem SCHLEIFE_START und
    # dem naechsten (verschachtelungs-korrekten) SCHLEIFE_ENDE in DERSELBEN
    # flachen Liste bilden den Schleifenkoerper (siehe
    # _passendes_schleifen_ende()/_schritte_ausfuehren()). "endlos" gewinnt
    # vor "wiederholungen", wenn beide gesetzt sind.
    "SCHLEIFE_START": ["wiederholungen", "endlos"],
    "SCHLEIFE_ENDE": [],
    # "pfade" ist keine flache Eingabe wie die anderen Aktionen (Liste von
    # {"gewicht","schritte"}), sondern wird ueber einen eigenen Dialog
    # bearbeitet (siehe gewichtet_editor.py) - hier trotzdem gelistet, damit
    # generischer Code (z.B. Parameter-Kopien) den Schluessel kennt.
    "GEWICHTET": ["pfade"],
}

AKTION_STANDARD_PARAMETER = {
    "WARTEN": {"sekunden": 1.0, "bonus_prozent": 0},
    "WARTEN_MIN_MAX": {"min": 1.0, "max": 3.0},
    "RECHTSKLICK": {},
    "LINKSKLICK": {},
    "DOPPELKLICK": {},
    "TASTE": {"taste": "SPACE"},
    "FOKUS": {},
    "MAUS_BEWEGEN": {"dx": 0, "dy": 0},
    "MAUS_ABS": {"x": 0, "y": 0},
    "WURM_KLICKEN": {},
    "BILD_WARTEN_BIS": {"bild": "", "variante": "", "timeout": 5.0, "endlos": 0,
                        "schwelle": bild_erkennung.SCHWELLE_STANDARD, "suchbereich": None},
    "BILD_WARTEN_BIS_WEG": {"bild": "", "variante": "", "timeout": 5.0, "endlos": 0,
                            "schwelle": bild_erkennung.SCHWELLE_STANDARD, "suchbereich": None},
    "BILD_KLICKEN": {"bild": "", "variante": "", "klick_typ": "L", "zufall": 1, "offset_x": 0, "offset_y": 0,
                     "timeout": 5.0, "endlos": 0, "schwelle": bild_erkennung.SCHWELLE_STANDARD,
                     "suchbereich": None},
    "BILD_KLICKEN_WENN_WEG": {"bild": "", "variante": "", "klick_typ": "L", "zufall": 1, "offset_x": 0, "offset_y": 0,
                              "timeout": 5.0, "endlos": 0, "schwelle": bild_erkennung.SCHWELLE_STANDARD,
                              "suchbereich": None},
    "BILD_KLICKEN_BIS": {"bild": "", "variante": "", "modus": "ZIEL_DA", "ziel_bild": "", "ziel_variante": "",
                         "klick_typ": "L", "zufall": 1, "offset_x": 0, "offset_y": 0,
                         "klickabstand": 1.0, "timeout": 30.0, "endlos": 0,
                         "schwelle": bild_erkennung.SCHWELLE_STANDARD, "suchbereich": None,
                         "ziel_suchbereich": None},
    "SCHLEIFE_START": {"wiederholungen": 3, "endlos": 0},
    "SCHLEIFE_ENDE": {},
    "GEWICHTET": {"pfade": []},
}

BEI_FEHLER_OPTIONEN = ["ABBRECHEN", "WEITER", "SPRUNG"]

# Stop-Mechanismus fuer die Ablauf-Ausfuehrung - unabhaengig vom Stop-
# Mechanismus des Fischbots selbst (fish_bot._stop_event), da beide getrennt
# voneinander gestartet/gestoppt werden koennen.
_stop_event = threading.Event()


class SchrittFehler(Exception):
    """Wird ausgeloest, wenn ein einzelner Aktionsschritt fehlschlaegt
    (z.B. Taste/Klick nicht von der HID-Maus bestaetigt, kein Wurm gefunden)."""


def ausfuehrung_stoppen():
    """Signalisiert einer laufenden skript_ausfuehren()-Ausfuehrung, sich
    sauber zu beenden (naechster Pruefpunkt, auch waehrend WARTEN)."""
    _stop_event.set()


def _gestoppt():
    return _stop_event.is_set()


class BildWaechter:
    """Laeuft in einem EIGENEN Hintergrund-Thread waehrend der gesamten
    Skript-Ausfuehrung und prueft periodisch, ob 'bild' sichtbar ist - im
    Gegensatz zu bei_fehler_override/sprung_ziel_override (die nur bei einem
    tatsaechlich FEHLGESCHLAGENEN Schritt greifen) reagiert der Waechter auf
    das blosse ERSCHEINEN eines Bildes, UNABHAENGIG davon, welcher Schritt
    gerade laeuft oder ob er erfolgreich ist - z.B. "wenn irgendwann ein
    Fehler-Popup auftaucht, egal wo im Ablauf ich gerade bin, zurueck zu
    Schritt 3".

    Wird an skript_ausfuehren() uebergeben und von dort durch alle Wartepunkte
    durchgereicht (siehe stop_event-Docstrings) - sowohl der aeussere
    Schritt-Loop (_schritte_ausfuehren()) als auch laufende Wartezeiten
    (_warten_mit_bonus()/_warte_unterbrechbar_bis()/BILD_*-Wartefunktionen)
    pruefen ist_ausgeloest() und brechen fruehzeitig ab, damit ein laufender
    30s-WARTEN-Schritt den Sprung nicht erst nach Ablauf bemerkt.

    cooldown verhindert, dass ein weiterhin sichtbares Bild sofort wieder
    denselben Sprung ausloest, sobald die Ausfuehrung am Sprungziel erneut
    vorbeikommt (sonst haengt der Ablauf in einer sofortigen Sprung-Schleife
    fest, bevor er ueberhaupt wieder wegkommt)."""

    def __init__(self, bild, sprung_ziel, cooldown=5.0, variante=None, schwelle=None,
                 poll_intervall=0.5, fenster_provider=None):
        self.bild = bild
        self.sprung_ziel = sprung_ziel
        self.cooldown = max(0.0, float(cooldown))
        self.variante = variante or None
        self.schwelle = schwelle if schwelle is not None else bild_erkennung.SCHWELLE_STANDARD
        self.poll_intervall = poll_intervall
        self.fenster_provider = fenster_provider
        self._ausgeloest = threading.Event()
        self._stop = threading.Event()
        self._letzter_treffer = 0.0
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._lauf, daemon=True,
                                        name="BildWaechter-%s" % self.bild)
        self._thread.start()

    def stoppen(self):
        self._stop.set()

    def _lauf(self):
        while not self._stop.is_set():
            if not self._ausgeloest.is_set():
                jetzt = time.time()
                if jetzt - self._letzter_treffer >= self.cooldown:
                    try:
                        treffer = bild_erkennung.bild_pruefen(self.bild, self.schwelle, self.variante,
                                                                fenster_provider=self.fenster_provider)
                    except Exception:
                        treffer = None
                    if treffer is not None:
                        self._letzter_treffer = jetzt
                        self._ausgeloest.set()
            self._stop.wait(self.poll_intervall)

    def ist_ausgeloest(self):
        """Reines Abfragen (OHNE zurueckzusetzen) - fuer Wartefunktionen, die
        nur fruehzeitig abbrechen sollen, aber NICHT selbst fuer den
        eigentlichen Sprung zustaendig sind (das macht ausschliesslich
        _schritte_ausfuehren() ueber pruefen_und_zuruecksetzen())."""
        return self._ausgeloest.is_set()

    def pruefen_und_zuruecksetzen(self):
        """True + setzt zurueck, wenn seit dem letzten Aufruf ein Treffer
        erkannt wurde (consume-once-Semantik, damit ein einzelner Treffer
        nicht mehrfach hintereinander zum Springen fuehrt - erst nach dem
        naechsten Cooldown-Ablauf kann _lauf() erneut ausloesen)."""
        if self._ausgeloest.is_set():
            self._ausgeloest.clear()
            return True
        return False


# ---------- Skript-Modell ----------

def neuer_schritt(aktion):
    """Erzeugt einen neuen Schritt mit Standard-Parametern fuer 'aktion'."""
    return {"aktion": aktion, "parameter": dict(AKTION_STANDARD_PARAMETER.get(aktion, {}))}


def standard_skript():
    """Das Beispiel-Skript aus der Aufgabenstellung (Wurm-Nachlege-Zyklus)."""
    def s(aktion, **werte):
        p = dict(AKTION_STANDARD_PARAMETER.get(aktion, {}))
        p.update(werte)
        return {"aktion": aktion, "parameter": p}

    return [
        s("WARTEN", sekunden=3.5),
        s("TASTE", taste="SPACE"),
        s("WARTEN", sekunden=2.0),
        s("WURM_KLICKEN"),
        s("TASTE", taste="SPACE"),
        s("WARTEN", sekunden=2.0),
        s("WURM_KLICKEN"),
        s("TASTE", taste="SPACE"),
        s("WARTEN", sekunden=30.0),
        s("WURM_KLICKEN"),
        s("TASTE", taste="SPACE"),
    ]


def _dateipfad(name):
    return os.path.join(BASE_DIR, "aktion_%s.json" % name)


def verfuegbare_skripte():
    """Namen aller aktion_<name>.json-Dateien im Projektverzeichnis (ohne
    Praefix/Endung), alphabetisch sortiert."""
    ergebnis = []
    for f in os.listdir(BASE_DIR):
        if f.startswith("aktion_") and f.endswith(".json"):
            ergebnis.append(f[len("aktion_"):-len(".json")])
    return sorted(ergebnis)


def skript_laden(name):
    """Laedt die Schritt-Liste aus aktion_<name>.json."""
    with open(_dateipfad(name), "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("schritte", [])


def skript_speichern(name, schritte):
    """Speichert eine Schritt-Liste als aktion_<name>.json (ueberschreibt)."""
    data = {"name": name, "schritte": schritte}
    with open(_dateipfad(name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def skript_loeschen(name):
    """Loescht aktion_<name>.json unwiderruflich (No-Op, falls die Datei
    bereits nicht mehr existiert - z.B. doppelter Klick)."""
    pfad = _dateipfad(name)
    if os.path.exists(pfad):
        os.remove(pfad)


def sicherstellen_standard_skript():
    """Legt beim allerersten Start (noch keine aktion_*.json vorhanden) das
    Beispiel-Skript aus der Aufgabenstellung an.

    Returns:
        str: Name des Standard-Skripts (unabhaengig davon, ob es gerade neu
            angelegt wurde oder schon existierte).
    """
    if not verfuegbare_skripte():
        skript_speichern(STANDARD_SKRIPT_NAME, standard_skript())
    return STANDARD_SKRIPT_NAME


# ---------- Schritt-Beschreibung (fuer Log/Anzeige) ----------

def schritt_beschreibung(schritt):
    aktion = schritt.get("aktion", "?")
    p = schritt.get("parameter", {})
    if aktion == "WARTEN":
        bonus = p.get("bonus_prozent", 0)
        zusatz = " (+0-%s%% Zufall)" % bonus if bonus else ""
        return "WARTEN %ss%s" % (p.get("sekunden", 0), zusatz)
    if aktion == "WARTEN_MIN_MAX":
        return "WARTEN_MIN_MAX %s-%ss" % (p.get("min", 0), p.get("max", 0))
    if aktion == "TASTE":
        return "TASTE %s" % p.get("taste", "")
    if aktion == "MAUS_BEWEGEN":
        return "MAUS_BEWEGEN dx=%s dy=%s" % (p.get("dx", 0), p.get("dy", 0))
    if aktion == "MAUS_ABS":
        return "MAUS_ABS x=%s y=%s" % (p.get("x", 0), p.get("y", 0))
    if aktion in ("BILD_WARTEN_BIS", "BILD_WARTEN_BIS_WEG"):
        variante = " [Variante: %s]" % p["variante"] if p.get("variante") else ""
        return "%s '%s'%s (%s, Schwelle %s)" % (
            aktion, p.get("bild", ""), variante, _timeout_text(_bild_timeout(p)), p.get("schwelle", 0))
    if aktion in ("BILD_KLICKEN", "BILD_KLICKEN_WENN_WEG"):
        zufall = "zufaellig in Hitbox" if p.get("zufall", 1) else "exakt Mitte+Offset"
        variante = " [Variante: %s]" % p["variante"] if p.get("variante") else ""
        return "%s '%s'%s Typ=%s %s Offset(%s,%s) (%s, Schwelle %s)" % (
            aktion, p.get("bild", ""), variante, p.get("klick_typ", "L"), zufall,
            p.get("offset_x", 0), p.get("offset_y", 0),
            _timeout_text(_bild_timeout(p)), p.get("schwelle", 0))
    if aktion == "BILD_KLICKEN_BIS":
        variante = " [Variante: %s]" % p["variante"] if p.get("variante") else ""
        modus = (p.get("modus") or "ZIEL_DA").upper()
        if modus == "BILD_WEG":
            ziel_text = "bis '%s' verschwindet" % p.get("bild", "")
        else:
            ziel_variante = " [Variante: %s]" % p["ziel_variante"] if p.get("ziel_variante") else ""
            ziel_text = "bis '%s'%s da" % (p.get("ziel_bild", ""), ziel_variante)
        return "BILD_KLICKEN_BIS '%s'%s %s (Abstand %ss, %s)" % (
            p.get("bild", ""), variante, ziel_text,
            p.get("klickabstand", 1.0), _timeout_text(_bild_timeout(p)))
    if aktion == "SCHLEIFE_START":
        wiederholung = "endlos" if p.get("endlos") else "%sx" % p.get("wiederholungen", 1)
        return "\U0001F501 SCHLEIFE START (%s)" % wiederholung
    if aktion == "SCHLEIFE_ENDE":
        return "\U0001F501 SCHLEIFE ENDE"
    if aktion == "GEWICHTET":
        pfade = p.get("pfade", [])
        gewichte = "/".join(str(int(pf.get("gewicht", 0))) for pf in pfade)
        gesamt_schritte = sum(len(pf.get("schritte", [])) for pf in pfade)
        return "\U0001F3B2 GEWICHTET %s (%d Pfade, %d Schritte gesamt)" % (
            gewichte or "-", len(pfade), gesamt_schritte)
    return aktion


def gewichtet_kompakt(p):
    """Kurzform der Gewichte fuer die kompakte Zeilenanzeige im Editor,
    z.B. "80/10/10" (ohne Emoji/Klammerzusatz - siehe schritt_beschreibung()
    fuer die ausfuehrliche Variante)."""
    pfade = p.get("pfade", [])
    return "/".join(str(int(pf.get("gewicht", 0))) for pf in pfade) or "-"


# ---------- Ausfuehrung ----------

def _ziel_hwnd(fenster_provider=None):
    """Ermittelt das zu fokussierende METIN2-hwnd - GENAU das isolierte
    Fenster, falls gesetzt (siehe fenster_provider-Doku in
    schritt_ausfuehren()), sonst das erstbeste per Titel gefundene
    (win32gui.FindWindow(None, titel), bisheriges Verhalten fuer nicht
    isolierte Ausfuehrung)."""
    hwnd = None
    if fenster_provider is not None:
        fenster = fenster_provider()
        hwnd = fenster.get("hwnd") if fenster else None
    if not hwnd:
        hwnd = win32gui.FindWindow(None, METIN2_FENSTER_TITEL)
    return hwnd


def _fokussiere_metin2(fenster_provider=None):
    """Holt das METIN2-Fenster in den Vordergrund, bevor eine Tastatur-Aktion
    ueber die HID-Firmware gesendet wird - Windows liefert Tastatureingaben
    nur an das fokussierte Fenster, unabhaengig davon, dass die HID-Firmware
    selbst "blind" sendet. Kein Fenster gefunden/Fokussieren fehlgeschlagen ->
    nur eine Warnung loggen, der Ablauf laeuft trotzdem weiter (z.B. falls
    Metin2 gerade neu startet).

    IMMER 3s Wartezeit NACH SetForegroundWindow (empirisch fuer SendInput-
    Tastatureingaben noetig, siehe fish_bot.FOKUS_WARTEZEIT_S) - fuer den
    MAUS-Klick-Pfad stattdessen _fokus_fuer_klick_sicherstellen() verwenden
    (deutlich schneller, ueberspringt die Wartezeit komplett, wenn das
    Fenster schon fokussiert ist)."""
    hwnd = _ziel_hwnd(fenster_provider)
    if not hwnd:
        print("[aktion_skript] WARNUNG: METIN2-Fenster nicht gefunden - Fokus nicht gesetzt")
        return
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        print("[aktion_skript] WARNUNG: METIN2-Fenster konnte nicht fokussiert werden: %s" % e)
        return
    time.sleep(3.0)


def _fokus_fuer_klick_sicherstellen(fenster_provider=None, hwnd=None):
    """Stellt sicher, dass das Zielfenster fokussiert ist, BEVOR die HID-Maus
    klickt/zieht - ein Klick auf ein NICHT fokussiertes Fenster wird von
    Metin2 i.d.R. ignoriert, obwohl die HID-Firmware den Klick bestaetigt
    (bestaetigter Regressions-Fall bei Fenster-Isolation auf mehrere
    parallele Instanzen, siehe fish_bot._fenster_fokussiert_sicherstellen() -
    dieselbe Funktion wird hier wiederverwendet: ueberspringt
    SetForegroundWindow+Wartezeit KOMPLETT, wenn das Fenster schon fokussiert
    ist, im Gegensatz zu _fokussiere_metin2()s IMMER 3s Wartezeit (die fuer
    SendInput-Tastatureingaben kalibriert ist, auf dem klickkritischen Pfad
    aber viel zu langsam waere).

    hwnd: optionales BEREITS ermitteltes hwnd - spart einen zusaetzlichen
        fenster_provider()-Aufruf, wenn der Aufrufer 'fenster' ohnehin schon
        fuer etwas anderes braucht (z.B. MAUS_ABS fuer die Koordinaten-
        umrechnung) - fenster_provider() soll pro Schritt nur EINMAL
        aufgerufen werden (siehe fenster_provider-Docstring: "wird bei JEDEM
        ... Schritt NEU aufgerufen", nicht mehrfach INNERHALB eines
        Schritts). Hat Vorrang vor fenster_provider, falls beides gesetzt
        ist."""
    if hwnd is None:
        hwnd = _ziel_hwnd(fenster_provider)
    fish_bot._fenster_fokussiert_sicherstellen(hwnd)


# Tastatur laeuft ueber pynput (SendInput), NICHT ueber die Arduino-HID-Firmware:
# die Firmware-Tastendruecke kamen trotz bestaetigtem ACK nicht zuverlaessig in
# Metin2 an (siehe Debugging in test_taste_skript*.py), waehrend pynput
# nachweislich ankommt. Maus-Aktionen bleiben bewusst auf der HID-Maus (siehe
# _klicken()/_maus_zu_ziel_bewegen()), da SetCursorPos in dieser Session nicht
# funktioniert (siehe hid_maus.maus_ziehen()).
_pynput_tastatur = _PynputController()

# Bildet die in hid_maus._TASTEN_ERLAUBT erlaubten Namen auf pynput-Sondertasten
# ab - alles, was hier fehlt, ist ein normales Zeichen (Buchstabe/Ziffer) und
# wird direkt als String an pynput uebergeben.
_PYNPUT_SONDERTASTEN = {
    "SPACE": _PynputKey.space,
    "ENTER": _PynputKey.enter,
    "TAB": _PynputKey.tab,
    "ESC": _PynputKey.esc,
    "BACKSPACE": _PynputKey.backspace,
    "DEL": _PynputKey.delete,
    "SHIFT": _PynputKey.shift,
    "CTRL": _PynputKey.ctrl,
    "ALT": _PynputKey.alt,
    "UP": _PynputKey.up,
    "DOWN": _PynputKey.down,
    "LEFT": _PynputKey.left,
    "RIGHT": _PynputKey.right,
}
for _i in range(1, 13):
    _PYNPUT_SONDERTASTEN["F%d" % _i] = getattr(_PynputKey, "f%d" % _i)


def _pynput_taste_objekt(name):
    """Liefert das pynput-Tastenobjekt (Key-Enum oder 1-Zeichen-String) fuer
    einen in hid_maus.TASTEN_ERLAUBT gueltigen Namen, oder None."""
    if name in _PYNPUT_SONDERTASTEN:
        return _PYNPUT_SONDERTASTEN[name]
    if len(name) == 1:
        return name.lower()
    return None


def _taste_senden_pynput(name):
    """Drueckt und laesst eine Taste per pynput los (echtes KEY_DOWN/KEY_UP
    ueber SendInput) - im Gegensatz zur Arduino-HID-Firmware kommt das
    nachweislich in Metin2 an."""
    taste = _pynput_taste_objekt(name)
    if taste is None:
        print("[aktion_skript] Unbekannte Taste fuer pynput: %r" % name)
        return False
    try:
        _pynput_tastatur.press(taste)
        time.sleep(0.1)
        _pynput_tastatur.release(taste)
        return True
    except Exception as e:
        print("[aktion_skript] pynput-Fehler bei Taste '%s': %s" % (name, e))
        return False


class _MausKontext:
    """Kontextmanager: haelt (falls 'dispatcher' gegeben) waehrend des
    with-Blocks die gemeinsame HID-Maus per MausDispatcher - No-Op, wenn
    dispatcher None ist (Standardfall: bisheriges Verhalten unveraendert,
    kein Lock, direkte Ausfuehrung).

    Wird NUR um die eigentliche Klick-/Beweg-Aktion gelegt (nicht um
    WARTEN/BILD_WARTEN_BIS*-Wartezeiten) - dadurch geben Warte-Aktionen die
    Maus automatisch frei, ohne das extra behandeln zu muessen: sie haben
    sie nie angefordert (siehe makro_manager.py/Aufgabenstellung "Warte-
    Aktionen geben die Maus frei")."""

    def __init__(self, dispatcher, prioritaet):
        self.dispatcher = dispatcher
        self.prioritaet = prioritaet

    def __enter__(self):
        if self.dispatcher is not None:
            self.dispatcher.maus_holen(self.prioritaet)
        return self

    def __exit__(self, *exc_info):
        if self.dispatcher is not None:
            self.dispatcher.maus_freigeben()
        return False


def _stop_event_aufloesen(stop_event):
    """Liefert 'stop_event', falls gegeben, sonst das globale _stop_event -
    zentrale Stelle fuer die 'dispatcher/stop_event=None -> bisheriges
    Verhalten' Rueckwaertskompatibilitaet (siehe skript_ausfuehren())."""
    return stop_event if stop_event is not None else _stop_event


def _kombinierter_stop_pruefen(ev, waechter):
    """Liefert ein Callable[[], bool], das True liefert, wenn ENTWEDER 'ev'
    (echter Stopp) ODER 'waechter' (siehe BildWaechter) ausgeloest hat - fuer
    bild_erkennung.bild_warten_bis_sichtbar()/_weg(), deren stop_pruefen-
    Parameter unveraendert bleibt (kein neuer Parameter dort noetig, siehe
    bild_erkennung.py)."""
    if waechter is None:
        return ev.is_set
    return lambda: ev.is_set() or waechter.ist_ausgeloest()


def _warten_mit_bonus(sekunden, bonus_prozent, stop_event=None, waechter=None):
    """Wartet 'sekunden' * Zufallsfaktor (0 bis bonus_prozent% laenger),
    unterbrechbar durch ausfuehrung_stoppen() (oder das uebergebene
    'stop_event' - siehe skript_ausfuehren()) - auch waehrend langer Waits.
    Bricht ZUSAETZLICH fruehzeitig ab, wenn 'waechter' (siehe BildWaechter)
    zwischenzeitlich ausgeloest hat, damit ein langer WARTEN-Schritt den
    Sprung nicht erst nach Ablauf bemerkt - das eigentliche Springen macht
    dann _schritte_ausfuehren(), sobald die Kontrolle dorthin zurueckkehrt."""
    ev = _stop_event_aufloesen(stop_event)
    bonus = max(0.0, min(40.0, float(bonus_prozent))) / 100.0
    faktor = random.uniform(1.0, 1.0 + bonus) if bonus > 0 else 1.0
    ende = time.time() + float(sekunden) * faktor
    while time.time() < ende:
        if ev.is_set() or (waechter is not None and waechter.ist_ausgeloest()):
            return
        time.sleep(min(0.1, ende - time.time()))


def _warte_unterbrechbar_bis(ende, stop_event=None, waechter=None):
    """Schlaeft in 0.1s-Schritten bis zum Zeitpunkt 'ende', unterbrechbar
    durch ausfuehrung_stoppen() (oder das uebergebene 'stop_event') sowie
    durch einen ausgeloesten 'waechter' (siehe _warten_mit_bonus())."""
    ev = _stop_event_aufloesen(stop_event)
    while time.time() < ende:
        if ev.is_set() or (waechter is not None and waechter.ist_ausgeloest()):
            return
        time.sleep(min(0.1, ende - time.time()))


def _warten_min_max_schritt(p, stop_event=None, waechter=None):
    """Wartet eine zufaellige Dauer zwischen 'min' und 'max' Sekunden."""
    lo = float(p.get("min", 0))
    hi = float(p.get("max", lo))
    if hi < lo:
        lo, hi = hi, lo
    _warte_unterbrechbar_bis(time.time() + random.uniform(lo, hi), stop_event=stop_event,
                              waechter=waechter)


def _wurm_klicken_schritt(maus, dispatcher=None, prioritaet="MITTEL", fenster_provider=None):
    """Sucht das METIN2-Fenster frisch und delegiert an fish_bot.wurm_klicken()
    (dieselbe Logik wie im Fischbot selbst: Score-Schwelle, Hitbox-Jitter).

    fenster_provider: optionales Callable[[], dict|None] - siehe
        schritt_ausfuehren(). None (Standard) sucht wie bisher das erste
        METIN2-Fenster per Titel (fish_bot.fenster_finden_geprueft()).

    Fenster-Suche/Screenshot brauchen die Maus nicht - nur der eigentliche
    wurm_klicken()-Aufruf (Bewegen+Rechtsklick) haelt dafuer den Dispatcher."""
    fenster = fenster_provider() if fenster_provider is not None else fish_bot.fenster_finden_geprueft()
    if fenster is None:
        raise SchrittFehler("METIN2-Fenster nicht gefunden/nicht plausibel")
    screenshot = fish_bot.screenshot_holen(fenster)
    with _MausKontext(dispatcher, prioritaet):
        if not fish_bot.wurm_klicken(maus, fenster, screenshot):
            raise SchrittFehler("Kein Wurm-Stapel gefunden oder Klick nicht bestaetigt")


def _bild_name(p):
    name = (p.get("bild") or "").strip()
    if not name:
        raise SchrittFehler("Kein Bild ausgewaehlt")
    return name


def _bild_variante(p):
    """Liest den optionalen 'variante'-Parameter (leer/fehlend -> None, damit
    bild_erkennung.py auf die Standard-Variante zurueckfaellt)."""
    variante = (p.get("variante") or "").strip()
    return variante or None


def _bild_timeout(p):
    """Liest 'timeout' - bei endlos=1 wird 0 zurueckgegeben (siehe
    bild_erkennung.bild_warten_bis_sichtbar()/_weg(): timeout<=0 = unbegrenzt
    warten, nur per Stopp unterbrechbar)."""
    if p.get("endlos"):
        return 0
    return float(p.get("timeout", 5.0))


def _timeout_text(timeout):
    return "endlos" if timeout <= 0 else "Timeout %ss" % timeout


def _bild_warten_bis_schritt(p, stop_event=None, waechter=None, fenster_provider=None):
    name = _bild_name(p)
    variante = _bild_variante(p)
    timeout = _bild_timeout(p)
    schwelle = float(p.get("schwelle", bild_erkennung.SCHWELLE_STANDARD))
    suchbereich = p.get("suchbereich")
    ev = _stop_event_aufloesen(stop_event)
    treffer = bild_erkennung.bild_warten_bis_sichtbar(
        name, timeout, schwelle, stop_pruefen=_kombinierter_stop_pruefen(ev, waechter), variante=variante,
        fenster_provider=fenster_provider, suchbereich=suchbereich)
    if treffer is None:
        raise SchrittFehler("Bild '%s' nicht erschienen (%s)" % (name, _timeout_text(timeout)))


def _bild_warten_bis_weg_schritt(p, stop_event=None, waechter=None, fenster_provider=None):
    name = _bild_name(p)
    variante = _bild_variante(p)
    timeout = _bild_timeout(p)
    schwelle = float(p.get("schwelle", bild_erkennung.SCHWELLE_STANDARD))
    suchbereich = p.get("suchbereich")
    ev = _stop_event_aufloesen(stop_event)
    weg, _letzte = bild_erkennung.bild_warten_bis_weg(
        name, timeout, schwelle, stop_pruefen=_kombinierter_stop_pruefen(ev, waechter), variante=variante,
        fenster_provider=fenster_provider, suchbereich=suchbereich)
    if not weg:
        raise SchrittFehler("Bild '%s' ist nach %s immer noch da" % (name, _timeout_text(timeout)))


def _bild_klickpunkt(bbox, bild_name, p, variante=None):
    """Bestimmt den Klickpunkt fuer eine bbox=(x,y,w,h,score): bei zufall=1
    (Standard) ein Zufallspunkt innerhalb der gespeicherten Hitbox (oder des
    gesamten Bildes, falls keine Hitbox gespeichert ist - siehe
    bild_erkennung.zufallspunkt_in_treffer()), bei zufall=0 exakt die Mitte.
    In beiden Faellen wird offset_x/offset_y danach noch addiert."""
    x, y, w, h, _score = bbox
    if p.get("zufall", 1):
        px, py = bild_erkennung.zufallspunkt_in_treffer((x, y, w, h), bild_name, variante)
    else:
        px, py = x + w // 2, y + h // 2
    return px + int(p.get("offset_x", 0)), py + int(p.get("offset_y", 0))


def _aktuelle_mausposition():
    """Liest die aktuelle Cursor-Position per GetCursorPos() aus - im
    Gegensatz zu SetCursorPos() funktioniert das Auslesen in dieser Session
    zuverlaessig."""
    punkt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(punkt))
    return punkt.x, punkt.y


def _maus_zu_ziel_bewegen(maus, ziel_x, ziel_y):
    """Bewegt die Maus zur absoluten Bildschirmposition (ziel_x, ziel_y) -
    NICHT per SetCursorPos() (funktioniert in dieser Session nicht, der
    Zeiger bleibt stehen), sondern ueber die Arduino-HID-Firmware
    (maus.maus_bewegen() sendet seit hid_maus.py MOVE_ABS direkt eine
    absolute Zielposition, keine gestufte Relativbewegung mehr noetig).

    Returns:
        bool: False, wenn der Schritt von der HID-Firmware nicht bestaetigt
            wurde.
    """
    return maus.maus_bewegen(ziel_x, ziel_y)


def _klicken(maus, klick_typ):
    """Fuehrt einen Links-, Rechts- oder Doppelklick aus, je nach klick_typ
    ('L'/'R'/'D') - 'D' fuehrt zwei rasche Linksklicks hintereinander aus
    (die HID-Firmware kennt keinen eigenen Doppelklick-Befehl)."""
    typ = str(klick_typ).upper()
    if typ.startswith("R"):
        return maus.klick_rechts()
    if typ.startswith("D"):
        erster = maus.klick_links()
        time.sleep(DOPPELKLICK_ABSTAND_S)
        zweiter = maus.klick_links()
        return erster and zweiter
    return maus.klick_links()


def _bild_klicken_schritt(maus, p, dispatcher=None, prioritaet="MITTEL", stop_event=None, waechter=None,
                           fenster_provider=None):
    """Wartet auf das Bild und klickt auf einen Punkt gemaess _bild_klickpunkt().

    Loggt bei jedem Aufruf Fundort/Hitbox/Klickpunkt/Mausposition vor und
    nach der Bewegung sowie das Klick-Ergebnis - zum Debuggen, ob der
    Klickpunkt korrekt berechnet wird und die Maus sich tatsaechlich dorthin
    bewegt (siehe _maus_zu_ziel_bewegen()).

    Die Maus wird NUR fuer den eigentlichen Beweg+Klick-Teil gehalten (siehe
    _MausKontext) - die Wartezeit auf das Bild selbst braucht sie nicht."""
    name = _bild_name(p)
    variante = _bild_variante(p)
    timeout = _bild_timeout(p)
    schwelle = float(p.get("schwelle", bild_erkennung.SCHWELLE_STANDARD))
    suchbereich = p.get("suchbereich")
    ev = _stop_event_aufloesen(stop_event)

    treffer = bild_erkennung.bild_warten_bis_sichtbar(
        name, timeout, schwelle, stop_pruefen=_kombinierter_stop_pruefen(ev, waechter), variante=variante,
        fenster_provider=fenster_provider, suchbereich=suchbereich)
    if treffer is None:
        raise SchrittFehler("Bild '%s' nicht gefunden (%s)" % (name, _timeout_text(timeout)))

    tx, ty, tw, th, tscore = treffer
    print("[BILD_KLICKEN] '%s' gefunden: x=%d y=%d w=%d h=%d (Score %.3f)" %
          (name, tx, ty, tw, th, tscore))

    hitbox = bild_erkennung.hitbox_laden(name, variante)
    if hitbox:
        print("[BILD_KLICKEN] Hitbox: x=%d y=%d w=%d h=%d" %
              (hitbox["x"], hitbox["y"], hitbox["w"], hitbox["h"]))
    else:
        print("[BILD_KLICKEN] Hitbox: keine gespeichert (ganzes Bild gilt als Hitbox)")

    kx, ky = _bild_klickpunkt(treffer, name, p, variante)
    print("[BILD_KLICKEN] Gewaehlter Klickpunkt: x=%d y=%d" % (kx, ky))

    with _MausKontext(dispatcher, prioritaet):
        _fokus_fuer_klick_sicherstellen(fenster_provider)
        vor_x, vor_y = _aktuelle_mausposition()
        print("[BILD_KLICKEN] Mausposition VOR Bewegung: x=%d y=%d" % (vor_x, vor_y))

        if not _maus_zu_ziel_bewegen(maus, kx, ky):
            raise SchrittFehler("Maus-Bewegen zu Bild '%s' fehlgeschlagen" % name)

        nach_x, nach_y = _aktuelle_mausposition()
        print("[BILD_KLICKEN] Mausposition NACH Bewegung: x=%d y=%d" % (nach_x, nach_y))

        time.sleep(KLICK_VORSICHTSMARGE_S)
        klick_ok = _klicken(maus, p.get("klick_typ", "L"))
        print("[BILD_KLICKEN] Klick bestaetigt: %s" % klick_ok)
        if not klick_ok:
            raise SchrittFehler("Klick auf Bild '%s' nicht bestaetigt" % name)


def _bild_klicken_wenn_weg_schritt(maus, p, dispatcher=None, prioritaet="MITTEL", stop_event=None,
                                    waechter=None, fenster_provider=None):
    """Wartet, bis das Bild verschwindet, und klickt auf einen Punkt (gemaess
    _bild_klickpunkt()) innerhalb der zuletzt bekannten Position."""
    name = _bild_name(p)
    variante = _bild_variante(p)
    timeout = _bild_timeout(p)
    schwelle = float(p.get("schwelle", bild_erkennung.SCHWELLE_STANDARD))
    suchbereich = p.get("suchbereich")
    ev = _stop_event_aufloesen(stop_event)

    weg, letzte = bild_erkennung.bild_warten_bis_weg(
        name, timeout, schwelle, stop_pruefen=_kombinierter_stop_pruefen(ev, waechter), variante=variante,
        fenster_provider=fenster_provider, suchbereich=suchbereich)
    if not weg:
        raise SchrittFehler("Bild '%s' ist nach %s immer noch da" % (name, _timeout_text(timeout)))
    if letzte is None:
        raise SchrittFehler("Bild '%s' wurde waehrend der Wartezeit nie gesehen - "
                            "keine Position zum Klicken bekannt" % name)
    kx, ky = _bild_klickpunkt(letzte, name, p, variante)

    with _MausKontext(dispatcher, prioritaet):
        _fokus_fuer_klick_sicherstellen(fenster_provider)
        if not _maus_zu_ziel_bewegen(maus, kx, ky):
            raise SchrittFehler("Maus-Bewegen zur letzten Position von '%s' fehlgeschlagen" % name)
        time.sleep(KLICK_VORSICHTSMARGE_S)
        if not _klicken(maus, p.get("klick_typ", "L")):
            raise SchrittFehler("Klick nach Verschwinden von '%s' nicht bestaetigt" % name)


def _bild_klicken_bis_schritt(maus, p, dispatcher=None, prioritaet="MITTEL", stop_event=None,
                               waechter=None, fenster_provider=None):
    """Klickt wiederholt auf 'bild' (mit 'klickabstand' Sekunden Pause
    zwischen den Klicks), bis eine Abbruchbedingung eintritt - je nach
    'modus':
      - "ZIEL_DA" (Standard): bis 'ziel_bild' erscheint (z.B. ein Icon so
        lange anklicken, bis sich der Spielzustand aendert und ein anderes
        Bild sichtbar wird).
      - "BILD_WEG": bis 'bild' SELBST nicht mehr sichtbar ist (kein
        separates Ziel-Bild noetig) - z.B. ein Icon anklicken, bis es
        verschwindet.

    Jeder Zyklus prueft ZUERST die Abbruchbedingung, dann erst das Klick-
    Bild - im ZIEL_DA-Modus wird ein Zyklus, in dem 'bild' gerade nicht
    sichtbar ist, uebersprungen (kein Fehler), da 'ziel_bild' trotzdem
    jederzeit erscheinen kann. Nutzt bild_erkennung.bild_pruefen()
    (Einzelversuch, kein Polling/Warten) statt bild_warten_bis_sichtbar(),
    da hier SELBST zwischen zwei Pruefungen gepollt wird (mit klickabstand
    statt POLL_INTERVALL als Takt)."""
    name = _bild_name(p)
    variante = _bild_variante(p)
    modus = (p.get("modus") or "ZIEL_DA").strip().upper()
    ziel_name = (p.get("ziel_bild") or "").strip()
    if modus == "ZIEL_DA" and not ziel_name:
        raise SchrittFehler("BILD_KLICKEN_BIS: kein Ziel-Bild angegeben (Abbruchbedingung)")
    ziel_variante = (p.get("ziel_variante") or "").strip() or None
    klickabstand = max(0.0, float(p.get("klickabstand", 1.0)))
    timeout = _bild_timeout(p)
    schwelle = float(p.get("schwelle", bild_erkennung.SCHWELLE_STANDARD))
    suchbereich = p.get("suchbereich")
    ziel_suchbereich = p.get("ziel_suchbereich")
    ev = _stop_event_aufloesen(stop_event)

    ende = None if timeout <= 0 else time.time() + timeout
    while True:
        if ev.is_set() or (waechter is not None and waechter.ist_ausgeloest()):
            return

        treffer = bild_erkennung.bild_pruefen(name, schwelle, variante, fenster_provider=fenster_provider,
                                               suchbereich=suchbereich)

        if modus == "BILD_WEG":
            if treffer is None:
                return  # 'bild' ist weg - fertig, Erfolg
        else:
            if bild_erkennung.bild_pruefen(ziel_name, schwelle, ziel_variante,
                                            fenster_provider=fenster_provider,
                                            suchbereich=ziel_suchbereich) is not None:
                return  # Ziel-Bild da - fertig, Erfolg

        if treffer is not None:
            kx, ky = _bild_klickpunkt(treffer, name, p, variante)
            with _MausKontext(dispatcher, prioritaet):
                _fokus_fuer_klick_sicherstellen(fenster_provider)
                if _maus_zu_ziel_bewegen(maus, kx, ky):
                    time.sleep(KLICK_VORSICHTSMARGE_S)
                    _klicken(maus, p.get("klick_typ", "L"))

        if ende is not None and time.time() >= ende:
            if modus == "BILD_WEG":
                bedingung = "Bild '%s' verschwindet" % name
            else:
                bedingung = "Ziel-Bild '%s' erscheint" % ziel_name
            raise SchrittFehler(
                "BILD_KLICKEN_BIS: %s nach %s nicht eingetreten" % (bedingung, _timeout_text(timeout)))

        _warte_unterbrechbar_bis(time.time() + klickabstand, stop_event=ev, waechter=waechter)


def _gewichteten_pfad_waehlen(pfade):
    """Waehlt zufaellig einen Pfad aus 'pfade' (Liste von {"gewicht","schritte"})
    aus, gewichtet nach dem jeweiligen 'gewicht'. Die Gewichte werden
    normalisiert (die Summe muss nicht 100 ergeben - 80/10/10 wird intern zu
    80/100, 10/100, 10/100).

    Returns:
        list: die 'schritte'-Liste des gewaehlten Pfads, oder [] wenn 'pfade'
            leer ist oder alle Gewichte <= 0 sind (kein gueltiger Pfad).
    """
    gueltige = [(max(0.0, float(pf.get("gewicht", 0))), pf.get("schritte", [])) for pf in pfade]
    gesamt = sum(g for g, _ in gueltige)
    if gesamt <= 0:
        return []
    ziel = random.uniform(0, gesamt)
    kumuliert = 0.0
    for gewicht, schritte in gueltige:
        kumuliert += gewicht
        if ziel <= kumuliert:
            return schritte
    return gueltige[-1][1]  # Rundungssicherheit (Gleitkomma-Summe knapp < ziel)


def _gewichtet_schritt(maus, p, bei_fehler, log, tiefe, dispatcher=None,
                        prioritaet="MITTEL", stop_event=None, sprung_ziel=None, waechter=None,
                        fenster_provider=None):
    """Waehlt einen Pfad gewichtet aus und fuehrt dessen Schritte rekursiv aus
    (siehe _schritte_ausfuehren()). bei_fehler/Stop-Flag gelten dabei genauso
    wie fuer alle anderen Schritte - ein GESTOPPT propagiert automatisch nach
    aussen (dasselbe stop_event wie der aeussere Ablauf), ein ABGEBROCHEN wird
    als SchrittFehler nach aussen gemeldet, damit der aeussere Ablauf (je nach
    dessen eigenem bei_fehler) ebenfalls entsprechend reagiert. dispatcher/
    prioritaet/sprung_ziel/waechter werden unveraendert an die Schritte des
    gewaehlten Pfads weitergereicht."""
    if tiefe > GEWICHTET_MAX_TIEFE:
        raise SchrittFehler(
            "GEWICHTET: maximale Verschachtelungstiefe (%d) erreicht - "
            "vermutlich ein Pfad, der sich (indirekt) selbst enthaelt" % GEWICHTET_MAX_TIEFE)

    pfade = p.get("pfade", [])
    if not pfade:
        raise SchrittFehler("GEWICHTET: keine Pfade definiert")

    schritte = _gewichteten_pfad_waehlen(pfade)
    if not schritte:
        raise SchrittFehler("GEWICHTET: kein gueltiger Pfad gewaehlt (alle Gewichte <= 0?)")

    log("  GEWICHTET: Pfad mit %d Schritt(en) gewaehlt (Tiefe %d)" % (len(schritte), tiefe))
    ergebnis = _schritte_ausfuehren(schritte, maus, bei_fehler, log, status=None, tiefe=tiefe + 1,
                                     dispatcher=dispatcher, prioritaet=prioritaet, stop_event=stop_event,
                                     sprung_ziel=sprung_ziel, waechter=waechter, fenster_provider=fenster_provider)
    if ergebnis == "ABGEBROCHEN":
        raise SchrittFehler("GEWICHTET: gewaehlter Pfad wurde abgebrochen (siehe vorherige Fehler)")
    # "GESTOPPT" braucht keine Sonderbehandlung: derselbe stop_event wird im
    # aeusseren Ablauf verwendet, der naechste is_set()-Check dort greift
    # automatisch.


def schritt_ausfuehren(schritt, maus, bei_fehler="ABBRECHEN", log=print, tiefe=0,
                        dispatcher=None, prioritaet="MITTEL", stop_event=None, sprung_ziel=None,
                        waechter=None, fenster_provider=None):
    """Fuehrt einen einzelnen Schritt aus. Wirft SchrittFehler bei Fehlschlag
    (z.B. HID-Maus hat einen Klick/Tastendruck nicht bestaetigt).

    bei_fehler/log/tiefe werden nur fuer GEWICHTET-Schritte gebraucht (deren
    gewaehlter Pfad rekursiv wieder eine vollstaendige Schritt-Liste ist) -
    fuer alle anderen Aktionen spielen sie keine Rolle, die Standardwerte
    reichen dort aus (bestehende Aufrufe schritt_ausfuehren(schritt, maus)
    bleiben unveraendert gueltig).

    dispatcher: optionale MausDispatcher-Instanz (siehe maus_dispatcher.py) -
        None (Standard) laesst alles wie bisher direkt ohne Lock laufen
        (Einzel-Skript-Ausfuehrung ueber aktion_editor.py). Ist ein
        dispatcher gegeben, wird er NUR um die eigentlichen Klick-/Beweg-
        Aktionen gelegt (siehe _MausKontext) - Warte-Aktionen fordern die
        Maus dadurch automatisch nie an und geben sie effektiv frei, waehrend
        andere Makros parallel darauf zugreifen koennen (siehe
        makro_manager.py).
    prioritaet: an dispatcher.maus_holen() durchgereicht (siehe
        maus_dispatcher.PRIORITAET_*), wirkungslos wenn dispatcher None ist.
    stop_event: optionales threading.Event fuer EIGENSTAENDIGEN Stop dieses
        Ablaufs (z.B. je ein Event pro parallelem Makro in makro_manager.py) -
        None (Standard) nutzt weiterhin das globale _stop_event/
        ausfuehrung_stoppen() wie bisher.
    waechter: optionale BildWaechter-Instanz (siehe skript_ausfuehren()) -
        wird unveraendert an alle wartenden/klickenden Teilschritte
        durchgereicht, damit ein Treffer des Waechters JEDE laufende
        Wartezeit sofort unterbricht (siehe _kombinierter_stop_pruefen()).
        None (Standard) = kein Waechter aktiv, unveraendertes Verhalten.
    fenster_provider: optionales Callable[[], dict|None] fuer die Fenster-
        Isolation eines Makros auf GENAU EIN METIN2-Fenster (mehrere
        gleichzeitig offene Spielfenster, siehe modules.fenster.
        alle_spielfenster_finden()/fenster_von_hwnd() und makro_manager.py) -
        wird bei JEDEM Bild-/Fokus-/Wurm-Schritt NEU aufgerufen (liefert die
        aktuelle Fensterposition, falls das Fenster inzwischen bewegt wurde)
        und fuer MAUS_ABS verwendet, um die dort fensterrelativ gemeinten
        x/y-Koordinaten in absolute Bildschirmkoordinaten umzurechnen. None
        (Standard) = "Alle Fenster"/bisheriges Verhalten: MAUS_ABS bleibt
        absolut, Bild-/Fokus-/Wurm-Schritte suchen wie bisher das erste
        METIN2-Fenster per Titel.
    """
    aktion = schritt.get("aktion")
    p = schritt.get("parameter", {})

    if aktion == "WARTEN":
        _warten_mit_bonus(p.get("sekunden", 0), p.get("bonus_prozent", 0), stop_event=stop_event,
                           waechter=waechter)

    elif aktion == "WARTEN_MIN_MAX":
        _warten_min_max_schritt(p, stop_event=stop_event, waechter=waechter)

    elif aktion == "RECHTSKLICK":
        with _MausKontext(dispatcher, prioritaet):
            _fokus_fuer_klick_sicherstellen(fenster_provider)
            if not maus.klick_rechts():
                raise SchrittFehler("Rechtsklick nicht bestaetigt")

    elif aktion == "LINKSKLICK":
        with _MausKontext(dispatcher, prioritaet):
            _fokus_fuer_klick_sicherstellen(fenster_provider)
            if not maus.klick_links():
                raise SchrittFehler("Linksklick nicht bestaetigt")

    elif aktion == "DOPPELKLICK":
        with _MausKontext(dispatcher, prioritaet):
            _fokus_fuer_klick_sicherstellen(fenster_provider)
            if not _klicken(maus, "D"):
                raise SchrittFehler("Doppelklick nicht bestaetigt")

    elif aktion == "TASTE":
        # Laeuft ueber pynput (SendInput), nicht ueber die HID-Maus - braucht
        # den Dispatcher nicht (kein Zugriff auf die gemeinsame serielle
        # Verbindung).
        name = (p.get("taste") or "").strip()
        if not name:
            raise SchrittFehler("Kein Tastenname angegeben")
        _fokussiere_metin2(fenster_provider=fenster_provider)
        if not _taste_senden_pynput(name):
            raise SchrittFehler("Taste '%s' nicht bestaetigt" % name)

    elif aktion == "FOKUS":
        # Manuell einfuegbarer Fokus-Schritt (siehe AKTION_PARAMETER["FOKUS"]-
        # Doku) - dieselbe Fokussierung wie automatisch vor TASTE, aber frei
        # platzierbar, z.B. vor einer Folge reiner Maus-Aktionen (LINKSKLICK/
        # BILD_KLICKEN/...), die sonst KEINE eigene Fokussierung ausloesen.
        _fokussiere_metin2(fenster_provider=fenster_provider)

    elif aktion == "MAUS_BEWEGEN":
        # maus.maus_bewegen() erwartet seit hid_maus.py eine absolute
        # Zielposition (MOVE_ABS) - dx/dy bleiben aus Anwendersicht weiterhin
        # eine relative Verschiebung, werden also erst auf die per
        # GetCursorPos() ermittelte aktuelle Position aufaddiert.
        with _MausKontext(dispatcher, prioritaet):
            _fokus_fuer_klick_sicherstellen(fenster_provider)
            aktuelle_x, aktuelle_y = _aktuelle_mausposition()
            ziel_x = aktuelle_x + int(p.get("dx", 0))
            ziel_y = aktuelle_y + int(p.get("dy", 0))
            if not maus.maus_bewegen(ziel_x, ziel_y):
                raise SchrittFehler("Mausbewegung nicht bestaetigt")

    elif aktion == "MAUS_ABS":
        # Ohne fenster_provider (== "Alle Fenster"/Einzel-Skript-Ausfuehrung)
        # bleiben x/y wie bisher absolute Bildschirmkoordinaten. Bei
        # Fenster-Isolation sind x/y dagegen relativ zum isolierten Fenster
        # gemeint - die aktuelle Fensterposition (frisch geholt, siehe
        # fenster_provider-Docstring oben) wird deshalb addiert.
        with _MausKontext(dispatcher, prioritaet):
            ziel_x, ziel_y = int(p.get("x", 0)), int(p.get("y", 0))
            if fenster_provider is not None:
                # fenster_provider() nur EINMAL pro Schritt aufrufen (siehe
                # dessen Docstring) - das bereits geholte 'fenster' wird
                # daher auch fuer die Fokus-Pruefung wiederverwendet, statt
                # _fokus_fuer_klick_sicherstellen() ein zweites Mal selbst
                # aufrufen zu lassen.
                fenster = fenster_provider()
                if fenster is None:
                    raise SchrittFehler("Zielfenster nicht gefunden - MAUS_ABS uebersprungen")
                ziel_x += fenster["x"]
                ziel_y += fenster["y"]
                _fokus_fuer_klick_sicherstellen(hwnd=fenster.get("hwnd"))
            else:
                _fokus_fuer_klick_sicherstellen()
            if not maus.maus_ziehen(ziel_x, ziel_y):
                raise SchrittFehler("Maus-Ziehen fehlgeschlagen")

    elif aktion == "WURM_KLICKEN":
        _wurm_klicken_schritt(maus, dispatcher=dispatcher, prioritaet=prioritaet,
                               fenster_provider=fenster_provider)

    elif aktion == "BILD_WARTEN_BIS":
        _bild_warten_bis_schritt(p, stop_event=stop_event, waechter=waechter,
                                  fenster_provider=fenster_provider)

    elif aktion == "BILD_WARTEN_BIS_WEG":
        _bild_warten_bis_weg_schritt(p, stop_event=stop_event, waechter=waechter,
                                      fenster_provider=fenster_provider)

    elif aktion == "BILD_KLICKEN":
        _bild_klicken_schritt(maus, p, dispatcher=dispatcher, prioritaet=prioritaet, stop_event=stop_event,
                               waechter=waechter, fenster_provider=fenster_provider)

    elif aktion == "BILD_KLICKEN_WENN_WEG":
        _bild_klicken_wenn_weg_schritt(maus, p, dispatcher=dispatcher, prioritaet=prioritaet,
                                        stop_event=stop_event, waechter=waechter,
                                        fenster_provider=fenster_provider)

    elif aktion == "BILD_KLICKEN_BIS":
        _bild_klicken_bis_schritt(maus, p, dispatcher=dispatcher, prioritaet=prioritaet, stop_event=stop_event,
                                   waechter=waechter, fenster_provider=fenster_provider)

    elif aktion == "GEWICHTET":
        _gewichtet_schritt(maus, p, bei_fehler, log, tiefe,
                            dispatcher=dispatcher, prioritaet=prioritaet, stop_event=stop_event,
                            sprung_ziel=sprung_ziel, waechter=waechter, fenster_provider=fenster_provider)

    else:
        raise SchrittFehler("Unbekannte Aktion: %r" % aktion)


def _passendes_schleifen_ende(schritte, start_index):
    """Findet den Index des zum SCHLEIFE_START bei 'start_index' passenden
    SCHLEIFE_ENDE - unter Beruecksichtigung VERSCHACHTELTER Schleifen (eine
    SCHLEIFE_START/SCHLEIFE_ENDE-Zaehltiefe, aehnlich wie Klammern zaehlen).

    Returns:
        int | None: Index des passenden SCHLEIFE_ENDE, oder None wenn keins
            gefunden wurde (unbalancierte Schleife - Bedienfehler im Editor).
    """
    tiefe = 0
    for i in range(start_index, len(schritte)):
        aktion = schritte[i].get("aktion")
        if aktion == "SCHLEIFE_START":
            tiefe += 1
        elif aktion == "SCHLEIFE_ENDE":
            tiefe -= 1
            if tiefe == 0:
                return i
    return None


def _sprung_ziel_index(sprung_ziel, gesamt):
    """Loest 'sprung_ziel' (siehe skript_ausfuehren()) zu einem 0-basierten
    Index innerhalb einer 'gesamt' Schritte langen Liste auf.

    'sprung_ziel' ist 1-basiert (wie in der GUI angezeigte Schrittnummern):
    None/"" /"ANFANG"/<=1 -> Schritt 1 (Index 0). Ungueltige/zu grosse Werte
    werden auf den gueltigen Bereich begrenzt, statt einen Fehler zu werfen -
    ein Bedienfehler bei der Sprungziel-Eingabe soll den Ablauf nicht per
    Absturz beenden."""
    if gesamt <= 0:
        return 0
    if sprung_ziel is None:
        return 0
    if isinstance(sprung_ziel, str):
        text = sprung_ziel.strip().upper()
        if not text or text == "ANFANG":
            return 0
        try:
            sprung_ziel = int(text)
        except ValueError:
            return 0
    try:
        ziel = int(sprung_ziel) - 1
    except (TypeError, ValueError):
        return 0
    return max(0, min(ziel, gesamt - 1))


def _effektives_fehlerverhalten(schritt, bei_fehler, sprung_ziel):
    """Liefert (bei_fehler, sprung_ziel), das fuer den fehlgeschlagenen
    'schritt' tatsaechlich gilt: ein einzelner Schritt kann ueber die
    Editor-UI eigene "bei_fehler_override"/"sprung_ziel_override"-Werte
    tragen (siehe aktion_editor._fehler_override_feld()), die das fuer den
    GESAMTEN Ablauf gewaehlte Verhalten NUR fuer diesen einen Schritt
    ueberschreiben. Kein/leerer Override -> das ambiente (Skript- bzw.
    Schleifen-/Pfad-weite) bei_fehler/sprung_ziel gilt unveraendert."""
    override = (schritt.get("bei_fehler_override") or "").strip()
    if override:
        return override, schritt.get("sprung_ziel_override", sprung_ziel)
    return bei_fehler, sprung_ziel


def _schritte_ausfuehren(schritte, maus, bei_fehler, log, status, tiefe=0,
                          dispatcher=None, prioritaet="MITTEL", stop_event=None,
                          sprung_ziel=None, waechter=None, fenster_provider=None):
    """Interne rekursive Kernschleife hinter skript_ausfuehren(). tiefe>0
    bedeutet: wir befinden uns innerhalb eines gewaehlten GEWICHTET-Pfads
    ODER innerhalb eines SCHLEIFE_START/SCHLEIFE_ENDE-Koerpers (siehe
    _gewichtet_schritt()/die SCHLEIFE_START-Behandlung unten). status wird
    dabei bewusst nicht mehr durchgereicht (bleibt None) - eine "aktueller
    Schritt"-Anzeige fuer verschachtelte Ablaeufe wuerde ein eigenes
    Indexierungsschema fuer die GUI brauchen, das hier nicht benoetigt wird.

    dispatcher/prioritaet/stop_event/waechter: siehe schritt_ausfuehren() -
    werden unveraendert an jeden Schritt durchgereicht.

    waechter: siehe skript_ausfuehren() - wird VOR jedem Schritt geprueft
    (siehe pruefen_und_zuruecksetzen()); loest er aus, wird UNABHAENGIG vom
    aktuellen Schritt/dessen bei_fehler-Verhalten sofort zu dessen
    sprung_ziel gesprungen (das ist der ganze Sinn dieser Funktion - im
    Gegensatz zu einem bei_fehler_override, der nur bei einem tatsaechlich
    fehlgeschlagenen Schritt greift).

    sprung_ziel: nur relevant, wenn bei_fehler == "SPRUNG" (siehe
    skript_ausfuehren()) - bei einem fehlgeschlagenen Schritt wird NICHT
    abgebrochen und NICHT einfach zum naechsten Schritt weitergegangen,
    sondern zu _sprung_ziel_index(sprung_ziel, len(schritte)) gesprungen
    (bezogen auf DIESE, ggf. verschachtelte Schritt-Liste - ein Sprung
    innerhalb eines SCHLEIFE-Koerpers bleibt z.B. innerhalb dieses Koerpers).

    SCHLEIFE_START/SCHLEIFE_ENDE sind Marker-Schritte statt eigener,
    verschachtelter Objekte (im Gegensatz zu GEWICHTET): alle Schritte
    ZWISCHEN einem SCHLEIFE_START und seinem passenden SCHLEIFE_ENDE (siehe
    _passendes_schleifen_ende()) bilden den Schleifenkoerper und werden
    'wiederholungen'-mal (oder endlos, siehe SCHLEIFE_START-Parameter)
    erneut ausgefuehrt, bevor es NACH dem SCHLEIFE_ENDE weitergeht - daher
    ein index-basiertes while statt eines einfachen for, das den Index nach
    einem Schleifenblock ueberspringen (statt ihn linear durchzuzaehlen)
    muss."""
    ev = _stop_event_aufloesen(stop_event)
    gesamt = len(schritte)
    index = 0
    while index < gesamt:
        schritt = schritte[index]
        anzeige = index + 1
        aktion = schritt.get("aktion")

        if ev.is_set():
            log("Ablauf gestoppt vor Schritt %d/%d" % (anzeige, gesamt))
            return "GESTOPPT"

        if waechter is not None and waechter.pruefen_und_zuruecksetzen():
            index = _sprung_ziel_index(waechter.sprung_ziel, gesamt)
            log("  Bild-Waechter ('%s') ausgeloest - Springe zu Schritt %d/%d" %
                (waechter.bild, index + 1, gesamt))
            continue

        if aktion == "SCHLEIFE_START":
            ende_index = _passendes_schleifen_ende(schritte, index)
            if ende_index is None:
                log("  FEHLER bei Schritt %d: SCHLEIFE_START ohne passendes SCHLEIFE_ENDE" % anzeige)
                if bei_fehler == "ABBRECHEN":
                    log("Ablauf abgebrochen (bei_fehler=ABBRECHEN).")
                    return "ABGEBROCHEN"
                index += 1
                continue

            p = schritt.get("parameter", {})
            endlos = bool(p.get("endlos"))
            wiederholungen = max(0, int(p.get("wiederholungen", 1) or 0))
            koerper = schritte[index + 1:ende_index]

            if status:
                status(anzeige, gesamt, schritt)
            log("Schritt %d/%d: %s" % (anzeige, gesamt, schritt_beschreibung(schritt)))

            durchlauf = 0
            while endlos or durchlauf < wiederholungen:
                if ev.is_set():
                    log("Ablauf gestoppt in Schleife (Durchlauf %d)" % (durchlauf + 1))
                    return "GESTOPPT"
                durchlauf += 1
                log("  Schleifen-Durchlauf %d%s" % (durchlauf, "" if endlos else "/%d" % wiederholungen))
                ergebnis = _schritte_ausfuehren(
                    koerper, maus, bei_fehler, log, status=None, tiefe=tiefe + 1,
                    dispatcher=dispatcher, prioritaet=prioritaet, stop_event=ev,
                    sprung_ziel=sprung_ziel, waechter=waechter, fenster_provider=fenster_provider)
                if ergebnis in ("GESTOPPT", "ABGEBROCHEN"):
                    return ergebnis

            index = ende_index + 1
            continue

        if aktion == "SCHLEIFE_ENDE":
            # Nur erreichbar, wenn kein passendes SCHLEIFE_START existierte
            # (Bedienfehler im Editor - Markerpaar wurde nicht symmetrisch
            # bearbeitet) - als No-Op ueberspringen statt abzubrechen.
            index += 1
            continue

        if status:
            status(anzeige, gesamt, schritt)
        beschreibung = schritt_beschreibung(schritt)
        log("Schritt %d/%d: %s" % (anzeige, gesamt, beschreibung))

        try:
            schritt_ausfuehren(schritt, maus, bei_fehler=bei_fehler, log=log, tiefe=tiefe,
                                dispatcher=dispatcher, prioritaet=prioritaet, stop_event=ev,
                                sprung_ziel=sprung_ziel, waechter=waechter, fenster_provider=fenster_provider)
        except SchrittFehler as e:
            log("  FEHLER bei Schritt %d (%s): %s" % (anzeige, beschreibung, e))
            eff_bei_fehler, eff_sprung_ziel = _effektives_fehlerverhalten(schritt, bei_fehler, sprung_ziel)
            if eff_bei_fehler == "ABBRECHEN":
                log("Ablauf abgebrochen (bei_fehler=ABBRECHEN).")
                return "ABGEBROCHEN"
            if eff_bei_fehler == "SPRUNG":
                index = _sprung_ziel_index(eff_sprung_ziel, gesamt)
                log("  Springe zu Schritt %d/%d" % (index + 1, gesamt))
                continue
        except Exception as e:
            log("  UNERWARTETER FEHLER bei Schritt %d (%s): %s" % (anzeige, beschreibung, e))
            eff_bei_fehler, eff_sprung_ziel = _effektives_fehlerverhalten(schritt, bei_fehler, sprung_ziel)
            if eff_bei_fehler == "ABBRECHEN":
                log("Ablauf abgebrochen (bei_fehler=ABBRECHEN).")
                return "ABGEBROCHEN"
            if eff_bei_fehler == "SPRUNG":
                index = _sprung_ziel_index(eff_sprung_ziel, gesamt)
                log("  Springe zu Schritt %d/%d" % (index + 1, gesamt))
                continue

        if ev.is_set():
            log("Ablauf gestoppt nach Schritt %d/%d" % (anzeige, gesamt))
            return "GESTOPPT"

        index += 1

    log("Ablauf abgeschlossen (%d Schritte)." % gesamt)
    return "FERTIG"


def skript_ausfuehren(schritte, maus, bei_fehler="ABBRECHEN", log=print, status=None,
                       dispatcher=None, prioritaet="MITTEL", stop_event=None, sprung_ziel=None,
                       waechter_bild=None, waechter_sprung_ziel=None, waechter_cooldown=5.0,
                       waechter_variante=None, waechter_schwelle=None, fenster_provider=None):
    """Fuehrt eine Schritt-Liste sequenziell aus (blockierend - vom Aufrufer
    in einem eigenen Thread zu starten).

    Args:
        schritte: Liste von Schritt-Dicts (siehe neuer_schritt()).
        maus: bereits verbundene HIDMaus-Instanz.
        bei_fehler: "ABBRECHEN" (Standard), "WEITER" oder "SPRUNG" -
            Verhalten, wenn ein Schritt eine SchrittFehler auswirft.
            "SPRUNG" springt zu 'sprung_ziel' statt abzubrechen oder einfach
            zum naechsten Schritt weiterzugehen.
        log: Callable(str), fuer jede Log-Zeile aufgerufen.
        status: optionales Callable(index_ab_1, gesamt, schritt), vor jedem
            Schritt aufgerufen (fuer eine "aktueller Schritt"-Anzeige).
        dispatcher: optionale maus_dispatcher.MausDispatcher-Instanz - siehe
            schritt_ausfuehren()-Docstring. None (Standard) = bisheriges
            Verhalten, kein Lock, direkte Ausfuehrung (Einzel-Skript ueber
            aktion_editor.py bleibt dadurch unveraendert).
        prioritaet: siehe maus_dispatcher.PRIORITAET_* - nur relevant, wenn
            dispatcher gegeben ist.
        stop_event: optionales eigenes threading.Event fuer diesen Ablauf
            (siehe makro_manager.py - jedes parallele Makro bekommt sein
            EIGENES Event, damit stoppe_makro() nur DIESES eine stoppt,
            nicht alle). None (Standard) nutzt weiterhin das globale
            _stop_event/ausfuehrung_stoppen() wie bisher - in dem Fall wird
            es hier wie gehabt zurueckgesetzt (bei einem selbst uebergebenen
            stop_event bleibt dessen Zustand unangetastet, das verwaltet der
            Aufrufer selbst, siehe makro_manager.MakroManager).
        sprung_ziel: nur relevant, wenn bei_fehler=="SPRUNG" - 1-basierte
            Schrittnummer, zu der bei einem Fehler gesprungen wird
            (None/""/"ANFANG"/<=1 = Schritt 1, siehe _sprung_ziel_index()).
            Werte ausserhalb des gueltigen Bereichs werden begrenzt statt
            einen Fehler auszuloesen.
        waechter_bild: optionaler Bildname (siehe bild_erkennung.
            verfuegbare_bilder()) - ist er gesetzt, laeuft waehrend der
            GESAMTEN Ausfuehrung (unabhaengig von tiefe/aktuellem Schritt,
            auch innerhalb von Schleifen/GEWICHTET-Pfaden) im Hintergrund ein
            BildWaechter mit, der bei ERSCHEINEN dieses Bildes zu
            'waechter_sprung_ziel' springt - GENAU dann, wenn der naechste
            Schritt an der Reihe waere (siehe _schritte_ausfuehren()), NICHT
            erst bei einem fehlgeschlagenen Schritt (im Gegensatz zu
            bei_fehler_override). None (Standard) = kein Waechter, bisheriges
            Verhalten unveraendert.
        waechter_sprung_ziel: 1-basierte Schrittnummer (siehe sprung_ziel),
            zu der der Waechter bei einem Treffer springt.
        waechter_cooldown: Sekunden, die NACH einem Treffer mindestens
            vergehen muessen, bevor der Waechter erneut auf das Bild prueft -
            verhindert, dass ein weiterhin sichtbares Bild sofort wieder
            denselben Sprung ausloest (Standard 5.0s).
        waechter_variante/waechter_schwelle: siehe bild_erkennung.
            bild_pruefen() - optional, None nutzt die dortigen Standardwerte.
        fenster_provider: siehe schritt_ausfuehren()-Docstring - isoliert die
            GESAMTE Ausfuehrung (inkl. Bild-Waechter oben) auf ein einzelnes
            METIN2-Fenster, statt (Standard, None) wie bisher das erste per
            Titel gefundene Fenster zu verwenden (siehe modules.fenster.
            alle_spielfenster_finden()/fenster_von_hwnd() und makro_manager.py:
            starte_makro(..., fenster_hwnd=...)).

    Returns:
        str: "FERTIG" | "ABGEBROCHEN" (Fehler + bei_fehler=ABBRECHEN) |
             "GESTOPPT" (ausfuehrung_stoppen()/eigenes stop_event wurde
             gesetzt)
    """
    if stop_event is None:
        _stop_event.clear()
    ev = _stop_event_aufloesen(stop_event)

    waechter = None
    if waechter_bild:
        waechter = BildWaechter(waechter_bild, waechter_sprung_ziel, cooldown=waechter_cooldown,
                                 variante=waechter_variante, schwelle=waechter_schwelle,
                                 fenster_provider=fenster_provider)
        waechter.start()
    try:
        return _schritte_ausfuehren(schritte, maus, bei_fehler, log, status, tiefe=0,
                                     dispatcher=dispatcher, prioritaet=prioritaet, stop_event=ev,
                                     sprung_ziel=sprung_ziel, waechter=waechter,
                                     fenster_provider=fenster_provider)
    finally:
        if waechter is not None:
            waechter.stoppen()
