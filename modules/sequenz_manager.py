# -*- coding: utf-8 -*-
"""sequenz_manager.py - Sequenz-Engine fuer das Automation Command Center.

Eine *Sequenz* ist eine geordnete Liste von *Schritten*. Jeder Schritt ist
einer von drei Typen:

    TRIGGER  -- wartet, bis ein Pixel-Trigger (trigger_<name>.json) erfuellt ist
    ABLAUF   -- spielt eine aufgenommene Klick-/Tasten-Folge (ablauf_<name>.json)
    WARTEN   -- wartet einfach eine feste Zeit (+ Zufall)

Schritte koennen bei Fehler zu einem anderen Schritt springen (Goto).
Sequenzen laufen einmal, X-mal oder endlos. Der Ablauf laeuft in einem
Hintergrund-Thread und kann pausiert, weich gestoppt (Soft-Stop) oder hart
abgebrochen werden (Not-Aus / Hard-Stop) - beides ueber threading.Event.

Datenformate (kompatibel zu command_center.py):
    trigger_<name>.json : {"pixel": [{"x", "y", "farbe": "#rrggbb"}], ...}
    ablauf_<name>.json  : {"events": [{"typ","x","y","zeit_bis_naechster_ms",
                                       "zufall_ms","pixel_unscharfe","key"}], ...}
    sequenz_<name>.json : siehe Sequenz.to_dict()
"""

import os
import json
import time
import random
import threading
from datetime import datetime

try:
    from .statistic_manager import StatistikManager
except ImportError:  # Standalone-Import (ohne Package)
    from statistic_manager import StatistikManager

try:
    from .fenster import fenster_finden as _fenster_finden
except ImportError:
    try:
        from fenster import fenster_finden as _fenster_finden
    except ImportError:
        def _fenster_finden(titel):  # Fallback ohne Fenster-Modul
            return None

# Projekt-Hauptordner (eine Ebene ueber modules/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Trigger-Standardwerte (laut Spezifikation)
TRIGGER_TOLERANZ = 10     # Farbtoleranz pro Kanal (0..255)
TRIGGER_TIMEOUT = 60      # Sekunden, danach gilt der Trigger als fehlgeschlagen

# Schritt-Typen
TYP_TRIGGER = "TRIGGER"
TYP_ABLAUF = "ABLAUF"
TYP_WARTEN = "WARTEN"
SCHRITT_TYPEN = [TYP_TRIGGER, TYP_ABLAUF, TYP_WARTEN]


class _Abbruch(Exception):
    """Intern: Soft-Stop oder Hard-Stop wurde ausgeloest."""


class _SchrittFehler(Exception):
    """Intern: Ein Schritt ist fehlgeschlagen und es gibt kein Goto-Ziel."""


# =====================================================================
#  Datenmodell
# =====================================================================
class SequenzSchritt:
    """Ein einzelner Schritt einer Sequenz."""

    def __init__(self, typ=TYP_WARTEN, name="", wert="",
                 warte_ms=0, zufall_ms=0, goto_step=-1, goto_bedingung="fehler"):
        self.typ = (typ or TYP_WARTEN).upper()
        self.name = name or ""          # Anzeigename (i.d.R. == wert)
        self.wert = wert or ""          # Ressourcen-Name (Trigger-/Ablauf-Name)
        self.warte_ms = int(warte_ms or 0)
        self.zufall_ms = int(zufall_ms or 0)
        # Ziel-Index (0-basiert) fuer Goto; -1 == kein Sprung
        self.goto_step = int(goto_step if goto_step is not None else -1)
        self.goto_bedingung = goto_bedingung or "fehler"

    def to_dict(self):
        return {
            "typ": self.typ,
            "name": self.name,
            "wert": self.wert,
            "warte_ms": self.warte_ms,
            "zufall_ms": self.zufall_ms,
            "goto_step": self.goto_step,
            "goto_bedingung": self.goto_bedingung,
        }

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(
            typ=d.get("typ", TYP_WARTEN),
            name=d.get("name", ""),
            wert=d.get("wert", d.get("name", "")),
            warte_ms=d.get("warte_ms", 0),
            zufall_ms=d.get("zufall_ms", 0),
            goto_step=d.get("goto_step", -1),
            goto_bedingung=d.get("goto_bedingung", "fehler"),
        )

    def kurz(self):
        """Kompakte Beschreibung fuer Listen-Anzeige."""
        ziel = self.wert or self.name or "-"
        if self.typ == TYP_WARTEN:
            return "WARTEN"
        return "%s: %s" % (self.typ, ziel)


