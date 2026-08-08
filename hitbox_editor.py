#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hitbox_editor.py - Bildbearbeiter fuer Szenen-Bilder (bilder_szenen/*.png):
kombinierter Toplevel-Dialog mit zwei Modi.

Modus "Hitbox" (ein Rechteck): schraenkt ein, wo innerhalb eines gefundenen
Bildes der Zufallsklickpunkt gewaehlt wird (siehe bild_erkennung.py,
BILD_KLICKEN/BILD_KLICKEN_WENN_WEG in aktion_skript.py). Ohne Hitbox gilt das
gesamte gefundene Bild als Klickbereich.

Modus "Maske" (mehrere Rechtecke, additiv): markiert Bereiche, die bei der
Bilderkennung selbst (cv2.matchTemplate) ignoriert werden sollen - z.B. Timer,
Zahlen oder blinkende Icons, die sich im Spiel veraendern und sonst faelsch-
licherweise einen Treffer verhindern wuerden (255=erkennen, 0=ignorieren,
siehe bild_erkennung.maske_*()).

Beide Modi sind unabhaengig voneinander: die Maske beeinflusst NICHT die
Hitbox und umgekehrt - ein Bild kann beides gleichzeitig haben.

Varianten: pro Bild koennen mehrere BENANNTE Hitbox-/Masken-Varianten
existieren (Feld "Variante:", Standardname = Bildname ohne Endung, siehe
bild_erkennung.standard_variante()). Gespeichert als
<bild>_hitbox_<variante>.json bzw. <bild>_mask_<variante>.png. Welche
Variante zur Laufzeit genutzt wird, waehlt der optionale "variante"-Parameter
der BILD_*-Aktionen in aktion_skript.py (leer = Standard-Variante).

Einhaengen (siehe aktion_editor.py):
    HitboxEditor(self, bild_name="wurm.png", on_save_callback=self._bilder_aktualisieren)
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import cv2
from PIL import Image, ImageTk

import bild_erkennung

BG = "#1e1e2e"
BG2 = "#11111b"
FG = "#cdd6f4"
MUTED = "#a6adc8"
ACCENT = "#89b4fa"
GRUEN = "#a6e3a1"
ROT = "#f38ba8"

MAX_BREITE = 700   # Maximale Vorschau-Groesse (px) - groessere Bilder werden
MAX_HOEHE = 500    # herunterskaliert, kleinere 1:1 angezeigt (keine Hochskalierung).


