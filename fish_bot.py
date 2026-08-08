#!/usr/bin/env python3
"""fish_bot.py - Automatisiertes Angeln im METIN2-Fenster per HSV-/Template-
Erkennung und HID-Maus/-Tastatur.

Der Bot laeuft als Zustandsautomat (siehe bot_schleife()). Das Popup-Fenster
ist der EINZIGE Trigger zum Angeln - kein automatisches Wurm-Nachlegen, keine
gestaffelten Wiederholungsversuche mehr (wurm_klicken() bleibt als Funktion
fuer die manuelle WURM_KLICKEN-Aktion in aktion_skript.py erhalten, wird aber
von fish_bot.py selbst nicht mehr automatisch aufgerufen):

  FISCHEN --(Popup schliesst, 0.5s entprellt)--> WARTE_EINHOLEN
  WARTE_EINHOLEN --(3.5s Basiswartezeit, Leertaste)--> PRUEFE_POPUP
  PRUEFE_POPUP --(2.0s Basiswartezeit, Popup da)--> FISCHEN
               --(kein Popup)--> WARTE_EINHOLEN (erneut auswerfen, Schleife
                 zum Start - kein Fehler-Endzustand mehr, laeuft bis
                 bot_anhalten())

Alle Wartezeiten laufen ueber warte_mit_bonus() (0-40% Zufallsbonus).

FISCHEN selbst (siehe zustand_fischen()) laeuft als ZWEI getrennte, parallel
laufende Loops statt einer einzigen Schleife:
  - _mess_loop() (eigener Thread): misst so schnell wie moeglich (Ziel
    MESS_INTERVALL_S, ~10-15x/s) Popup- und Fischposition, bewegt aber nie
    die Maus und klickt nie.
  - _klick_loop() (Hauptthread): liest nur die neueste Messung aus dem
    gemeinsamen MessZustand und klickt, wenn der Fisch im Ring stillsteht -
    entkoppelt von der (teureren) Messrate durch MIN_KLICK_ABSTAND_S.
Grund: bei ~250px/s Fischgeschwindigkeit machte eine einzelne Schleife
(Screenshot + Verarbeitung + Klick-Overhead in Serie, ~1 Zyklus/s) die
gemessene Position beim naechsten Zyklus laengst wertlos.
"""

import os
import csv
import json
import sys
import time
import math
import ctypes
import random
import logging
import threading
import statistics

import cv2
import numpy as np
from PIL import ImageGrab

try:
    import dxcam
except ImportError:
    dxcam = None

from pynput.keyboard import Controller as _PynputController, Key as _PynputKey
import win32gui

from modules.fenster import fenster_finden
from hid_maus import HIDMaus
from popup_erkennung import popup_finden

user32 = ctypes.windll.user32

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_logger = logging.getLogger("FishBot")
_logger.setLevel(logging.DEBUG)

FENSTER_TITEL = "METIN2"
HID_PORT = "COM7"

# Sekunden Wartezeit NACH win32gui.SetForegroundWindow(), bevor die Leertaste
# tatsaechlich gesendet wird (siehe leertaste_tippen()) - nur relevant, wenn
# der Bot per fenster_provider auf ein bestimmtes von MEHREREN offenen
# METIN2-Fenstern isoliert ist (siehe FischBotKontext). Derselbe Wert wie
# aktion_skript._fokussiere_metin2() (dort empirisch als noetig ermittelt,
# damit Metin2 den Fokuswechsel registriert, bevor Tastatureingaben ueber
# SendInput ankommen).
FOKUS_WARTEZEIT_S = 3.0

# Sekunden Wartezeit NACH win32gui.SetForegroundWindow() im KLICK-Pfad (siehe
# _fenster_fokussiert_sicherstellen()) - bewusst VIEL kuerzer als
# FOKUS_WARTEZEIT_S (3s waeren auf dem klickkritischen Pfad toedlich: der
# Fisch ist laengst weitergeschwommen, bevor der Klick rausgeht). Nur ein
# grober erster Wert (Maus-Klicks laufen ueber die Arduino-HID-Firmware, NICHT
# ueber SendInput wie die Leertaste - die 3s dort wurden empirisch FUER
# SendInput ermittelt und muessen hier nicht gelten). Bei Beobachtungen von
# weiterhin ignorierten Klicks nach Fokuswechsel hier zuerst hochsetzen.
KLICK_FOKUS_WARTEZEIT_S = 0.15

# HSV-Untergrenze/Obergrenze des Ziels (H, S, V), per Test ermittelt.
HSV_UNTERGRENZE = np.array([73, 99, 116], dtype=np.uint8)
HSV_OBERGRENZE = np.array([144, 154, 132], dtype=np.uint8)
MIN_KONTUR_FLAECHE = 30  # Pixel, per Test ermittelt

# Zielintervall des MESS-Loops (_mess_loop()) - so schnell wie sinnvoll
# moeglich, angepeilt sind 10-15 Messungen/s (bei ~250px/s Fischgeschwindigkeit
# noetig, um den Fisch ueberhaupt noch dort zu treffen, wo er gemessen wurde).
# Als festes Taktschema umgesetzt (naechste += Intervall, siehe _mess_loop()),
# nicht als time.sleep() NACH der Verarbeitung - letzteres addiert die
# Verarbeitungszeit ungewollt oben drauf und driftet damit von der Zielrate weg
# (das war mitverantwortlich fuer die vorherige tatsaechliche Zykluszeit von
# ~1s statt der nominellen 0.2s).
MESS_INTERVALL_S = 0.08  # Sekunden (~12.5x/s, Mitte des 10-15x/s-Zielbereichs)
# Pollintervall des KLICK-Loops (_klick_loop()) - deutlich kleiner als
# MIN_KLICK_ABSTAND_S, damit ein Ring+Stillstand-Fenster nicht knapp verpasst
# wird, aber gross genug, um nicht sinnlos CPU zu verbrennen (der Loop tut
# zwischen zwei Klicks nichts als eine Momentaufnahme zu lesen und zu pruefen).
KLICK_LOOP_INTERVALL_S = 0.02  # Sekunden (~50x/s Polling)

RING_PUFFER_PX = 10  # Puffer auf den gemessenen Box-Radius (Klick-Hitbox groesser
                      # als der sichtbare Kreis) - ersetzt das fruehere KREIS_FAKTOR
                      # (0.85, verengend), das fuer die alte, ungenauere
                      # Ring-Linien-Erkennung gedacht war.
STATUS_LOG_INTERVALL = 1.0  # Sekunden - Status-Log max. 1x pro Sekunde
POPUP_HALTEZEIT = 1.0  # Sekunden - letzte Popup-Position bei Flackern beibehalten
RING_HITBOX_PX = 4  # Pixel - zusaetzliche Klick-Toleranz ueber den Ringrand hinaus

# Puffer um die zuletzt gemessene Popup-Box herum, der beim naechsten
# Mess-Tick tatsaechlich gescreenshottet wird (siehe _popup_roi()) - deutlich
# kleiner als das gesamte Fenster, was der Hauptgrund ist, warum der Mess-Loop
# MESS_INTERVALL_S ueberhaupt erreichen kann (ein Screenshot des ganzen
# Fensters ist der teuerste Teil eines Messdurchlaufs).
MESS_ROI_PUFFER_PX = 40  # Pixel, zusaetzlich zum gemessenen Popup-Radius

# Rauschfilter fuer die rohe Fisch-Erkennung (siehe FischGlaetter):
# Glitzer/Schatten/Erkennungsaussetzer lassen die rohe Position um
# 50-100px springen - deutlich mehr als jede plausible Fischbewegung
# zwischen zwei Messungen (~10-15/s). Zweistufig gefiltert:
#   1. Ausreisser-Filter: eine neue rohe Position, die mehr als
#      MAX_SPRUNG_PX vom letzten AKZEPTIERTEN Punkt entfernt ist, wird
#      verworfen (die letzte akzeptierte Position bleibt bestehen).
#   2. Median (statt gleitendem Durchschnitt) ueber die letzten
#      GLAETTER_FENSTER AKZEPTIERTEN Positionen - ein Mittelwert wird von
#      einzelnen Ausreissern verzerrt, der Median ignoriert sie komplett.
MAX_SPRUNG_PX = 40  # Pixel, ab dem eine neue Position als Ausreisser gilt
# Nach so vielen AUFEINANDERFOLGENDEN verworfenen Punkten wird der naechste
# Punkt zwangsweise akzeptiert, egal wie weit er entfernt ist - sonst wuerde
# der Filter einfrieren, wenn der Fisch tatsaechlich weit springt (z.B. ein
# neuer Fisch an anderer Ring-Position nach einem Fang).
MAX_VERWORFENE_SERIE = 3
GLAETTER_FENSTER = 4  # Anzahl akzeptierter Positionen, aus denen der Median gebildet wird

# Stillstand-Erkennung (siehe fisch_steht_still()): der Fisch gilt als still,
# wenn er sich ueber die letzten STILLSTAND_FRAMES ROHEN (ungeglaetteten)
# Positionen um weniger als STILLSTAND_SCHWELLE_PX bewegt hat. Beide als
# eigene Konstanten, um sie unabhaengig voneinander leicht antasten zu
# koennen (z.B. STILLSTAND_SCHWELLE_PX hochsetzen, falls die Erkennung
# selbst noch leicht zittert).
STILLSTAND_SCHWELLE_PX = 5  # Pixel
STILLSTAND_FRAMES = 3       # Anzahl verglichener ROHER Positionen

# Klick-Sperre waehrend FISCHEN: ein neuer Klick ist erst erlaubt, wenn seit
# dem letzten Klick mindestens diese vielen Sekunden vergangen sind. Der
# Klick-Loop pollt viel schneller (KLICK_LOOP_INTERVALL_S) als er klicken
# darf - das verhindert Klick-Spam bei jedem Poll, waehrend trotzdem mehrere
# Klicks pro Popup moeglich bleiben, solange der Fisch weiter im Ring
# stillsteht (siehe _klick_loop()).
MIN_KLICK_ABSTAND_S = 0.1  # Sekunden

# Radius aus der Popup-BOX (Box-Breite/Hoehe / 2, siehe popup_erkennung.py) -
# eine Box muss mindestens ~40px breit sein, um als echtes Popup zu gelten,
# also Radius >= 20.
MIN_RADIUS = 20  # Popup-Box-Radius, ab dem ein Fund als echtes Popup gilt
# Analyse der aufgezeichneten live_popup_*.png-Sequenz (98 Frames) zeigte eine
# klare Radius-Verteilung: echte Fisch-Ringe clustern bei ~64px, waehrend
# andere runde UI-Elemente in Nicht-Angel-Screenshots faelschlich mit
# ~166-171px erkannt wurden (z.B. Inventar-/Fenster-Ausschnitte) - beide
# liegen unter MAX_BOX_ANTEIL in popup_erkennung.py und wurden bisher NICHT
# durch eine obere Radius-Grenze abgefangen. MAX_RADIUS mit komfortablem
# Puffer ueber dem beobachteten echten Cluster (64px), aber klar unter dem
# falschen Cluster (166px).
MAX_RADIUS = 110  # Popup-Box-Radius, ab dem ein Fund als Fehlerkennung gilt
POPUP_SCHLIESS_DEBOUNCE = 0.5  # Sekunden - 'Popup zu' muss so lange anhalten (Entprellung)

# Plausibilitaets-Grenzen fuer die von fenster_finden() gelieferte Fenster-
# groesse. Beobachtete gute Werte lagen bei 798x627 (wurm.png) und 816x639
# (Live-Test); ein Ausreisser von 993x519 (Fenster mitten in Verschiebung/
# Groessenaenderung) fuehrte zu 0 Wurm-Treffern, weil die fraktionale ROI bei
# so einem abweichenden Seitenverhaeltnis ins Leere zeigt. Der Bereich hier
# liegt komfortabel um die beobachteten guten Werte, schliesst 993x519 aber
# klar aus.
FENSTER_BREITE_MIN, FENSTER_BREITE_MAX = 750, 900
FENSTER_HOEHE_MIN, FENSTER_HOEHE_MAX = 580, 700