class Sequenz:
    """Eine benannte, geordnete Liste von Schritten mit Schleifen-Einstellung."""

    def __init__(self, name="", schritte=None,
                 schleife_endlos=False, schleife_x=1,
                 erstellt=None, geaendert=None):
        self.name = name
        self.schritte = schritte or []
        self.schleife_endlos = bool(schleife_endlos)
        self.schleife_x = max(1, int(schleife_x or 1))
        self.erstellt = erstellt
        self.geaendert = geaendert

    # ---------- Serialisierung ----------
    def to_dict(self):
        return {
            "name": self.name,
            "schleife_endlos": self.schleife_endlos,
            "schleife_x": self.schleife_x,
            "erstellt": self.erstellt,
            "geaendert": self.geaendert,
            "schritte": [s.to_dict() for s in self.schritte],
        }

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        schritte = [SequenzSchritt.from_dict(s) for s in d.get("schritte", [])]
        return cls(
            name=d.get("name", ""),
            schritte=schritte,
            schleife_endlos=d.get("schleife_endlos", False),
            schleife_x=d.get("schleife_x", 1),
            erstellt=d.get("erstellt"),
            geaendert=d.get("geaendert"),
        )

    # ---------- Schritt-Manipulation ----------
    def hinzufuegen(self, schritt, index=None):
        if index is None or index < 0 or index > len(self.schritte):
            self.schritte.append(schritt)
        else:
            self.schritte.insert(index, schritt)

    def entfernen(self, index):
        if 0 <= index < len(self.schritte):
            return self.schritte.pop(index)
        return None

    def verschieben(self, index, richtung):
        """Verschiebt einen Schritt um +/-1. Gibt den neuen Index zurueck."""
        neu = index + richtung
        if 0 <= index < len(self.schritte) and 0 <= neu < len(self.schritte):
            self.schritte[index], self.schritte[neu] = \
                self.schritte[neu], self.schritte[index]
            return neu
        return index

    # ---------- Info ----------
    def geschaetzte_dauer_s(self):
        """Grobe Schaetzung der Wartezeit-Summe in Sekunden.

        Trigger-Wartezeiten und Ablauf-Laengen sind variabel und werden hier
        nur ueber die konfigurierten Wartezeiten (warte_ms + halber Zufall)
        beruecksichtigt.
        """
        gesamt_ms = 0
        for s in self.schritte:
            gesamt_ms += s.warte_ms + s.zufall_ms / 2.0
        return gesamt_ms / 1000.0


