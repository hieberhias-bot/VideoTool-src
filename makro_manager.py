#!/usr/bin/env python3
"""makro_manager.py - Startet/verwaltet mehrere Bot-Skripte (aktion_*.json)
PARALLEL, je in einem eigenen Thread, mit Prioritaets-Arbitrierung der
gemeinsam genutzten HID-Maus (siehe maus_dispatcher.py) statt des bisherigen
"nur ein Ablauf gleichzeitig"-Verhaltens (aktion_editor.AktionsSkriptTab
bleibt davon unberuehrt - MakroManager ist ein ZUSAETZLICHER, paralleler
Weg, Skripte laufen zu lassen, kein Ersatz).

Jedes gestartete Makro bekommt sein EIGENES threading.Event als Stop-Signal
(siehe aktion_skript.skript_ausfuehren(stop_event=...)) - dadurch stoppt
stoppe_makro() gezielt nur EIN Makro, nicht alle gleichzeitig (im Gegensatz
zum globalen aktion_skript.ausfuehrung_stoppen(), das fuer die
Einzel-Skript-Ausfuehrung in aktion_editor.py gedacht ist und davon
unberuehrt bleibt).

Der Fisch-Bot (fish_bot.py) kann ueber fish_bot_starten() als eigenes,
hochpriorisiertes "Makro" parallel zu den Skripten laufen: siehe
DispatcherMaus, ein transparenter Wrapper um die echte HID-Maus, der jede
Maus-Aktion ueber denselben MausDispatcher arbitriert, den auch die Skripte
benutzen. fish_bot.py wurde inzwischen um einen FischBotKontext erweitert
(siehe dort), damit auch MEHRERE Fisch-Bot-Instanzen gleichzeitig laufen
koennen, je auf ein eigenes METIN2-Fenster isoliert (siehe
fischbot_starten_alle_fenster()) - analog zu starte_makro_alle_fenster() fuer
Bot-Skripte.
"""

import os
import threading
import time
import functools

import aktion_skript
import fish_bot
import modules.fenster as fenster_modul
from maus_dispatcher import MausDispatcher, PRIORITAET_HOCH, PRIORITAET_MITTEL

# Interner Schluessel fuer den Fisch-Bot in self._makros - "__"-umschlossen,
# damit er nicht mit einem echten Skriptnamen (aktion_<name>.json) kollidiert.
FISCHBOT_NAME = "__fischbot__"

# Trennzeichen zwischen Skriptname und Fenster-Label in einem Instanz-
# Schluessel (siehe starte_makro_alle_fenster()) - "::" statt z.B. "@", da
# Skriptnamen selbst schon Sonderzeichen enthalten koennen und "::" in der
# Praxis nie in einem per Editor vergebenen Skriptnamen vorkommt.
_INSTANZ_TRENNER = "::"


class MakroManagerFehler(Exception):
    """Wird ausgeloest bei ungueltigen Operationen (z.B. Skript nicht ladbar,
    Makro laeuft bereits, keine HID-Maus verbunden)."""