# Fenster-Eckpruefung (siehe fenster_eckpruefung()): validiert VOR dem
# eigentlichen Bot-Start, dass ein automatisch erkanntes Fenster (NICHT ein
# manuell/fest vorgegebener Bereich) auch WIRKLICH ein echtes, korrekt
# positioniertes METIN2-Fenster zeigt - je Ecke ein zugeordnetes Referenzbild
# (siehe eckpruefung_laden()/eckpruefung_speichern(), UI im Fisch-Bot-Tab von
# command_center.py), das NUR in seiner eigenen Fensterecke gesucht wird
# (nicht im ganzen Fenster) - das prueft nicht nur "ist das Bild ueberhaupt
# sichtbar", sondern auch "sitzt es an der ERWARTETEN Stelle" (z.B. Hinweis
# auf ein DPI-/Skalierungsproblem, siehe screenshot_holen()-Diagnose).
_ECKPRUEFUNG_DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fenster_eckpruefung.json")
ECKEN = ("oben_links", "oben_rechts", "unten_links", "unten_rechts")
# Anteil der Fensterbreite/-hoehe, der als Such-Ausschnitt je Ecke gilt -
# grosszuegig genug fuer normale Icon-Platzierungen nahe der Ecke, aber eng
# genug, um wirklich nur DIESE Ecke (nicht z.B. die Bildmitte) zu pruefen.
# Ueberschreibbar/dauerhaft speicherbar ueber die UI (Fisch-Bot-Tab "Fenster-
# Pruefung (Ecken)", siehe eckpruefung_laden()["anteil"]) - gilt dann GLOBAL
# fuer JEDEN Aufrufer (Fisch-Bot UND MAKRO TOOLS, siehe
# fenster_eckpruefung_bestehen()), bis er wieder geaendert wird. Dies hier
# ist nur der Standardwert, falls noch nichts gespeichert wurde.
ECKBEREICH_ANTEIL_STANDARD = 0.35
ECKBEREICH_ANTEIL_MIN, ECKBEREICH_ANTEIL_MAX = 0.05, 0.5
# Mindestanzahl passender Ecken, damit der Start ueberhaupt fortgesetzt wird
# (siehe bot_starten()) - bei WENIGER konfigurierten Ecken als diesem Wert
# muessen stattdessen ALLE konfigurierten passen (siehe fenster_eckpruefung()-
# Aufrufer in bot_starten()). Passen nicht ALLE konfigurierten Ecken, aber
# mindestens so viele, wird der Start trotzdem fortgesetzt - nur mit einer
# Warnung im Log statt eines Abbruchs.
ECKPRUEFUNG_MIN_TREFFER = 2

# Basiswartezeiten (Sekunden) fuer den Zustandsautomaten - alle ueber
# warte_mit_bonus() mit 0-40% Zufallsbonus versehen.
WARTE_EINHOLEN_BASIS = 3.5
PRUEFE_POPUP_BASIS = 2.0

# CSV-Datenlogger fuer FISCHEN (siehe _csv_logger_init()/_csv_zeile_schreiben()).
# Nur Diagnosedaten - beeinflusst die Klick-Logik nicht.
CSV_LOG_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fish_daten.csv")
CSV_SPALTEN = [
    "timestamp_ms", "fenster", "popup_erkannt", "radius", "fisch_gefunden",
    "fisch_x", "fisch_y", "distanz_zum_ring", "im_ring", "klick_gesendet",
    "zyklus_pause", "latenz_ms", "fisch_speed_px_s",
]


def _csv_pfad_fuer_label(label):
    """CSV-Pfad fuer eine benannte Instanz (siehe FischBotKontext.label) -
    'Fenster 2' -> fish_daten_Fenster_2.csv, damit parallele, je auf ein
    Fenster isolierte Fisch-Bot-Instanzen sich nicht gegenseitig dieselbe
    Datei ueberschreiben. Ohne Label (Standardfall: eine einzelne, nicht
    isolierte Instanz) bleibt es beim bisherigen CSV_LOG_PFAD."""
    if not label:
        return CSV_LOG_PFAD
    sicher = "".join(c if c.isalnum() else "_" for c in label)
    basis, ext = os.path.splitext(CSV_LOG_PFAD)
    return "%s_%s%s" % (basis, sicher, ext)


class FischBotKontext:
    """Buendelt den GESAMTEN pro-Instanz-Laufzeitzustand einer bot_starten()-
    Ausfuehrung (Stop-Flag, Popup-Haltezeit-Glaettung, Fenstergroessen-
    Plausibilitaetscache, Status-Log-Drosselung, CSV-Logger) - noetig, damit
    MEHRERE Fisch-Bot-Instanzen (je auf ein eigenes METIN2-Fenster isoliert
    ueber fenster_provider, siehe bot_starten()) GLEICHZEITIG in
    verschiedenen Threads laufen koennen, ohne sich ueber gemeinsame
    Modul-Globals gegenseitig zu stoeren - z.B. wuerde ein gemeinsamer
    Fenstergroessen-Cache bei zwei unterschiedlich grossen/positionierten
    Fenstern staendig faelschlich 'Groesse hat sich geaendert' ausloesen,
    und ein gemeinsamer CSV-Writer wuerde Zeilen zweier Fenster in derselben
    Datei vermischen.

    Modul-Funktionen nehmen ueberall einen optionalen 'kontext'-Parameter
    entgegen (None faellt auf _STANDARD_KONTEXT zurueck - siehe dort) -
    genau dasselbe Rueckwaertskompatibilitaets-Muster wie 'stop_event' in
    aktion_skript.py/'dispatcher' in maus_dispatcher.py.

    label: nur fuer Logs/CSV-Dateiname (z.B. "Fenster 2") - None (Standard)
        fuer eine einzelne, nicht isolierte Instanz (bisheriges Verhalten,
        CSV-Datei bleibt fish_daten.csv).
    """

    def __init__(self, label=None):
        self.label = label
        self.stop_event = threading.Event()
        self.letzter_status_log = 0.0
        self.letzte_popup_position = None
        self.letzte_popup_zeit = 0.0
        self.letzte_gueltige_fenstergroesse = None  # (w, h) der zuletzt akzeptierten Messung
        self.fenstergroesse_kandidat = None  # (w, h) einer abweichenden Messung, siehe _fenster_plausibel()
        self.programmstart = time.time()
        self.csv_datei = None
        self.csv_writer = None
        # _mess_loop() UND _klick_loop() DIESER Instanz schreiben beide CSV-
        # Zeilen aus ihrem jeweils eigenen Thread - dieser Lock verhindert,
        # dass zwei gleichzeitige writerow()-Aufrufe sich gegenseitig
        # verstuemmeln (ein Lock PRO Instanz genuegt, verschiedene
        # Instanzen schreiben ohnehin in verschiedene Dateien).
        self.csv_lock = threading.Lock()

    def log_praefix(self):
        return "[%s] " % self.label if self.label else ""


# Modul-globaler Standard-Kontext fuer Aufrufer, die (wie bisher, vor
# Einfuehrung der Mehrfenster-Unterstuetzung) einen einzelnen, nicht
# isolierten Fisch-Bot betreiben - bot_starten()/bot_anhalten() OHNE
# 'kontext'-Argument teilen sich diese eine Instanz, genau wie vorher das
# einzelne globale _stop_event.
_STANDARD_KONTEXT = FischBotKontext()


def _kontext_aufloesen(kontext):
    return kontext if kontext is not None else _STANDARD_KONTEXT

# Wurm-Nachlegen: Icon-Template aus wurm.png zugeschnitten (Slot bei x=631,y=277
# in C:/Users/vm1/Desktop/projekt/wurm.png, reiner Icon-Ausschnitt ohne die dort
# handgezeichnete Markierung und ohne die Stueckzahl-Ziffern).
WURM_TEMPLATE_PFAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "resources", "wurm_icon.png")
WURM_MATCH_SCHWELLE = 0.6  # cv2.matchTemplate-Score, ab dem ein Fund zaehlt
WURM_MIN_ABSTAND_PX = 15   # unterdrueckt Mehrfachtreffer auf demselben Slot
# Ab diesem Score gilt ein Treffer als sicher genug zum Klicken. Urspruenglich
# auf 0.9 gesetzt, aber ein Live-Test zeigte, dass auch ein echter, tatsaechlich
# vorhandener Stapel an derselben Position wie zuvor nur noch 0.678 erreichte
# (Wasseranimation/veraenderte Stueckzahl-Ziffer im Icon-Bereich draengen den
# Score runter, obwohl es der echte Stapel ist). Seit die ROI (unten) auf die
# eine Wurm-Zeile eingegrenzt ist, uebernimmt die raeumliche Filterung den
# Grossteil der False-Positive-Abwehr - die Score-Schwelle kann daher auf die
# Basis-Matchschwelle abgesenkt werden, ohne echte Stapel zu verwerfen.
WURM_SCORE_SICHER = WURM_MATCH_SCHWELLE

# Suchbereich fuers Inventar als Anteil der Fenstergroesse. War urspruenglich
# (0.75, 0.35, 1.0, 0.92) - deckte damit die halbe untere Fensterhaelfte ab und
# fing dabei zusaetzlich zu den echten Wurm-Stapeln 2 False-Positives auf
# anderen Inventar-Icons weiter unten ein (Live-Log: Treffer bei y-Fraktion
# 0.76 und 0.86, Scores nur 0.68/0.64, gegenueber 0.997/0.8 fuer die echten
# Stapel). Neu kalibriert auf die tatsaechliche Wurm-Zeile anhand zweier
# Messungen: Referenzbild wurm.png (798x627) hat die Stapel bei y=287 ->
# Fraktion 0.458; ein Live-Screenshot (816x639) hatte sie bei y=291 ->
# Fraktion 0.455. Beide stimmen eng ueberein - das Band unten deckt diese
# Zeile mit komfortablem Rand ab, aber nicht mehr die Zeilen darunter.
WURM_ROI = (0.75, 0.41, 1.0, 0.50)  # (x_min, y_min, x_max, y_max) je 0..1

# Icon ist ca. 20x22px, der Inventar-Slot drumherum typischerweise 32x32px.
# +-5px Erweiterung ergibt eine Hitbox von 30x32px - groesser als das Icon,
# aber knapp unter der Slot-Groesse, damit kein Nachbar-Slot getroffen wird.
WURM_HITBOX_ERWEITERUNG = 5  # Pixel, in jede Richtung ab dem Icon-Mittelpunkt
if WURM_HITBOX_ERWEITERUNG > 10:
    _logger.warning(
        "WURM_HITBOX_ERWEITERUNG=%d ist ungewoehnlich gross - Klick koennte "
        "in einen Nachbar-Slot treffen (Slot-Groesse ca. 32x32px)",
        WURM_HITBOX_ERWEITERUNG,
    )

_wurm_template = cv2.imread(WURM_TEMPLATE_PFAD)
if _wurm_template is None:
    _logger.warning("Wurm-Template nicht gefunden: %s - Wurm-Klick deaktiviert",
                     WURM_TEMPLATE_PFAD)

# Zustaende des Angel-Automaten (siehe bot_schleife()) - das Popup-Fenster
# ist der einzige Trigger zum Angeln, daher nur noch EIN Pruefzustand statt
# der frueheren PRUEFE_POPUP_1-4-Eskalationskette (Wurm-Nachlegen,
# gestaffelte Wartezeiten) und kein "alles versucht"-Fehler-Endzustand mehr.
ZUSTAND_FISCHEN = "FISCHEN"
ZUSTAND_WARTE_EINHOLEN = "WARTE_EINHOLEN"
ZUSTAND_PRUEFE_POPUP = "PRUEFE_POPUP"
ZUSTAND_GESTOPPT = "GESTOPPT"   # Terminalzustand: extern angehalten (siehe bot_anhalten())