# =====================================================================
#  Engine
# =====================================================================
class SequenzManager:
    """Laedt/speichert Sequenzen und fuehrt sie in einem Thread aus."""

    def __init__(self, basis_dir=None, log_callback=None, status_callback=None):
        self.basis_dir = basis_dir or BASE_DIR
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.stats = StatistikManager(self.basis_dir)

        # Steuer-Events
        self._soft_stop = threading.Event()   # nach aktuellem Schritt anhalten
        self._hard_stop = threading.Event()   # sofort abbrechen (Not-Aus)
        self._pause = threading.Event()        # gesetzt == laeuft, geloescht == pausiert
        self._pause.set()

        self._thread = None
        self.laeuft = False
        self.pausiert = False

    # ---------- Logging / Status ----------
    def _log(self, msg):
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass
        else:
            print(msg)

    def _status(self, name, schritt_idx, gesamt, durchlauf):
        if self.status_callback:
            try:
                self.status_callback(name, schritt_idx, gesamt, durchlauf)
            except Exception:
                pass

    # =================================================================
    #  Datei-Zugriff
    # =================================================================
    def get_sequenz_dateien(self):
        try:
            dateien = os.listdir(self.basis_dir)
        except OSError:
            return []
        return sorted(f for f in dateien
                      if f.startswith("sequenz_") and f.endswith(".json"))

    def get_sequenz_namen(self):
        return [f[len("sequenz_"):-len(".json")]
                for f in self.get_sequenz_dateien()]

    def get_trigger_namen(self):
        try:
            dateien = os.listdir(self.basis_dir)
        except OSError:
            return []
        return sorted(f[len("trigger_"):-len(".json")] for f in dateien
                      if f.startswith("trigger_") and f.endswith(".json"))

    def get_ablauf_namen(self):
        try:
            dateien = os.listdir(self.basis_dir)
        except OSError:
            return []
        return sorted(f[len("ablauf_"):-len(".json")] for f in dateien
                      if f.startswith("ablauf_") and f.endswith(".json"))

    def _sequenz_pfad(self, name):
        return os.path.join(self.basis_dir, "sequenz_%s.json" % name)

    def laden(self, name):
        pfad = self._sequenz_pfad(name)
        if not os.path.exists(pfad):
            self._log("Sequenz nicht gefunden: %s" % name)
            return None
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                daten = json.load(f)
            seq = Sequenz.from_dict(daten)
            if not seq.name:
                seq.name = name
            return seq
        except Exception as e:
            self._log("Fehler beim Laden von '%s': %s" % (name, e))
            return None

    def speichern(self, sequenz):
        if not sequenz.name:
            self._log("Sequenz hat keinen Namen - nicht gespeichert.")
            return False
        jetzt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not sequenz.erstellt:
            sequenz.erstellt = jetzt
        sequenz.geaendert = jetzt
        pfad = self._sequenz_pfad(sequenz.name)
        try:
            with open(pfad, "w", encoding="utf-8") as f:
                json.dump(sequenz.to_dict(), f, indent=2, ensure_ascii=False)
            self._log("Sequenz gespeichert: %s" % sequenz.name)
            return True
        except Exception as e:
            self._log("Fehler beim Speichern von '%s': %s" % (sequenz.name, e))
            return False

    def loeschen(self, name):
        pfad = self._sequenz_pfad(name)
        if os.path.exists(pfad):
            try:
                os.remove(pfad)
                self._log("Sequenz geloescht: %s" % name)
                return True
            except OSError as e:
                self._log("Fehler beim Loeschen: %s" % e)
        return False

    # =================================================================
    #  Ausfuehrung (Thread-Steuerung)
    # =================================================================
    def start(self, sequenz):
        if self._thread and self._thread.is_alive():
            self._log("Es laeuft bereits eine Sequenz.")
            return False
        if not sequenz or not sequenz.schritte:
            self._log("Sequenz ist leer - nichts zu tun.")
            return False
        self._soft_stop.clear()
        self._hard_stop.clear()
        self._pause.set()
        self.laeuft = True
        self.pausiert = False
        self._thread = threading.Thread(
            target=self._ausfuehren, args=(sequenz,), daemon=True)
        self._thread.start()
        return True

    def stop(self, hart=False):
        """Weicher Stop (nach aktuellem Schritt) oder harter Not-Aus."""
        if hart:
            self._hard_stop.set()
            self._log("NOT-AUS ausgeloest - Sequenz wird sofort abgebrochen.")
        else:
            self._soft_stop.set()
            self._log("Stop angefordert - Sequenz haelt nach aktuellem Schritt an.")
        # Falls pausiert: aufwecken, damit der Thread den Stop sieht.
        self._pause.set()

    def not_aus(self):
        self.stop(hart=True)

    def pause(self):
        """Umschalten zwischen Pause und Weiter."""
        if not self.laeuft:
            return
        if self._pause.is_set():
            self._pause.clear()
            self.pausiert = True
            self._log("Sequenz pausiert.")
        else:
            self._pause.set()
            self.pausiert = False
            self._log("Sequenz fortgesetzt.")

    def ist_aktiv(self):
        return bool(self._thread and self._thread.is_alive())

    # ---------- interne Wartepunkte ----------
    def _abbruch_pruefen(self):
        if self._hard_stop.is_set() or self._soft_stop.is_set():
            raise _Abbruch()

    def _pause_pruefen(self):
        """Blockiert, solange pausiert - bricht bei Stop sauber ab."""
        while not self._pause.is_set():
            if self._hard_stop.is_set() or self._soft_stop.is_set():
                raise _Abbruch()
            time.sleep(0.05)

    def _schlaf(self, dauer_s):
        """Schlaeft in kleinen Schritten und reagiert auf Hard-Stop/Pause."""
        ende = time.time() + max(0.0, dauer_s)
        while time.time() < ende:
            if self._hard_stop.is_set():
                raise _Abbruch()
            self._pause_pruefen()
            time.sleep(min(0.05, ende - time.time()))

    # =================================================================
    #  Ausfuehrungs-Logik
    # =================================================================
    def _ausfuehren(self, sequenz):
        start_zeit = time.time()
        erfolg = True
        status_text = "ok"
        self._log("=== Sequenz '%s' gestartet ===" % sequenz.name)
        try:
            durchlauf = 0
            while True:
                durchlauf += 1
                if not sequenz.schleife_endlos and durchlauf > sequenz.schleife_x:
                    break
                if sequenz.schleife_endlos:
                    self._log("--- Durchlauf %d (endlos) ---" % durchlauf)
                else:
                    self._log("--- Durchlauf %d / %d ---"
                              % (durchlauf, sequenz.schleife_x))

                i = 0
                while i < len(sequenz.schritte):
                    self._abbruch_pruefen()
                    self._pause_pruefen()
                    schritt = sequenz.schritte[i]
                    self._status(sequenz.name, i + 1,
                                 len(sequenz.schritte), durchlauf)
                    ok = self._schritt_ausfuehren(schritt, i)
                    self._abbruch_pruefen()
                    if ok:
                        i += 1
                    else:
                        # Fehlerbehandlung: Goto-Sprung oder Abbruch
                        if 0 <= schritt.goto_step < len(sequenz.schritte):
                            self._log("Schritt %d fehlgeschlagen -> springe zu "
                                      "Schritt %d" % (i + 1, schritt.goto_step + 1))
                            i = schritt.goto_step
                        else:
                            raise _SchrittFehler(
                                "Schritt %d (%s) fehlgeschlagen"
                                % (i + 1, schritt.typ))
        except _Abbruch:
            erfolg = False
            status_text = "not-aus" if self._hard_stop.is_set() else "gestoppt"
            self._log("Sequenz abgebrochen (%s)." % status_text)
        except _SchrittFehler as e:
            erfolg = False
            status_text = str(e)
            self._log("Sequenz fehlgeschlagen: %s" % e)
        except Exception as e:  # unerwartet - defensiv abfangen
            erfolg = False
            status_text = "fehler: %s" % e
            self._log("Unerwarteter Fehler: %s" % e)
        finally:
            dauer = time.time() - start_zeit
            if erfolg:
                self._log("=== Sequenz '%s' erfolgreich beendet (%.1fs) ==="
                          % (sequenz.name, dauer))
            try:
                self.stats.update_stats(sequenz.name, erfolg,
                                        dauer_s=dauer, status=status_text)
            except Exception:
                pass
            self.laeuft = False
            self.pausiert = False
            self._soft_stop.clear()
            self._hard_stop.clear()
            self._pause.set()
            # Status-Callback mit Abschluss-Signal (Durchlauf 0 = Ende)
            self._status(sequenz.name, 0, len(sequenz.schritte), 0)

    def _schritt_ausfuehren(self, schritt, index):
        """Fuehrt einen einzelnen Schritt aus. True == Erfolg."""
        ziel = schritt.wert or schritt.name
        if schritt.typ == TYP_TRIGGER:
            self._log("Schritt %d TRIGGER: warte auf '%s' ..." % (index + 1, ziel))
            ok = self._warte_auf_trigger(ziel)
        elif schritt.typ == TYP_ABLAUF:
            self._log("Schritt %d ABLAUF: spiele '%s' ..." % (index + 1, ziel))
            ok = self._spiele_ablauf(ziel)
        elif schritt.typ == TYP_WARTEN:
            self._log("Schritt %d WARTEN ..." % (index + 1))
            ok = True
        else:
            self._log("Schritt %d: unbekannter Typ '%s' - uebersprungen."
                      % (index + 1, schritt.typ))
            ok = True

        # Wartezeit nach dem Schritt (nur bei Erfolg)
        if ok:
            self._warte(schritt.warte_ms, schritt.zufall_ms)
        return ok

    # ---------- Schritt-Typ: WARTEN ----------
    def _warte(self, warte_ms, zufall_ms):
        gesamt_ms = int(warte_ms or 0)
        if zufall_ms and zufall_ms > 0:
            gesamt_ms += random.randint(0, int(zufall_ms))
        if gesamt_ms > 0:
            self._schlaf(gesamt_ms / 1000.0)

    # ---------- Schritt-Typ: TRIGGER ----------
    def _farbe_zu_rgb(self, farbe):
        """Wandelt "#rrggbb" oder [r,g,b] in ein (r,g,b)-Tupel."""
        if isinstance(farbe, str):
            h = farbe.lstrip("#")
            if len(h) >= 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        if isinstance(farbe, (list, tuple)) and len(farbe) >= 3:
            return (int(farbe[0]), int(farbe[1]), int(farbe[2]))
        return (0, 0, 0)

    def _lade_trigger_pixel(self, trigger_name):
        pfad = os.path.join(self.basis_dir, "trigger_%s.json" % trigger_name)
        if not os.path.exists(pfad):
            self._log("Trigger-Datei fehlt: trigger_%s.json" % trigger_name)
            return None
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                daten = json.load(f)
        except Exception as e:
            self._log("Trigger '%s' Ladefehler: %s" % (trigger_name, e))
            return None
        pixel = []
        for p in daten.get("pixel", []):
            pixel.append((int(p["x"]), int(p["y"]),
                          self._farbe_zu_rgb(p.get("farbe"))))
        return pixel

    def _warte_auf_trigger(self, trigger_name, timeout=TRIGGER_TIMEOUT):
        pixel = self._lade_trigger_pixel(trigger_name)
        if pixel is None:
            return False
        if not pixel:
            self._log("Trigger '%s' hat keine Pixel." % trigger_name)
            return False
        try:
            import pyautogui
        except ImportError:
            self._log("pyautogui nicht installiert - Trigger nicht pruefbar.")
            return False

        start = time.time()
        while True:
            if self._hard_stop.is_set() or self._soft_stop.is_set():
                raise _Abbruch()
            self._pause_pruefen()
            if self._pixel_passen(pixel, pyautogui):
                self._log("Trigger '%s' erfuellt." % trigger_name)
                return True
            if time.time() - start > timeout:
                self._log("Trigger '%s' Timeout nach %ds."
                          % (trigger_name, timeout))
                return False
            time.sleep(0.1)

    def _pixel_passen(self, pixel, pyautogui):
        for x, y, (r2, g2, b2) in pixel:
            try:
                r1, g1, b1 = pyautogui.pixel(x, y)
            except Exception:
                return False
            if (abs(r1 - r2) > TRIGGER_TOLERANZ or
                    abs(g1 - g2) > TRIGGER_TOLERANZ or
                    abs(b1 - b2) > TRIGGER_TOLERANZ):
                return False
        return True

    # ---------- Schritt-Typ: ABLAUF ----------
    def _spiele_ablauf(self, ablauf_name):
        pfad = os.path.join(self.basis_dir, "ablauf_%s.json" % ablauf_name)
        if not os.path.exists(pfad):
            self._log("Ablauf-Datei fehlt: ablauf_%s.json" % ablauf_name)
            return False
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                daten = json.load(f)
            events = daten if isinstance(daten, list) else daten.get("events", [])
        except Exception as e:
            self._log("Ablauf '%s' Ladefehler: %s" % (ablauf_name, e))
            return False
        if not events:
            self._log("Ablauf '%s' hat keine Events." % ablauf_name)
            return False

        try:
            import pyautogui
        except ImportError:
            self._log("pyautogui nicht installiert - Ablauf nicht spielbar.")
            return False

        # Fenster-relative Basis bestimmen
        base_x, base_y = 0, 0
        if (isinstance(daten, dict) and daten.get("fenster_relativ")
                and isinstance(daten.get("fenster"), dict)):
            finfo = daten["fenster"]
            win = _fenster_finden(finfo.get("titel"))
            if win:
                base_x, base_y = win["x"], win["y"]
                self._log("Fenster '%s' gefunden @ %d,%d." % (finfo.get("titel"), base_x, base_y))
            else:
                base_x, base_y = finfo.get("x", 0), finfo.get("y", 0)
                self._log("Fenster '%s' nicht gefunden - nutze Aufnahme-Position." % finfo.get("titel"))

        try:
            for i, ev in enumerate(events):
                if self._hard_stop.is_set() or self._soft_stop.is_set():
                    raise _Abbruch()
                self._pause_pruefen()

                typ = (ev.get("typ") or ev.get("type") or "").lower()
                x = base_x + ev.get("x", 0)
                y = base_y + ev.get("y", 0)

                unscharf = ev.get("pixel_unscharfe", 0)
                if unscharf and unscharf > 0:
                    x += random.randint(-unscharf, unscharf)
                    y += random.randint(-unscharf, unscharf)

                if typ in ("move", "mousemove"):
                    pyautogui.moveTo(x, y)
                elif typ in ("click", "klick"):
                    pyautogui.click(x, y)
                elif typ in ("ldown", "mousedown"):
                    pyautogui.mouseDown(x, y)
                elif typ in ("lup", "mouseup"):
                    pyautogui.mouseUp(x, y)
                elif typ in ("key", "taste"):
                    taste = ev.get("key") or ev.get("taste")
                    if taste:
                        pyautogui.press(str(taste))

                # Wartezeit bis zum naechsten Event
                if i < len(events) - 1:
                    feste_ms = ev.get("zeit_bis_naechster_ms",
                                      ev.get("delay", 0))
                    zufall_ms = ev.get("zufall_ms", 0)
                    gesamt_ms = feste_ms + (random.randint(0, zufall_ms)
                                            if zufall_ms > 0 else 0)
                    if gesamt_ms > 0:
                        self._schlaf(gesamt_ms / 1000.0)
            return True
        except _Abbruch:
            raise
        except Exception as e:
            self._log("Fehler beim Abspielen von '%s': %s" % (ablauf_name, e))
            return False


