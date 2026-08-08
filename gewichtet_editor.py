#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gewichtet_editor.py - Dialog "Gewichteter Pfad bearbeiten" fuer die
GEWICHTET-Aktion (siehe aktion_skript.py: _gewichtet_schritt()).

Ein GEWICHTET-Schritt waehlt zur Laufzeit zufaellig (gewichtet) einen von
mehreren Pfaden aus und fuehrt dessen Schritte aus. Dieser Dialog bearbeitet
schritt["parameter"]["pfade"] = [{"gewicht": <zahl>, "schritte": [...]}, ...].

Jeder Pfad bekommt eine eigene Schritt-Liste, die exakt dieselben Aktions-
Buttons und Eingabefelder verwendet wie der Haupt-Editor (aktion_editor.py) -
technisch durch Wiederverwendung von dessen modulweiten Funktionen
(parameter_felder_bauen() etc.) statt Duplikation. Ein Pfad darf selbst
wieder einen GEWICHTET-Schritt enthalten (rekursiv, oeffnet einen weiteren
GewichtetEditor uebereinander) - die Tiefenbegrenzung dafuer erzwingt
aktion_skript.py (GEWICHTET_MAX_TIEFE) zur Laufzeit, nicht dieser Editor.

Aenderungen wirken sich erst beim Klick auf "OK" auf den uebergebenen
'schritt' aus (Arbeitskopie via copy.deepcopy) - "Abbrechen" verwirft sie.
"""

import copy
import tkinter as tk
from tkinter import ttk, messagebox

import aktion_skript
from aktion_editor import (
    AKTIONS_BUTTONS, parameter_felder_bauen,
    BG, BG2, BG3, FG, MUTED, ACCENT, GRUEN, ROT, GELB,
)


class GewichtetEditor(tk.Toplevel):
    def __init__(self, parent, schritt, on_save_callback=None):
        """
        Args:
            parent: Eltern-Widget.
            schritt: das GEWICHTET-Schritt-Dict aus der aeusseren Schritt-
                Liste - wird erst bei OK veraendert (schritt["parameter"]["pfade"]).
            on_save_callback: optionales Callable(), nach erfolgreichem OK
                aufgerufen (z.B. um die aeussere Zeilenliste neu zu zeichnen).
        """
        super().__init__(parent)
        self.title("Gewichteter Pfad bearbeiten")
        self.configure(bg=BG)
        self.geometry("950x620")
        self.transient(parent)

        self.schritt = schritt
        self.on_save_callback = on_save_callback
        schritt.setdefault("parameter", {})
        pfade = copy.deepcopy(schritt["parameter"].get("pfade", []))
        self.pfade = pfade if pfade else [{"gewicht": 100, "schritte": []}]

        self._build_ui()
        self._pfade_neu_zeichnen()

        self.grab_set()
        self.focus_set()

    # ================= UI-Aufbau =================

    def _build_ui(self):
        kopf = ttk.Frame(self)
        kopf.pack(fill="x", padx=14, pady=(14, 4))
        ttk.Label(kopf, text="GEWICHTETER PFAD", style="Header.TLabel").pack(side="left")
        self.lbl_summe = ttk.Label(kopf, text="Summe: 0%", foreground=MUTED)
        self.lbl_summe.pack(side="right")

        hinweis = ttk.Label(
            self,
            text="Waehlt zur Laufzeit zufaellig einen der Pfade (gewichtet nach Prozent). "
                 "Die Summe muss nicht exakt 100 ergeben - sie wird automatisch normalisiert.",
            foreground=MUTED, wraplength=900)
        hinweis.pack(fill="x", padx=14, pady=(0, 6))

        ttk.Button(self, text="＋ Pfad hinzufuegen",
                  command=self._pfad_hinzufuegen).pack(anchor="w", padx=14, pady=(0, 6))

        aussen = ttk.Frame(self)
        aussen.pack(fill="both", expand=True, padx=14, pady=4)
        self._canvas = tk.Canvas(aussen, bg=BG2, highlightthickness=0)
        scroll = ttk.Scrollbar(aussen, orient="vertical", command=self._canvas.yview)
        self.innen = ttk.Frame(self._canvas)
        self.innen.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self.innen, anchor="nw")
        self._canvas.configure(yscrollcommand=scroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        unten = ttk.Frame(self)
        unten.pack(fill="x", padx=14, pady=10)
        ttk.Button(unten, text="✔ OK", style="Success.TButton",
                  command=self._ok).pack(side="left", padx=4)
        ttk.Button(unten, text="Abbrechen", command=self.destroy).pack(side="left", padx=4)

    # ================= Pfad-Bloecke =================

    def _pfade_neu_zeichnen(self):
        for kind in self.innen.winfo_children():
            kind.destroy()
        for i, pfad in enumerate(self.pfade):
            self._pfad_block_bauen(self.innen, i, pfad)
        self._summe_aktualisieren()

    def _pfad_block_bauen(self, container, i, pfad):
        rahmen = ttk.LabelFrame(container, text="Pfad %d" % (i + 1))
        rahmen.pack(fill="x", padx=4, pady=6)

        kopf = ttk.Frame(rahmen)
        kopf.pack(fill="x", padx=8, pady=(6, 4))
        ttk.Label(kopf, text="Gewicht:").pack(side="left")
        gewicht_entry = ttk.Entry(kopf, width=6)
        gewicht_entry.insert(0, _zahl_text(pfad.get("gewicht", 0)))
        gewicht_entry.pack(side="left", padx=4)

        def gewicht_uebernehmen(event=None, i=i, entry=gewicht_entry):
            try:
                self.pfade[i]["gewicht"] = float(entry.get().strip())
            except ValueError:
                pass
            self._summe_aktualisieren()
        gewicht_entry.bind("<FocusOut>", gewicht_uebernehmen)
        gewicht_entry.bind("<Return>", gewicht_uebernehmen)
        ttk.Label(kopf, text="%").pack(side="left")

        ttk.Label(kopf, text="   %d Schritt(e)" % len(pfad.get("schritte", [])),
                 foreground=MUTED).pack(side="left", padx=10)

        ttk.Button(kopf, text="\U0001F5D1 Pfad entfernen", style="Danger.TButton",
                  command=lambda i=i: self._pfad_entfernen(i)).pack(side="right", padx=4)

        # Aktions-Buttons fuer diesen Pfad (identische Liste wie Haupt-Editor)
        aktionen = ttk.Frame(rahmen)
        aktionen.pack(fill="x", padx=8, pady=(0, 4))
        halbe = (len(AKTIONS_BUTTONS) + 1) // 2
        zeile1 = ttk.Frame(aktionen)
        zeile1.pack(fill="x")
        zeile2 = ttk.Frame(aktionen)
        zeile2.pack(fill="x")
        for j, aktion in enumerate(AKTIONS_BUTTONS):
            ziel = zeile1 if j < halbe else zeile2
            ttk.Button(ziel, text="+ " + aktion,
                      command=lambda a=aktion, i=i: self._schritt_hinzufuegen(i, a)
                      ).pack(side="left", padx=2, pady=2)

        # Schritt-Liste dieses Pfads
        liste = ttk.Frame(rahmen)
        liste.pack(fill="x", padx=8, pady=(0, 8))
        for j, schritt in enumerate(pfad.get("schritte", [])):
            self._schritt_zeile_bauen(liste, i, j, schritt)
        if not pfad.get("schritte"):
            ttk.Label(liste, text="(keine Schritte - mit den Buttons oben hinzufuegen)",
                     foreground=MUTED).pack(anchor="w", pady=4)

    def _schritt_zeile_bauen(self, container, pi, si, schritt):
        aktion = schritt.get("aktion", "?")
        p = schritt.setdefault("parameter", {})
        zeile = ttk.Frame(container, style="Zeile.TFrame")
        zeile.pack(fill="x", pady=2, padx=2)

        ttk.Label(zeile, text="%2d" % (si + 1), width=3, style="Zeile.TLabel").pack(side="left")
        ttk.Label(zeile, text=aktion, width=18, style="Zeile.TLabel",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))

        if aktion == "GEWICHTET":
            ttk.Label(zeile, text="\U0001F3B2 " + aktion_skript.gewichtet_kompakt(p),
                     style="Zeile.TLabel").pack(side="left", padx=4)
            ttk.Button(zeile, text="Bearbeiten...",
                      command=lambda s=schritt: self._verschachtelt_bearbeiten(s)
                      ).pack(side="left", padx=4)
        else:
            parameter_felder_bauen(zeile, aktion, schritt)

        rechts = ttk.Frame(zeile, style="Zeile.TFrame")
        rechts.pack(side="right", padx=4)
        ttk.Button(rechts, text="▲", width=3,
                  command=lambda pi=pi, si=si: self._schritt_hoch(pi, si)).pack(side="left", padx=1)
        ttk.Button(rechts, text="▼", width=3,
                  command=lambda pi=pi, si=si: self._schritt_runter(pi, si)).pack(side="left", padx=1)
        ttk.Button(rechts, text="✖", width=3, style="Danger.TButton",
                  command=lambda pi=pi, si=si: self._schritt_loeschen(pi, si)).pack(side="left", padx=1)

    # ================= Pfad-Aktionen =================

    def _pfad_hinzufuegen(self):
        self.pfade.append({"gewicht": 10, "schritte": []})
        self._pfade_neu_zeichnen()

    def _pfad_entfernen(self, i):
        if len(self.pfade) <= 1:
            messagebox.showwarning("Hinweis", "Mindestens ein Pfad muss vorhanden bleiben.")
            return
        if not messagebox.askyesno("Pfad entfernen", "Pfad %d wirklich entfernen?" % (i + 1)):
            return
        del self.pfade[i]
        self._pfade_neu_zeichnen()

    # ================= Schritt-Aktionen (innerhalb eines Pfads) =================

    def _schritt_hinzufuegen(self, pi, aktion):
        self.pfade[pi].setdefault("schritte", []).append(aktion_skript.neuer_schritt(aktion))
        self._pfade_neu_zeichnen()

    def _schritt_hoch(self, pi, si):
        schritte = self.pfade[pi]["schritte"]
        if si <= 0 or si >= len(schritte):
            return
        schritte[si - 1], schritte[si] = schritte[si], schritte[si - 1]
        self._pfade_neu_zeichnen()

    def _schritt_runter(self, pi, si):
        schritte = self.pfade[pi]["schritte"]
        if si < 0 or si >= len(schritte) - 1:
            return
        schritte[si + 1], schritte[si] = schritte[si], schritte[si + 1]
        self._pfade_neu_zeichnen()

    def _schritt_loeschen(self, pi, si):
        schritte = self.pfade[pi]["schritte"]
        if 0 <= si < len(schritte):
            del schritte[si]
            self._pfade_neu_zeichnen()

    def _verschachtelt_bearbeiten(self, schritt):
        GewichtetEditor(self, schritt, on_save_callback=self._pfade_neu_zeichnen)

    # ================= Summe/Speichern =================

    def _summe_aktualisieren(self):
        summe = sum(max(0.0, float(pf.get("gewicht", 0))) for pf in self.pfade)
        farbe = MUTED
        if summe <= 0:
            farbe = ROT
        elif abs(summe - 100) > 20:
            farbe = GELB  # nur Hinweis - Gewichte werden zur Laufzeit normalisiert
        self.lbl_summe.config(text="Summe: %s%%" % _zahl_text(summe), foreground=farbe)

    def _ok(self):
        # Fokuswechsel auf den OK-Button hat bereits alle offenen Entry-
        # FocusOut-Handler ausgeloest, d.h. self.pfade ist an dieser Stelle
        # aktuell.
        if not self.pfade:
            messagebox.showwarning("Hinweis", "Mindestens ein Pfad wird benoetigt.")
            return
        summe = sum(max(0.0, float(pf.get("gewicht", 0))) for pf in self.pfade)
        if summe <= 0:
            messagebox.showwarning(
                "Hinweis", "Mindestens ein Pfad muss ein Gewicht > 0 haben.")
            return
        self.schritt["parameter"]["pfade"] = self.pfade
        if self.on_save_callback:
            self.on_save_callback()
        self.destroy()


def _zahl_text(wert):
    """Formatiert eine Zahl ohne unnoetige Nachkommastellen (10.0 -> '10')."""
    f = float(wert)
    if f == int(f):
        return str(int(f))
    return str(f)