# Stop-Mechanismus fuer Aufrufer, die den Bot in einem eigenen Thread laufen
# lassen (z.B. eine GUI). Das stop_event des jeweiligen FischBotKontext wird
# an mehreren Stellen im Zustandsautomaten geprueft (Zustandsuebergaenge,
# Wartezeiten), damit ein Stopp zuverlaessig innerhalb von hoechstens ein
# paar hundert Millisekunden greift.


def bot_anhalten(kontext=None):
    """Signalisiert dem laufenden Bot (egal in welchem Zustand), sich sauber
    zu beenden. Wird vom naechsten Pruefpunkt im Zustandsautomaten aufgegriffen.

    kontext: siehe FischBotKontext - None (Standard) stoppt den ueber den
        Standard-Kontext laufenden Bot (bisheriges Verhalten bei einer
        einzelnen, nicht isolierten Instanz). Fuer eine ueber
        makro_manager.MakroManager.fish_bot_starten() gestartete, auf ein
        bestimmtes Fenster isolierte Instanz muss der DAFUER verwendete
        kontext uebergeben werden (siehe dort) - sonst wird die falsche
        (oder gar keine) Instanz gestoppt."""
    _kontext_aufloesen(kontext).stop_event.set()


def _gestoppt(kontext=None):
    """True, wenn bot_anhalten() (mit demselben 'kontext') aufgerufen wurde
    und der Bot beenden soll."""
    return _kontext_aufloesen(kontext).stop_event.is_set()


def ziel_finden(screenshot_bgr):
    """Sucht die groesste Kontur innerhalb der HSV-Schwelle und liefert deren
    Schwerpunkt (cx, cy) relativ zum Screenshot, oder None wenn nichts passt.
    """
    hsv = cv2.cvtColor(screenshot_bgr, cv2.COLOR_BGR2HSV)
    maske = cv2.inRange(hsv, HSV_UNTERGRENZE, HSV_OBERGRENZE)

    konturen, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not konturen:
        return None

    groesste = max(konturen, key=cv2.contourArea)
    if cv2.contourArea(groesste) < MIN_KONTUR_FLAECHE:
        return None

    momente = cv2.moments(groesste)
    if momente["m00"] == 0:
        return None

    cx = int(momente["m10"] / momente["m00"])
    cy = int(momente["m01"] / momente["m00"])
    return cx, cy


def _fenster_plausibel(fenster, kontext=None):
    """Prueft, ob eine fenster_finden()-Messung plausibel ist, BEVOR sie fuer
    Screenshot/ROI-Berechnungen verwendet wird.

    Zwei Bedingungen muessen erfuellt sein:
      - Breite/Hoehe liegen innerhalb der festen Plausibilitaetsgrenzen
        (FENSTER_BREITE_/HOEHE_MIN/MAX).
      - Die Groesse ist identisch zur zuletzt akzeptierten Groesse DIESES
        Kontexts (oder es gibt noch keine Baseline - dann wird diese Messung
        zur neuen Baseline). Der Cache liegt bewusst auf dem FischBotKontext
        (nicht mehr modulglobal), damit zwei PARALLELE, auf unterschiedlich
        grosse/positionierte Fenster isolierte Instanzen sich nicht
        gegenseitig eine 'Groesse hat sich geaendert'-Warnung ausloesen.

    Eine abweichende Groesse deutet auf eine laufende Fenster-Groessenaenderung
    oder -Verschiebung hin (siehe Vorfall: 993x519 statt der ueblichen
    816x639) - eine ROI, die auf so einer Momentaufnahme basiert, wuerde
    daneben klicken. Bleibt die abweichende Groesse aber im DARAUFFOLGENDEN
    Zyklus IDENTISCH (siehe kontext.fenstergroesse_kandidat), ist die
    Aenderung offensichtlich ABGESCHLOSSEN (kein Resize mehr "in Bewegung")
    - dann wird sie als neue Baseline uebernommen, statt fuer den Rest der
    Bot-Laufzeit auf JEDEM Zyklus erneut abgelehnt zu werden (siehe Vorfall:
    Nutzer hat die Fenster-/Bildschirmgroesse waehrend des Laufens dauerhaft
    veraendert - der Bot haette sonst ab da nie wieder ein Fenster akzeptiert).
    """
    kontext = _kontext_aufloesen(kontext)

    # Manuell/fix vorgegebener Bereich (siehe makro_manager.MakroManager.
    # fish_bot_starten(fenster_bereich=...)): keine GetWindowRect()-Messung,
    # also auch kein Risiko einer transienten Resize-Fehlmessung, die diese
    # Pruefung eigentlich abfangen soll - der Benutzer hat die Groesse bewusst
    # so gewaehlt, IMMER als plausibel behandeln.
    if fenster.get("fenster_fest"):
        return True

    w, h = fenster["w"], fenster["h"]

    if not (FENSTER_BREITE_MIN <= w <= FENSTER_BREITE_MAX
            and FENSTER_HOEHE_MIN <= h <= FENSTER_HOEHE_MAX):
        _logger.warning(
            "%sFenstergroesse %dx%d ausserhalb des plausiblen Bereichs (Breite "
            "%d-%d, Hoehe %d-%d) - Zyklus wird uebersprungen",
            kontext.log_praefix(), w, h, FENSTER_BREITE_MIN, FENSTER_BREITE_MAX,
            FENSTER_HOEHE_MIN, FENSTER_HOEHE_MAX,
        )
        return False

    if kontext.letzte_gueltige_fenstergroesse is not None and (w, h) != kontext.letzte_gueltige_fenstergroesse:
        if kontext.fenstergroesse_kandidat == (w, h):
            # Zweiter Zyklus IN FOLGE mit exakt dieser neuen Groesse - kein
            # transientes Resize mehr, sondern die neue Dauerzustand. Neue
            # Baseline uebernehmen, statt weiter jeden Zyklus abzulehnen.
            _logger.info(
                "%sFenstergroesse dauerhaft auf %dx%d geaendert (zuvor %dx%d) - "
                "neue Baseline uebernommen",
                kontext.log_praefix(), w, h, *kontext.letzte_gueltige_fenstergroesse,
            )
            kontext.letzte_gueltige_fenstergroesse = (w, h)
            kontext.fenstergroesse_kandidat = None
            return True

        _logger.warning(
            "%sFenstergroesse hat sich geaendert: %dx%d (zuletzt gueltig: %dx%d) "
            "- vermutlich Groessenaenderung/Verschiebung im Gange, Zyklus "
            "wird uebersprungen",
            kontext.log_praefix(), w, h, *kontext.letzte_gueltige_fenstergroesse,
        )
        kontext.fenstergroesse_kandidat = (w, h)
        return False

    kontext.fenstergroesse_kandidat = None
    kontext.letzte_gueltige_fenstergroesse = (w, h)
    return True


def fenster_finden_geprueft(kontext=None, fenster_provider=None):
    """fenster_finden() plus Plausibilitaets-Check (siehe _fenster_plausibel()).

    Args:
        kontext: siehe FischBotKontext - None (Standard) nutzt den
            Standard-Kontext (bisheriges Verhalten).
        fenster_provider: optionales Callable[[], dict|None] (siehe
            modules.fenster.fenster_von_hwnd()) - ist es gesetzt, wird GENAU
            dieses Fenster verwendet (frisch bei jedem Aufruf, fuer eine auf
            ein bestimmtes Fenster isolierte Instanz), statt (Standard, None)
            wie bisher das erste METIN2-Fenster per Titel zu suchen.

    Gibt None zurueck, wenn kein Fenster gefunden wurde ODER die gefundene
    Groesse nicht plausibel ist - beide Faelle werden von den bestehenden
    'fenster is None'-Pruefungen in den Zustaenden identisch behandelt: in
    diesem Zyklus nichts tun, beim naechsten Durchlauf erneut versuchen.
    """
    fenster = fenster_provider() if fenster_provider is not None else fenster_finden(FENSTER_TITEL)
    if fenster is None:
        _logger.warning("%sFenster '%s' nicht gefunden", _kontext_aufloesen(kontext).log_praefix(),
                         FENSTER_TITEL)
        return None
    if not _fenster_plausibel(fenster, kontext=kontext):
        return None
    return fenster


def eckpruefung_laden():
    """Laedt die konfigurierten Eckbereich-Bilder + den Eckbereich-Anteil
    (siehe eckpruefung_speichern()/fenster_eckpruefung()) aus
    _ECKPRUEFUNG_DATEI.

    Returns:
        dict: alle 4 Schluessel aus ECKEN -> Bildname (leerer String = fuer
            diese Ecke nicht konfiguriert), PLUS "anteil" -> float (siehe
            ECKBEREICH_ANTEIL_STANDARD/_eckbereich_koordinaten()) - beides mit
            sinnvollen Standardwerten, auch wenn die Datei fehlt oder
            unvollstaendig/beschaedigt ist (kein Fehler).
    """
    daten = {}
    try:
        with open(_ECKPRUEFUNG_DATEI, "r", encoding="utf-8") as f:
            daten = json.load(f)
    except (OSError, ValueError):
        pass
    ergebnis = {ecke: (daten.get(ecke) or "").strip() for ecke in ECKEN}
    try:
        anteil = float(daten.get("anteil", ECKBEREICH_ANTEIL_STANDARD))
    except (TypeError, ValueError):
        anteil = ECKBEREICH_ANTEIL_STANDARD
    ergebnis["anteil"] = max(ECKBEREICH_ANTEIL_MIN, min(ECKBEREICH_ANTEIL_MAX, anteil))
    return ergebnis


def eckpruefung_speichern(daten):
    """Speichert die Eckbereich-Bild-Zuordnung + den Eckbereich-Anteil (siehe
    eckpruefung_laden()) - 'daten' muss nicht alle Schluessel enthalten:
    fehlende ECKEN gelten als leer (nicht konfiguriert), ein fehlendes
    'anteil' faellt auf ECKBEREICH_ANTEIL_STANDARD zurueck. Gilt GLOBAL fuer
    JEDEN Aufrufer der Eckpruefung (Fisch-Bot UND MAKRO TOOLS)."""
    ausgabe = {ecke: (daten.get(ecke) or "").strip() for ecke in ECKEN}
    try:
        anteil = float(daten.get("anteil", ECKBEREICH_ANTEIL_STANDARD))
    except (TypeError, ValueError):
        anteil = ECKBEREICH_ANTEIL_STANDARD
    ausgabe["anteil"] = max(ECKBEREICH_ANTEIL_MIN, min(ECKBEREICH_ANTEIL_MAX, anteil))
    with open(_ECKPRUEFUNG_DATEI, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, indent=2, ensure_ascii=False)


def _eckbereich_koordinaten(ecke, breite, hoehe, anteil):
    """Fensterrelative (x0,y0,x1,y1) des Such-Ausschnitts fuer 'ecke' (siehe
    eckpruefung_laden()['anteil'])."""
    bw = max(1, int(breite * anteil))
    bh = max(1, int(hoehe * anteil))
    if ecke == "oben_links":
        return 0, 0, bw, bh
    if ecke == "oben_rechts":
        return breite - bw, 0, breite, bh
    if ecke == "unten_links":
        return 0, hoehe - bh, bw, hoehe
    return breite - bw, hoehe - bh, breite, hoehe  # "unten_rechts"


