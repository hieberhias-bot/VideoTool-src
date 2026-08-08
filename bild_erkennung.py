#!/usr/bin/env python3
"""bild_erkennung.py - Bildbasierte Szenen-Erkennung per Template-Matching.

Der Benutzer legt PNG-Ausschnitte (Icons, Fenster, Buttons) in den Ordner
bilder_szenen/ ab. bild_finden() sucht so ein Bild per cv2.matchTemplate im
aktuellen METIN2-Fenster-Screenshot (Screenshot-Erfassung wiederverwendet aus
fish_bot.py: fenster_finden_geprueft() + screenshot_holen()).

bild_warten_bis_sichtbar()/bild_warten_bis_weg() sind die Bausteine fuer die
BILD_WARTEN_BIS*/BILD_KLICKEN*-Aktionen in aktion_skript.py - dort werden sie
mit einer stop_pruefen-Callable (aktion_skript._gestoppt) verdrahtet, damit
lange Wartezeiten genauso unterbrechbar sind wie WARTEN-Schritte. Sie liefern
die volle Treffer-Bounding-Box (nicht nur den Mittelpunkt), damit
zufallspunkt_in_treffer() einen Klickpunkt innerhalb einer optionalen,
bild-spezifischen Hitbox (siehe hitbox_speichern()) waehlen kann.
"""

import os
import re
import json
import time
import random

import cv2
import numpy as np

import fish_bot

BILDER_ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bilder_szenen")
SCHWELLE_STANDARD = 0.7
POLL_INTERVALL = 0.3  # Sekunden zwischen zwei Screenshot-Versuchen beim Warten


class BildErkennungFehler(Exception):
    """Wird ausgeloest, wenn ein referenziertes Bild nicht geladen werden kann
    (Datei fehlt/ist kein gueltiges Bild) - im Unterschied zu 'auf dem
    Bildschirm nicht gefunden', was ein normales/erwartetes Ergebnis ist."""


def sicherstellen_ordner():
    """Legt bilder_szenen/ an, falls es noch nicht existiert."""
    os.makedirs(BILDER_ORDNER, exist_ok=True)


_MASKEN_MUSTER = re.compile(r"^.+_mask(?:_.+)?\.png$", re.IGNORECASE)


def _ist_masken_datei(dateiname):
    """True fuer generierte Masken-Dateien: die alte Form <bild>_mask.png
    ODER die neue benannte Form <bild>_mask_<variante>.png (siehe
    maske_speichern()) - beides sind Begleitdateien, keine eigenstaendigen
    Szenen-Bilder zur Auswahl."""
    return bool(_MASKEN_MUSTER.match(dateiname))


def verfuegbare_bilder():
    """Namen aller .png-Dateien in bilder_szenen/, alphabetisch sortiert.

    Schliesst Masken-Dateien aus (siehe _ist_masken_datei()).
    """
    sicherstellen_ordner()
    return sorted(f for f in os.listdir(BILDER_ORDNER)
                  if f.lower().endswith(".png") and not _ist_masken_datei(f))


def _bild_pfad(bild_name):
    return os.path.join(BILDER_ORDNER, bild_name)


def _bild_laden(bild_name):
    pfad = _bild_pfad(bild_name)
    template = cv2.imread(pfad)
    if template is None:
        raise BildErkennungFehler("Bild nicht gefunden/ladbar: %s" % pfad)
    return template


def bild_groesse(bild_name):
    """Liefert (breite, hoehe) von 'bild_name' in bilder_szenen/ - z.B. fuer
    aktion_editor.py, um VOR dem Speichern eines 'suchbereich' zu warnen,
    falls der markierte Bereich kleiner als das Bild selbst ist (siehe
    bild_finden_robust(): ein Suchbereich, der kleiner als die kleinste
    Skalierungsstufe des Templates ist, liefert IMMER None, egal ob das Bild
    dort tatsaechlich sichtbar ist).

    Raises:
        BildErkennungFehler: wenn 'bild_name' nicht geladen werden kann.
    """
    h, w = _bild_laden(bild_name).shape[:2]
    return w, h