# =====================================================================
#  Pool: mehrere Sequenzen gleichzeitig laufen lassen
# =====================================================================
class SequenzPool:
    """Verwaltet beliebig viele parallel laufende Sequenzen.

    Jeder Lauf bekommt eine eigene ID und einen eigenen SequenzManager
    (mit eigenem Thread, Pause- und Stop-Steuerung). Die Datei-Methoden
    (laden/speichern/...) bleiben beim einzelnen SequenzManager.

    Hinweis: Es gibt nur EINEN Mauszeiger - Sequenzen, die gleichzeitig
    klicken, stoeren sich physisch. Sinnvoll v.a. bei trigger-lastigen
    Sequenzen, die meist nur warten.
    """

    def __init__(self, basis_dir=None, log_callback=None, status_callback=None):
        self.basis_dir = basis_dir or BASE_DIR
        self.log_callback = log_callback
        # status_callback(run_id, name, schritt_idx, gesamt, durchlauf)
        self.status_callback = status_callback
        self._runs = {}       # run_id -> {"mgr": SequenzManager, "name": str}
        self._counter = 0

    def _log(self, rid, msg):
        if self.log_callback:
            try:
                self.log_callback("[#%d] %s" % (rid, msg))
            except Exception:
                pass

    def _status(self, rid, name, idx, gesamt, durchlauf):
        # Abschluss-Signal (idx==0 und durchlauf==0): Lauf entfernen
        if idx == 0 and durchlauf == 0:
            self._runs.pop(rid, None)
        if self.status_callback:
            try:
                self.status_callback(rid, name, idx, gesamt, durchlauf)
            except Exception:
                pass

    def start(self, sequenz):
        """Startet eine (Kopie der) Sequenz als neuen Lauf. Gibt run_id zurueck."""
        if not sequenz or not sequenz.schritte:
            return None
        self._counter += 1
        rid = self._counter
        # Tiefe Kopie, damit spaetere GUI-Aenderungen den Lauf nicht beeinflussen
        seq = Sequenz.from_dict(sequenz.to_dict())
        mgr = SequenzManager(
            self.basis_dir,
            log_callback=(lambda m, r=rid: self._log(r, m)),
            status_callback=(lambda n, i, g, d, r=rid: self._status(r, n, i, g, d)))
        if not mgr.start(seq):
            self._counter -= 1
            return None
        self._runs[rid] = {"mgr": mgr, "name": seq.name}
        return rid

    def pause(self, rid):
        r = self._runs.get(rid)
        if r:
            r["mgr"].pause()

    def stop(self, rid, hart=False):
        r = self._runs.get(rid)
        if r:
            r["mgr"].stop(hart=hart)

    def stop_all(self, hart=True):
        for r in list(self._runs.values()):
            r["mgr"].stop(hart=hart)

    def aktive(self):
        """Liste aktiver Laeufe: [{run_id, name, pausiert}] nach ID sortiert."""
        result = []
        for rid, v in sorted(self._runs.items()):
            result.append({"run_id": rid, "name": v["name"],
                           "pausiert": v["mgr"].pausiert})
        return result

    def anzahl(self):
        return len(self._runs)