def fenster_eckpruefung(fenster):
    """Prueft die konfigurierten Eckbereich-Bilder (siehe eckpruefung_laden())
    gegen 'fenster' - JEDE konfigurierte Ecke wird NUR in ihrem eigenen
    Eckbereich gesucht (siehe _eckbereich_koordinaten()), nicht im ganzen
    Fenster: bestaetigt damit nicht nur, DASS das Bild sichtbar ist, sondern
    auch, dass es an der ERWARTETEN Stelle sitzt.

    Args:
        fenster: dict{"x","y","w","h",...} - das zu pruefende Fenster (siehe
            screenshot_holen()).

    Returns:
        dict{eckenname: bool}: NUR fuer konfigurierte Ecken (unkonfigurierte
            fehlen im Ergebnis komplett - weder Erfolg noch Fehlschlag).
    """
    import bild_erkennung  # spaeter Import: bild_erkennung.py importiert seinerseits fish_bot

    zuordnung = eckpruefung_laden()
    anteil = zuordnung["anteil"]
    ergebnisse = {}
    screenshot = None
    for ecke in ECKEN:
        bild_name = zuordnung[ecke]
        if not bild_name:
            continue
        if screenshot is None:
            screenshot = screenshot_holen(fenster)
        x0, y0, x1, y1 = _eckbereich_koordinaten(ecke, fenster["w"], fenster["h"], anteil)
        ausschnitt = screenshot[y0:y1, x0:x1]
        variante = bild_erkennung.standard_variante(bild_name)
        try:
            treffer = bild_erkennung.bild_finden(ausschnitt, bild_name, bild_erkennung.SCHWELLE_STANDARD,
                                                  variante)
        except bild_erkennung.BildErkennungFehler:
            treffer = None
        ergebnisse[ecke] = treffer is not None
    return ergebnisse


def fenster_eckpruefung_bestehen(fenster, log_praefix=""):
    """Fuehrt fenster_eckpruefung() aus und entscheidet, ob ein Start (Fisch-
    Bot ODER ein normales Bot-Skript ueber makro_manager.MakroManager.
    starte_makro()) fortgesetzt werden darf - loggt dabei selbst (INFO bei
    allen, WARNING bei teilweise, ERROR bei zu wenig erkannten Ecken, siehe
    ECKPRUEFUNG_MIN_TREFFER). Gedacht als gemeinsamer Aufrufpunkt fuer BEIDE
    Start-Wege, damit die Eckpruefung ueberall gleich greift, nicht nur beim
    Fisch-Bot.

    Wird vom Aufrufer NICHT fuer manuell/fest vorgegebene Bereiche
    aufgerufen (siehe fenster.get('fenster_fest')) - dort hat der Benutzer
    die Position bewusst selbst gewaehlt.

    Returns:
        bool: True, wenn der Start fortgesetzt werden darf (auch wenn NICHT
            ALLE konfigurierten Ecken passten, aber mindestens
            ECKPRUEFUNG_MIN_TREFFER von ihnen - oder wenn ueberhaupt keine
            Ecke konfiguriert ist, dann ist die Pruefung ein No-Op). False,
            wenn zu wenige Ecken passten - der Aufrufer sollte den Start
            dann abbrechen.
    """
    ergebnisse = fenster_eckpruefung(fenster)
    if not ergebnisse:
        return True
    treffer = [e for e, ok in ergebnisse.items() if ok]
    fehlgeschlagen = [e for e, ok in ergebnisse.items() if not ok]
    mindest = min(ECKPRUEFUNG_MIN_TREFFER, len(ergebnisse))
    if len(treffer) < mindest:
        _logger.error(
            "%sFenster-Eckpruefung fehlgeschlagen: nur %d/%d konfigurierte Ecke(n) "
            "erkannt (mindestens %d noetig) - nicht erkannt: %s - Abbruch",
            log_praefix, len(treffer), len(ergebnisse), mindest, ", ".join(fehlgeschlagen))
        return False
    if fehlgeschlagen:
        _logger.warning(
            "%sFenster-Eckpruefung: nur %d/%d konfigurierte Ecke(n) erkannt - nicht "
            "erkannt: %s (Start trotzdem fortgesetzt)",
            log_praefix, len(treffer), len(ergebnisse), ", ".join(fehlgeschlagen))
    else:
        _logger.info("%sFenster-Eckpruefung: alle %d konfigurierte(n) Ecke(n) erkannt",
                     log_praefix, len(ergebnisse))
    return True


_dxcam_kamera = None       # lazy erzeugte dxcam-Kamera, siehe _dxcam_holen()
_dxcam_kaputt = False       # True, sobald dxcam einmal fehlgeschlagen ist -
                             # dann fuer den Rest des Prozesses direkt auf
                             # ImageGrab ausweichen, statt bei jedem Tick neu
                             # zu scheitern


def _dxcam_holen():
    """Liefert die (einmalig erzeugte) dxcam-Kamera, oder None wenn dxcam
    nicht installiert ist oder auf diesem System nicht funktioniert.

    dxcam nutzt die DXGI Desktop Duplication API und ist dadurch um
    Groessenordnungen schneller als PIL ImageGrab (per Messung auf dieser
    VirtualBox-VM: ImageGrab ~30-70ms/Aufruf unabhaengig von der
    Ausschnittsgroesse, dxcam ~0-3ms/Aufruf) - ImageGrab war der dominante
    Anteil der ~100-150ms Mess-Zyklus-Zeit, nicht die (bereits per ROI
    eingegrenzte) cv2-Verarbeitung. dxcam.create() wird bewusst nur EINMAL
    pro Prozess aufgerufen (kostet selbst ~130ms) und danach wiederverwendet.

    output_color="BGR" laesst dxcam direkt im von OpenCV erwarteten Format
    liefern, ohne zusaetzliche cv2.cvtColor()-Konvertierung.
    """
    global _dxcam_kamera, _dxcam_kaputt
    if _dxcam_kamera is not None or _dxcam_kaputt:
        return _dxcam_kamera
    if dxcam is None:
        _dxcam_kaputt = True
        return None
    try:
        _dxcam_kamera = dxcam.create(output_color="BGR")
    except Exception as e:
        _logger.warning("dxcam.create() fehlgeschlagen (%s) - falle auf PIL "
                         "ImageGrab zurueck", e)
        _dxcam_kaputt = True
        return None
    return _dxcam_kamera


def _screenshot_dxcam(box):
    """Versucht einen Screenshot von 'box' (absolute Bildschirmkoordinaten,
    (x0, y0, x1, y1)) per dxcam. Gibt None zurueck, wenn dxcam nicht
    verfuegbar ist oder (trotz new_frame_only=False) kein Frame liefert -
    der Aufrufer faellt dann auf ImageGrab zurueck.
    """
    kamera = _dxcam_holen()
    if kamera is None:
        return None
    try:
        return kamera.grab(region=box, new_frame_only=False)
    except Exception as e:
        _logger.warning("dxcam.grab() fehlgeschlagen (%s) - falle auf PIL "
                         "ImageGrab zurueck", e)
        return None


def _screenshot_pil(box):
    """Screenshot von 'box' (absolute Bildschirmkoordinaten) per PIL
    ImageGrab - Fallback, wenn dxcam nicht verfuegbar ist/fehlschlaegt."""
    bild = ImageGrab.grab(bbox=box)
    return cv2.cvtColor(np.array(bild), cv2.COLOR_RGB2BGR)


def screenshot_holen(fenster, region=None):
    """Screenshot des Fensterbereichs als BGR-Array (fuer OpenCV).

    Ohne region wird das GESAMTE Fenster erfasst (mit Groessen-Diagnose,
    siehe unten). Mit region=(x0, y0, x1, y1) (fensterrelative Pixel-
    koordinaten) wird nur dieser Ausschnitt erfasst - deutlich schneller als
    das ganze Fenster (siehe _mess_loop()/_popup_roi(), die nach der ersten
    Popup-Erkennung nur noch einen Ausschnitt um die zuletzt bekannte
    Popup-Position greifen, um die MESS_INTERVALL_S-Zielrate zu erreichen).

    Nutzt bevorzugt dxcam (siehe _dxcam_holen()), faellt bei Nichtverfuegbarkeit
    oder Fehlern automatisch auf PIL ImageGrab zurueck.
    """
    if region is not None:
        x0, y0, x1, y1 = region
        box = (fenster["x"] + x0, fenster["y"] + y0, fenster["x"] + x1, fenster["y"] + y1)
    else:
        box = (fenster["x"], fenster["y"], fenster["x"] + fenster["w"], fenster["y"] + fenster["h"])

    ergebnis = _screenshot_dxcam(box)
    if ergebnis is None:
        ergebnis = _screenshot_pil(box)

    if region is not None:
        return ergebnis

    # DIAGNOSE (Wurm-Klick-Koordinatenproblem): erfasste Bildgroesse muss
    # exakt fenster["w"]/["h"] entsprechen. Weicht sie ab, liefern
    # GetWindowRect (fenster.x/y/w/h) und die Screenshot-Quelle unterschiedliche
    # Koordinatensysteme (z.B. DPI-Skalierung) - dann waeren alle aus dem
    # Screenshot abgeleiteten Klickpositionen falsch skaliert.
    erfasst_h, erfasst_w = ergebnis.shape[:2]
    if (erfasst_w, erfasst_h) != (fenster["w"], fenster["h"]):
        _logger.warning(
            "screenshot_holen: erfasste Groesse %dx%d weicht von fenster %dx%d ab "
            "(fenster=%s) - moegliches DPI-/Skalierungsproblem!",
            erfasst_w, erfasst_h, fenster["w"], fenster["h"], fenster,
        )

    return ergebnis


def _popup_roi(popup, fenster_breite, fenster_hoehe):
    """Berechnet einen Bildausschnitt (x0, y0, x1, y1, fensterrelativ) rund
    um eine zuletzt bekannte Popup-Position, gross genug um Ring UND Fisch
    vollstaendig zu erfassen (Radius + MESS_ROI_PUFFER_PX in jede Richtung),
    aber deutlich kleiner als das gesamte Fenster. Auf die Fenstergrenzen
    begrenzt.
    """
    cx, cy, r = popup
    puffer = r + MESS_ROI_PUFFER_PX
    x0 = max(0, int(cx - puffer))
    y0 = max(0, int(cy - puffer))
    x1 = min(fenster_breite, int(cx + puffer))
    y1 = min(fenster_hoehe, int(cy + puffer))
    return x0, y0, x1, y1


def maus_bewegen(x, y, maus=None):
    """Bewegt den Cursor an eine absolute Bildschirmposition.

    Nutzt die HID-Maus (maus.maus_bewegen -> MOVE_ABS), da SetCursorPos in
    dieser Session nicht funktioniert. Falls keine HID-Maus uebergeben wird,
    faellt die Funktion auf die Windows-API zurueck.
    """
    if maus is not None:
        maus.maus_bewegen_abs(int(x), int(y))
    else:
        user32.SetCursorPos(int(x), int(y))


def fisch_im_kreis(punkt, mittelpunkt, radius):
    """Prueft, ob 'punkt' (Fischmitte) innerhalb des gemessenen Popup-Radius
    plus RING_PUFFER_PX liegt. Beide (x, y).

    Der gemessene Radius kommt jetzt aus der Popup-BOX (siehe
    popup_erkennung.py), nicht mehr aus einer exakt umschliessenden Ring-
    Linie - deshalb wird er per Puffer VERGROESSERT (Klick-Hitbox groesser
    als der sichtbare Kreis, damit auch knapp ausserhalb noch geklickt
    werden kann), statt wie zuvor per KREIS_FAKTOR verengt.
    """
    radius_effektiv = radius + RING_PUFFER_PX
    dx = punkt[0] - mittelpunkt[0]
    dy = punkt[1] - mittelpunkt[1]
    return (dx * dx + dy * dy) <= (radius_effektiv * radius_effektiv)


def _distanz(punkt, mittelpunkt):
    """Euklidischer Abstand zwischen zwei (x, y)-Punkten - fuer den CSV-Logger."""
    dx = punkt[0] - mittelpunkt[0]
    dy = punkt[1] - mittelpunkt[1]
    return (dx * dx + dy * dy) ** 0.5