def bild_finden_robust(frame, bildname, schwelle=SCHWELLE_STANDARD,
                        min_scale=0.8, max_scale=1.2, steps=9, variante=None):
    """Sucht 'bildname' per Multi-Scale-Template-Matching mit robuster
    Vorverarbeitung im gegebenen Frame - dieselbe Vorverarbeitung wie
    fish_loop.popup_matchtemplate() (BilateralFilter(7,85,85) + Graustufen
    auf Frame UND Template), zusaetzlich ueber mehrere Groessen skaliert
    (np.linspace(min_scale, max_scale, steps)), damit leicht abweichende
    UI-Skalierungen/Fenstergroessen nicht zum Verfehlen des Treffers fuehren
    - im Gegensatz zur alten Einzel-Scale/Einzel-Vorverarbeitung, die bei
    Rauschen, Groessenaenderungen und Helligkeitsschwankungen versagte.

    Maske/Hitbox-Unterstuetzung bleibt erhalten: eine gespeicherte Maske
    (siehe maske_speichern()) wird pro Skalierungsschritt mitskaliert und
    beim Matching beruecksichtigt; die zurueckgegebene Breite/Hoehe ist
    bewusst die ORIGINAL-Templategroesse (nicht die am besten passende
    skalierte Groesse), damit die bestehende, auf Original-Bildkoordinaten
    kalibrierte Hitbox-Logik (siehe zufallspunkt_in_treffer()) unveraendert
    weiterfunktioniert.

    Args:
        frame: BGR-Bild (Screenshot), oder None (z.B. Fenster gerade nicht
            verfuegbar) - liefert dann direkt None statt zu laden/zu matchen.
        variante: optionaler Varianten-Name fuer die Maske (siehe
            maske_laden()/standard_variante()).

    Returns:
        tuple[int, int, int, int, float] | None: (cx, cy, breite, hoehe, score)
            - Mittelpunkt (aus der tatsaechlich am besten passenden Skalierung)
            und ORIGINAL-Templategroesse, plus bester Match-Score ueber alle
            Skalierungen. None, wenn kein Treffer >= schwelle gefunden wurde.

    Raises:
        BildErkennungFehler: wenn 'bildname' nicht geladen werden kann
            (nur, wenn 'frame' nicht None ist).
    """
    if frame is None:
        return None

    template = _bild_laden(bildname)
    th, tw = template.shape[:2]

    maske = maske_laden(bildname, variante)
    if maske is not None and maske.shape[:2] != (th, tw):
        # Stale Maske (Bild wurde seitdem ausgetauscht/anders zugeschnitten) -
        # sicherheitshalber ignorieren statt mit falscher Groesse zu matchen.
        maske = None

    frame_grau = cv2.cvtColor(cv2.bilateralFilter(frame, 7, 85, 85), cv2.COLOR_BGR2GRAY)
    template_grau = cv2.cvtColor(cv2.bilateralFilter(template, 7, 85, 85), cv2.COLOR_BGR2GRAY)
    fh, fw = frame_grau.shape[:2]

    bester = None  # (score, x, y, skalierte_breite, skalierte_hoehe)
    for scale in np.linspace(min_scale, max_scale, steps):
        sw = max(1, int(round(tw * scale)))
        sh = max(1, int(round(th * scale)))
        if sh > fh or sw > fw:
            continue
        skaliert = cv2.resize(template_grau, (sw, sh))

        if maske is not None:
            skalierte_maske = cv2.resize(maske, (sw, sh), interpolation=cv2.INTER_NEAREST)
            ergebnis = cv2.matchTemplate(frame_grau, skaliert, cv2.TM_CCOEFF_NORMED, mask=skalierte_maske)
            # Siehe bild_finden()-Historie: maskiertes TM_CCOEFF_NORMED kann
            # NaN ODER +-Infinity liefern (Fensterpositionen ohne Varianz in
            # den uebrigen Pixeln, Division durch ~0) - cv2.minMaxLoc()
            # behandelt beides nicht sicher. Bugfix: ohne posinf/neginf
            # wandelt np.nan_to_num() ein +Infinity in den groesstmoeglichen
            # ENDLICHEN float32-Wert (~3.4e38) um, NICHT in einen sinnvollen
            # "kein Treffer"-Score - das gewinnt dann faelschlich als
            # globales Maximum in cv2.minMaxLoc() und meldet einen
            # astronomischen Score weit ueber jeder Schwelle, obwohl real
            # gar keine Uebereinstimmung vorliegt (siehe Diagnose: Bild MIT
            # Maske meldete Score 3.4e38 statt eines Wertes in [-1, 1]).
            # NaN/+Inf/-Inf werden daher alle einheitlich auf -1.0 (schlechtest
            # moeglicher Score) abgebildet.
            ergebnis = np.nan_to_num(ergebnis, nan=-1.0, posinf=-1.0, neginf=-1.0)
        else:
            ergebnis = cv2.matchTemplate(frame_grau, skaliert, cv2.TM_CCOEFF_NORMED)

        _, max_val, _, max_loc = cv2.minMaxLoc(ergebnis)
        if bester is None or max_val > bester[0]:
            bester = (max_val, max_loc[0], max_loc[1], sw, sh)

    if bester is None or bester[0] < schwelle:
        return None

    score, x, y, sw, sh = bester
    cx, cy = x + sw // 2, y + sh // 2
    return cx, cy, tw, th, float(score)


