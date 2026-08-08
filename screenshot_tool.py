#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screenshot_tool.py - Wiederverwendbare Bildschirm-Ausschnitt-Auswahl
("Snipping Tool"-artig): ein Vollbild-transparentes Toplevel, in dem der
Nutzer per Maus-Drag ein Rechteck aufzieht.

Eigenes Modul (statt Teil von bild_erkennung.py), da bild_erkennung.py
bewusst frei von Tkinter/GUI-Abhaengigkeiten gehalten ist (dort geht es nur
um Bilderkennungs-Logik, die z.B. auch aus fish_bot.py ohne GUI genutzt
wird). aktion_editor.py nutzt dieses Modul fuer den Knopf
"Bild einfuegen (Screenshot)".
"""

import tkinter as tk

from PIL import ImageGrab

ROT = "#f38ba8"


def screenshot_auswahl_bereich(parent=None):
    """Oeffnet ein transparentes Vollbild-Toplevel; der Nutzer zieht mit der
    Maus ein Rechteck auf. Blockiert (via wait_window), bis der Nutzer
    loslaesst oder mit ESC abbricht - fuer den direkten Aufruf aus einem
    Button-Callback gedacht.

    Einschraenkung: deckt per '-fullscreen' den Monitor ab, auf dem das
    Fenster erscheint (i.d.R. den primaeren) - kein echtes virtuelles
    Multi-Monitor-Vollbild.

    Args:
        parent: optionales Eltern-Widget (fuer die Toplevel-Erzeugung).

    Returns:
        PIL.Image.Image | None: der ausgewaehlte Bildschirmausschnitt, oder
            None bei Abbruch (ESC) oder einem zu kleinen/versehentlichen
            "Klick ohne Ziehen".
    """
    ergebnis = {"bild": None}
    zustand = {"start_x": None, "start_y": None, "rect_id": None}

    fenster = tk.Toplevel(parent) if parent is not None else tk.Tk()
    fenster.attributes("-fullscreen", True)
    try:
        fenster.attributes("-alpha", 0.30)
    except tk.TclError:
        pass  # Plattform ohne Fenster-Transparenz - Auswahl funktioniert trotzdem.
    try:
        fenster.attributes("-topmost", True)
    except tk.TclError:
        pass
    fenster.configure(bg="black")
    fenster.config(cursor="cross")

    canvas = tk.Canvas(fenster, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    hinweis = tk.Label(fenster, text="Bereich per Maus-Drag auswaehlen  -  ESC = Abbrechen",
                       bg="black", fg="white", font=("Segoe UI", 11))
    hinweis.place(relx=0.5, rely=0.02, anchor="n")

    def auf_maus_druecken(event):
        zustand["start_x"], zustand["start_y"] = event.x_root, event.y_root
        if zustand["rect_id"] is not None:
            canvas.delete(zustand["rect_id"])
        zustand["rect_id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline=ROT, width=2)

    def auf_maus_ziehen(event):
        if zustand["rect_id"] is None:
            return
        x0 = zustand["start_x"] - fenster.winfo_rootx()
        y0 = zustand["start_y"] - fenster.winfo_rooty()
        canvas.coords(zustand["rect_id"], x0, y0, event.x, event.y)

    def auf_maus_loslassen(event):
        x0, y0 = zustand["start_x"], zustand["start_y"]
        x1, y1 = event.x_root, event.y_root
        abschliessen(x0, y0, x1, y1)

    def auf_escape(event=None):
        abschliessen(None, None, None, None)

    def abschliessen(x0, y0, x1, y1):
        # Fenster VOR dem Screenshot verstecken, sonst wuerde die eigene
        # (halbtransparente) Overlay-Flaeche mit erfasst.
        try:
            fenster.withdraw()
            fenster.update()
        except tk.TclError:
            pass
        if x0 is not None and x1 is not None:
            links, rechts = sorted((x0, x1))
            oben, unten = sorted((y0, y1))
            if rechts - links >= 2 and unten - oben >= 2:
                try:
                    ergebnis["bild"] = ImageGrab.grab(bbox=(links, oben, rechts, unten))
                except Exception as e:
                    print("[screenshot_tool] Fehler beim Erfassen: %s" % e)
                    ergebnis["bild"] = None
        try:
            fenster.destroy()
        except tk.TclError:
            pass

    canvas.bind("<ButtonPress-1>", auf_maus_druecken)
    canvas.bind("<B1-Motion>", auf_maus_ziehen)
    canvas.bind("<ButtonRelease-1>", auf_maus_loslassen)
    fenster.bind("<Escape>", auf_escape)
    fenster.focus_force()

    fenster.wait_window()
    return ergebnis["bild"]
