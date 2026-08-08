#!/usr/bin/env python3
"""live_erkennung_vorschau.py - Live-Debug-Fenster fuer die Bild-Erkennung.

Zeigt den aktuellen Screenshot eines gewaehlten Spielfensters IN ECHTZEIT,
mit eingezeichneten Rechtecken fuer jedes ausgewaehlte bilder_szenen-
Referenzbild: duenne Linie = Template-Match-Bereich, dicke Linie = die
dafuer gespeicherte Klick-Hitbox (falls vorhanden, siehe
bild_erkennung.hitbox_laden()) - also GENAU das, was aktion_skript.py beim
Ausfuehren eines BILD_*-Schritts tatsaechlich sieht/anklickt.

Im Gegensatz zu video_test.py/processor.py (altes VisionProcessor-Experiment
gegen eine aufgezeichnete Videodatei) laeuft dies LIVE gegen den Bildschirm
und nutzt DIESELBE Erkennung wie der eigentliche Bot (bild_erkennung.py),
nicht eine eigene/andere Implementierung - das Vorschau-Fenster zeigt also
zuverlaessig, was der Bot in diesem Moment "sieht".

Verwendung:
    python live_erkennung_vorschau.py
Fragt zuerst interaktiv auf der Konsole, welches Fenster und welche Bilder
beobachtet werden sollen, oeffnet danach ein Vorschau-Fenster. Beenden mit
'q' oder ESC (im Vorschau-Fenster) bzw. Strg+C.

Die eigentliche Anzeige-Schleife steckt in live_vorschau_schleife() - die
nimmt statt einer interaktiven Konsolenabfrage einen fertigen
fenster_provider (siehe modules.fenster.fenster_von_hwnd()) entgegen und
laesst sich daher auch PROGRAMMATISCH einbetten, z.B. von
command_center.py/makro_manager.py, um beim Start des echten Fisch-Bots
automatisch ein Vorschau-Fenster mitzustarten (siehe dort
live_vorschau=True bei MakroManager.fish_bot_starten()).
"""

import sys
import argparse
import functools

import cv2

import bild_erkennung
import fish_bot
import modules.fenster as fenster_modul

# Default-Fenstertitel fuer die interaktive Nutzung (main()) - bei
# programmatischer Einbettung mit mehreren gleichzeitigen Instanzen (siehe
# live_vorschau_schleife()) vergibt der Aufrufer stattdessen einen je Instanz
# EINDEUTIGEN Titel, da der Fenstertitel bei OpenCV/HighGUI zugleich die
# Fenster-Identitaet ist (gleicher Titel = dasselbe Fenster).
_STANDARD_TITEL = "Live-Erkennungsvorschau (q/ESC zum Beenden)"

# Reihenfolge = Zuordnung Bild -> Farbe (BGR), zyklisch bei mehr Bildern als Farben.
_FARBEN = [
    (0, 255, 0), (0, 165, 255), (255, 80, 80), (0, 255, 255),
    (255, 0, 255), (255, 255, 0), (128, 128, 255), (180, 255, 180),
]


def _manueller_bereich():
    """Laesst den Bereich per Maus aufziehen (siehe fenster_modul.
    bereich_manuell_auswaehlen()) und verpackt ihn im selben Format wie
    alle_spielfenster_finden() (inkl. hwnd=None als Markierung fuer 'kein
    echtes Fenster, Position wird NICHT pro Frame neu abgefragt' - siehe
    main())."""
    print("Bitte im aufgehenden Overlay den zu beobachtenden Bereich aufziehen "
          "(Maus gedrueckt halten + ziehen, ESC zum Abbrechen)...")
    bereich = fenster_modul.bereich_manuell_auswaehlen()
    if bereich is None:
        print("Abgebrochen/kein Bereich ausgewaehlt.")
        return None
    return {"hwnd": None, "titel": "manueller Bereich", "x": bereich["x"], "y": bereich["y"],
            "breite": bereich["w"], "hoehe": bereich["h"]}