def bild_finden(screenshot_bgr, bild_name, schwelle=SCHWELLE_STANDARD, variante=None):
    """Sucht 'bild_name' per robustem Multi-Scale-Template-Matching im
    gegebenen Screenshot (siehe bild_finden_robust() fuer die Details der
    Vorverarbeitung/Skalierung - diese Funktion ist ein duenner Wrapper mit
    den Standard-Skalierungsgrenzen, damit alle bestehenden Aufrufer
    (BILD_WARTEN_BIS/BILD_KLICKEN* in aktion_skript.py) automatisch von der
    robusteren Erkennung profitieren, ohne ihre eigene Signatur zu aendern).

    Args:
        variante: optionaler Varianten-Name fuer die Maske (siehe
            maske_laden()/standard_variante()). None/leer = Standard-Variante
            (Bildname ohne Endung, mit Fallback auf eine alte Vor-Varianten-
            Maskendatei, falls vorhanden).

    Returns:
        tuple[int, int, int, int, float] | None: (cx, cy, breite, hoehe, score)
            - Mittelpunkt und (Original-)Groesse des Treffers relativ zum
            Screenshot, plus Match-Score. None, wenn kein Treffer >= schwelle
            gefunden wurde (oder screenshot_bgr None ist).

    Raises:
        BildErkennungFehler: wenn 'bild_name' nicht geladen werden kann.
    """
    return bild_finden_robust(screenshot_bgr, bild_name, schwelle=schwelle, variante=variante)


def bild_bester_score(screenshot_bgr, bild_name, variante=None):
    """Wie bild_finden(), aber OHNE Schwellenwert-Filter - liefert IMMER den
    besten gefundenen Match ueber alle Skalierungsstufen zurueck, egal wie
    niedrig der Score ist (Schwelle -2.0 - garantiert unter jedem echten
    TM_CCOEFF_NORMED-Score, der immer in [-1, 1] liegt).

    Gedacht zum Debuggen ("warum wird ein Bild nicht erkannt, obwohl es
    sichtbar ist - liegt der Score nah an der Schwelle, oder komplett
    daneben?", siehe live_erkennung_vorschau.py) - bei einem echten
    Erkennungsversuch IMMER bild_finden() mit einer sinnvollen Schwelle
    verwenden, NICHT diese Funktion (die liefert auch bei einem voelligen
    Fehltreffer noch irgendeinen - dann bedeutungslosen - 'besten' Score).

    Returns:
        tuple[int, int, int, int, float] | None: wie bild_finden(), oder None
            nur wenn der Suchbereich kleiner als die kleinste Skalierungsstufe
            des Templates ist (siehe bild_finden_robust()) oder
            screenshot_bgr None ist.
    """
    return bild_finden_robust(screenshot_bgr, bild_name, schwelle=-2.0, variante=variante)