def wurm_stapel_finden(screenshot_bgr):
    """Findet alle Wurm-Icons im Inventarbereich per Template-Matching.

    Sucht nur innerhalb von WURM_ROI (Inventar-Bereich), nicht im gesamten
    Screenshot - dasselbe Icon kann zusaetzlich in der Schnellzugriffsleiste
    haengen, das soll hier nicht mitgezaehlt werden.

    Returns:
        list[tuple[float, int, int]]: (score, x, y) je Fund, nach Score
            absteigend sortiert (sicherster Treffer zuerst). x, y sind
            Icon-Mittelpunkte relativ zum Screenshot. Leer, wenn kein
            Wurm-Icon gefunden wurde oder kein Template geladen ist.
    """
    if _wurm_template is None:
        return []

    h, w = screenshot_bgr.shape[:2]
    x0, y0 = int(w * WURM_ROI[0]), int(h * WURM_ROI[1])
    x1, y1 = int(w * WURM_ROI[2]), int(h * WURM_ROI[3])
    roi = screenshot_bgr[y0:y1, x0:x1]

    # DIAGNOSE: ROI-Box im Screenshot-Koordinatensystem protokollieren, damit
    # sich nachvollziehen laesst, welcher Bildbereich tatsaechlich durchsucht
    # wurde (Inventar offen/an erwarteter Stelle? Fensterformat abweichend?).
    _logger.debug(
        "wurm_stapel_finden: Screenshot=%dx%d (BxH), WURM_ROI=%s -> Box (%d,%d)-(%d,%d) [%dx%d px]",
        w, h, WURM_ROI, x0, y0, x1, y1, x1 - x0, y1 - y0,
    )

    th, tw = _wurm_template.shape[:2]
    if roi.shape[0] < th or roi.shape[1] < tw:
        _logger.debug(
            "wurm_stapel_finden: ROI (%dx%d) kleiner als Template (%dx%d) - abgebrochen",
            roi.shape[1], roi.shape[0], tw, th,
        )
        return []

    ergebnis = cv2.matchTemplate(roi, _wurm_template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(ergebnis >= WURM_MATCH_SCHWELLE)
    treffer = sorted(
        ((float(ergebnis[y, x]), x + tw // 2, y + th // 2) for x, y in zip(xs, ys)),
        reverse=True,
    )
    # DIAGNOSE: Anzahl/beste Scores der Rohtreffer - viele Treffer nahe der
    # Schwelle (statt weniger Treffer mit hohem Score nahe 1.0) deuten auf
    # False-Positives (z.B. Hintergrundtextur statt echtem Icon) hin.
    _logger.debug(
        "wurm_stapel_finden: %d Rohtreffer >= %.2f, Top-Scores=%s",
        len(treffer), WURM_MATCH_SCHWELLE,
        [round(s, 3) for s, _, _ in treffer[:5]],
    )

    # Nicht-Maximum-Unterdrueckung: nahe beieinanderliegende Treffer (derselbe
    # Slot, mehrere Pixel mit hohem Score) auf einen Punkt zusammenfassen.
    # 'treffer' ist bereits nach Score absteigend sortiert, daher behaelt das
    # hier jeweils den besten Score pro Slot.
    kandidaten = []  # (score, mx, my) in ROI-Koordinaten
    for score, mx, my in treffer:
        if all((mx - bx) ** 2 + (my - by) ** 2 > WURM_MIN_ABSTAND_PX ** 2
               for _, bx, by in kandidaten):
            kandidaten.append((score, mx, my))

    # Zurueck in Screenshot-Koordinaten (ROI-Offset addieren), nach Score
    # absteigend sortiert (sicherster Treffer zuerst).
    kandidaten = [(score, mx + x0, my + y0) for score, mx, my in kandidaten]
    kandidaten.sort(key=lambda k: k[0], reverse=True)
    _logger.debug(
        "wurm_stapel_finden: %d Stapel nach NMS (Score, x, y): %s",
        len(kandidaten), [(round(s, 3), x, y) for s, x, y in kandidaten],
    )
    return kandidaten


def wurm_klicken(maus, fenster, screenshot_bgr):
    """Klickt den Wurm-Stapel mit dem hoechsten Match-Score im Inventar an.

    Es wird nur geklickt, wenn der beste Treffer WURM_SCORE_SICHER erreicht.
    Schwaechere Treffer sind vermutlich False-Positives auf Hintergrundtextur
    statt einem echten Icon (siehe wurm_stapel_finden()) - in dem Fall wird
    NICHT geklickt, um keinen Zufallsklick auszuloesen.
    """
    # DIAGNOSE: Zeitpunkt und Fensterdaten protokollieren, zu denen dieser
    # Screenshot fuer den Wurm-Klick entstanden ist - zum Abgleich mit den
    # fenster-Werten aus dem vorangegangenen FISCHEN-Zustand.
    erfasst_h, erfasst_w = screenshot_bgr.shape[:2]
    _logger.debug(
        "wurm_klicken @ %.3f: fenster=%s Screenshot-Groesse=%dx%d (BxH)",
        time.time(), fenster, erfasst_w, erfasst_h,
    )

    stapel = wurm_stapel_finden(screenshot_bgr)
    if not stapel:
        _logger.warning("Kein Wurm-Stapel im Inventar gefunden")
        return False

    score, ziel_x, ziel_y = stapel[0]
    if score < WURM_SCORE_SICHER:
        _logger.warning(
            "Bester Wurm-Treffer zu unsicher (Score %.3f < %.2f) bei (%d, %d) - "
            "kein Klick, vermutlich False-Positive auf Hintergrund",
            score, WURM_SCORE_SICHER, ziel_x, ziel_y,
        )
        return False

    klick_x = ziel_x + random.randint(-WURM_HITBOX_ERWEITERUNG, WURM_HITBOX_ERWEITERUNG)
    klick_y = ziel_y + random.randint(-WURM_HITBOX_ERWEITERUNG, WURM_HITBOX_ERWEITERUNG)

    bildschirm_x = fenster["x"] + klick_x
    bildschirm_y = fenster["y"] + klick_y

    # Hitbox-Groesse = Icon-Groesse + Erweiterung nach allen Seiten (siehe
    # WURM_HITBOX_ERWEITERUNG-Kommentar: 20x22 Icon -> 30x32 Hitbox bei +-5px).
    th, tw = _wurm_template.shape[:2]
    hitbox_w = tw + 2 * WURM_HITBOX_ERWEITERUNG
    hitbox_h = th + 2 * WURM_HITBOX_ERWEITERUNG
    _logger.debug(
        "Wurm-Hitbox: %dx%d px um (%d, %d) [Score %.3f], gewaehlter Klickpunkt (%d, %d)",
        hitbox_w, hitbox_h, ziel_x, ziel_y, score, klick_x, klick_y,
    )
    _logger.info("Klicke (rechts) Wurm-Stapel bei (%d, %d)", bildschirm_x, bildschirm_y)
    _logger.info("maus_zieht_zu=(%d, %d)", bildschirm_x, bildschirm_y)
    _fenster_fokussiert_sicherstellen(fenster.get("hwnd"))
    maus_bewegen(bildschirm_x, bildschirm_y, maus)
    # Dieselbe kurze Vorsichtsmarge wie im FISCHEN-Klick-Loop (siehe dort,
    # _klick_loop()): maus_bewegen() blockiert zwar schon bis zur MOVED-
    # Bestaetigung der Firmware, aber der Spiel-Client braucht zusaetzlich
    # eine kurze (unbekannte, nicht messbare) Latenz, um den neuen Cursor
    # INTERN zu registrieren, bevor ein Klick an dieser Position ankommt -
    # ohne diese Marge geht der Klick sonst ins Leere/an die alte Position
    # (derselbe historische Bug wie beim Fisch-Klick, dort bereits behoben,
    # hier aber bisher gefehlt).
    time.sleep(0.02)
    if not maus.klick_rechts():
        _logger.warning("Wurm-Klick fehlgeschlagen (keine Bestaetigung von der HID-Maus)")
        return False
    return True


def _popup_gueltig(popup):
    """Filtert Popup-Erkennungen mit unplausiblem Radius heraus (Fehlerkennung).

    Ein echtes Angeln-Popup hat einen (aus der Box gemessenen) Radius
    zwischen MIN_RADIUS und MAX_RADIUS; kleinere Treffer sind vermutlich
    Bildrauschen, groessere andere helle/runde UI-Elemente im Screenshot
    (siehe MAX_RADIUS-Kommentar - beobachtete Fehlerkennungen bei ~166-171px,
    verglichen mit ~64px fuer den echten Ring).
    """
    if popup is not None and not (MIN_RADIUS <= popup[2] <= MAX_RADIUS):
        return None
    return popup


def _popup_mit_haltezeit(popup, kontext=None):
    """Ueberbrueckt kurzes Flackern von popup_finden().

    Wird gerade kein Popup erkannt, aber es gab innerhalb der letzten
    POPUP_HALTEZEIT Sekunden eine Erkennung, wird deren Position weiterverwendet.
    """
    kontext = _kontext_aufloesen(kontext)
    jetzt = time.time()

    if popup is not None:
        kontext.letzte_popup_position = popup
        kontext.letzte_popup_zeit = jetzt
        return popup

    if (kontext.letzte_popup_position is not None
            and (jetzt - kontext.letzte_popup_zeit) <= POPUP_HALTEZEIT):
        return kontext.letzte_popup_position

    return None


def _status_loggen(popup, ziel, ring_treffer, kontext=None):
    """Loggt den Erkennungsstatus eines Zyklus, aber hoechstens 1x pro Sekunde."""
    kontext = _kontext_aufloesen(kontext)
    jetzt = time.time()
    if jetzt - kontext.letzter_status_log < STATUS_LOG_INTERVALL:
        return
    kontext.letzter_status_log = jetzt
    _logger.debug(
        "%spopup=%s ziel=%s im_ring=%s",
        kontext.log_praefix(),
        popup if popup is not None else "kein Popup",
        ziel if ziel is not None else "kein Ziel",
        ring_treffer,
    )


def _popup_jetzt_sichtbar(fenster):
    """Einmalige, ungeglaettete Pruefung: ist gerade ein gueltiges Popup
    (Radius >= MIN_RADIUS) sichtbar?

    Im Gegensatz zu _popup_mit_haltezeit() (fuer kontinuierliches Polling
    waehrend FISCHEN) ist das hier ein einzelner Schnappschuss-Check, wie er
    in den PRUEFE_POPUP_*-Zustaenden nach einer Wartezeit gebraucht wird.
    """
    screenshot = screenshot_holen(fenster)
    return _popup_gueltig(popup_finden(screenshot)) is not None


def warte_mit_bonus(basis_sekunden, kontext=None):
    """Wartet basis_sekunden * Zufallsfaktor - 0 bis 40% Bonus auf die Basiszeit.

    Macht feste Wartezeiten (3.5s, 2s, ...) weniger vorhersagbar/robotisch.
    In kurzen Schritten unterteilt (statt einem einzigen time.sleep()), damit
    bot_anhalten() auch waehrend einer laufenden Wartezeit innerhalb von
    hoechstens ~100ms greift.
    """
    ende = time.time() + basis_sekunden * random.uniform(1.0, 1.4)
    while time.time() < ende:
        if _gestoppt(kontext):
            return
        time.sleep(min(0.1, ende - time.time()))


_pynput_tastatur = _PynputController()


def leertaste_tippen(maus, hwnd=None):
    """Tippt die Leertaste ueber pynput (SendInput), NICHT ueber die
    Arduino-HID-Firmware: Firmware-Tastendruecke kamen trotz bestaetigtem ACK
    nicht zuverlaessig in Metin2 an (siehe aktion_skript.py/test_taste_skript*.py),
    waehrend pynput nachweislich ankommt. 'maus' bleibt Parameter (Aufrufer
    unveraendert), wird fuer die Taste selbst aber nicht mehr benutzt.

    hwnd: optionales Fenster-Handle - ist es gesetzt (isolierte Instanz auf
        EINES von MEHREREN offenen METIN2-Fenstern, siehe FischBotKontext),
        wird dieses Fenster ERST per win32gui.SetForegroundWindow() in den
        Vordergrund geholt (SendInput liefert IMMER an das aktuell
        fokussierte Fenster, unabhaengig davon, fuer welches Fenster die
        Taste eigentlich gedacht war - siehe aktion_skript._fokussiere_metin2(),
        dieselbe Notwendigkeit). None (Standard, einzelne nicht isolierte
        Instanz) ueberspringt den Fokuswechsel komplett (bisheriges,
        overhead-freies Verhalten - dort ist ohnehin nur ein Fenster offen)."""
    if hwnd:
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(FOKUS_WARTEZEIT_S)
        except Exception as e:
            _logger.warning("Fenster (hwnd=%s) konnte nicht fokussiert werden: %s", hwnd, e)
    try:
        _pynput_tastatur.press(_PynputKey.space)
        time.sleep(0.1)
        _pynput_tastatur.release(_PynputKey.space)
        return True
    except Exception as e:
        _logger.warning("Leertaste-Tipp (pynput) fehlgeschlagen: %s", e)
        return False


def _fenster_fokussiert_sicherstellen(hwnd, kontext=None):
    """Bringt hwnd nur dann per win32gui.SetForegroundWindow() in den
    Vordergrund, wenn es das nicht ohnehin BEREITS ist - siehe _klick_loop(),
    der das VOR jedem Maus-Klick aufruft: die HID-Firmware bewegt/klickt den
    ECHTEN Windows-Cursor wie eine physische Maus, und ein Klick auf ein
    NICHT fokussiertes/aktives Fenster wird von Metin2 i.d.R. ignoriert
    (bestaetigter Regressions-Fall: seit der Fenster-Isolation auf mehrere
    parallele Instanzen/Fenster - siehe FischBotKontext - kann JEDE andere
    Instanz (z.B. per leertaste_tippen()) sowie ein zeitgleich laufendes
    Makro-Skript zwischenzeitlich ein ANDERES Fenster fokussieren, wodurch
    Klicks dieser Instanz plausibel ins Leere gehen, OBWOHL 'KLICK GESENDET'
    geloggt wird). Der bereits-fokussiert-Check haelt den haeufigen Fall
    (Fenster ist schon vorne) auf dem klickkritischen Pfad overhead-frei -
    nur bei tatsaechlichem Fokuswechsel entsteht die kurze Wartezeit
    (KLICK_FOKUS_WARTEZEIT_S)."""
    if not hwnd:
        return
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(KLICK_FOKUS_WARTEZEIT_S)
    except Exception as e:
        _logger.warning("%sFenster (hwnd=%s) vor Klick konnte nicht fokussiert werden: %s",
                         _kontext_aufloesen(kontext).log_praefix(), hwnd, e)


def _csv_logger_init(kontext=None):
    """Oeffnet die CSV-Datei DIESES Kontexts neu (bestehender Inhalt wird
    ueberschrieben) und schreibt den Spalten-Header - siehe
    _csv_pfad_fuer_label() (per Label eine EIGENE Datei, damit parallele
    Instanzen sich nicht gegenseitig ueberschreiben). Wird in bot_starten()
    beim Start aufgerufen.

    Bewusst nicht auf Modulebene ausgefuehrt, damit ein blosses 'import
    fish_bot' (z.B. fuer Tests/einzelne Funktionsaufrufe) keine Datei
    unbeabsichtigt anlegt/ueberschreibt.
    """
    kontext = _kontext_aufloesen(kontext)
    kontext.programmstart = time.time()
    pfad = _csv_pfad_fuer_label(kontext.label)
    kontext.csv_datei = open(pfad, "w", newline="", encoding="utf-8")
    kontext.csv_writer = csv.writer(kontext.csv_datei)
    kontext.csv_writer.writerow(CSV_SPALTEN)
    kontext.csv_datei.flush()
    _logger.info("%sCSV-Datenlogger initialisiert: %s", kontext.log_praefix(), pfad)


def _csv_zeile_schreiben(fenster, popup, ziel, distanz, ring_treffer, klick_gesendet,
                          latenz_ms, fisch_speed, kontext=None):
    """Schreibt eine Zeile FISCHEN-Diagnosedaten in die CSV-Datei DIESES
    Kontexts (falls der Logger via _csv_logger_init() initialisiert wurde)
    und flusht sofort, damit bei einem Abbruch keine Zeile verloren geht.

    Reines Logging - hat keinerlei Einfluss auf die Klick-Logik in
    _mess_loop()/_klick_loop(). Thread-sicher (siehe kontext.csv_lock), da
    beide Loops aus ihrem jeweils eigenen Thread heraus schreiben.
    """
    kontext = _kontext_aufloesen(kontext)
    if kontext.csv_writer is None:
        return
    timestamp_ms = int((time.time() - kontext.programmstart) * 1000)
    zeile = [
        timestamp_ms,
        f"{fenster['w']}x{fenster['h']}",
        1 if popup is not None else 0,
        popup[2] if popup is not None else "",
        1 if ziel is not None else 0,
        ziel[0] if ziel is not None else "",
        ziel[1] if ziel is not None else "",
        f"{distanz:.2f}" if distanz is not None else "",
        1 if ring_treffer else 0,
        1 if klick_gesendet else 0,
        MESS_INTERVALL_S,
        f"{latenz_ms:.1f}" if latenz_ms is not None else "",
        f"{fisch_speed:.1f}" if fisch_speed is not None else "",
    ]
    with kontext.csv_lock:
        kontext.csv_writer.writerow(zeile)
        kontext.csv_datei.flush()


def _fisch_geschwindigkeit(letzte_fisch, ziel, jetzt):
    """Schaetzt die Fischgeschwindigkeit in px/s aus der zuletzt bekannten
    Fischposition (siehe _mess_loop(), das 'letzte_fisch' zwischen Ticks
    durchreicht). None, wenn keine Vergleichsposition oder kein aktuelles
    Ziel vorliegt.
    """
    if letzte_fisch is None or ziel is None:
        return None
    lx, ly, lt = letzte_fisch
    dt = jetzt - lt
    if dt <= 0:
        return None
    return _distanz(ziel, (lx, ly)) / dt


class FischGlaetter:
    """Filtert die rohe Fisch-Erkennung zweistufig gegen Rauschen (siehe
    MAX_SPRUNG_PX/MAX_VERWORFENE_SERIE/GLAETTER_FENSTER fuer die Konstanten):

    1. Ausreisser-Filter: eine neue rohe Position, die mehr als
       MAX_SPRUNG_PX vom letzten AKZEPTIERTEN Punkt entfernt ist, gilt als
       Glitzer/Schatten/Aussetzer und wird verworfen - die letzte
       akzeptierte Position bleibt fuer diesen Tick bestehen (siehe
       gefilterte_position()). Nach MAX_VERWORFENE_SERIE aufeinanderfolgenden
       Verwerfungen wird der naechste Punkt zwangsweise akzeptiert, damit ein
       echter weiter Sprung (z.B. neuer Fisch an anderer Ring-Position) den
       Filter nicht dauerhaft einfrieren laesst.
    2. Median (statt gleitendem Durchschnitt) ueber die letzten
       GLAETTER_FENSTER AKZEPTIERTEN Positionen (siehe position()) - ein
       Mittelwert wird von einzelnen Ausreissern verzerrt, der Median
       ignoriert sie komplett. Bei einer ERZWUNGENEN Akzeptanz (s.o.) wird
       das Median-Fenster geleert und faengt bei der neuen Position frisch
       an - sonst wuerde der Median trotz Ausreisser-Filter noch mehrere
       Ticks lang zur alten (jetzt falschen) Position hin verzerrt bleiben,
       und der "friert nicht ein"-Zweck des 3er-Limits waere unterlaufen.

    position(x, y) gibt die MEDIAN-GEGLAETTETE Position zurueck (fuer
    Ring-Check und Klickpunkt). Die Stillstand-Erkennung (siehe
    fisch_steht_still()) soll dagegen auf der GEFILTERTEN, aber NICHT
    median-geglaetteten Positionshistorie laufen (siehe gefilterte_position())
    - deutlich schneller reagierend als der Median, aber bereits robust
    gegen einzelne Glitzer-Ausreisser.
    """

    def __init__(self, fenster=GLAETTER_FENSTER, max_sprung_px=MAX_SPRUNG_PX,
                 max_verworfene_serie=MAX_VERWORFENE_SERIE):
        self._fenster = fenster
        self._max_sprung_px = max_sprung_px
        self._max_verworfene_serie = max_verworfene_serie
        self._letzte_akzeptierte = None  # (x, y) oder None (noch kein Punkt gesehen)
        self._verworfene_serie = 0
        self._median_positionen = []     # letzte (bis zu) 'fenster' AKZEPTIERTE Positionen

    def position(self, x, y):
        """Verarbeitet eine neue rohe Fisch-Position (Ausreisser-Filter +
        Median, siehe Klassendoku) und gibt die aktuelle median-geglaettete
        Position als (int, int) zurueck."""
        erzwungen = False
        if self._letzte_akzeptierte is None:
            akzeptiert = True
        else:
            sprung = math.dist((x, y), self._letzte_akzeptierte)
            if sprung <= self._max_sprung_px:
                akzeptiert = True
            elif self._verworfene_serie >= self._max_verworfene_serie:
                akzeptiert = True
                erzwungen = True
            else:
                akzeptiert = False

        if akzeptiert:
            self._letzte_akzeptierte = (x, y)
            self._verworfene_serie = 0
            if erzwungen:
                self._median_positionen.clear()
            self._median_positionen.append((x, y))
            if len(self._median_positionen) > self._fenster:
                self._median_positionen.pop(0)
        else:
            self._verworfene_serie += 1
            # _letzte_akzeptierte bleibt unveraendert - die Position "haelt".

        xs = [p[0] for p in self._median_positionen]
        ys = [p[1] for p in self._median_positionen]
        return int(round(statistics.median(xs))), int(round(statistics.median(ys)))

    def gefilterte_position(self):
        """Die zuletzt AKZEPTIERTE (Ausreisser-gefilterte, aber NICHT
        median-geglaettete) Position, oder None vor dem ersten position()-
        Aufruf - fuer die Stillstand-Erkennung, siehe Klassendoku."""
        return self._letzte_akzeptierte

    def reset(self):
        """Setzt den Glaetter vollstaendig zurueck (z.B. fuer einen neuen Fisch)."""
        self._letzte_akzeptierte = None
        self._verworfene_serie = 0
        self._median_positionen.clear()


def fisch_steht_still(historie):
    """True, wenn sich der Fisch zwischen der aeltesten und der neuesten der
    letzten STILLSTAND_FRAMES GEFILTERTEN (Ausreisser-bereinigten, aber NICHT
    median-geglaetteten) Positionen um weniger als STILLSTAND_SCHWELLE_PX
    bewegt hat.

    Arbeitet bewusst auf FischGlaetter.gefilterte_position() (Ausreisser
    bereits verworfen), nicht auf der ROHEN Erkennung direkt und nicht auf
    der median-geglaetteten Endposition - der Median reagiert erst mit ein
    paar Ticks Verzoegerung auf echten Stillstand, waehrend die gefilterte
    (aber ungemittelte) Position ihn sofort zeigt, ohne dabei durch einzelne
    Glitzer-Sprunge (50-100px, siehe FischGlaetter) faelschlich als Bewegung
    gewertet zu werden.

    Ersetzt die fruehere Vorhersage-basierte Klick-Logik (Speed-/Linien-
    Extrapolation): Die rohe Fisch-Erkennung rauscht zu stark (Spruenge
    >60px zwischen aufeinanderfolgenden Erkennungen, siehe analyse_fisch.py),
    um eine zuverlaessige Vorhersage der zukuenftigen Position zu erlauben.
    Statt zu raten, WOHIN sich der Fisch als naechstes bewegt, wird jetzt
    abgewartet, bis er stillsteht, und dann auf die (geglaettete) aktuelle
    Position geklickt.

    Args:
        historie: Liste von gefilterten (x, y)-Tupeln, chronologisch
            (aeltestes zuerst) - siehe gefilterte_historie in _mess_loop().
            Ein fehlender Messwert (kein Ziel erkannt) darf NICHT in diese
            Historie eingehen - siehe _mess_loop(), das die Historie nur bei
            einem tatsaechlichen Treffer erweitert, sonst gilt der Tick als
            "nicht still" (kein Schein-Stillstand bei Aussetzern).
    """
    if len(historie) < STILLSTAND_FRAMES:
        return False
    letzte = historie[-STILLSTAND_FRAMES:]
    distanz = math.dist(letzte[0], letzte[-1])
    return distanz < STILLSTAND_SCHWELLE_PX


class MessZustand:
    """Thread-sicherer Container fuer die neueste Messung aus _mess_loop().

    _klick_loop() liest ausschliesslich ueber momentaufnahme() daraus - so
    bekommt die Klick-Logik immer den zuletzt bekannten Stand, unabhaengig
    davon, wie oft sie selbst pollt (siehe KLICK_LOOP_INTERVALL_S), ohne dass
    Mess- und Klick-Loop sich gegenseitig blockieren.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.fenster = None
        self.popup = None          # (cx, cy, r) oder None
        self.fisch_glatt = None    # geglaettete Fischposition (x, y) oder None
        self.zeitpunkt = 0.0       # time.time() der letzten Messung
        self.steht_still = False
        self.ergebnis = None       # Folgezustand, sobald _mess_loop() FISCHEN beendet

    def aktualisieren(self, fenster, popup, fisch_glatt, zeitpunkt, steht_still):
        with self._lock:
            self.fenster = fenster
            self.popup = popup
            self.fisch_glatt = fisch_glatt
            self.zeitpunkt = zeitpunkt
            self.steht_still = steht_still

    def momentaufnahme(self):
        """Gibt (fenster, popup, fisch_glatt, zeitpunkt, steht_still) als
        konsistente Einzel-Kopie zurueck (kein Wert kann waehrend des Lesens
        von einem parallelen aktualisieren()-Aufruf ueberschrieben werden)."""
        with self._lock:
            return self.fenster, self.popup, self.fisch_glatt, self.zeitpunkt, self.steht_still


def _mess_loop(mess_zustand, fertig_event, kontext=None, fenster_provider=None):
    """SCHNELLER MESS-LOOP (eigener Thread, siehe zustand_fischen()): erfasst
    kontinuierlich Popup- und Fischposition, OHNE selbst die Maus zu bewegen
    oder zu klicken - das erledigt ausschliesslich _klick_loop() im
    Hauptthread, anhand der hier in 'mess_zustand' abgelegten Werte.

    Screenshot-Strategie: solange bereits eine Popup-Position bekannt ist,
    wird NUR ein Ausschnitt um diese Position erfasst (siehe _popup_roi()) -
    deutlich schneller als das ganze Fenster und damit der Hauptgrund, warum
    MESS_INTERVALL_S (~10-15x/s) ueberhaupt erreichbar ist. Findet dieser
    Ausschnitt kein Popup mehr, wird zur Sicherheit sofort im GANZEN Fenster
    nachgesehen, bevor 'Popup zu' gilt (der Ausschnitt koennte knapp daneben
    liegen, nicht nur weil das Popup wirklich geschlossen wurde). Ohne
    bekannte Popup-Position (erster Tick, oder nachdem sie verloren ging)
    wird ebenfalls das ganze Fenster erfasst.

    Fischposition: wird ueber FischGlaetter zweistufig gefiltert (Ausreisser-
    Filter + Median ueber GLAETTER_FENSTER akzeptierte Positionen, siehe
    dort) - das median-geglaettete Ergebnis ist die Position, die
    _klick_loop() fuer den Ring-Check UND den Klickpunkt verwendet. Die
    Stillstand-Erkennung (fisch_steht_still()) laeuft dagegen auf der
    GEFILTERTEN, aber NICHT median-geglaetteten Positionshistorie (siehe
    FischGlaetter.gefilterte_position()), damit sie schnell reagiert, ohne
    von einzelnen Glitzer-Ausreissern getaeuscht zu werden.

    Setzt fertig_event UND mess_zustand.ergebnis, sobald FISCHEN enden soll
    (Popup entprellt geschlossen, oder bot_anhalten()) - zustand_fischen()
    wartet auf beides, um den Folgezustand zu bestimmen.
    """
    popup_war_je_offen = False
    geschlossen_seit = None
    letzte_popup_box = None  # (cx, cy, r) - steuert den ROI-Ausschnitt der naechsten Messung
    glaetter = FischGlaetter()
    gefilterte_historie = []  # Ausreisser-gefilterte (nicht median-geglaettete) Positionen fuer fisch_steht_still()
    letzte_fisch = None  # (x, y, zeitpunkt) - nur fuer die in der CSV geloggte Geschwindigkeit

    naechste_messung = time.time()
    while True:
        if _gestoppt(kontext):
            mess_zustand.ergebnis = ZUSTAND_GESTOPPT
            fertig_event.set()
            return

        fenster = fenster_finden_geprueft(kontext=kontext, fenster_provider=fenster_provider)
        if fenster is None:
            time.sleep(MESS_INTERVALL_S)
            naechste_messung = time.time()
            continue

        region = (_popup_roi(letzte_popup_box, fenster["w"], fenster["h"])
                   if letzte_popup_box is not None else None)
        screenshot = screenshot_holen(fenster, region=region)
        t_screenshot = time.time()
        versatz_x, versatz_y = region[:2] if region is not None else (0, 0)

        popup_roh = popup_finden(screenshot)
        ziel = ziel_finden(screenshot)

        if popup_roh is None and region is not None:
            screenshot = screenshot_holen(fenster)
            t_screenshot = time.time()
            versatz_x, versatz_y = 0, 0
            popup_roh = popup_finden(screenshot)
            ziel = ziel_finden(screenshot)

        if popup_roh is not None:
            popup_roh = (popup_roh[0] + versatz_x, popup_roh[1] + versatz_y, popup_roh[2])
        if ziel is not None:
            ziel = (ziel[0] + versatz_x, ziel[1] + versatz_y)

        popup = _popup_mit_haltezeit(_popup_gueltig(popup_roh), kontext=kontext)
        letzte_popup_box = popup

        fisch_glatt = None
        steht_still = False
        if ziel is not None:
            fisch_glatt = glaetter.position(ziel[0], ziel[1])
            gefilterte_historie.append(glaetter.gefilterte_position())
            if len(gefilterte_historie) > STILLSTAND_FRAMES:
                gefilterte_historie.pop(0)
            steht_still = fisch_steht_still(gefilterte_historie)

        kreis_treffer = bool(popup is not None and fisch_glatt is not None
                             and fisch_im_kreis(fisch_glatt, (popup[0], popup[1]), popup[2]))
        distanz = (_distanz(fisch_glatt, (popup[0], popup[1]))
                   if (popup is not None and fisch_glatt is not None) else None)
        fisch_speed = _fisch_geschwindigkeit(letzte_fisch, ziel, t_screenshot)
        letzte_fisch = (ziel[0], ziel[1], t_screenshot) if ziel is not None else letzte_fisch

        mess_zustand.aktualisieren(fenster, popup, fisch_glatt, t_screenshot, steht_still)

        _status_loggen(popup, ziel, kreis_treffer, kontext=kontext)
        _csv_zeile_schreiben(fenster, popup, ziel, distanz, kreis_treffer, False, None, fisch_speed,
                              kontext=kontext)

        if popup is not None:
            popup_war_je_offen = True
            geschlossen_seit = None
        elif popup_war_je_offen:
            jetzt = time.time()
            if geschlossen_seit is None:
                geschlossen_seit = jetzt
            elif jetzt - geschlossen_seit >= POPUP_SCHLIESS_DEBOUNCE:
                mess_zustand.ergebnis = ZUSTAND_WARTE_EINHOLEN
                fertig_event.set()
                return

        naechste_messung += MESS_INTERVALL_S
        pause = naechste_messung - time.time()
        if pause > 0:
            time.sleep(pause)
        else:
            naechste_messung = time.time()  # Verarbeitung war langsamer als das Ziel - nicht aufholen


def _klick_loop(maus, mess_zustand, fertig_event, kontext=None):
    """KLICK-LOGIK (Hauptthread, siehe zustand_fischen()): liest nur die
    neueste Messung aus mess_zustand (siehe _mess_loop()) und klickt GENAU
    dann, wenn der Fisch im Ring ist UND laut Messung STILLSTEHT - bewegt er
    sich, wird NICHT geklickt (keine Vorhersage/Extrapolation; die rohe
    Erkennung rauscht dafuer zu stark, siehe fisch_steht_still()).

    Hoechstens EIN Klick pro Stillstand-Phase: 'stillstand_bereits_geklickt'
    merkt sich, ob in der aktuell laufenden Phase (steht_still durchgehend
    True) schon geklickt wurde. Ein Klick wird also nur beim UEBERGANG in
    den Stillstand ausgeloest, nicht bei jedem weiteren Poll, waehrend der
    Fisch weiter stillsteht - vorher fuehrte das dazu, dass ein und
    derselbe stehende Fisch mehrfach angeklickt wurde. Erst wenn steht_still
    wieder False wird (Fisch bewegt sich, oder wird kurz nicht erkannt) wird
    die Sperre zurueckgesetzt; die naechste Stillstand-Phase darf dann
    wieder genau einmal klicken. MIN_KLICK_ABSTAND_S bleibt zusaetzlich als
    Sicherheitsnetz bestehen (schuetzt gegen Doppelklicks, falls steht_still
    durch Erkennungsrauschen kurz zwischen True/False flackert). Kein
    Klick-Limit pro Popup: es darf beliebig oft neu 'still' werden und dabei
    jedes Mal einmal klicken, solange das Popup offen bleibt.
    """
    letzter_klick_zeit = None
    stillstand_bereits_geklickt = False  # True = in dieser Stillstand-Phase schon geklickt
    klicks_in_diesem_popup = 0

    praefix = _kontext_aufloesen(kontext).log_praefix()
    while not fertig_event.is_set():
        if _gestoppt(kontext):
            return

        fenster, popup, fisch_glatt, mess_zeitpunkt, steht_still = mess_zustand.momentaufnahme()

        if not steht_still:
            # Fisch bewegt sich (oder wird gerade nicht erkannt) - neue
            # Stillstand-Phase moeglich, Klick-Sperre dieser Phase aufheben.
            stillstand_bereits_geklickt = False

        if (popup is not None and fisch_glatt is not None and steht_still
                and not stillstand_bereits_geklickt):
            im_ring = fisch_im_kreis(fisch_glatt, (popup[0], popup[1]), popup[2])
            jetzt = time.time()
            sperre_abgelaufen = (letzter_klick_zeit is None
                                  or (jetzt - letzter_klick_zeit) >= MIN_KLICK_ABSTAND_S)

            if im_ring and sperre_abgelaufen:
                ziel_x, ziel_y = fisch_glatt
                bildschirm_x = fenster["x"] + int(round(ziel_x))
                bildschirm_y = fenster["y"] + int(round(ziel_y))
                _logger.info("%sFisch im Kreis + Stillstand bei (%d, %d) [geglaettet]",
                             praefix, bildschirm_x, bildschirm_y)
                _logger.info("%smaus_zieht_zu=(%d, %d)", praefix, bildschirm_x, bildschirm_y)
                _fenster_fokussiert_sicherstellen(fenster.get("hwnd"), kontext=kontext)
                maus_bewegen(bildschirm_x, bildschirm_y, maus)
                # maus_bewegen() blockiert bereits bis zur MOVED-Bestaetigung
                # der Firmware (per Messung ~2-4ms Seriell-Rundlauf) - die
                # Cursor-Position ist zu diesem Zeitpunkt also sicher gesetzt.
                # Dieser kurze Rest-Puffer ist NICHT fuer die HID-Bestaetigung
                # noetig, sondern eine Vorsichtsmarge dafuer, dass der
                # Spiel-Client den neuen Cursor intern registriert, bevor der
                # Klick eintrifft (unbekannte, nicht messbare Client-Latenz).
                # War 0.08s; auf 0.02s reduziert, da die Bewegung selbst
                # bereits bestaetigt ist - bei Beobachtungen von erneut
                # daneben gehenden Klicks hier zuerst wieder hochsetzen.
                time.sleep(0.02)
                klick_erfolg = maus.klick_links()
                latenz_ms = (time.time() - mess_zeitpunkt) * 1000
                _logger.info("%sKLICK GESENDET: ziel=(%d, %d) erfolg=%s",
                             praefix, bildschirm_x, bildschirm_y, klick_erfolg)
                if not klick_erfolg:
                    _logger.warning("%sKlick fehlgeschlagen (keine Bestaetigung von der HID-Maus)", praefix)

                letzter_klick_zeit = jetzt
                stillstand_bereits_geklickt = True
                klicks_in_diesem_popup += 1
                _logger.info("%sKlick %d in diesem Popup", praefix, klicks_in_diesem_popup)

                distanz = _distanz(fisch_glatt, (popup[0], popup[1]))
                _csv_zeile_schreiben(fenster, popup, fisch_glatt, distanz, True, True,
                                      latenz_ms, None, kontext=kontext)

        time.sleep(KLICK_LOOP_INTERVALL_S)


def zustand_fischen(maus, kontext=None, fenster_provider=None):
    """FISCHEN: startet zwei parallele Loops (siehe Modul-Docstring) und
    wartet, bis der Mess-Loop entscheidet, dass FISCHEN enden soll.

    _mess_loop() laeuft in einem eigenen Thread und ist die einzige Quelle
    fuer Popup-/Fischposition; er bewegt nie die Maus. _klick_loop() laeuft
    im Hauptthread, liest nur die neueste Messung und klickt bei
    Ring-Treffer + Stillstand hoechstens einmal pro Stillstand-Phase (siehe
    dort) - kein Klick-Limit pro Popup, aber pro Phase nur ein Klick.

    Einziger Ausstiegsgrund aus FISCHEN bleibt das (entprellte) Schliessen
    des Popups (POPUP_SCHLIESS_DEBOUNCE, geprueft in _mess_loop()) - oder
    bot_anhalten().
    """
    mess_zustand = MessZustand()
    fertig_event = threading.Event()
    kontext = _kontext_aufloesen(kontext)

    mess_thread = threading.Thread(
        target=_mess_loop, args=(mess_zustand, fertig_event),
        kwargs={"kontext": kontext, "fenster_provider": fenster_provider},
        daemon=True, name="FischMessLoop%s" % ("-" + kontext.label if kontext.label else ""))
    mess_thread.start()

    _klick_loop(maus, mess_zustand, fertig_event, kontext=kontext)

    mess_thread.join()

    if _gestoppt(kontext):
        return ZUSTAND_GESTOPPT
    return mess_zustand.ergebnis


def zustand_warte_einholen(maus, kontext=None, fenster_provider=None):
    """WARTE_EINHOLEN: kurz warten (Angel einholen lassen), dann Leertaste
    (auswerfen) - der Einstiegspunkt jedes Wurf-Zyklus ("Schleife zum
    Start")."""
    warte_mit_bonus(WARTE_EINHOLEN_BASIS, kontext=kontext)
    if _gestoppt(kontext):
        return ZUSTAND_GESTOPPT
    hwnd = None
    if fenster_provider is not None:
        fenster = fenster_provider()
        hwnd = fenster.get("hwnd") if fenster else None
    leertaste_tippen(maus, hwnd=hwnd)
    return ZUSTAND_PRUEFE_POPUP


def zustand_pruefe_popup(maus, kontext=None, fenster_provider=None):
    """PRUEFE_POPUP: einzige Pruefung, ob nach dem Auswerfen ein Popup da
    ist - das Popup-Fenster ist der EINZIGE Trigger zum Angeln. Kein Popup
    -> zurueck zu WARTE_EINHOLEN (erneut auswerfen), keine Eskalation (kein
    Wurm-Nachlegen, keine gestaffelten Wartezeiten/Versuche) und kein
    Fehler-Endzustand mehr - der Bot versucht es einfach unbegrenzt weiter,
    bis bot_anhalten() aufgerufen wird."""
    warte_mit_bonus(PRUEFE_POPUP_BASIS, kontext=kontext)
    if _gestoppt(kontext):
        return ZUSTAND_GESTOPPT
    fenster = fenster_finden_geprueft(kontext=kontext, fenster_provider=fenster_provider)
    if fenster is not None and _popup_jetzt_sichtbar(fenster):
        return ZUSTAND_FISCHEN

    return ZUSTAND_WARTE_EINHOLEN


_ZUSTAND_HANDLER = {
    ZUSTAND_FISCHEN: zustand_fischen,
    ZUSTAND_WARTE_EINHOLEN: zustand_warte_einholen,
    ZUSTAND_PRUEFE_POPUP: zustand_pruefe_popup,
}


def bot_schleife(maus, kontext=None, fenster_provider=None):
    """Treibt den Zustandsautomaten an, bis bot_anhalten() aufgerufen wird.

    Kein Fehler-Endzustand mehr (siehe Modul-Docstring: das Popup-Fenster
    ist der einzige Trigger, keine Eskalation) - laeuft bei fehlendem
    Koeder/Biss einfach unbegrenzt mit WARTE_EINHOLEN<->PRUEFE_POPUP weiter.

    kontext/fenster_provider: siehe bot_starten() - werden unveraendert an
        jeden Zustand durchgereicht.

    Returns:
        str: "GESTOPPT" (bot_anhalten() wurde aufgerufen).
    """
    kontext = _kontext_aufloesen(kontext)
    zustand = ZUSTAND_FISCHEN
    while zustand != ZUSTAND_GESTOPPT:
        _logger.info("%sZustand: %s", kontext.log_praefix(), zustand)
        zustand = _ZUSTAND_HANDLER[zustand](maus, kontext=kontext, fenster_provider=fenster_provider)

    _logger.info("%sBot sauber gestoppt (bot_anhalten() aufgerufen)", kontext.log_praefix())
    return "GESTOPPT"


def bot_starten(port=None, maus=None, kontext=None, fenster_provider=None, label=None):
    """Verbindet die HID-Maus und startet den Zustandsautomaten - blockierend,
    bis bot_anhalten() aufgerufen wird (kein automatischer Fehler-
    Endzustand mehr, siehe Modul-Docstring).

    Im Gegensatz zu main() ruft diese Funktion nie sys.exit() auf, sondern
    gibt einen Statuscode zurueck. Gedacht fuer Aufrufer, die den Bot in
    einem eigenen Thread laufen lassen wollen (z.B. eine GUI) - dort wuerde
    sys.exit() nur den Thread beenden, ohne den Aufrufer sauber zu informieren.

    Args:
        port: serieller Port, nur relevant wenn maus=None. Leer/None -> HIDMaus
            erkennt den Arduino automatisch per VID/PID (_port_auto_finden()
            in hid_maus.py) statt den frueher hier hart verdrahteten HID_PORT
            zu verwenden, der bei jedem Neu-Verbinden des Arduino veraltet war.
        maus: optionale bereits verbundene HIDMaus-Instanz. Wird sie
            uebergeben, oeffnet bot_starten() KEINE eigene serielle Verbindung
            (ein COM-Port erlaubt i.d.R. nur eine offene Verbindung gleich-
            zeitig) und schliesst sie am Ende auch NICHT - der Aufrufer bleibt
            Eigentuemer. Ohne maus verbindet/trennt bot_starten() wie gehabt
            selbststaendig.
        kontext: optionale FischBotKontext-Instanz - None (Standard) nutzt
            den Modul-weiten Standard-Kontext (bisheriges Verhalten: EINE
            Instanz, per bot_anhalten() ohne Argument stoppbar). Fuer
            MEHRERE gleichzeitig laufende, je auf ein Fenster isolierte
            Instanzen (siehe makro_manager.MakroManager.fish_bot_starten())
            erzeugt/verwaltet der Aufrufer EIGENE FischBotKontext-Objekte,
            genau wie bei aktion_skript.skript_ausfuehren(stop_event=...).
        fenster_provider: optionales Callable[[], dict|None] (siehe
            modules.fenster.fenster_von_hwnd()) - isoliert diesen Lauf auf
            ein bestimmtes METIN2-Fenster statt (Standard, None) das erste
            per Titel gefundene zu verwenden.
        label: nur verwendet, wenn 'kontext' None ist UND der Standard-
            Kontext noch KEIN Label traegt - setzt dessen Label (fuer Logs/
            CSV-Dateiname, siehe FischBotKontext). Bei einem selbst
            uebergebenen 'kontext' wird dessen eigenes Label verwendet,
            dieser Parameter dann ignoriert.

    Returns:
        str: "VERBINDUNGSFEHLER" | "FENSTERPRUEFUNG_FEHLGESCHLAGEN" | "GESTOPPT"
    """
    if kontext is None:
        kontext = _STANDARD_KONTEXT
        if label is not None:
            kontext.label = label
    kontext.stop_event.clear()

    eigene_verbindung = maus is None
    if eigene_verbindung:
        # port=None/"" laesst HIDMaus.__init__() selbst per _port_auto_finden()
        # (VID/PID-Suche) den Arduino erkennen, statt hier blind auf den
        # veralteten, hart verdrahteten HID_PORT zurueckzufallen.
        maus = HIDMaus(port=port)
        if not maus.port:
            _logger.error(
                "Kein Arduino gefunden (weder Port angegeben noch per "
                "Auto-Erkennung erkannt) - Abbruch")
            return "VERBINDUNGSFEHLER"
        if not maus.verbinden():
            _logger.error("Keine Verbindung zur HID-Maus auf %s - Abbruch", maus.port)
            return "VERBINDUNGSFEHLER"

    if not maus.ping():
        _logger.error("HID-Maus antwortet nicht auf PING - Abbruch")
        if eigene_verbindung:
            maus.schliessen()
        return "VERBINDUNGSFEHLER"

    # Fenster-Eckpruefung (siehe fenster_eckpruefung_bestehen()) - NUR fuer
    # automatisch erkannte Fenster (fenster_fest=True markiert einen manuell/
    # fest vorgegebenen Bereich, siehe makro_manager.MakroManager.
    # fish_bot_starten(fenster_bereich=...) - dort hat der Benutzer die
    # Position bewusst selbst gewaehlt, keine Pruefung noetig/sinnvoll).
    # Findet dieser EINMALIGE Check gerade kein Fenster, wird er uebersprungen
    # (kein Abbruch) - die normale, fortlaufende "Fenster nicht gefunden"-
    # Behandlung im Zustandsautomaten greift dann wie gehabt. Derselbe Check
    # laeuft auch fuer normale Bot-Skripte (siehe makro_manager.MakroManager.
    # starte_makro()), damit die Eckpruefung ueberall gleich greift.
    fenster = fenster_provider() if fenster_provider is not None else fenster_finden(FENSTER_TITEL)
    if fenster is not None and not fenster.get("fenster_fest"):
        if not fenster_eckpruefung_bestehen(fenster, log_praefix=kontext.log_praefix()):
            if eigene_verbindung:
                maus.schliessen()
            return "FENSTERPRUEFUNG_FEHLGESCHLAGEN"

    _csv_logger_init(kontext=kontext)
    _logger.info("%sFishBot laeuft.", kontext.log_praefix())
    try:
        ergebnis = bot_schleife(maus, kontext=kontext, fenster_provider=fenster_provider)
    finally:
        if eigene_verbindung:
            maus.schliessen()
        if kontext.csv_datei is not None:
            kontext.csv_datei.close()
    return ergebnis


def main():
    """CLI-Einstiegspunkt (python fish_bot.py).

    Fuer programmatische Nutzung aus anderem Code (z.B. eine GUI, die den Bot
    in einem eigenen Thread starten und per bot_anhalten() stoppen will) siehe
    bot_starten() - main() ist nur ein duenner Wrapper mit CLI-Exitcodes.
    """
    _logger.info("Abbruch mit Strg+C.")
    try:
        ergebnis = bot_starten()
    except KeyboardInterrupt:
        _logger.info("Abbruch durch Strg+C")
        bot_anhalten()
        return

    if ergebnis == "VERBINDUNGSFEHLER":
        sys.exit(1)


if __name__ == "__main__":
    main()