class DispatcherMaus:
    """Transparenter Wrapper um eine echte HIDMaus (oder ein Objekt mit
    derselben Schnittstelle): reicht alle Attribute/Methoden unveraendert an
    'maus' durch, haelt aber fuer die eigentlichen Maus-Aktionen
    (Klicks/Bewegen) den gemeinsamen MausDispatcher.

    Gedacht fuer Aufrufer, die selbst NICHTS vom Dispatcher wissen sollen
    (z.B. fish_bot.py - laut Aufgabenstellung nicht zu veraendern), aber
    trotzdem als priorisiertes Makro am gemeinsam genutzten COM-Port
    teilnehmen sollen (siehe MakroManager.fish_bot_starten()).
    """

    def __init__(self, maus, dispatcher, prioritaet=PRIORITAET_HOCH):
        self._maus = maus
        self._dispatcher = dispatcher
        self._prioritaet = prioritaet

    def __getattr__(self, name):
        # Greift nur, wenn 'name' NICHT als echte Methode unten definiert ist
        # (klick_links() etc. werden normal auf dieser Klasse gefunden und
        # landen nie hier) - alles andere (ping(), verbinden(), schliessen(),
        # taste_*() ...) geht 1:1 an die echte Maus durch.
        return getattr(self._maus, name)

    def _mit_dispatcher(self, methodenname, *args, **kwargs):
        if self._dispatcher is None:
            return getattr(self._maus, methodenname)(*args, **kwargs)
        self._dispatcher.maus_holen(self._prioritaet)
        try:
            return getattr(self._maus, methodenname)(*args, **kwargs)
        finally:
            self._dispatcher.maus_freigeben()

    def klick_links(self):
        return self._mit_dispatcher("klick_links")

    def klick_rechts(self):
        return self._mit_dispatcher("klick_rechts")

    def maus_bewegen(self, x, y):
        return self._mit_dispatcher("maus_bewegen", x, y)

    def maus_bewegen_abs(self, x, y):
        return self._mit_dispatcher("maus_bewegen_abs", x, y)

    def maus_ziehen(self, x, y):
        return self._mit_dispatcher("maus_ziehen", x, y)


class _LaufendesMakro:
    """Interner Zustand eines gestarteten Makros (Skript oder Fisch-Bot).

    'name' ist der (innerhalb von self._makros eindeutige) Instanz-
    Schluessel: fuer eine einzelne, nicht fenster-isolierte Ausfuehrung
    identisch mit basis_name (dem Skriptnamen); bei Mehrfenster-Fan-out
    (siehe starte_makro_alle_fenster()) enthaelt er zusaetzlich ein
    Fenster-Label (z.B. "mein_skript::Fenster 2"), waehrend basis_name
    weiterhin nur "mein_skript" ist - dadurch koennen mehrere Instanzen
    DESSELBEN Skripts gleichzeitig in self._makros stehen."""

    def __init__(self, name, prioritaet, stop_event, basis_name=None, fenster_label=None):
        self.name = name
        self.basis_name = basis_name if basis_name is not None else name
        self.fenster_label = fenster_label   # z.B. "Fenster 2" oder None ("Alle Fenster"/kein Fan-out)
        self.prioritaet = prioritaet
        self.thread = None
        self.stop_event = stop_event
        self.status = "LAEUFT"     # LAEUFT | FERTIG | ABGEBROCHEN | GESTOPPT | FEHLER | VERBINDUNGSFEHLER
        self.gestartet_um = time.time()
        self.beendet_um = None
        self.fehler = None