def _aktueller_treffer(bild_name, schwelle, variante=None, fenster_provider=None, suchbereich=None):
    """Ein einzelner Versuch: Fenster suchen, Screenshot (ggf. nur ein
    Ausschnitt, siehe suchbereich), Bild suchen.

    Args:
        fenster_provider: optionales Callable[[], dict|None], das (frisch,
            bei JEDEM Aufruf neu) das zu verwendende Fenster liefert - fuer
            die Fenster-Isolation eines Makros auf genau EIN METIN2-Fenster
            (siehe aktion_skript.py/modules.fenster.fenster_von_hwnd()).
            None (Standard) = bisheriges Verhalten: das erste per Titel
            gefundene Fenster (fish_bot.fenster_finden_geprueft()) wird
            verwendet, wie vor Einfuehrung der Mehrfenster-Unterstuetzung.
        suchbereich: optionales dict{"x0","y0","x1","y1"}, FENSTERRELATIV
            (siehe modules.fenster.fenster_bereich_markieren()) - ist es
            gesetzt, wird NUR dieser Ausschnitt erfasst/durchsucht statt des
            GANZEN Fensters (schneller, siehe fish_bot.screenshot_holen(
            region=...)/aktion_editor.py's "Zielbereich..."-Button) - sinnvoll,
            weil METIN2-Fenster immer (ungefaehr) dieselbe Groesse haben,
            ein einmal markierter Bereich also unabhaengig von der AKTUELLEN
            Fensterposition wiederverwendbar bleibt. None (Standard) = ganzes
            Fenster, bisheriges Verhalten.

    Returns:
        tuple[int, int, int, int, float] | None: (bildschirm_x, bildschirm_y,
            breite, hoehe, score) der Treffer-Bounding-Box (bildschirm_x/y =
            OBERE LINKE Ecke, Fenster-Offset bereits addiert), oder None wenn
            das Fenster gerade nicht verfuegbar ist oder das Bild nicht
            gefunden wurde.
    """
    fenster = fenster_provider() if fenster_provider is not None else fish_bot.fenster_finden_geprueft()
    if fenster is None:
        return None
    if suchbereich is not None:
        region = (suchbereich["x0"], suchbereich["y0"], suchbereich["x1"], suchbereich["y1"])
        screenshot = fish_bot.screenshot_holen(fenster, region=region)
        versatz_x, versatz_y = suchbereich["x0"], suchbereich["y0"]
    else:
        screenshot = fish_bot.screenshot_holen(fenster)
        versatz_x, versatz_y = 0, 0
    treffer = bild_finden(screenshot, bild_name, schwelle, variante)
    if treffer is None:
        return None
    cx, cy, tw, th, score = treffer
    x = fenster["x"] + versatz_x + cx - tw // 2
    y = fenster["y"] + versatz_y + cy - th // 2
    return x, y, tw, th, score


def bild_pruefen(bild_name, schwelle=SCHWELLE_STANDARD, variante=None, fenster_provider=None,
                  suchbereich=None):
    """Einzelner, SOFORTIGER Versuch (kein Warten/Polling) - ist 'bild_name'
    gerade im METIN2-Fenster sichtbar? Siehe bild_warten_bis_sichtbar() fuer
    die wartende Variante (z.B. fuer BILD_KLICKEN_BIS in aktion_skript.py,
    das pro Klick-Zyklus selbst pollt statt zu warten).

    Args:
        fenster_provider: siehe _aktueller_treffer() - None (Standard) belaesst
            das bisherige "erstes gefundenes METIN2-Fenster"-Verhalten.
        suchbereich: siehe _aktueller_treffer().

    Returns:
        tuple[int, int, int, int, float] | None: (bildschirm_x, bildschirm_y,
            breite, hoehe, score) der Treffer-Bounding-Box, oder None.
    """
    return _aktueller_treffer(bild_name, schwelle, variante, fenster_provider=fenster_provider,
                               suchbereich=suchbereich)