def _fenster_auswaehlen():
    fenster_liste = fenster_modul.alle_spielfenster_finden()
    if not fenster_liste:
        print("Kein METIN2-Fenster gefunden - Spiel gestartet?")
        wahl = input("'m' fuer manuellen Bereich, sonst Enter zum Beenden: ").strip().lower()
        if wahl == "m":
            manuell = _manueller_bereich()
            if manuell is not None:
                return manuell
        sys.exit(1)
    if len(fenster_liste) == 1:
        f = fenster_liste[0]
        print(f"Ein Fenster gefunden (hwnd={f['hwnd']}) pos=({f['x']},{f['y']}) "
              f"{f['breite']}x{f['hoehe']}.")
        wahl = input("Enter zum Verwenden, oder 'm' fuer manuellen Bereich: ").strip().lower()
        if wahl == "m":
            manuell = _manueller_bereich()
            if manuell is not None:
                return manuell
        return f

    print("Gefundene Fenster:")
    for f in fenster_liste:
        print(f"  {f['nummer']}: hwnd={f['hwnd']} pos=({f['x']},{f['y']}) "
              f"{f['breite']}x{f['hoehe']}")
    wahl = input("Welches Fenster beobachten? (Nummer, oder 'm' fuer manuellen "
                 "Bereich): ").strip().lower()
    if wahl == "m":
        manuell = _manueller_bereich()
        if manuell is not None:
            return manuell
    try:
        nummer = int(wahl)
    except ValueError:
        nummer = 1
    return next((f for f in fenster_liste if f["nummer"] == nummer), fenster_liste[0])


def _bilder_auswaehlen():
    alle = bild_erkennung.verfuegbare_bilder()
    if not alle:
        print("Keine Bilder in bilder_szenen/ vorhanden.")
        sys.exit(1)

    print("\nVerfuegbare Bilder:")
    for i, b in enumerate(alle, 1):
        print(f"  {i}: {b}")
    wahl = input("Welche Bilder beobachten? (Nummern, Komma-getrennt, leer = alle): ").strip()
    if not wahl:
        return alle
    indizes = []
    for teil in wahl.split(","):
        teil = teil.strip()
        if teil.isdigit():
            indizes.append(int(teil))
    ausgewaehlt = [alle[i - 1] for i in indizes if 1 <= i <= len(alle)]
    return ausgewaehlt or alle


def _hitbox_rechteck(bild_name, variante, x0, y0):
    """Liefert die gespeicherte Klick-Hitbox (siehe bild_erkennung.
    hitbox_laden()) als Frame-relatives Rechteck (x0,y0 = obere linke Ecke
    des Template-Treffers), oder None wenn keine Hitbox gespeichert ist."""
    hitbox = bild_erkennung.hitbox_laden(bild_name, variante)
    if hitbox is None:
        return None
    hx0 = x0 + hitbox["x"]
    hy0 = y0 + hitbox["y"]
    return hx0, hy0, hx0 + hitbox["w"], hy0 + hitbox["h"]


