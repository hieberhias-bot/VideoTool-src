#!/usr/bin/env python3
"""modules/fenster.py - Fenster-Erkennung fuer fenster-relative Aufnahmen"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.WindowFromPoint.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]

_GA_ROOT = 2


def _dpi_awareness_setzen():
    """Macht diesen Prozess DPI-aware (Per-Monitor V2, mit Fallback auf die
    aeltere systemweite DPI-Awareness), BEVOR irgendwo GetWindowRect()
    aufgerufen wird.

    Ohne dies liefert GetWindowRect() bei Windows-Anzeigeskalierung >100%
    DPI-virtualisierte (verkleinerte) Koordinaten, waehrend die Screenshot-
    Backends (dxcam/DXGI in fish_bot.py, PIL ImageGrab) in echten physischen
    Bildschirm-Pixeln arbeiten. Die daraus gebildete Screenshot-Box weicht
    dann vom tatsaechlichen Fenster ab (typisch: Box zu weit links/oben,
    zeigt Desktop-Hintergrund statt des vollstaendigen Fensterinhalts) - und
    saemtliche daraus abgeleiteten Erkennungs-/Klickkoordinaten sind
    entsprechend verschoben. Siehe die DPI-Diagnose-Warnung in
    fish_bot.screenshot_holen(), die genau dieses Symptom erkennt.
    """
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE (Win 8.1+) - liefert korrekte
        # physische Koordinaten auch bei mehreren Monitoren mit
        # unterschiedlicher Skalierung.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            # Aeltere Windows-Versionen ohne shcore (systemweit, kein
            # Per-Monitor-Support, aber immer noch besser als gar keine
            # DPI-Awareness).
            user32.SetProcessDPIAware()
        except OSError:
            pass


_dpi_awareness_setzen()

verfuegbar = True

# Systemfenster/Overlays, die nie als Zielfenster dienen sollen
_AUSSCHLUSS = ("microsoft text input", "program manager", "shell_traywnd",
               "default ime", "windows input experience", "task switching",
               "start", "search", "notification")

def _ist_ignorieren(titel):
    t = titel.lower()
    return not titel.strip() or any(s in t for s in _AUSSCHLUSS)

def _alle_fenster():
    fenster = []
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            laenge = user32.GetWindowTextLengthW(hwnd)
            titel = ""
            if laenge > 0:
                buf = ctypes.create_unicode_buffer(laenge + 1)
                user32.GetWindowTextW(hwnd, buf, laenge + 1)
                titel = buf.value
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 0 and h > 0 and not _ist_ignorieren(titel):
                fenster.append((hwnd, titel, rect.left, rect.top, w, h))
        return True
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return fenster

def fenster_holen(titel_teil):
    for hwnd, titel, x, y, w, h in _alle_fenster():
        if titel_teil.lower() in titel.lower():
            return hwnd
    return None

def fenster_finden(titel_teil):
    hwnd = fenster_holen(titel_teil)
    if not hwnd:
        return None
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    breite = rect.right - rect.left
    hoehe = rect.bottom - rect.top
    return {"x": rect.left, "y": rect.top, "w": breite, "h": hoehe}

def alle_spielfenster_finden(titel_teil="METIN2"):
    """Findet ALLE sichtbaren Fenster, deren Titel 'titel_teil' enthaelt (z.B.
    mehrere gleichzeitig offene METIN2-Clients) - im Gegensatz zu
    fenster_holen()/fenster_finden(), die nur das ERSTE (per EnumWindows-
    Reihenfolge, nicht positionsbasiert) Treffer-Fenster liefern.

    Jedes Fenster bekommt eine 1-basierte 'nummer' gemaess seiner Position
    (oben-links zuerst: primaer nach y, sekundaer nach x sortiert) - diese
    Nummer ist NUR fuer die Dauer eines Aufrufs stabil (ein neuer Aufruf nach
    Bewegen/Schliessen eines Fensters kann die Nummern verschieben), sie ist
    also fuer die GUI-Anzeige gedacht, nicht als dauerhafte Fenster-ID (siehe
    fenster_von_hwnd() dafuer).

    Returns:
        list[dict]: je Fenster {"hwnd","titel","x","y","breite","hoehe","nummer"},
            sortiert nach 'nummer'.
    """
    treffer = [(hwnd, titel, x, y, w, h) for hwnd, titel, x, y, w, h in _alle_fenster()
               if titel_teil.lower() in titel.lower()]
    treffer.sort(key=lambda t: (t[3], t[2]))  # (y, x) -> oben-links zuerst

    ergebnis = []
    for i, (hwnd, titel, x, y, w, h) in enumerate(treffer, start=1):
        ergebnis.append({"hwnd": hwnd, "titel": titel, "x": x, "y": y,
                          "breite": w, "hoehe": h, "nummer": i})
    return ergebnis


def fenster_von_hwnd(hwnd):
    """Liest die AKTUELLE Position/Groesse eines bereits bekannten Fensters
    (per hwnd) frisch aus - fuer die Fenster-Isolation: die Position wird bei
    jedem Zyklus neu geholt, falls das Fenster inzwischen bewegt wurde (siehe
    aktion_skript.py: fenster_provider-Callables kapseln genau diesen
    Aufruf).

    Returns:
        dict | None: {"hwnd","titel","x","y","w","h"} (dieselbe Form wie
            fenster_finden(), plus hwnd/titel) - dieselbe Feldbenennung wie
            der Rest des Ausfuehrungscodes (fish_bot.screenshot_holen() etc.
            erwarten "w"/"h", nicht "breite"/"hoehe" - siehe
            alle_spielfenster_finden() fuer die GUI-Anzeigeform). None, wenn
            das Fenster nicht mehr existiert oder nicht mehr sichtbar ist
            (z.B. inzwischen geschlossen).
    """
    if not hwnd or not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    laenge = user32.GetWindowTextLengthW(hwnd)
    titel = ""
    if laenge > 0:
        buf = ctypes.create_unicode_buffer(laenge + 1)
        user32.GetWindowTextW(hwnd, buf, laenge + 1)
        titel = buf.value
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return {"hwnd": hwnd, "titel": titel, "x": rect.left, "y": rect.top, "w": w, "h": h}


def fenster_unter_cursor():
    """Ermittelt das groesste NICHT-System-Fenster unter der aktuellen Mausposition."""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    mx, my = point.x, point.y

    kandidaten = []
    for hwnd, titel, x, y, w, h in _alle_fenster():
        if x <= mx < x + w and y <= my < y + h:
            kandidaten.append((hwnd, titel, x, y, w, h))

    if not kandidaten:
        return None

    # Groesstes Fenster unter dem Cursor waehlen (meist das Spielfenster)
    kandidaten.sort(key=lambda k: k[4] * k[5], reverse=True)
    hwnd, titel, x, y, w, h = kandidaten[0]
    return {"x": x, "y": y, "w": w, "h": h, "titel": titel}


def bereich_manuell_auswaehlen(master=None):
    """Laesst den Benutzer per Maus-Ziehen ein Rechteck auf dem Bildschirm
    aufziehen (wie bei einem Screenshot-Tool) und liefert es als fester
    Bildschirm-Bereich zurueck - unabhaengig von GetWindowRect/hwnd, z.B.
    wenn die automatische Fenstererkennung gerade falsch liegt (siehe
    live_erkennung_vorschau.py: von einem anderen Fenster ueberdeckte
    Bereiche werden trotzdem mitgegrabbt, weil Bildschirm-Screenshots immer
    das zeigen, was an der jeweiligen Stelle GERADE sichtbar/obenauf liegt -
    das laesst sich per manuellem Bereich nicht umgehen, wohl aber eine
    falsch erkannte Fenster-Position/-Groesse).

    Oeffnet dazu kurz ein durchsichtiges Vollbild-Overlay ueber den GESAMTEN
    virtuellen Bildschirm (SM_XVIRTUALSCREEN/SM_CXVIRTUALSCREEN etc. - deckt
    auch Mehrfach-Monitor-Setups ab, deren Ursprung nicht bei (0,0) liegt).
    Abbrechen mit ESC.

    Args:
        master: optionales bereits existierendes Tk-Wurzelfenster (z.B.
            command_center.CommandCenter.root). Wird ein Toplevel DIESES
            Fensters verwendet (mit wait_window() statt einer eigenen
            mainloop()) - ein ZWEITES eigenstaendiges tk.Tk() im selben
            Prozess wie eine bereits laufende Tkinter-App fuehrt zu
            eingefrorener/nicht mehr reagierender Oberflaeche (mehrere
            Tcl-Interpreter im selben Prozess sind nicht sauber unterstuetzt).
            None (Standard) = eigenstaendiger Aufruf ohne bestehende
            Tkinter-App (siehe live_erkennung_vorschau.py) - dort weiterhin
            ein eigenes tk.Tk().

    Returns:
        dict{"x","y","w","h","hwnd"} | None: aufgezogener Bereich in
            absoluten Bildschirmkoordinaten (plus per WindowFromPoint
            ermitteltes hwnd am Mittelpunkt, siehe unten), oder None bei
            Abbruch (ESC) oder einem zu kleinen Rechteck (<10x10px,
            vermutlich ein versehentlicher Klick ohne Ziehen).
    """
    import tkinter as tk

    vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

    root = tk.Toplevel(master) if master is not None else tk.Tk()
    root.geometry(f"{vw}x{vh}+{vx}+{vy}")
    root.overrideredirect(True)
    root.attributes("-alpha", 0.25)
    root.attributes("-topmost", True)
    root.config(cursor="crosshair")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        vw // 2, 30,
        text="Bereich aufziehen (Maus gedrueckt halten + ziehen) - ESC zum Abbrechen",
        fill="white", font=("Segoe UI", 14))

    def _cursor_screen_pos():
        """Echte physische Bildschirm-Mausposition per GetCursorPos - NICHT
        event.x/event.y verwenden: Tk berechnet Maus-Event-Koordinaten ueber
        seine eigene (zur Laufzeit per SetProcessDpiAwareness() gesetzten
        Process-DPI-Awareness ggf. nicht konsistente) Skalierung, was bei
        Skalierung != 100% zu einem falschen/verkleinerten aufgezogenen
        Bereich fuehrt (Symptom: Bereich sieht beim Ziehen optisch richtig
        aus, matcht aber danach keine Bilder mehr, weil der tatsaechlich
        gespeicherte Bereich nicht zu den echten Bildschirmpixeln passt, die
        dxcam/ImageGrab liefern)."""
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    start = {}
    rechteck_id = [None]
    ergebnis = {}

    def auf_start(_event):
        sx, sy = _cursor_screen_pos()
        start["x"], start["y"] = sx - vx, sy - vy
        rechteck_id[0] = canvas.create_rectangle(
            start["x"], start["y"], start["x"], start["y"], outline="red", width=2)

    def auf_ziehen(_event):
        if rechteck_id[0] is not None:
            sx, sy = _cursor_screen_pos()
            canvas.coords(rechteck_id[0], start["x"], start["y"], sx - vx, sy - vy)

    def auf_loslassen(_event):
        if "x" in start:
            sx, sy = _cursor_screen_pos()
            x0, y0, x1, y1 = start["x"], start["y"], sx - vx, sy - vy
            ergebnis["rect"] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        root.destroy()

    def auf_abbrechen(_event=None):
        root.destroy()

    canvas.bind("<ButtonPress-1>", auf_start)
    canvas.bind("<B1-Motion>", auf_ziehen)
    canvas.bind("<ButtonRelease-1>", auf_loslassen)
    root.bind("<Escape>", auf_abbrechen)

    root.focus_force()
    if master is not None:
        # wait_window() verarbeitet die BESTEHENDE mainloop() weiter (statt
        # eine zweite/eigene zu starten) und kehrt erst zurueck, wenn 'root'
        # (das Toplevel) zerstoert wird - das uebliche Muster fuer modale
        # Tkinter-Dialoge (siehe tkinter.simpledialog/messagebox).
        root.wait_window()
    else:
        root.mainloop()

    rect = ergebnis.get("rect")
    if rect is None:
        return None
    x0, y0, x1, y1 = rect
    breite, hoehe = x1 - x0, y1 - y0
    if breite < 10 or hoehe < 10:
        return None

    abs_x, abs_y = vx + x0, vy + y0
    # hwnd am Mittelpunkt des Bereichs mitliefern - NUR fuer SetForegroundWindow()
    # beim Tastendruck (siehe fish_bot.leertaste_tippen()), die eigentliche
    # Bildschirm-Aufnahme bleibt am fixen manuellen Bereich, nicht an diesem
    # Fenster hwnd (siehe bot_starten()-Doku oben: FEST, keine Verfolgung).
    hwnd = None
    try:
        punkt = wintypes.POINT(abs_x + breite // 2, abs_y + hoehe // 2)
        gefunden = user32.WindowFromPoint(punkt)
        if gefunden:
            hwnd = user32.GetAncestor(gefunden, _GA_ROOT) or gefunden
    except OSError:
        hwnd = None

    return {"x": abs_x, "y": abs_y, "w": breite, "h": hoehe, "hwnd": hwnd}


# Typische METIN2-Fenstergroesse (Beobachtungswert, siehe fish_bot.
# FENSTER_BREITE_/HOEHE_MIN/MAX fuer den Plausibilitaets-Toleranzbereich
# darum) - nur ein Platzhalter-Fallback fuer fenster_bereich_markieren(),
# wenn GERADE kein echtes METIN2-Fenster offen ist.
_METIN2_TYPISCHE_BREITE = 816
_METIN2_TYPISCHE_HOEHE = 639


def fenster_bereich_markieren(master=None, titel_teil="METIN2"):
    """Laesst den Benutzer per Maus-Ziehen einen FENSTERRELATIVEN Bereich
    markieren (0,0 = obere linke Fensterecke) - im Unterschied zu
    bereich_manuell_auswaehlen() (liefert einen FESTEN absoluten Bildschirm-
    bereich) gedacht fuer aktion_editor.py: der 'suchbereich' eines BILD_*-
    Schritts (siehe bild_erkennung._aktueller_treffer(suchbereich=...))
    schraenkt die Bild-Erkennung auf einen Teil des Fensters ein statt das
    GANZE Fenster zu durchsuchen - sinnvoll, weil METIN2-Fenster immer
    (ungefaehr) dieselbe Groesse haben, der Bereich also unabhaengig von der
    AKTUELLEN Fensterposition wiederverwendbar ist.

    Ist gerade (mindestens) ein 'titel_teil'-Fenster offen, wird das Overlay
    EXAKT ueber dessen aktuelle Position/Groesse gelegt (halbdurchsichtig,
    wie bereich_manuell_auswaehlen() - der echte, LIVE Fensterinhalt
    scheint durch, man kann also praezise auf UI-Elemente zielen). Ist KEIN
    Fenster offen, zeigt stattdessen eine undurchsichtige Platzhalterflaeche
    in der typischen METIN2-Fenstergroesse (_METIN2_TYPISCHE_BREITE/HOEHE) -
    weniger praezise, aber immerhin nutzbar, ohne dass das Spiel dafuer
    laufen muss.

    Args:
        master: siehe bereich_manuell_auswaehlen().
        titel_teil: siehe alle_spielfenster_finden().

    Returns:
        dict{"x0","y0","x1","y1"} | None: FENSTERRELATIVE Pixelkoordinaten
            (auf die Fenstergroesse begrenzt), oder None bei Abbruch (ESC)
            oder einem zu kleinen Rechteck (<10x10px).
    """
    import tkinter as tk

    fenster_liste = alle_spielfenster_finden(titel_teil)
    if fenster_liste:
        f = fenster_liste[0]
        ox, oy, ow, oh = f["x"], f["y"], f["breite"], f["hoehe"]
        live = True
    else:
        ow, oh = _METIN2_TYPISCHE_BREITE, _METIN2_TYPISCHE_HOEHE
        vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        ox = vx + max(0, (vw - ow) // 2)
        oy = vy + max(0, (vh - oh) // 2)
        live = False

    root = tk.Toplevel(master) if master is not None else tk.Tk()
    root.geometry(f"{ow}x{oh}+{ox}+{oy}")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.config(cursor="crosshair")
    if live:
        root.attributes("-alpha", 0.25)
    canvas = tk.Canvas(root, bg=("black" if live else "#222222"), highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    if not live:
        canvas.create_text(
            ow // 2, 20,
            text="Kein Metin2-Fenster offen - Platzhaltergroesse %dx%d" % (ow, oh),
            fill="white", font=("Segoe UI", 11))
    canvas.create_text(
        ow // 2, oh - 20,
        text="Bereich aufziehen (Maus gedrueckt halten + ziehen) - ESC zum Abbrechen",
        fill="white", font=("Segoe UI", 11))

    def _cursor_screen_pos():
        # Siehe bereich_manuell_auswaehlen()._cursor_screen_pos() - dieselbe
        # DPI-Begruendung (echte physische Koordinaten statt event.x/y).
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    start = {}
    rechteck_id = [None]
    ergebnis = {}

    def auf_start(_event):
        sx, sy = _cursor_screen_pos()
        start["x"], start["y"] = sx - ox, sy - oy
        rechteck_id[0] = canvas.create_rectangle(
            start["x"], start["y"], start["x"], start["y"], outline="red", width=2)

    def auf_ziehen(_event):
        if rechteck_id[0] is not None:
            sx, sy = _cursor_screen_pos()
            canvas.coords(rechteck_id[0], start["x"], start["y"], sx - ox, sy - oy)

    def auf_loslassen(_event):
        if "x" in start:
            sx, sy = _cursor_screen_pos()
            x0, y0, x1, y1 = start["x"], start["y"], sx - ox, sy - oy
            ergebnis["rect"] = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        root.destroy()

    def auf_abbrechen(_event=None):
        root.destroy()

    canvas.bind("<ButtonPress-1>", auf_start)
    canvas.bind("<B1-Motion>", auf_ziehen)
    canvas.bind("<ButtonRelease-1>", auf_loslassen)
    root.bind("<Escape>", auf_abbrechen)

    root.focus_force()
    if master is not None:
        root.wait_window()
    else:
        root.mainloop()

    rect = ergebnis.get("rect")
    if rect is None:
        return None
    x0, y0, x1, y1 = rect
    x0 = max(0, min(x0, ow))
    y0 = max(0, min(y0, oh))
    x1 = max(0, min(x1, ow))
    y1 = max(0, min(y1, oh))
    if (x1 - x0) < 10 or (y1 - y0) < 10:
        return None
    return {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}