def bild_warten_bis_sichtbar(bild_name, timeout, schwelle=SCHWELLE_STANDARD, stop_pruefen=None,
                              variante=None, fenster_provider=None, suchbereich=None):
    """Wartet, bis 'bild_name' im METIN2-Fenster sichtbar wird (oder timeout
    ablaeuft). Unterbrechbar via stop_pruefen (Callable[[], bool]).

    Args:
        timeout: maximale Wartezeit in Sekunden. None oder <=0 bedeutet
            ENDLOS warten (kein Timeout) - sucht dann unbegrenzt weiter, bis
            das Bild gefunden wird oder stop_pruefen() True liefert (siehe
            aktion_skript.py: BILD_WARTEN_BIS/BILD_KLICKEN* mit endlos=1).
        fenster_provider: siehe _aktueller_treffer().
        suchbereich: siehe _aktueller_treffer().

    Returns:
        tuple[int, int, int, int, float] | None: (bildschirm_x, bildschirm_y,
            breite, hoehe, score) der Treffer-Bounding-Box, oder None bei
            Timeout/Stop (bei endlos=True also nur bei Stop).
    """
    endlos = timeout is None or timeout <= 0
    ende = None if endlos else time.time() + timeout
    while True:
        if stop_pruefen and stop_pruefen():
            return None
        treffer = _aktueller_treffer(bild_name, schwelle, variante, fenster_provider=fenster_provider,
                                      suchbereich=suchbereich)
        if treffer is not None:
            return treffer
        if endlos:
            time.sleep(POLL_INTERVALL)
            continue
        rest = ende - time.time()
        if rest <= 0:
            return None
        time.sleep(min(POLL_INTERVALL, rest))


def bild_warten_bis_weg(bild_name, timeout, schwelle=SCHWELLE_STANDARD, stop_pruefen=None,
                         variante=None, fenster_provider=None, suchbereich=None):
    """Wartet, bis 'bild_name' NICHT mehr sichtbar ist (oder timeout ablaeuft).
    Unterbrechbar via stop_pruefen.

    Args:
        timeout: maximale Wartezeit in Sekunden. None oder <=0 bedeutet
            ENDLOS warten (kein Timeout) - siehe bild_warten_bis_sichtbar().
        fenster_provider: siehe _aktueller_treffer().
        suchbereich: siehe _aktueller_treffer().

    Returns:
        tuple[bool, tuple|None]: (verschwunden, letzte_bbox)
            - verschwunden=True, wenn das Bild am Ende nicht mehr da war (auch
              wenn es von Anfang an nie zu sehen war). letzte_bbox ist die
              zuletzt bekannte (bildschirm_x, bildschirm_y, breite, hoehe,
              score)-Bounding-Box, waehrend das Bild noch sichtbar war (oder
              None, wenn es waehrend der gesamten Wartezeit nie gesehen wurde)
              - fuer BILD_KLICKEN_WENN_WEG.
    """
    endlos = timeout is None or timeout <= 0
    ende = None if endlos else time.time() + timeout
    letzte_bbox = None
    while True:
        if stop_pruefen and stop_pruefen():
            return False, letzte_bbox
        treffer = _aktueller_treffer(bild_name, schwelle, variante, fenster_provider=fenster_provider,
                                      suchbereich=suchbereich)
        if treffer is None:
            return True, letzte_bbox
        letzte_bbox = treffer
        if endlos:
            time.sleep(POLL_INTERVALL)
            continue
        rest = ende - time.time()
        if rest <= 0:
            return False, letzte_bbox
        time.sleep(min(POLL_INTERVALL, rest))


# ---------- Varianten-Verwaltung (Hitbox/Maske, pro Bild MEHRERE benannte
# Varianten moeglich) ----------
#
# Jede Variante hat einen frei waehlbaren Namen (Standard: Bildname ohne
# Endung, siehe standard_variante()). Dateien:
#   Hitbox: <bild-ohne-endung>_hitbox_<variante>.json
#   Maske:  <bild-ohne-endung>_mask_<variante>.png
#
# Abwaertskompatibilitaet: vor Einfuehrung der Varianten gespeicherte Dateien
# (<bild-ohne-endung>.json bzw. <bild-ohne-endung>_mask.png, OHNE Varianten-
# Infix) werden weiterhin gelesen, wenn die Standard-Variante angefragt wird
# und keine neu-benannte Datei existiert - bestehende Hitboxen/Masken aus
# Ablaeufen von vor dieser Aenderung bleiben so nutzbar.

def _bild_basis(bild_name):
    basis, _ext = os.path.splitext(bild_name)
    return basis