def live_vorschau_schleife(fenster_provider, bilder=None, fenster_titel=_STANDARD_TITEL,
                            laeuft_check=None):
    """Die eigentliche Anzeige-Schleife, entkoppelt von der interaktiven
    Konsolenabfrage in main() - siehe Modul-Docstring fuer den Zweck der
    programmatischen Einbettung.

    Args:
        fenster_provider: Callable[[], dict|None], liefert bei jedem Aufruf
            das aktuell zu beobachtende Fenster (siehe modules.fenster.
            fenster_von_hwnd()/fenster_finden()) frisch neu - z.B. ein
            functools.partial(fenster_von_hwnd, hwnd) fuer Fensterverfolgung,
            oder 'lambda: fester_bereich' fuer einen manuell aufgezogenen
            Bereich. Liefert der Provider None (Fenster geschlossen), endet
            die Schleife.
        bilder: Liste zu beobachtender bilder_szenen-Namen - None (Standard)
            beobachtet ALLE per bild_erkennung.verfuegbare_bilder() bekannten.
        fenster_titel: Titel des cv2-Vorschau-Fensters - bei MEHREREN
            gleichzeitig laufenden Instanzen (z.B. je eine pro Fisch-Bot-
            Fenster beim Mehrfenster-Fan-out) muss dies je Aufruf EINDEUTIG
            sein, sonst teilen sich mehrere Instanzen versehentlich dasselbe
            OpenCV-Fenster.
        laeuft_check: optionales Callable[[], bool] - liefert es False, endet
            die Schleife (zusaetzlich zu 'q'/ESC im Vorschau-Fenster und
            geschlossenem Zielfenster). None (Standard) = nur ueber 'q'/ESC/
            geschlossenes Zielfenster beendbar (interaktive Nutzung).
    """
    if bilder is None:
        bilder = bild_erkennung.verfuegbare_bilder()
    if not bilder:
        return
    schwelle = bild_erkennung.SCHWELLE_STANDARD
    zuordnung = [(name, _FARBEN[i % len(_FARBEN)]) for i, name in enumerate(bilder)]

    try:
        while laeuft_check is None or laeuft_check():
            fenster = fenster_provider()
            if fenster is None:
                break

            frame = fish_bot.screenshot_holen(fenster)
            anzeige = frame.copy()

            zeile_y = 22
            for bild_name, farbe in zuordnung:
                variante = bild_erkennung.standard_variante(bild_name)
                try:
                    treffer = bild_erkennung.bild_finden(frame, bild_name, schwelle, variante)
                except bild_erkennung.BildErkennungFehler as e:
                    treffer = None
                    status = f"FEHLER: {e}"
                else:
                    status = None

                if treffer is not None:
                    cx, cy, w, h, score = treffer
                    x0, y0 = int(cx - w / 2), int(cy - h / 2)
                    x1, y1 = int(cx + w / 2), int(cy + h / 2)
                    cv2.rectangle(anzeige, (x0, y0), (x1, y1), farbe, 1)

                    hitbox_rect = _hitbox_rechteck(bild_name, variante, x0, y0)
                    if hitbox_rect is not None:
                        hx0, hy0, hx1, hy1 = hitbox_rect
                        cv2.rectangle(anzeige, (hx0, hy0), (hx1, hy1), farbe, 3)

                    cv2.putText(anzeige, f"{bild_name} {score:.2f}", (x0, max(12, y0 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, farbe, 1, cv2.LINE_AA)
                    status = f"TREFFER {score:.2f}"
                elif status is None:
                    # Kein Treffer >= Schwelle - trotzdem den TATSAECHLICH
                    # besten gefundenen Score zeigen (siehe bild_bester_score()):
                    # "0.12 statt Treffer" bedeutet etwas ganz anderes als
                    # "0.58 statt Treffer" (Schwelle 0.60) - im ersten Fall ist
                    # vermutlich das Referenzbild/der Suchbereich falsch, im
                    # zweiten reicht evtl. schon eine etwas niedrigere Schwelle.
                    try:
                        bester = bild_erkennung.bild_bester_score(frame, bild_name, variante)
                    except bild_erkennung.BildErkennungFehler:
                        bester = None
                    if bester is not None:
                        bcx, bcy, bw, bh, bscore = bester
                        status = f"kein Treffer (bester Score {bscore:.2f} < Schwelle {schwelle:.2f})"
                        if bscore >= schwelle - 0.15:
                            bx0, by0 = int(bcx - bw / 2), int(bcy - bh / 2)
                            bx1, by1 = int(bcx + bw / 2), int(bcy + bh / 2)
                            cv2.rectangle(anzeige, (bx0, by0), (bx1, by1), farbe, 1, cv2.LINE_4)
                    else:
                        status = "kein Treffer (Suchbereich kleiner als Bild?)"

                cv2.putText(anzeige, f"{bild_name}: {status}", (10, zeile_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, farbe, 1, cv2.LINE_AA)
                zeile_y += 20

            cv2.imshow(fenster_titel, anzeige)
            taste = cv2.waitKey(1) & 0xFF
            if taste in (ord('q'), 27):
                break
    finally:
        try:
            cv2.destroyWindow(fenster_titel)
        except cv2.error:
            pass


def main():
    fenster_info = _fenster_auswaehlen()
    hwnd = fenster_info["hwnd"]
    # hwnd=None => manuell aufgezogener Bereich (siehe _manueller_bereich()):
    # keine echte Fensterverfolgung, Position/Groesse bleiben fuer die
    # gesamte Sitzung fest.
    if hwnd is None:
        bereich_fest = {"x": fenster_info["x"], "y": fenster_info["y"],
                         "w": fenster_info["breite"], "h": fenster_info["hoehe"]}
        fenster_provider = lambda: dict(bereich_fest)
    else:
        fenster_provider = functools.partial(fenster_modul.fenster_von_hwnd, hwnd)

    bilder = _bilder_auswaehlen()
    print(f"\nBeobachte {len(bilder)} Bild(er) live (Schwelle {bild_erkennung.SCHWELLE_STANDARD}).")
    print("Duenne Linie = Template-Treffer, dicke Linie = gespeicherte Klick-Hitbox.")
    print("Vorschau-Fenster mit 'q' oder ESC schliessen.\n")

    try:
        live_vorschau_schleife(fenster_provider, bilder)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()


def _cli_main(argv):
    """Nicht-interaktiver Modus fuer die programmatische Einbettung (siehe
    Modul-Docstring): startet HIER als EIGENER PROZESS statt als Thread im
    command_center.py/makro_manager.py-Interpreter - OpenCV/HighGUI-Fenster
    aus einem Hintergrund-Thread heraus, waehrend Tkinter im selben Prozess
    gleichzeitig seine eigene Windows-Nachrichtenschleife faehrt, hat sich in
    der Praxis als instabil erwiesen (GUI blieb haengen/reagierte nicht mehr).
    Ein eigener Prozess ist davon vollstaendig unabhaengig."""
    parser = argparse.ArgumentParser(description="Live-Erkennungsvorschau (nicht-interaktiv)")
    ziel = parser.add_mutually_exclusive_group(required=True)
    ziel.add_argument("--hwnd", type=int, help="Fenster-Handle (Fensterverfolgung, siehe fenster_von_hwnd())")
    ziel.add_argument("--bereich", help="fester Bereich als 'x,y,w,h'")
    ziel.add_argument("--fenstertitel", help="per Fenstertitel suchen (siehe fenster_finden())")
    parser.add_argument("--titel", default=_STANDARD_TITEL, help="Titel des Vorschau-Fensters")
    parser.add_argument("--bilder", help="Komma-getrennte bilder_szenen-Namen (leer = alle)")
    ns = parser.parse_args(argv)

    if ns.hwnd is not None:
        fenster_provider = functools.partial(fenster_modul.fenster_von_hwnd, ns.hwnd)
    elif ns.bereich is not None:
        x, y, w, h = (int(teil) for teil in ns.bereich.split(","))
        bereich_fest = {"x": x, "y": y, "w": w, "h": h}
        fenster_provider = lambda: dict(bereich_fest)
    else:
        fenster_provider = functools.partial(fenster_modul.fenster_finden, ns.fenstertitel)

    bilder = ns.bilder.split(",") if ns.bilder else None
    try:
        live_vorschau_schleife(fenster_provider, bilder, fenster_titel=ns.titel)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if len(sys.argv) > 1:
        _cli_main(sys.argv[1:])
    else:
        main()