def _rechtecke_aus_maske(maske):
    """Rekonstruiert eine ungefaehre Liste von Rechtecken aus einer bereits
    gespeicherten Maske (fuer den Editor: 'weiteres Rechteck hinzufuegen',
    ohne die vorhandene Maske beim Neu-Oeffnen zu verlieren). Die Maske selbst
    bleibt die eigentliche Wahrheit - das hier ist nur eine Anzeige-Hilfe."""
    invertiert = cv2.bitwise_not(maske)  # maskierte (schwarze) Bereiche -> weiss
    konturen, _ = cv2.findContours(invertiert, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rechtecke = []
    for k in konturen:
        x, y, w, h = cv2.boundingRect(k)
        if w > 0 and h > 0:
            rechtecke.append({"x": x, "y": y, "w": w, "h": h})
    return rechtecke


class HitboxEditor(tk.Toplevel):
    def __init__(self, parent, bild_name=None, on_save_callback=None):
        super().__init__(parent)
        self.title("Bildbearbeiter (Hitbox / Maske)")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.on_save_callback = on_save_callback

        self._pil_bild = None          # Original-PIL-Bild (fuer die Originalgroesse)
        self._photo = None             # ImageTk.PhotoImage - Referenz muss gehalten werden!
        self._skalierung = 1.0         # Vorschau-Pixel = Original-Pixel * skalierung
        self._rect_id_temp = None      # Canvas-Item des Rechtecks waehrend des Ziehens
        self._ziehen_start = None      # (canvas_x, canvas_y) beim Ziehen des Rechtecks

        self._modus_var = tk.StringVar(value="hitbox")
        self._hitbox_original = None   # {"x","y","w","h"} in Original-Bildpixeln oder None
        self._maske_rechtecke = []     # Liste von {"x","y","w","h"} in Original-Bildpixeln

        self._build_ui()

        bilder = bild_erkennung.verfuegbare_bilder()
        self.combo_bild["values"] = bilder
        if bild_name and bild_name in bilder:
            self.combo_bild.set(bild_name)
        elif bilder:
            self.combo_bild.set(bilder[0])
        if self.combo_bild.get():
            self._bild_laden()

    def _build_ui(self):
        kopf = ttk.Frame(self)
        kopf.pack(fill="x", padx=15, pady=10)
        ttk.Label(kopf, text="Bildbearbeiter", font=("Segoe UI", 14, "bold"),
                  foreground=ACCENT).pack(side="left")

        auswahl = ttk.Frame(self)
        auswahl.pack(fill="x", padx=15, pady=(0, 4))
        ttk.Label(auswahl, text="Bild:").pack(side="left")
        self.combo_bild = ttk.Combobox(auswahl, state="readonly", width=32)
        self.combo_bild.pack(side="left", padx=5)
        self.combo_bild.bind("<<ComboboxSelected>>", lambda e: self._bild_laden())

        # ---- Varianten-Auswahl (benannte Hitbox-/Masken-Variante) ----
        variante_zeile = ttk.Frame(self)
        variante_zeile.pack(fill="x", padx=15, pady=(0, 8))
        ttk.Label(variante_zeile, text="Variante:").pack(side="left")
        # Editierbar (kein state="readonly"): der Nutzer kann sowohl eine
        # bestehende Variante waehlen als auch einen neuen Namen eintippen,
        # um eine weitere Variante anzulegen.
        self.combo_variante = ttk.Combobox(variante_zeile, width=20)
        self.combo_variante.pack(side="left", padx=5)
        self.combo_variante.bind("<<ComboboxSelected>>", self._variante_laden)
        self.combo_variante.bind("<Return>", self._variante_laden)
        self.combo_variante.bind("<FocusOut>", self._variante_laden)
        ttk.Button(variante_zeile, text="⧉ Duplizieren",
                  command=self._variante_duplizieren).pack(side="left", padx=(10, 3))
        ttk.Button(variante_zeile, text="\U0001F5D1 Variante loeschen", style="Danger.TButton",
                  command=self._variante_loeschen).pack(side="left", padx=3)

        # ---- Modus-Umschalter ----
        modus_frame = ttk.Frame(self)
        modus_frame.pack(fill="x", padx=15, pady=(0, 5))
        ttk.Label(modus_frame, text="Modus:").pack(side="left")
        ttk.Radiobutton(modus_frame, text="Hitbox (Klickbereich)", variable=self._modus_var,
                        value="hitbox", command=self._modus_gewechselt).pack(side="left", padx=(5, 15))
        ttk.Radiobutton(modus_frame, text="Maske (bei Erkennung ignorierte Bereiche)",
                        variable=self._modus_var, value="maske",
                        command=self._modus_gewechselt).pack(side="left")

        self.lbl_hinweis = ttk.Label(self, foreground=MUTED)
        self.lbl_hinweis.pack(anchor="w", padx=15, pady=(0, 5))

        canvas_rahmen = ttk.Frame(self)
        canvas_rahmen.pack(padx=15, pady=5)
        self.canvas = tk.Canvas(canvas_rahmen, bg=BG2, width=MAX_BREITE, height=MAX_HOEHE,
                                highlightthickness=1, highlightbackground=ACCENT)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._on_maus_press)
        self.canvas.bind("<B1-Motion>", self._on_maus_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_maus_release)

        self.lbl_koordinaten = ttk.Label(self, text="Kein Bild geladen.", foreground=MUTED)
        self.lbl_koordinaten.pack(anchor="w", padx=15, pady=(5, 5))

        # ---- Masken-Rechteckliste (nur im Maske-Modus mit Inhalt gefuellt) ----
        self._maske_liste_frame = ttk.Frame(self)
        self._maske_liste_frame.pack(fill="x", padx=15, pady=(0, 5))

        # ---- Aktions-Buttons (Inhalt je nach Modus neu aufgebaut) ----
        self._aktionen_frame = ttk.Frame(self)
        self._aktionen_frame.pack(fill="x", padx=15, pady=10)

        self._modus_gewechselt()

    # ================= Modus-Umschaltung =================

    def _modus_gewechselt(self):
        modus = self._modus_var.get()
        if modus == "hitbox":
            self.lbl_hinweis.config(
                text="Mit der Maus EIN Rechteck aufziehen: der Zufallsklick landet spaeter darin.")
        else:
            self.lbl_hinweis.config(
                text="Mit der Maus beliebig viele Rechtecke aufziehen: diese Bereiche werden bei "
                     "der Bilderkennung ignoriert (z.B. Timer/blinkende Icons).")

        for w in self._maske_liste_frame.winfo_children():
            w.destroy()
        if modus == "maske":
            ttk.Label(self._maske_liste_frame, text="Masken-Rechtecke:").pack(anchor="w")
            liste_zeile = ttk.Frame(self._maske_liste_frame)
            liste_zeile.pack(fill="x")
            self._maske_listbox = tk.Listbox(liste_zeile, bg=BG2, fg=FG, height=4,
                                             font=("Consolas", 9))
            self._maske_listbox.pack(side="left", fill="x", expand=True)
            ttk.Button(liste_zeile, text="Ausgewaehltes entfernen",
                      command=self._maske_rechteck_entfernen).pack(side="left", padx=(8, 0))
            self._maske_liste_aktualisieren()

        for w in self._aktionen_frame.winfo_children():
            w.destroy()
        if modus == "hitbox":
            ttk.Button(self._aktionen_frame, text="✔ Hitbox speichern", style="Success.TButton",
                      command=self._hitbox_speichern).pack(side="left", padx=5)
            ttk.Button(self._aktionen_frame, text="\U0001F5D1 Hitbox entfernen",
                      style="Danger.TButton", command=self._hitbox_entfernen).pack(side="left", padx=5)
        else:
            ttk.Button(self._aktionen_frame, text="✔ Maske speichern", style="Success.TButton",
                      command=self._maske_speichern_klick).pack(side="left", padx=5)
            ttk.Button(self._aktionen_frame, text="\U0001F5D1 Maske loeschen",
                      style="Danger.TButton", command=self._maske_loeschen_klick).pack(side="left", padx=5)
        ttk.Button(self._aktionen_frame, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)

        self._canvas_neu_zeichnen()

    # ================= Bild laden/anzeigen =================

    def _bild_laden(self):
        name = self.combo_bild.get()
        if not name:
            return
        pfad = os.path.join(bild_erkennung.BILDER_ORDNER, name)
        try:
            self._pil_bild = Image.open(pfad).convert("RGB")
        except Exception as e:
            messagebox.showerror("Fehler", "Bild konnte nicht geladen werden:\n%s" % e)
            return

        bild_w, bild_h = self._pil_bild.size
        self._skalierung = min(1.0, MAX_BREITE / bild_w, MAX_HOEHE / bild_h)
        anzeige_w = max(1, int(bild_w * self._skalierung))
        anzeige_h = max(1, int(bild_h * self._skalierung))

        anzeige_bild = self._pil_bild
        if self._skalierung != 1.0:
            anzeige_bild = self._pil_bild.resize((anzeige_w, anzeige_h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(anzeige_bild)

        self.canvas.config(width=anzeige_w, height=anzeige_h)

        self._varianten_liste_aktualisieren(bevorzugt=bild_erkennung.standard_variante(name))
        self._variante_laden()

    # ================= Varianten-Verwaltung =================

    def _varianten_liste_aktualisieren(self, bevorzugt=None):
        """Aktualisiert die Werte-Liste des Varianten-Feldes fuer das
        aktuell gewaehlte Bild (immer inkl. der Standard-Variante, auch wenn
        dafuer noch keine Datei existiert - das ist das Ziel eines ersten
        Speicherns). 'bevorzugt' wird als aktueller Wert gesetzt, falls
        angegeben; sonst bleibt der bisherige Text erhalten."""
        name = self.combo_bild.get()
        if not name:
            self.combo_variante["values"] = []
            self.combo_variante.set("")
            return
        standard = bild_erkennung.standard_variante(name)
        varianten = bild_erkennung.varianten_liste(name)
        if standard not in varianten:
            varianten = sorted(varianten + [standard])
        self.combo_variante["values"] = varianten
        ziel = bevorzugt if bevorzugt is not None else (self.combo_variante.get().strip() or standard)
        self.combo_variante.set(ziel)

    def _aktuelle_variante(self):
        name = self.combo_bild.get()
        if not name:
            return ""
        return self.combo_variante.get().strip() or bild_erkennung.standard_variante(name)

    def _variante_laden(self, event=None):
        """Laedt Hitbox+Maske fuer (aktuelles Bild, aktuelle Variante) neu -
        aufgerufen sowohl beim Bildwechsel (ueber _bild_laden()) als auch,
        wenn nur die Variante gewechselt/eingegeben wird."""
        name = self.combo_bild.get()
        if not name:
            return
        variante = self._aktuelle_variante()
        self._hitbox_original = bild_erkennung.hitbox_laden(name, variante)
        maske_bild = bild_erkennung.maske_laden(name, variante)
        self._maske_rechtecke = _rechtecke_aus_maske(maske_bild) if maske_bild is not None else []

        if self._modus_var.get() == "maske" and hasattr(self, "_maske_listbox"):
            self._maske_liste_aktualisieren()
        self._canvas_neu_zeichnen()

    def _variante_duplizieren(self):
        name = self.combo_bild.get()
        if not name:
            messagebox.showwarning("Hinweis", "Kein Bild ausgewaehlt.")
            return
        quelle = self._aktuelle_variante()
        ziel = simpledialog.askstring(
            "Variante duplizieren",
            "Neuer Variantenname (Kopie von '%s'):" % quelle, parent=self)
        if not ziel:
            return
        ziel = ziel.strip()
        try:
            bild_erkennung.variante_kopieren(name, quelle, ziel)
        except bild_erkennung.BildErkennungFehler as e:
            messagebox.showerror("Fehler", str(e))
            return
        self._varianten_liste_aktualisieren(bevorzugt=ziel)
        self._variante_laden()
        self._callback_aufrufen()
        messagebox.showinfo("Dupliziert", "Variante '%s' wurde als '%s' dupliziert." % (quelle, ziel))

    def _variante_loeschen(self):
        name = self.combo_bild.get()
        if not name:
            return
        variante = self._aktuelle_variante()
        if not messagebox.askyesno(
                "Variante loeschen",
                "Variante '%s' (Hitbox UND Maske) von '%s' wirklich loeschen?" % (variante, name)):
            return
        bild_erkennung.variante_entfernen(name, variante)
        self._varianten_liste_aktualisieren(bevorzugt=bild_erkennung.standard_variante(name))
        self._variante_laden()
        self._callback_aufrufen()

    def _canvas_neu_zeichnen(self):
        """Zeichnet das Bild plus die zum aktiven Modus gehoerigen, bereits
        gesetzten Rechtecke neu (einzige Quelle der Wahrheit: self._hitbox_original
        bzw. self._maske_rechtecke - das Canvas ist nur deren Darstellung)."""
        self.canvas.delete("all")
        if self._photo is not None:
            self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._rect_id_temp = None

        if self._pil_bild is None:
            return
        bild_w, bild_h = self._pil_bild.size

        if self._modus_var.get() == "hitbox":
            if self._hitbox_original:
                hb = self._hitbox_original
                self._rechteck_zeichnen(hb, GRUEN)
                self._koordinaten_anzeigen(
                    "Hitbox: X=%d  Y=%d  Breite=%d  Hoehe=%d  (Original-Bildpixel)"
                    % (hb["x"], hb["y"], hb["w"], hb["h"]))
            else:
                self._koordinaten_anzeigen(
                    "Keine Hitbox gespeichert - das gesamte Bild (%dx%d px) gilt als Klickbereich."
                    % (bild_w, bild_h), MUTED)
        else:
            for r in self._maske_rechtecke:
                self._rechteck_zeichnen(r, ROT)
            if self._maske_rechtecke:
                self._koordinaten_anzeigen(
                    "%d Masken-Rechteck(e) markiert (Original-Bildpixel, siehe Liste)."
                    % len(self._maske_rechtecke))
            else:
                self._koordinaten_anzeigen(
                    "Keine Maske gespeichert - das gesamte Bild (%dx%d px) wird zur Erkennung genutzt."
                    % (bild_w, bild_h), MUTED)

    def _rechteck_zeichnen(self, r, farbe):
        x0 = r["x"] * self._skalierung
        y0 = r["y"] * self._skalierung
        x1 = (r["x"] + r["w"]) * self._skalierung
        y1 = (r["y"] + r["h"]) * self._skalierung
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=farbe, width=2,
                                     fill=farbe, stipple="gray50")

    def _koordinaten_anzeigen(self, text, farbe=FG):
        self.lbl_koordinaten.config(text=text, foreground=farbe)

    # ================= Maus-Interaktion (Rechteck aufziehen) =================

    def _canvas_grenzen(self, x, y):
        breite = int(self.canvas["width"])
        hoehe = int(self.canvas["height"])
        return max(0, min(x, breite)), max(0, min(y, hoehe))

    def _on_maus_press(self, event):
        if self._pil_bild is None:
            return
        x, y = self._canvas_grenzen(event.x, event.y)
        self._ziehen_start = (x, y)
        if self._rect_id_temp is not None:
            self.canvas.delete(self._rect_id_temp)
        # Waehrend des Ziehens immer ROT (auch im Hitbox-Modus) - wird beim
        # Loslassen ggf. auf GRUEN umgefaerbt (siehe _canvas_neu_zeichnen()).
        self._rect_id_temp = self.canvas.create_rectangle(
            x, y, x, y, outline=ROT, width=2, fill=ROT, stipple="gray50")

    def _on_maus_drag(self, event):
        if self._ziehen_start is None or self._rect_id_temp is None:
            return
        x, y = self._canvas_grenzen(event.x, event.y)
        x0, y0 = self._ziehen_start
        self.canvas.coords(self._rect_id_temp, x0, y0, x, y)

    def _on_maus_release(self, event):
        if self._ziehen_start is None or self._rect_id_temp is None:
            return
        x, y = self._canvas_grenzen(event.x, event.y)
        x0, y0 = self._ziehen_start
        links, rechts = sorted((x0, x))
        oben, unten = sorted((y0, y))
        self._ziehen_start = None
        self.canvas.delete(self._rect_id_temp)
        self._rect_id_temp = None

        if rechts - links < 2 or unten - oben < 2:
            return  # Zu kleines/versehentliches Rechteck (blosser Klick) -> verwerfen.

        rechteck = self._rechteck_aus_canvas(links, rechts, oben, unten)
        if self._modus_var.get() == "hitbox":
            self._hitbox_original = rechteck
        else:
            self._maske_rechtecke.append(rechteck)
            self._maske_liste_aktualisieren()
        self._canvas_neu_zeichnen()

    def _rechteck_aus_canvas(self, links, rechts, oben, unten):
        ox = int(links / self._skalierung)
        oy = int(oben / self._skalierung)
        ow = max(1, int((rechts - links) / self._skalierung))
        oh = max(1, int((unten - oben) / self._skalierung))
        return {"x": ox, "y": oy, "w": ow, "h": oh}

    # ================= Masken-Rechteckliste =================

    def _maske_liste_aktualisieren(self):
        self._maske_listbox.delete(0, "end")
        for i, r in enumerate(self._maske_rechtecke, 1):
            self._maske_listbox.insert(
                "end", "%d: X=%d Y=%d Breite=%d Hoehe=%d" % (i, r["x"], r["y"], r["w"], r["h"]))

    def _maske_rechteck_entfernen(self):
        sel = self._maske_listbox.curselection()
        if not sel:
            return
        del self._maske_rechtecke[sel[0]]
        self._maske_liste_aktualisieren()
        self._canvas_neu_zeichnen()

    # ================= Speichern/Entfernen: Hitbox =================

    def _hitbox_speichern(self):
        name = self.combo_bild.get()
        if not name:
            messagebox.showwarning("Hinweis", "Kein Bild ausgewaehlt.")
            return
        if not self._hitbox_original:
            messagebox.showwarning("Hinweis",
                "Kein Rechteck aufgezogen - bitte mit der Maus eine Hitbox markieren, "
                "oder 'Hitbox entfernen' fuer das gesamte Bild als Klickbereich.")
            return
        variante = self._aktuelle_variante()
        try:
            bild_erkennung.hitbox_speichern(name, self._hitbox_original, variante)
        except bild_erkennung.BildErkennungFehler as e:
            messagebox.showerror("Fehler", str(e))
            return
        self._varianten_liste_aktualisieren(bevorzugt=variante)
        self._callback_aufrufen()
        messagebox.showinfo("Gespeichert", "Hitbox '%s' fuer '%s' gespeichert." % (variante, name))
        self.destroy()

    def _hitbox_entfernen(self):
        name = self.combo_bild.get()
        if not name:
            return
        bild_erkennung.hitbox_entfernen(name, self._aktuelle_variante())
        self._hitbox_original = None
        self._canvas_neu_zeichnen()
        self._callback_aufrufen()

    # ================= Speichern/Entfernen: Maske =================

    def _maske_speichern_klick(self):
        name = self.combo_bild.get()
        if not name:
            messagebox.showwarning("Hinweis", "Kein Bild ausgewaehlt.")
            return
        if not self._maske_rechtecke:
            messagebox.showwarning("Hinweis",
                "Keine Masken-Rechtecke markiert - bitte mit der Maus mindestens ein Rechteck "
                "aufziehen, oder 'Maske loeschen' fuer keine Maskierung.")
            return
        variante = self._aktuelle_variante()
        try:
            bild_erkennung.maske_speichern(name, self._maske_rechtecke, variante)
        except bild_erkennung.BildErkennungFehler as e:
            messagebox.showerror("Fehler", str(e))
            return
        self._varianten_liste_aktualisieren(bevorzugt=variante)
        self._callback_aufrufen()
        messagebox.showinfo("Gespeichert",
                           "Maske '%s' fuer '%s' gespeichert (%d Rechteck(e))."
                           % (variante, name, len(self._maske_rechtecke)))
        self.destroy()

    def _maske_loeschen_klick(self):
        name = self.combo_bild.get()
        if not name:
            return
        bild_erkennung.maske_entfernen(name, self._aktuelle_variante())
        self._maske_rechtecke = []
        if hasattr(self, "_maske_listbox"):
            self._maske_liste_aktualisieren()
        self._canvas_neu_zeichnen()
        self._callback_aufrufen()

    def _callback_aufrufen(self):
        if self.on_save_callback:
            try:
                self.on_save_callback()
            except Exception:
                pass