def standard_variante(bild_name):
    """Der Standard-Variantenname fuer 'bild_name' - der Bildname ohne
    Endung. Wird verwendet, wenn keine Variante angegeben ist (variante=None
    bzw. leerer String), und ist im Editor der vorausgefuellte Name."""
    return _bild_basis(bild_name)


def _variante_sicher(variante):
    """Validiert einen Variantennamen vor dem Schreiben einer Datei (nicht
    leer, keine Pfad-Sonderzeichen)."""
    v = (variante or "").strip()
    if not v:
        raise BildErkennungFehler("Variantenname darf nicht leer sein.")
    if any(z in v for z in ("/", "\\", "..")):
        raise BildErkennungFehler("Ungueltiger Variantenname: %r" % variante)
    return v


def _hitbox_pfad(bild_name, variante):
    return os.path.join(BILDER_ORDNER, "%s_hitbox_%s.json" % (_bild_basis(bild_name), variante))


def _hitbox_pfad_legacy(bild_name):
    return os.path.join(BILDER_ORDNER, _bild_basis(bild_name) + ".json")


def _maske_pfad(bild_name, variante):
    return os.path.join(BILDER_ORDNER, "%s_mask_%s.png" % (_bild_basis(bild_name), variante))


def _maske_pfad_legacy(bild_name):
    return os.path.join(BILDER_ORDNER, _bild_basis(bild_name) + "_mask.png")


def hitbox_varianten(bild_name):
    """Namen aller vorhandenen Hitbox-Varianten fuer 'bild_name' (alphabetisch),
    inkl. der Standard-Variante, falls (nur) eine alte Vor-Varianten-Datei
    existiert."""
    sicherstellen_ordner()
    praefix = _bild_basis(bild_name) + "_hitbox_"
    varianten = set()
    for f in os.listdir(BILDER_ORDNER):
        if f.startswith(praefix) and f.endswith(".json"):
            varianten.add(f[len(praefix):-len(".json")])
    if os.path.exists(_hitbox_pfad_legacy(bild_name)):
        varianten.add(standard_variante(bild_name))
    return sorted(varianten)


def maske_varianten(bild_name):
    """Namen aller vorhandenen Masken-Varianten fuer 'bild_name' (alphabetisch),
    inkl. der Standard-Variante, falls (nur) eine alte Vor-Varianten-Datei
    existiert."""
    sicherstellen_ordner()
    praefix = _bild_basis(bild_name) + "_mask_"
    varianten = set()
    for f in os.listdir(BILDER_ORDNER):
        if f.startswith(praefix) and f.lower().endswith(".png"):
            varianten.add(f[len(praefix):-len(".png")])
    if os.path.exists(_maske_pfad_legacy(bild_name)):
        varianten.add(standard_variante(bild_name))
    return sorted(varianten)


def varianten_liste(bild_name):
    """Vereinigung aus Hitbox- und Masken-Varianten fuer 'bild_name' - fuer
    die Varianten-Dropdown im Editor (hitbox_editor.py)."""
    return sorted(set(hitbox_varianten(bild_name)) | set(maske_varianten(bild_name)))


def hitbox_laden(bild_name, variante=None):
    """Laedt die gespeicherte Hitbox fuer 'bild_name'/'variante' (Standard-
    Variante, falls nicht angegeben), falls vorhanden.

    Returns:
        dict{"x","y","w","h"} | None: Pixel-Koordinaten relativ zur Original-
            Bildgroesse (nicht zu einer skalierten Vorschau!), oder None, wenn
            keine (gueltige) Hitbox gespeichert ist - dann gilt das gesamte
            gefundene Bild als Hitbox.
    """
    standard = standard_variante(bild_name)
    variante = (variante or standard).strip() or standard
    pfad = _hitbox_pfad(bild_name, variante)
    if not os.path.exists(pfad) and variante == standard:
        pfad = _hitbox_pfad_legacy(bild_name)
    if not os.path.exists(pfad):
        return None
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            data = json.load(f)
        hitbox = data.get("hitbox")
        if not hitbox:
            return None
        return {"x": int(hitbox["x"]), "y": int(hitbox["y"]),
                "w": int(hitbox["w"]), "h": int(hitbox["h"])}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        return None