class MakroManager:
    """Verwaltet parallel laufende Bot-Skripte + optional den Fisch-Bot -
    alle teilen sich EINE HID-Maus-Verbindung ueber einen gemeinsamen
    MausDispatcher (siehe maus_dispatcher.py).

    Args:
        maus_getter: Callable[[], HIDMaus|None] - liefert die aktuell
            verbundene HID-Maus (gleiches Muster wie
            aktion_editor.AktionsSkriptTab). Default liefert immer None -
            macht die Klasse ohne Argumente konstruierbar/testbar; ein
            echter starte_makro()-Aufruf schlaegt dann kontrolliert mit
            MakroManagerFehler fehl statt mit einem AttributeError tief in
            aktion_skript.py.
        dispatcher: optionale gemeinsame MausDispatcher-Instanz - wird sonst
            selbst erzeugt.
        basis_dir: Verzeichnis der aktion_<name>.json-Dateien - Standard ist
            aktion_skript.BASE_DIR.
        log: Callable(str) fuer allgemeine Manager-Meldungen (Start/Stopp) -
            NICHT die Schritt-fuer-Schritt-Logs einzelner Makros (siehe
            starte_makro()'s schritt_log-Parameter dafuer).
    """

    def __init__(self, maus_getter=None, dispatcher=None, basis_dir=None, log=print):
        self.maus_getter = maus_getter or (lambda: None)
        self.dispatcher = dispatcher if dispatcher is not None else MausDispatcher()
        self.basis_dir = basis_dir or aktion_skript.BASE_DIR
        self.log = log
        self._lock = threading.Lock()
        self._makros = {}  # name -> _LaufendesMakro

    def _hid_maus_oder_fehler(self, makro_name):
        maus = self.maus_getter()
        if maus is None:
            raise MakroManagerFehler(
                "Keine HID-Maus verbunden - Makro '%s' nicht gestartet." % makro_name)
        return maus

    def starte_makro(self, skript_name, prioritaet=PRIORITAET_MITTEL, bei_fehler="ABBRECHEN",
                      schritt_log=None, fenster_hwnd=None, instanz_key=None, fenster_label=None):
        """Startet 'skript_name' (aktion_<skript_name>.json) in einem eigenen
        Thread mit gegebener Prioritaet, parallel zu bereits laufenden
        Makros. Eine Instanz desselben instanz_key darf nicht bereits laufen.

        Args:
            schritt_log: optionales Callable(skript_name, zeile) fuer die
                Schritt-fuer-Schritt-Logs DIESES Makros (zusaetzlich zum
                allgemeinen self.log()) - z.B. fuer eine Live-Anzeige je
                Makro im MAKRO TOOLS-Reiter.
            fenster_hwnd: optionales Fenster-Handle (siehe modules.fenster.
                alle_spielfenster_finden()) - ist es gesetzt, wird DIESES
                Skript auf GENAU DIESES Fenster isoliert (Screenshots/
                Bilderkennung/Klicks nur dort, siehe aktion_skript.
                skript_ausfuehren(fenster_provider=...)); die Position wird
                dabei bei jedem Zyklus per modules.fenster.fenster_von_hwnd()
                neu geholt. None (Standard) = bisheriges "Alle Fenster"-
                Verhalten (kein fenster_provider, siehe aktion_skript.py).
            instanz_key: Schluessel, unter dem diese Ausfuehrung in
                laufende_makros()/stoppe_makro() erscheint - Standard ist
                'skript_name' selbst (bisheriges Verhalten: ein Skriptname =
                eine laufende Instanz). Fuer den Mehrfenster-Fan-out (siehe
                starte_makro_alle_fenster()) vergibt der Aufrufer je Fenster
                einen EIGENEN instanz_key, damit mehrere Instanzen
                DESSELBEN Skripts gleichzeitig laufen koennen.
            fenster_label: nur fuer die Anzeige (siehe laufende_makros()) -
                z.B. "Fenster 2", None wenn kein Fan-out.

        Returns:
            bool: True, wenn der Thread gestartet wurde.

        Raises:
            MakroManagerFehler: wenn bereits eine Instanz mit diesem
                instanz_key laeuft, keine HID-Maus verbunden ist, oder das
                Skript nicht geladen werden kann.
        """
        instanz_key = instanz_key if instanz_key is not None else skript_name
        with self._lock:
            bestehend = self._makros.get(instanz_key)
            if bestehend is not None and bestehend.status == "LAEUFT":
                raise MakroManagerFehler("Makro '%s' laeuft bereits." % instanz_key)

            maus = self._hid_maus_oder_fehler(instanz_key)

            try:
                schritte = aktion_skript.skript_laden(skript_name)
            except (OSError, ValueError) as e:
                raise MakroManagerFehler("Skript '%s' konnte nicht geladen werden: %s" % (skript_name, e))
            if not schritte:
                raise MakroManagerFehler("Skript '%s' hat keine Schritte." % skript_name)

            eintrag = _LaufendesMakro(instanz_key, prioritaet, threading.Event(),
                                       basis_name=skript_name, fenster_label=fenster_label)
            self._makros[instanz_key] = eintrag

        fenster_provider = None
        if fenster_hwnd is not None:
            fenster_provider = functools.partial(fenster_modul.fenster_von_hwnd, fenster_hwnd)

        def _log_zeile(msg):
            self.log("[%s] %s" % (instanz_key, msg))
            if schritt_log:
                schritt_log(instanz_key, msg)

        def lauf():
            try:
                # Fenster-Eckpruefung (siehe fish_bot.fenster_eckpruefung_bestehen())
                # - derselbe Check wie beim Fisch-Bot-Start, damit er nicht nur
                # dort, sondern auch bei jedem normalen Bot-Skript ueber MAKRO
                # TOOLS greift. NUR fuer automatisch erkannte Fenster (kein
                # fenster_fest-Bereich - starte_makro() unterstuetzt anders als
                # fish_bot_starten() ohnehin keinen manuellen Bereich).
                fenster = (fenster_provider() if fenster_provider is not None
                          else fish_bot.fenster_finden(fish_bot.FENSTER_TITEL))
                if fenster is not None and not fenster.get("fenster_fest"):
                    if not fish_bot.fenster_eckpruefung_bestehen(fenster, log_praefix="[%s] " % instanz_key):
                        eintrag.status = "FENSTERPRUEFUNG_FEHLGESCHLAGEN"
                        _log_zeile("Fenster-Eckpruefung fehlgeschlagen - Skript nicht gestartet")
                        return

                ergebnis = aktion_skript.skript_ausfuehren(
                    schritte, maus, bei_fehler=bei_fehler, log=_log_zeile,
                    dispatcher=self.dispatcher, prioritaet=prioritaet,
                    stop_event=eintrag.stop_event, fenster_provider=fenster_provider)
                eintrag.status = ergebnis
            except Exception as e:
                eintrag.status = "FEHLER"
                eintrag.fehler = str(e)
                _log_zeile("UNERWARTETER FEHLER: %s" % e)
            finally:
                eintrag.beendet_um = time.time()

        thread = threading.Thread(target=lauf, daemon=True, name="Makro-%s" % instanz_key)
        eintrag.thread = thread
        thread.start()
        fenster_text = " [%s]" % fenster_label if fenster_label else ""
        self.log("Makro gestartet: %s%s (Prioritaet %s)" % (instanz_key, fenster_text, prioritaet))
        return True

    def starte_makro_alle_fenster(self, skript_name, prioritaet=PRIORITAET_MITTEL, bei_fehler="ABBRECHEN",
                                   schritt_log=None):
        """Startet 'skript_name' fuer die "Alle Fenster"-Auswahl (siehe
        MAKRO TOOLS-Reiter): findet alle gerade offenen Spielfenster (siehe
        modules.fenster.alle_spielfenster_finden()) und startet je Fenster
        eine EIGENE, auf genau dieses Fenster isolierte Instanz - bei nur
        einem (oder keinem) gefundenen Fenster ist das Ergebnis identisch zum
        bisherigen Verhalten (eine einzige, nicht isolierte Instanz unter dem
        Skriptnamen selbst).

        Returns:
            list[str]: instanz_key jeder tatsaechlich gestarteten Instanz.

        Raises:
            MakroManagerFehler: siehe starte_makro() - wird NICHT abgefangen,
                schlaegt also bereits beim ersten Fenster fehl, wenn z.B.
                keine HID-Maus verbunden ist (bevor irgendein Thread
                gestartet wurde).
        """
        fenster_liste = fenster_modul.alle_spielfenster_finden()
        if len(fenster_liste) <= 1:
            hwnd = fenster_liste[0]["hwnd"] if fenster_liste else None
            self.starte_makro(skript_name, prioritaet, bei_fehler=bei_fehler, schritt_log=schritt_log,
                               fenster_hwnd=hwnd, instanz_key=skript_name)
            return [skript_name]

        gestartet = []
        for fenster in fenster_liste:
            label = "Fenster %d" % fenster["nummer"]
            instanz_key = "%s%s%s" % (skript_name, _INSTANZ_TRENNER, label)
            self.starte_makro(skript_name, prioritaet, bei_fehler=bei_fehler, schritt_log=schritt_log,
                               fenster_hwnd=fenster["hwnd"], instanz_key=instanz_key, fenster_label=label)
            gestartet.append(instanz_key)
        return gestartet

    def instanzen_von(self, skript_name):
        """Alle instanz_key, die aktuell zu 'skript_name' gehoeren (egal ob
        laufend oder bereits beendet) - fuer GUI-Code, der z.B. ALLE
        Fenster-Instanzen eines Skripts gleichzeitig stoppen will, ohne
        selbst die genauen Fenster-Labels zu kennen (siehe stoppe_alle_instanzen())."""
        with self._lock:
            return [k for k, m in self._makros.items() if m.basis_name == skript_name]

    def stoppe_alle_instanzen(self, skript_name, timeout=None):
        """Signalisiert ALLEN laufenden Instanzen von 'skript_name' (egal ob
        eine einzelne nicht-isolierte Instanz oder mehrere per
        starte_makro_alle_fenster() gestartete Fenster-Instanzen), sich zu
        beenden - das GUI-Gegenstueck zu starte_makro_alle_fenster(), da die
        GUI beim Stoppen i.d.R. nur den Skriptnamen kennt, nicht die genauen
        instanz_key der einzelnen Fenster-Instanzen.

        Returns:
            list[str]: instanz_key jeder Instanz, der ein Stopp signalisiert
                wurde.
        """
        gestoppt = []
        for instanz_key in self.instanzen_von(skript_name):
            if self.stoppe_makro(instanz_key, timeout=timeout):
                gestoppt.append(instanz_key)
        return gestoppt

    def fish_bot_starten(self, prioritaet=PRIORITAET_HOCH, fenster_hwnd=None, fenster_bereich=None,
                          instanz_key=None, fenster_label=None):
        """Startet fish_bot.py als eigenes Makro (Standard-Prioritaet HOCH),
        parallel zu Bot-Skripten - OHNE fish_bot.py-Verhalten fuer den
        unisolierten Fall zu aendern (siehe DispatcherMaus: die echte HID-
        Maus wird in einen fuer fish_bot transparenten Wrapper gehuellt, der
        jede Maus-Aktion ueber denselben MausDispatcher arbitriert wie die
        Skripte).

        Args:
            fenster_hwnd: optionales Fenster-Handle (siehe modules.fenster.
                alle_spielfenster_finden()) - ist es gesetzt, wird DIESE
                Fisch-Bot-Instanz auf GENAU DIESES Fenster isoliert (siehe
                fish_bot.bot_starten(fenster_provider=...)). None (Standard)
                = bisheriges Verhalten (erstes METIN2-Fenster per Titel).
            fenster_bereich: optionaler manuell festgelegter Bildschirmbereich
                (dict{"x","y","w","h"}, siehe modules.fenster.
                bereich_manuell_auswaehlen()) als Alternative zu fenster_hwnd
                - fuer den Fall, dass die automatische GetWindowRect()-
                Erkennung durch ueberlappende Fenster falschen Bildschirm-
                inhalt einfangen wuerde. Bleibt waehrend der gesamten Bot-
                Laufzeit FEST (keine Fenster-Bewegungsverfolgung wie bei
                fenster_hwnd). Wird ignoriert, wenn fenster_hwnd gesetzt ist.
            instanz_key: siehe MakroManager.starte_makro() - Standard ist
                FISCHBOT_NAME (bisheriges Verhalten: genau EINE laufende
                Fisch-Bot-Instanz). Fuer den Mehrfenster-Fan-out (siehe
                fischbot_starten_alle_fenster()) vergibt der Aufrufer je
                Fenster einen EIGENEN instanz_key.
            fenster_label: nur fuer Anzeige/CSV-Dateiname (siehe
                fish_bot.FischBotKontext) - z.B. "Fenster 2".

        Returns:
            bool: True, wenn der Thread gestartet wurde.

        Raises:
            MakroManagerFehler: wenn bereits eine Instanz mit diesem
                instanz_key laeuft, oder keine HID-Maus verbunden ist.
        """
        instanz_key = instanz_key if instanz_key is not None else FISCHBOT_NAME
        with self._lock:
            bestehend = self._makros.get(instanz_key)
            if bestehend is not None and bestehend.status == "LAEUFT":
                raise MakroManagerFehler("Fisch-Bot '%s' laeuft bereits." % instanz_key)

            maus = self._hid_maus_oder_fehler(instanz_key)
            arbitrierte_maus = DispatcherMaus(maus, self.dispatcher, prioritaet)

            eintrag = _LaufendesMakro(instanz_key, prioritaet, threading.Event(),
                                       basis_name=FISCHBOT_NAME, fenster_label=fenster_label)
            self._makros[instanz_key] = eintrag

        # Das MakroManager-Stop-Event WIRD das FischBotKontext-Stop-Event
        # (statt eines eigenen) - dadurch stoppt eintrag.stop_event.set()
        # (siehe stoppe_makro()) die Instanz direkt, ohne einen fish_bot-
        # spezifischen Sonderfall zu brauchen (im Gegensatz zum frueheren,
        # global-_stop_event-basierten fish_bot.bot_anhalten()-Aufruf, der
        # bei mehreren gleichzeitigen Instanzen die FALSCHE Instanz getroffen
        # haette).
        fisch_kontext = fish_bot.FischBotKontext(label=fenster_label)
        fisch_kontext.stop_event = eintrag.stop_event

        fenster_provider = None
        if fenster_hwnd is not None:
            fenster_provider = functools.partial(fenster_modul.fenster_von_hwnd, fenster_hwnd)
        elif fenster_bereich is not None:
            bereich_fest = dict(fenster_bereich)
            # "fenster_fest" markiert diesen Bereich als manuell/fix (siehe
            # fish_bot._fenster_plausibel()) - die uebliche Plausibilitaets-
            # pruefung (Breite/Hoehe muessen der TYPISCHEN METIN2-Fenstergroesse
            # entsprechen) waere hier fehl am Platz: sie soll transiente
            # GetWindowRect()-Fehlmessungen waehrend eines Resizes abfangen,
            # nicht eine bewusst vom Benutzer per Hand gewaehlte Groesse
            # ablehnen (die selten exakt in den engen Standard-Bereich faellt).
            bereich_fest["fenster_fest"] = True
            fenster_provider = lambda: dict(bereich_fest)

        def lauf():
            try:
                ergebnis = fish_bot.bot_starten(maus=arbitrierte_maus, kontext=fisch_kontext,
                                                 fenster_provider=fenster_provider)
                eintrag.status = ergebnis  # "GESTOPPT" | "FEHLER" | "VERBINDUNGSFEHLER"
            except Exception as e:
                eintrag.status = "FEHLER"
                eintrag.fehler = str(e)
                self.log("[%s] UNERWARTETER FEHLER: %s" % (instanz_key, e))
            finally:
                eintrag.beendet_um = time.time()

        thread = threading.Thread(target=lauf, daemon=True, name="Makro-%s" % instanz_key)
        eintrag.thread = thread
        thread.start()
        fenster_text = " [%s]" % fenster_label if fenster_label else ""
        self.log("Fisch-Bot gestartet als Makro: %s%s (Prioritaet %s)" % (instanz_key, fenster_text, prioritaet))
        return True

    def fischbot_starten_alle_fenster(self, prioritaet=PRIORITAET_HOCH):
        """Fisch-Bot-Gegenstueck zu MakroManager.starte_makro_alle_fenster():
        findet alle gerade offenen Spielfenster (siehe modules.fenster.
        alle_spielfenster_finden()) und startet je Fenster eine EIGENE, auf
        genau dieses Fenster isolierte Fisch-Bot-Instanz - bei nur einem
        (oder keinem) gefundenen Fenster ist das Ergebnis identisch zum
        bisherigen Verhalten (eine einzige, nicht isolierte Instanz unter
        FISCHBOT_NAME).

        Returns:
            list[str]: instanz_key jeder tatsaechlich gestarteten Instanz.

        Raises:
            MakroManagerFehler: siehe fish_bot_starten().
        """
        fenster_liste = fenster_modul.alle_spielfenster_finden()
        if len(fenster_liste) <= 1:
            hwnd = fenster_liste[0]["hwnd"] if fenster_liste else None
            self.fish_bot_starten(prioritaet, fenster_hwnd=hwnd, instanz_key=FISCHBOT_NAME)
            return [FISCHBOT_NAME]

        gestartet = []
        for fenster in fenster_liste:
            label = "Fenster %d" % fenster["nummer"]
            instanz_key = "%s%s%s" % (FISCHBOT_NAME, _INSTANZ_TRENNER, label)
            self.fish_bot_starten(prioritaet, fenster_hwnd=fenster["hwnd"], instanz_key=instanz_key,
                                   fenster_label=label)
            gestartet.append(instanz_key)
        return gestartet

    def fischbot_und_makro_starten_alle_fenster(self, skript_name, prioritaet=PRIORITAET_MITTEL,
                                                 fischbot_prioritaet=PRIORITAET_HOCH,
                                                 bei_fehler="ABBRECHEN", schritt_log=None,
                                                 versatz_s=1.5):
        """Kombination aus fischbot_starten_alle_fenster() und
        starte_makro_alle_fenster(): startet PRO offenem Spielfenster BEIDE -
        Fisch-Bot (eigene Prioritaet, Standard HOCH) UND 'skript_name' -
        isoliert auf dasselbe Fenster. Ersetzt die bisherige Einschraenkung
        in command_center.py ("'Alle Fenster' laesst sich nicht mit einem
        Parallelen Skript kombinieren") - beide Fan-outs liefen technisch
        schon vorher unabhaengig voneinander, kombiniert wurden sie nur noch
        nicht.

        'versatz_s' ist eine kleine Pause VOR jedem Fenster ausser dem
        ersten (Standard 1.5s) - rein zur Entzerrung des Starts (z.B. damit
        nicht alle Fenster im selben Sekundenbruchteil per
        SetForegroundWindow() um den Fokus konkurrieren); funktional noetig
        ist sie nicht, da jede Instanz ohnehin ueber den MausDispatcher
        arbitriert wird (siehe DispatcherMaus).

        Bei nur einem (oder keinem) gefundenen Fenster identisch zum
        bisherigen Einzel-Fenster-Verhalten (siehe
        command_center._start_fishbot_als_makro()).

        Returns:
            list[tuple[str, str]]: (fischbot_instanz_key, makro_instanz_key)
                je tatsaechlich gestartetem Fenster.

        Raises:
            MakroManagerFehler: siehe fish_bot_starten()/starte_makro() -
                bricht beim ERSTEN fehlgeschlagenen Start ab; bereits
                gestartete Fenster-Instanzen laufen dabei weiter (Aufrufer
                kann sie ueber stoppe_alle_instanzen() beenden).
        """
        fenster_liste = fenster_modul.alle_spielfenster_finden()
        if len(fenster_liste) <= 1:
            hwnd = fenster_liste[0]["hwnd"] if fenster_liste else None
            self.fish_bot_starten(fischbot_prioritaet, fenster_hwnd=hwnd, instanz_key=FISCHBOT_NAME)
            self.starte_makro(skript_name, prioritaet, bei_fehler=bei_fehler, schritt_log=schritt_log,
                               fenster_hwnd=hwnd, instanz_key=skript_name)
            return [(FISCHBOT_NAME, skript_name)]

        gestartet = []
        for i, fenster in enumerate(fenster_liste):
            if i > 0 and versatz_s > 0:
                time.sleep(versatz_s)
            label = "Fenster %d" % fenster["nummer"]
            fischbot_key = "%s%s%s" % (FISCHBOT_NAME, _INSTANZ_TRENNER, label)
            makro_key = "%s%s%s" % (skript_name, _INSTANZ_TRENNER, label)
            self.fish_bot_starten(fischbot_prioritaet, fenster_hwnd=fenster["hwnd"],
                                   instanz_key=fischbot_key, fenster_label=label)
            self.starte_makro(skript_name, prioritaet, bei_fehler=bei_fehler, schritt_log=schritt_log,
                               fenster_hwnd=fenster["hwnd"], instanz_key=makro_key, fenster_label=label)
            gestartet.append((fischbot_key, makro_key))
        return gestartet

    def stoppe_makro(self, skript_name, timeout=None):
        """Signalisiert dem laufenden Makro 'skript_name' (oder einem per
        fish_bot_starten()/starte_makro() vergebenen instanz_key), sich
        sauber zu beenden - blockiert NICHT auf das tatsaechliche
        Threadende, ausser 'timeout' ist gesetzt (siehe laufende_makros()
        fuer den aktuellen Stand).

        Fuer Fisch-Bot-Instanzen genuegt das einheitliche eintrag.stop_event
        (siehe fish_bot_starten(): dessen FischBotKontext.stop_event IST
        genau dieses Objekt) - kein fish_bot-spezifischer Sonderfall mehr
        noetig.

        Returns:
            bool: True, wenn ein laufendes Makro gefunden und ihm ein Stopp
                signalisiert wurde, False wenn keins mit diesem Namen (mehr)
                laeuft.
        """
        with self._lock:
            eintrag = self._makros.get(skript_name)
        if eintrag is None or eintrag.status != "LAEUFT":
            return False

        eintrag.stop_event.set()

        self.log("Stopp angefordert fuer Makro: %s" % skript_name)
        if timeout is not None:
            eintrag.thread.join(timeout)
        return True

    def stoppe_alle(self, timeout=None):
        """Signalisiert ALLEN gerade laufenden Makros (inkl. Fisch-Bot,
        falls aktiv), sich zu beenden.

        Returns:
            list[str]: Namen der Makros, denen ein Stopp signalisiert wurde.
        """
        with self._lock:
            laufende = [name for name, m in self._makros.items() if m.status == "LAEUFT"]
        gestoppt = []
        for name in laufende:
            if self.stoppe_makro(name, timeout=timeout):
                gestoppt.append(name)
        return gestoppt

    def makro_laeuft(self, skript_name):
        """True, wenn 'skript_name' (oder FISCHBOT_NAME) gerade laeuft -
        inklusive irgendeiner per starte_makro_alle_fenster() gestarteten
        Fenster-Instanz DIESES Skripts (basis_name-Vergleich, siehe
        _LaufendesMakro), nicht nur einer instanz_key-gleichen Instanz."""
        with self._lock:
            eintraege = list(self._makros.values())
        return any(m.basis_name == skript_name and m.status == "LAEUFT" for m in eintraege)

    def laufende_makros(self):
        """Liste aller BEKANNTEN Makro-INSTANZEN (aktuell laufend oder
        zuletzt beendet) mit Status - Grundlage fuer die Live-Anzeige im
        MAKRO TOOLS-Reiter. Bei Mehrfenster-Fan-out (siehe
        starte_makro_alle_fenster()) erscheint JEDE Fenster-Instanz eines
        Skripts als EIGENER Eintrag (gleicher 'basis_name', verschiedener
        'name'/instanz_key).

        Returns:
            list[dict]: je Instanz {"name","basis_name","fenster_label",
                "prioritaet","status","laeuft","laufzeit_s","fehler"} -
                laufzeit_s ist die Zeit seit dem Start (laufend) bzw. bis zum
                Ende (beendet). Leere Liste, wenn noch nie ein Makro
                gestartet wurde.
        """
        with self._lock:
            eintraege = list(self._makros.values())
        jetzt = time.time()
        ergebnis = []
        for m in eintraege:
            ende = m.beendet_um if m.beendet_um is not None else jetzt
            ergebnis.append({
                "name": m.name,
                "basis_name": m.basis_name,
                "fenster_label": m.fenster_label,
                "prioritaet": m.prioritaet,
                "status": m.status,
                "laeuft": m.status == "LAEUFT",
                "laufzeit_s": round(ende - m.gestartet_um, 1),
                "fehler": m.fehler,
            })
        return ergebnis