def hitbox_speichern(bild_name, hitbox, variante=None):
    """Speichert hitbox={"x","y","w","h"} (Pixel, Original-Bildgroesse) fuer
    'bild_name'/'variante' (Standard-Variante, falls nicht angegeben) -
    ueberschreibt eine evtl. bestehende Datei derselben Variante.

    Raises:
        BildErkennungFehler: bei leerem/ungueltigem Variantennamen.
    """
    variante = _variante_sicher(variante or standard_variante(bild_name))
    data = {"hitbox": {"x": int(hitbox["x"]), "y": int(hitbox["y"]),
                       "w": int(hitbox["w"]), "h": int(hitbox["h"])}}
    with open(_hitbox_pfad(bild_name, variante), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def hitbox_entfernen(bild_name, variante=None):
    """Loescht die gespeicherte Hitbox-Datei fuer 'bild_name'/'variante'
    (Standard-Variante, falls nicht angegeben) - danach gilt wieder das
    gesamte gefundene Bild als Klickbereich fuer diese Variante. Loescht bei
    der Standard-Variante zusaetzlich eine evtl. vorhandene alte
    Vor-Varianten-Datei."""
    standard = standard_variante(bild_name)
    variante = (variante or standard).strip() or standard
    pfad = _hitbox_pfad(bild_name, variante)
    if os.path.exists(pfad):
        os.remove(pfad)
    if variante == standard:
        legacy = _hitbox_pfad_legacy(bild_name)
        if os.path.exists(legacy):
            os.remove(legacy)


def zufallspunkt_in_treffer(bbox, bild_name, variante=None):
    """Waehlt einen zufaelligen Klickpunkt in absoluten Bildschirmkoordinaten:
    innerhalb der gespeicherten Hitbox von 'bild_name'/'variante', falls
    vorhanden, sonst irgendwo innerhalb der gesamten Treffer-Bounding-Box.

    Args:
        bbox: (bildschirm_x, bildschirm_y, breite, hoehe[, score]) - die obere
            linke Ecke + Groesse des Treffers, wie von bild_warten_bis_*()
            geliefert (der optionale 5. Wert 'score' wird ignoriert).
        bild_name: fuer die Hitbox-Suche (siehe hitbox_laden()).
        variante: optionaler Varianten-Name (siehe hitbox_laden()).

    Returns:
        tuple[int, int]: (bildschirm_x, bildschirm_y) des gewaehlten Punkts.
    """
    x, y, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
    hitbox = hitbox_laden(bild_name, variante)
    if hitbox is not None:
        hx = max(0, min(hitbox["x"], max(w - 1, 0)))
        hy = max(0, min(hitbox["y"], max(h - 1, 0)))
        hw = max(1, min(hitbox["w"], w - hx))
        hh = max(1, min(hitbox["h"], h - hy))
    else:
        hx, hy, hw, hh = 0, 0, w, h
    px = x + hx + random.randint(0, max(hw - 1, 0))
    py = y + hy + random.randint(0, max(hh - 1, 0))
    return px, py


# Eine Maske ist ein Graustufenbild in Originalbild-Groesse: 255=erkennen
# (Standard), 0=ignorieren (z.B. Timer/Zahlen/blinkende Icons). Wirkt NUR auf
# bild_finden()/die Erkennung - beeinflusst die Hitbox (siehe oben) nicht.

def maske_laden(bild_name, variante=None):
    """Laedt die gespeicherte Maske fuer 'bild_name'/'variante' (Standard-
    Variante, falls nicht angegeben), falls vorhanden.

    Returns:
        np.ndarray | None: Graustufen-Maske (Original-Bildgroesse), oder None
            wenn keine Maske gespeichert ist (dann wird das gesamte Bild fuer
            die Erkennung herangezogen).
    """
    standard = standard_variante(bild_name)
    variante = (variante or standard).strip() or standard
    pfad = _maske_pfad(bild_name, variante)
    if not os.path.exists(pfad) and variante == standard:
        pfad = _maske_pfad_legacy(bild_name)
    if not os.path.exists(pfad):
        return None
    return cv2.imread(pfad, cv2.IMREAD_GRAYSCALE)


def maske_speichern(bild_name, rechtecke, variante=None):
    """Erzeugt eine Graustufen-Maske aus einer Liste von Rechtecken
    ({"x","y","w","h"}, Original-Bildkoordinaten) und speichert sie fuer
    'bild_name'/'variante' (Standard-Variante, falls nicht angegeben) -
    ueberschreibt eine evtl. bestehende Maske derselben Variante.

    Die Maske hat dieselbe Groesse wie 'bild_name' selbst: ueberall 255
    (erkennen) ausser innerhalb der uebergebenen Rechtecke (0, ignorieren).

    Raises:
        BildErkennungFehler: bei leerem/ungueltigem Variantennamen.
    """
    variante = _variante_sicher(variante or standard_variante(bild_name))
    template = _bild_laden(bild_name)
    h, w = template.shape[:2]
    maske = np.full((h, w), 255, dtype=np.uint8)
    for r in rechtecke:
        x0 = max(0, min(int(r["x"]), w))
        y0 = max(0, min(int(r["y"]), h))
        x1 = max(x0, min(x0 + int(r["w"]), w))
        y1 = max(y0, min(y0 + int(r["h"]), h))
        maske[y0:y1, x0:x1] = 0
    cv2.imwrite(_maske_pfad(bild_name, variante), maske)


def maske_entfernen(bild_name, variante=None):
    """Loescht die gespeicherte Masken-Datei fuer 'bild_name'/'variante'
    (Standard-Variante, falls nicht angegeben) - danach wird wieder das
    gesamte Bild fuer die Erkennung dieser Variante herangezogen. Loescht bei
    der Standard-Variante zusaetzlich eine evtl. vorhandene alte
    Vor-Varianten-Datei."""
    standard = standard_variante(bild_name)
    variante = (variante or standard).strip() or standard
    pfad = _maske_pfad(bild_name, variante)
    if os.path.exists(pfad):
        os.remove(pfad)
    if variante == standard:
        legacy = _maske_pfad_legacy(bild_name)
        if os.path.exists(legacy):
            os.remove(legacy)


def variante_kopieren(bild_name, quelle_variante, ziel_variante):
    """Dupliziert Hitbox UND Maske von 'quelle_variante' zu 'ziel_variante'
    (jeweils nur, falls fuer die Quelle vorhanden) - fuer den 'Variante
    duplizieren'-Knopf im Editor.

    Raises:
        BildErkennungFehler: wenn 'quelle_variante' weder Hitbox noch Maske
            hat, oder 'ziel_variante' ungueltig ist.
    """
    ziel_variante = _variante_sicher(ziel_variante)
    hb = hitbox_laden(bild_name, quelle_variante)
    m = maske_laden(bild_name, quelle_variante)
    if hb is None and m is None:
        raise BildErkennungFehler(
            "Variante '%s' hat weder Hitbox noch Maske - nichts zu kopieren." % quelle_variante)
    if hb is not None:
        hitbox_speichern(bild_name, hb, ziel_variante)
    if m is not None:
        cv2.imwrite(_maske_pfad(bild_name, ziel_variante), m)


def variante_entfernen(bild_name, variante):
    """Loescht Hitbox UND Maske der angegebenen Variante (siehe
    hitbox_entfernen()/maske_entfernen())."""
    hitbox_entfernen(bild_name, variante)
    maske_entfernen(bild_name, variante)


def alle_varianten_entfernen(bild_name):
    """Loescht ALLE Hitbox-/Masken-Varianten von 'bild_name' (inkl. alter
    Vor-Varianten-Dateien) - fuer 'Bild loeschen': ohne das Bild selbst sind
    verwaiste Hitbox/Masken-Dateien nutzlos."""
    for variante in varianten_liste(bild_name):
        variante_entfernen(bild_name, variante)
    # Sicherheitshalber (deckt Faelle ab, in denen varianten_liste() durch
    # ein zwischenzeitlich geloeschtes Bild nichts mehr findet):
    hitbox_entfernen(bild_name)
    maske_entfernen(bild_name)


sicherstellen_ordner()
