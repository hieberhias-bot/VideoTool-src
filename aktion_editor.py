#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aktion_editor.py - Tkinter-Tab "Bot-Skripte" fuer aktionsbasierte Ablaeufe.

Getrennt vom aelteren, koordinatenbasierten Ablauf-System (ablauf_*.json,
AblaufEditor-Toplevel, pyautogui) in command_center.py - dieser Tab arbeitet
mit Aktionen (WARTEN/TASTE/WURM_KLICKEN/BILD_KLICKEN/...) statt aufgezeichneten
X/Y-Klicks und fuehrt sie ueber die HID-Maus-Hardware aus (siehe aktion_skript.py).

Die Schritt-Liste ist button-basiert: oben ein Knopf pro Aktions-Typ (fuegt
einen neuen, sofort inline editierbaren Schritt hinzu), jede Zeile darunter
traegt ihre Parameterfelder direkt in sich (kein separates Bearbeiten-Formular
mehr). Aenderungen an einem Feld werden bei Verlassen des Feldes (bzw. bei
Auswahl in einer Combobox/Checkbox) sofort in self.schritte uebernommen.

Einhaengen (siehe command_center.py):
    tab = AktionsSkriptTab(notebook, basis_dir, hid_maus_getter, log_callback)
    notebook.add(tab, text="Bot-Skripte")
    root.bind("<F8>", lambda e: tab.hotkey_f8())
"""

import os
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext, filedialog

from PIL import Image, ImageTk

import aktion_skript
import bild_erkennung
import hid_maus
import modules.fenster as fenster_modul
import screenshot_tool
from hitbox_editor import HitboxEditor

# Catppuccin Mocha - dieselbe Palette wie command_center.py/_setup_style()
BG = "#1e1e2e"
BG2 = "#11111b"
BG3 = "#313244"
FG = "#cdd6f4"
MUTED = "#a6adc8"
ACCENT = "#89b4fa"
GRUEN = "#a6e3a1"
ROT = "#f38ba8"
GELB = "#f9e2af"

# Aktions-Buttons oben im Editor (Reihenfolge = Anzeigereihenfolge). MAUS_ABS
# und WARTEN_MIN_MAX sind Ergaenzungen zur urspruenglich vorgegebenen 10er-
# Liste: beides sind bestehende bzw. neu geforderte Aktionen, die sonst ohne
# Button nicht (mehr) ueber die UI erreichbar waeren.
AKTIONS_BUTTONS = [
    "WARTEN", "WARTEN_MIN_MAX", "LINKSKLICK", "RECHTSKLICK", "DOPPELKLICK", "TASTE", "FOKUS",
    "MAUS_BEWEGEN",
    "MAUS_ABS", "BILD_KLICKEN", "BILD_WARTEN_BIS", "BILD_WARTEN_BIS_WEG",
    "BILD_KLICKEN_WENN_WEG", "BILD_KLICKEN_BIS", "WURM_KLICKEN",
    "SCHLEIFE_START", "SCHLEIFE_ENDE", "GEWICHTET",
]

_FLOAT_FELDER = {"sekunden", "bonus_prozent", "timeout", "schwelle", "min", "max", "klickabstand"}
_TEXT_FELDER = {"taste", "bild", "klick_typ", "variante", "ziel_bild", "ziel_variante"}


# ---------- Wiederverwendbare Feld-Baufunktionen (aktionsunabhaengig von
# AktionsSkriptTab) - genutzt sowohl von AktionsSkriptTab._zeile_bauen() als
# auch von gewichtet_editor.py fuer die Schritt-Zeilen innerhalb eines
# gewichteten Pfads, damit beide Editoren identische Felder/Verhalten je
# Aktions-Typ zeigen. ----------

def entry_feld(zeile, schritt, key, breite=6, label=None):
    if label:
        ttk.Label(zeile, text=label, style="Zeile.TLabel").pack(side="left", padx=(8, 2))
    entry = ttk.Entry(zeile, width=breite)
    entry.insert(0, str(schritt["parameter"].get(key, "")))
    entry.pack(side="left", padx=2)

    def uebernehmen(event=None):
        wert = entry.get().strip()
        if key in _TEXT_FELDER:
            schritt["parameter"][key] = wert
        else:
            typ = float if key in _FLOAT_FELDER else int
            try:
                schritt["parameter"][key] = typ(wert)
            except ValueError:
                pass  # ungueltige Eingabe: alten Wert im Schritt behalten
    entry.bind("<FocusOut>", uebernehmen)
    entry.bind("<Return>", uebernehmen)
    return entry


def hitbox_info_setzen(label, bild_name, variante=None):
    if not bild_name:
        label.config(text="Hitbox: -")
        return
    hb = bild_erkennung.hitbox_laden(bild_name, variante)
    if hb:
        label.config(text="Hitbox: %dx%d px" % (hb["w"], hb["h"]))
    else:
        label.config(text="Hitbox: ganzes Bild")


def bild_combo_feld(zeile, schritt, hitbox_label=None, bild_key="bild", variante_key="variante",
                     label="Bild:"):
    """Baut ein '<label>'-Dropdown PLUS ein daneben liegendes 'Variante:'-
    Dropdown (siehe bild_erkennung.varianten_liste()) - eine leere Variante
    bedeutet 'Standard-Variante' (Bildname ohne Endung, siehe
    bild_erkennung.standard_variante()).

    bild_key/variante_key: welche Parameter-Schluessel gelesen/geschrieben
    werden - Standard "bild"/"variante" fuer das (anzuklickende) Haupt-Bild;
    BILD_KLICKEN_BIS ruft dies ein zweites Mal mit bild_key="ziel_bild"/
    variante_key="ziel_variante" fuer das Abbruch-Bild auf (siehe
    parameter_felder_bauen())."""
    ttk.Label(zeile, text=label, style="Zeile.TLabel").pack(side="left", padx=(8, 2))
    combo = ttk.Combobox(zeile, state="readonly", width=18,
                         values=bild_erkennung.verfuegbare_bilder())
    combo.set(schritt["parameter"].get(bild_key, ""))
    combo.pack(side="left", padx=2)

    ttk.Label(zeile, text="Variante:", style="Zeile.TLabel").pack(side="left", padx=(8, 2))
    variante_combo = ttk.Combobox(zeile, state="readonly", width=12)
    variante_combo.pack(side="left", padx=2)

    def varianten_fuellen(bild_name):
        werte = [""] + (bild_erkennung.varianten_liste(bild_name) if bild_name else [])
        variante_combo["values"] = werte

    varianten_fuellen(schritt["parameter"].get(bild_key, ""))
    variante_combo.set(schritt["parameter"].get(variante_key, ""))

    def bild_uebernehmen(event=None):
        schritt["parameter"][bild_key] = combo.get()
        varianten_fuellen(combo.get())
        if schritt["parameter"].get(variante_key, "") not in variante_combo["values"]:
            schritt["parameter"][variante_key] = ""
            variante_combo.set("")
        if hitbox_label is not None:
            hitbox_info_setzen(hitbox_label, combo.get(), schritt["parameter"].get(variante_key, ""))
    combo.bind("<<ComboboxSelected>>", bild_uebernehmen)

    def variante_uebernehmen(event=None):
        schritt["parameter"][variante_key] = variante_combo.get()
        if hitbox_label is not None:
            hitbox_info_setzen(hitbox_label, combo.get(), variante_combo.get())
    variante_combo.bind("<<ComboboxSelected>>", variante_uebernehmen)

    return combo


def timeout_endlos_feld(zeile, schritt):
    """Baut das 'Timeout:'-Eingabefeld PLUS ein daneben liegendes 'endlos'-
    Haekchen (siehe aktion_skript._bild_timeout()/bild_erkennung.py:
    timeout<=0 = unbegrenzt suchen/warten, nur per Stopp unterbrechbar) - fuer
    BILD_WARTEN_BIS/BILD_WARTEN_BIS_WEG/BILD_KLICKEN/BILD_KLICKEN_WENN_WEG.
    Ist 'endlos' angehakt, wird das Timeout-Feld deaktiviert (sein Wert bleibt
    dabei fuer spaeter erhalten, falls 'endlos' wieder abgehakt wird)."""
    timeout_entry = entry_feld(zeile, schritt, "timeout", 5, "Timeout:")

    endlos_var = tk.BooleanVar(value=bool(schritt["parameter"].get("endlos")))

    def endlos_umschalten():
        schritt["parameter"]["endlos"] = 1 if endlos_var.get() else 0
        timeout_entry.config(state="disabled" if endlos_var.get() else "normal")

    ttk.Checkbutton(zeile, text="endlos", variable=endlos_var,
                   command=endlos_umschalten).pack(side="left", padx=(4, 2))
    if endlos_var.get():
        timeout_entry.config(state="disabled")


def suchbereich_feld(zeile, schritt, key="suchbereich", label="Zielbereich...", bild_key="bild"):
    """Baut den 'Zielbereich...'-Button (+ Statusanzeige + Loeschen-Button)
    fuer BILD_*-Aktionen: schraenkt die Bild-Suche auf einen fensterrelativen
    Teilbereich ein (siehe modules.fenster.fenster_bereich_markieren()/
    bild_erkennung._aktueller_treffer(suchbereich=...)), statt bei JEDEM
    Versuch das GANZE Fenster zu durchsuchen - schneller UND weniger
    anfaellig fuer Fehltreffer ausserhalb des erwarteten Bereichs, da METIN2-
    Fenster immer (ungefaehr) dieselbe Groesse haben.

    key/label: welcher Parameter-Schluessel gelesen/geschrieben wird bzw. wie
    der Button beschriftet ist - Standard "suchbereich"/"Zielbereich..." fuer
    das (anzuklickende) Haupt-Bild; BILD_KLICKEN_BIS ruft dies ein zweites
    Mal mit key="ziel_suchbereich"/label="Ziel-Zielbereich..."/
    bild_key="ziel_bild" fuer das Abbruch-Bild auf (siehe
    parameter_felder_bauen()) - beide Bilder duerfen UNABHAENGIGE Bereiche
    haben, da sie an ganz verschiedenen Stellen im Fenster sitzen koennen.
    bild_key: Parameter-Schluessel des zugehoerigen Bildnamens - fuer die
        Warnung in bereich_festlegen() (siehe dort): ein Suchbereich, der
        kleiner als das Bild selbst ist, findet NIE einen Treffer (Template-
        Matching kann nicht groesser als der Suchbereich sein), auch wenn das
        Bild dort tatsaechlich zu sehen ist - eine haeufige, sonst schwer zu
        findende Fehlerursache ("erkennt es nicht, obwohl es genau da ist")."""
    p = schritt["parameter"]
    lbl = ttk.Label(zeile, text="", style="Zeile.TLabel", foreground=MUTED)

    def text_aktualisieren():
        b = p.get(key)
        if b:
            lbl.config(text="Bereich: (%d,%d)-(%d,%d)" % (b["x0"], b["y0"], b["x1"], b["y1"]))
        else:
            lbl.config(text="Bereich: ganzes Fenster")

    def bereich_festlegen():
        neu = fenster_modul.fenster_bereich_markieren(master=zeile.winfo_toplevel())
        if neu is None:
            return
        bild_name = (p.get(bild_key) or "").strip()
        if bild_name:
            try:
                bw, bh = bild_erkennung.bild_groesse(bild_name)
            except bild_erkennung.BildErkennungFehler:
                bw = bh = None
            if bw is not None:
                rw, rh = neu["x1"] - neu["x0"], neu["y1"] - neu["y0"]
                if rw < bw or rh < bh:
                    messagebox.showwarning(
                        "Zielbereich zu klein",
                        "Der markierte Bereich (%dx%d) ist KLEINER als das Bild '%s' "
                        "(%dx%d) - die Erkennung findet dort NIE einen Treffer, selbst "
                        "wenn das Bild sichtbar ist (Template-Matching kann nicht groesser "
                        "als der Suchbereich sein). Bitte einen groesseren Bereich waehlen "
                        "(am besten deutlich groesser als das Bild selbst, mit Rand)."
                        % (rw, rh, bild_name, bw, bh))
        p[key] = neu
        text_aktualisieren()

    def bereich_loeschen():
        p[key] = None
        text_aktualisieren()

    ttk.Button(zeile, text=label, command=bereich_festlegen).pack(side="left", padx=(8, 2))
    ttk.Button(zeile, text="x", width=2, command=bereich_loeschen).pack(side="left", padx=(0, 2))
    lbl.pack(side="left", padx=(4, 2))
    text_aktualisieren()


def fehler_override_feld(zeile, schritt):
    """Baut ein generisches 'Bei Fehler:'-Dropdown PLUS 'Sprung zu'-Feld,
    das NUR fuer diesen einen Schritt gilt und (falls gesetzt) das fuer den
    gesamten Ablauf gewaehlte Bei-Fehler-Verhalten ueberschreibt (siehe
    aktion_skript._effektives_fehlerverhalten()). Leer/"" = kein Override,
    der Schritt nutzt weiterhin das globale Verhalten - gilt fuer JEDEN
    Aktions-Typ, daher hier generisch statt in parameter_felder_bauen()."""
    ttk.Label(zeile, text="⚠Bei Fehler:", style="Zeile.TLabel", foreground=MUTED).pack(
        side="left", padx=(10, 2))
    fehler_var = tk.StringVar(value=schritt.get("bei_fehler_override") or "")
    fehler_combo = ttk.Combobox(zeile, textvariable=fehler_var, state="readonly", width=11,
                                values=[""] + aktion_skript.BEI_FEHLER_OPTIONEN)
    fehler_combo.pack(side="left", padx=2)

    sprung_entry = ttk.Entry(zeile, width=4)
    sprung_entry.insert(0, str(schritt.get("sprung_ziel_override") or ""))
    sprung_entry.config(state="normal" if fehler_var.get() == "SPRUNG" else "disabled")
    sprung_entry.pack(side="left", padx=(2, 2))

    def fehler_uebernehmen(event=None):
        wert = fehler_var.get()
        if wert:
            schritt["bei_fehler_override"] = wert
        else:
            schritt.pop("bei_fehler_override", None)
        sprung_entry.config(state="normal" if wert == "SPRUNG" else "disabled")
    fehler_combo.bind("<<ComboboxSelected>>", fehler_uebernehmen)

    def sprung_uebernehmen(event=None):
        text = sprung_entry.get().strip()
        if text:
            schritt["sprung_ziel_override"] = text
        else:
            schritt.pop("sprung_ziel_override", None)
    sprung_entry.bind("<FocusOut>", sprung_uebernehmen)
    sprung_entry.bind("<Return>", sprung_uebernehmen)


def _alle_taste_schritte(schritte, praefix=""):
    """Sammelt (stelle, taste_wert) fuer alle TASTE-Schritte in 'schritte' -
    rekursiv auch innerhalb von GEWICHTET-Pfaden (siehe aktion_skript.py),
    da TASTE dort genauso vorkommen kann. 'stelle' ist ein sprechender
    Pfadname fuer Fehlermeldungen, z.B. "Schritt 3" oder
    "Schritt 2 -> Pfad 1, Schritt 1"."""
    gefunden = []
    for i, schritt in enumerate(schritte, 1):
        aktion = schritt.get("aktion")
        p = schritt.get("parameter", {})
        stelle = "%sSchritt %d" % (praefix, i)
        if aktion == "TASTE":
            gefunden.append((stelle, p.get("taste", "")))
        elif aktion == "GEWICHTET":
            for j, pfad in enumerate(p.get("pfade", []), 1):
                gefunden.extend(_alle_taste_schritte(
                    pfad.get("schritte", []), "%s -> Pfad %d, " % (stelle, j)))
    return gefunden


def _schleifen_balanciert(schritte):
    """Prueft, ob alle SCHLEIFE_START/SCHLEIFE_ENDE-Marker sauber
    verschachtelt sind (wie Klammern) - auch rekursiv innerhalb von
    GEWICHTET-Pfaden, da SCHLEIFE dort genauso vorkommen kann. Ohne diese
    Pruefung wuerde ein unbalanciertes Markerpaar erst zur Laufzeit auffallen
    (siehe aktion_skript._passendes_schleifen_ende(), das dann sauber mit
    einem Schritt-Fehler statt eines Absturzes reagiert - hier soll es aber
    idealerweise gar nicht erst dazu kommen)."""
    tiefe = 0
    for schritt in schritte:
        aktion = schritt.get("aktion")
        if aktion == "SCHLEIFE_START":
            tiefe += 1
        elif aktion == "SCHLEIFE_ENDE":
            tiefe -= 1
            if tiefe < 0:
                return False
        elif aktion == "GEWICHTET":
            for pfad in schritt.get("parameter", {}).get("pfade", []):
                if not _schleifen_balanciert(pfad.get("schritte", [])):
                    return False
    return tiefe == 0


def parameter_felder_bauen(zeile, aktion, schritt, zeile2=None):
    """Baut die aktionsspezifischen Eingabefelder fuer 'schritt' in 'zeile'
    (ohne Zeilenrahmen/Index/Aktion-Label/Rechts-Buttons - das macht der
    Aufrufer). Deckt alle Aktionen AUSSER GEWICHTET ab, das stattdessen einen
    eigenen "Bearbeiten..."-Dialog bekommt (siehe gewichtet_editor.py).

    zeile2: optionale ZWEITE Zeile fuer sehr feldreiche Aktionen (BILD_KLICKEN/
    _WENN_WEG/_BIS) - die "hintere" Haelfte ihrer Felder landet dort statt in
    'zeile', damit der Schritt als zusammenhaengender, aber MEHRZEILIGER Block
    dargestellt wird (siehe _zeile_bauen()), statt beliebig weit ueber den
    sichtbaren Bereich hinauszuwachsen. None (Standard) = alles in 'zeile',
    unveraendertes Verhalten fuer alle anderen/kuerzeren Aktionen sowie fuer
    gewichtet_editor.py (das nur eine Zeile pro Schritt hat)."""
    p = schritt.setdefault("parameter", {})
    z2 = zeile2 if zeile2 is not None else zeile

    if aktion == "WARTEN":
        entry_feld(zeile, schritt, "sekunden", 6, "Sek:")
        entry_feld(zeile, schritt, "bonus_prozent", 5, "Bonus%:")

    elif aktion == "WARTEN_MIN_MAX":
        entry_feld(zeile, schritt, "min", 6, "Min:")
        entry_feld(zeile, schritt, "max", 6, "Max:")

    elif aktion == "TASTE":
        entry_feld(zeile, schritt, "taste", 10, "Taste:")

    elif aktion == "MAUS_BEWEGEN":
        entry_feld(zeile, schritt, "dx", 6, "dx:")
        entry_feld(zeile, schritt, "dy", 6, "dy:")

    elif aktion == "MAUS_ABS":
        entry_feld(zeile, schritt, "x", 6, "x:")
        entry_feld(zeile, schritt, "y", 6, "y:")

    elif aktion in ("BILD_WARTEN_BIS", "BILD_WARTEN_BIS_WEG"):
        bild_combo_feld(zeile, schritt)
        timeout_endlos_feld(zeile, schritt)
        entry_feld(zeile, schritt, "schwelle", 5, "Schwelle:")
        suchbereich_feld(z2, schritt)

    elif aktion in ("BILD_KLICKEN", "BILD_KLICKEN_WENN_WEG"):
        # Zeile 1: Bild-Auswahl + Typ/Zufall. Zeile 2 (siehe zeile2-Docstring
        # oben): Offsets/Timeout/Hitbox-Info - haelt den Block schmal statt
        # beliebig breit.
        bild_combo_feld(zeile, schritt)

        ttk.Label(zeile, text="Typ:", style="Zeile.TLabel").pack(side="left", padx=(8, 2))
        typ_combo = ttk.Combobox(zeile, state="readonly", width=3, values=["L", "R", "D"])
        typ_combo.set(p.get("klick_typ", "L"))
        typ_combo.pack(side="left", padx=2)
        typ_combo.bind("<<ComboboxSelected>>",
                      lambda e: schritt["parameter"].__setitem__("klick_typ", typ_combo.get()))

        zufall_var = tk.BooleanVar(value=bool(p.get("zufall", 1)))
        ttk.Checkbutton(
            zeile, text="Zufall", variable=zufall_var,
            command=lambda: schritt["parameter"].__setitem__(
                "zufall", 1 if zufall_var.get() else 0)
        ).pack(side="left", padx=(6, 2))

        entry_feld(z2, schritt, "offset_x", 5, "OffX:")
        entry_feld(z2, schritt, "offset_y", 5, "OffY:")
        timeout_endlos_feld(z2, schritt)
        suchbereich_feld(z2, schritt)

        lbl_hitbox = ttk.Label(z2, text="Hitbox: -", style="Zeile.TLabel")
        lbl_hitbox.pack(side="left", padx=(10, 2))
        hitbox_info_setzen(lbl_hitbox, p.get("bild", ""), p.get("variante", ""))

    elif aktion == "BILD_KLICKEN_BIS":
        # Zwei Bild-Dropdowns: das anzuklickende Bild UND (im Modus ZIEL_DA)
        # das Ziel-Bild, dessen Erscheinen die Klick-Wiederholung beendet -
        # im Modus BILD_WEG wird stattdessen das Verschwinden des
        # angeklickten Bildes selbst abgewartet (siehe
        # aktion_skript._bild_klicken_bis_schritt()). Zeile 1: Bild+Modus+
        # Typ/Zufall. Zeile 2: Offsets/Klickabstand/Ziel-Bild/Timeout/Hitbox.
        bild_combo_feld(zeile, schritt, label="Bild:")

        ttk.Label(zeile, text="bis:", style="Zeile.TLabel").pack(side="left", padx=(8, 2))
        modus_var = tk.StringVar(value=p.get("modus", "ZIEL_DA"))
        modus_combo = ttk.Combobox(zeile, textvariable=modus_var, state="readonly", width=13,
                                   values=["ZIEL_DA", "BILD_WEG"])
        modus_combo.pack(side="left", padx=2)

        ttk.Label(zeile, text="Typ:", style="Zeile.TLabel").pack(side="left", padx=(8, 2))
        typ_combo = ttk.Combobox(zeile, state="readonly", width=3, values=["L", "R", "D"])
        typ_combo.set(p.get("klick_typ", "L"))
        typ_combo.pack(side="left", padx=2)
        typ_combo.bind("<<ComboboxSelected>>",
                      lambda e: schritt["parameter"].__setitem__("klick_typ", typ_combo.get()))

        zufall_var = tk.BooleanVar(value=bool(p.get("zufall", 1)))
        ttk.Checkbutton(
            zeile, text="Zufall", variable=zufall_var,
            command=lambda: schritt["parameter"].__setitem__(
                "zufall", 1 if zufall_var.get() else 0)
        ).pack(side="left", padx=(6, 2))

        entry_feld(z2, schritt, "offset_x", 5, "OffX:")
        entry_feld(z2, schritt, "offset_y", 5, "OffY:")
        entry_feld(z2, schritt, "klickabstand", 5, "Klickabstand(s):")

        # Bleibt bewusst IMMER auswaehlbar, auch im Modus BILD_WEG (wo es von
        # der Ausfuehrung ignoriert wird, siehe aktion_skript.
        # _bild_klicken_bis_schritt()) - beim Umschalten zwischen den Modi
        # soll man die Auswahl nicht verlieren/nicht gesperrt bekommen.
        bild_combo_feld(z2, schritt, bild_key="ziel_bild",
                        variante_key="ziel_variante", label="Ziel-Bild:")
        suchbereich_feld(z2, schritt, key="ziel_suchbereich", label="Ziel-Zielbereich...",
                         bild_key="ziel_bild")

        def modus_umschalten(event=None):
            schritt["parameter"]["modus"] = modus_var.get()
        modus_combo.bind("<<ComboboxSelected>>", modus_umschalten)

        timeout_endlos_feld(z2, schritt)
        suchbereich_feld(z2, schritt)

        lbl_hitbox = ttk.Label(z2, text="Hitbox: -", style="Zeile.TLabel")
        lbl_hitbox.pack(side="left", padx=(10, 2))
        hitbox_info_setzen(lbl_hitbox, p.get("bild", ""), p.get("variante", ""))

    elif aktion == "SCHLEIFE_START":
        wiederholen_entry = entry_feld(zeile, schritt, "wiederholungen", 5, "Wiederholungen:")

        endlos_var = tk.BooleanVar(value=bool(p.get("endlos")))

        def endlos_umschalten():
            schritt["parameter"]["endlos"] = 1 if endlos_var.get() else 0
            wiederholen_entry.config(state="disabled" if endlos_var.get() else "normal")

        ttk.Checkbutton(zeile, text="endlos", variable=endlos_var,
                       command=endlos_umschalten).pack(side="left", padx=(6, 2))
        if endlos_var.get():
            wiederholen_entry.config(state="disabled")
        ttk.Label(zeile, text="(Schritte bis zum passenden SCHLEIFE ENDE werden wiederholt)",
                 style="Zeile.TLabel", foreground=MUTED).pack(side="left", padx=(8, 2))

    elif aktion == "SCHLEIFE_ENDE":
        ttk.Label(zeile, text="— Ende des Schleifenkoerpers —",
                 style="Zeile.TLabel", foreground=MUTED).pack(side="left", padx=(8, 2))

    # RECHTSKLICK, LINKSKLICK, WURM_KLICKEN: keine Parameter.


class AktionsSkriptTab(ttk.Frame):
    def __init__(self, master, basis_dir, hid_maus_getter, log_callback=None,
                 fremd_aktiv_getter=None, on_save_callback=None):
        """
        Args:
            master: Eltern-Widget (das ttk.Notebook).
            basis_dir: Projektverzeichnis (fuer Konsistenz mit anderen Tabs,
                aktion_skript.py/bild_erkennung.py ermitteln ihren Pfad selbst).
            hid_maus_getter: Callable[[], HIDMaus|None] - liefert die aktuell
                verbundene HID-Maus-Instanz (dynamisch, da die Verbindung im
                Config-Tab jederzeit neu aufgebaut werden kann).
            log_callback: optionales Callable(str) - zusaetzliches externes
                Log-Ziel (z.B. das Haupt-Log des Command Centers).
            fremd_aktiv_getter: optionales Callable[[], bool] - liefert True,
                wenn parallel bereits ein anderer Prozess (z.B. der Fischbot)
                dieselbe HID-Verbindung benutzt. Ein Ablauf wird dann nicht
                gestartet (nicht thread-sicher, dieselbe serielle Leitung).
            on_save_callback: optionales Callable(), nach jedem erfolgreichen
                Speichern aufgerufen (siehe _skript_speichern()) - z.B. damit
                der MAKRO TOOLS-Reiter/die Fisch-Bot-Skriptauswahl im Command
                Center sofort ein hier neu gespeichertes Skript anzeigen,
                ohne dass "Aktualisieren" manuell geklickt werden muss.
        """
        super().__init__(master)
        self.basis_dir = basis_dir
        self.hid_maus_getter = hid_maus_getter
        self.ext_log = log_callback
        self.fremd_aktiv_getter = fremd_aktiv_getter
        self.on_save_callback = on_save_callback

        self.schritte = []
        self.aktueller_name = None
        self._lauf_aktiv = False
        self._zeilen_frames = []     # Frame je Zeile, Index == Schritt-Index
        self._aktiver_zeilen_index = None
        self._bild_ausgewaehlt = None   # Dateiname des zuletzt in der Bilder-Liste angeklickten Bildes
        self._bilder_foto_refs = []     # Referenzen auf Thumbnail-PhotoImages (sonst vom GC entfernt)

        self._style_einrichten()
        self._build_ui()
        self._skripte_aktualisieren()
        self._bilder_liste_neu_zeichnen()

        name = aktion_skript.sicherstellen_standard_skript()
        self._skript_laden(name)

    @property
    def laeuft(self):
        """True, waehrend ein Ablauf gerade ausgefuehrt wird (fuer externe
        Gegenpruefungen, z.B. bevor der Fischbot dieselbe HID-Verbindung nutzt)."""
        return self._lauf_aktiv

    def _style_einrichten(self):
        style = ttk.Style()
        style.configure("Zeile.TFrame", background=BG3)
        style.configure("ZeileAktiv.TFrame", background=ACCENT)
        style.configure("Zeile.TLabel", background=BG3, foreground=FG)
        style.configure("ZeileAktiv.TLabel", background=ACCENT, foreground=BG2)
        # Kleinere Variante der Standard-Buttons fuer "Schritt hinzufuegen" -
        # bei mittlerweile 15 Aktions-Typen (siehe AKTIONS_BUTTONS) sonst zu
        # breit fuer eine feste Zeile (siehe _build_ui(), jetzt mit
        # horizontalem Scroller statt fixer 2-Zeilen-Aufteilung).
        style.configure("Kompakt.TButton", padding=[6, 2], font=("Segoe UI", 8))

    # ================= UI-Aufbau =================

    def _build_ui(self):
        # Der gesamte Tab-Inhalt (Bildverwaltung + Aktions-Buttons +
        # Schritt-Liste + Ausfuehrung + Log) liegt in einem Frame ("inhalt"),
        # das als Fenster in einen Canvas eingebettet ist - damit ist die
        # GESAMTE Seite vertikal scrollbar, unabhaengig von der (kleineren)
        # inneren Schritt-Liste weiter unten, die zusaetzlich noch ihr
        # eigenes Scrollen hat (siehe self.liste_canvas).
        self.seiten_canvas = tk.Canvas(self, bg=BG2, highlightthickness=0)
        seiten_scroll = ttk.Scrollbar(self, orient="vertical", command=self.seiten_canvas.yview)
        inhalt = ttk.Frame(self.seiten_canvas)

        inhalt.bind(
            "<Configure>",
            lambda e: self.seiten_canvas.configure(scrollregion=self.seiten_canvas.bbox("all")))
        inhalt_fenster = self.seiten_canvas.create_window((0, 0), window=inhalt, anchor="nw")
        self.seiten_canvas.bind(
            "<Configure>",
            lambda e: self.seiten_canvas.itemconfigure(inhalt_fenster, width=e.width))
        self.seiten_canvas.configure(yscrollcommand=seiten_scroll.set)

        self.seiten_canvas.pack(side="left", fill="both", expand=True)
        seiten_scroll.pack(side="right", fill="y")

        # Mausrad fuer die ganze Seite - gleiche <Enter>/<Leave>-Technik wie
        # bei self.liste_canvas weiter unten. Betritt der Zeiger die innere
        # Schritt-Liste, uebernimmt deren eigene <Enter>-Bindung automatisch
        # wieder die globale Bindung (letzte bind_all() gewinnt).
        self.seiten_canvas.bind("<Enter>", self._seite_mausrad_aktivieren)
        self.seiten_canvas.bind("<Leave>", self._seite_mausrad_deaktivieren)

        kopf = ttk.Frame(inhalt)
        kopf.pack(fill="x", padx=18, pady=(14, 5))
        ttk.Label(kopf, text="BOT-SKRIPTE", style="Header.TLabel").pack(side="left")
        ttk.Label(kopf, text="  Aktionsbasierte Ablaeufe (HID-Maus/-Tastatur)",
                  foreground=MUTED).pack(side="left", padx=8)

        # ---- Skript-Auswahl ----
        auswahl = ttk.Frame(inhalt)
        auswahl.pack(fill="x", padx=18, pady=5)
        ttk.Label(auswahl, text="Skript:").pack(side="left")
        self.combo_skript = ttk.Combobox(auswahl, state="readonly", width=25)
        self.combo_skript.pack(side="left", padx=5)
        self.combo_skript.bind("<<ComboboxSelected>>", self._on_skript_gewaehlt)

        ttk.Button(auswahl, text="Neu", command=self._skript_neu).pack(side="left", padx=3)
        ttk.Button(auswahl, text="Speichern", style="Success.TButton",
                   command=self._skript_speichern).pack(side="left", padx=3)
        ttk.Button(auswahl, text="Speichern als...",
                   command=self._skript_speichern_als).pack(side="left", padx=3)
        ttk.Button(auswahl, text="Aktualisieren",
                   command=self._skripte_aktualisieren).pack(side="left", padx=3)

        # ---- Bilder (bilder_szenen): Liste mit Thumbnails + Verwaltung ----
        bilder_rahmen = ttk.LabelFrame(inhalt, text="Bilder (bilder_szenen)")
        bilder_rahmen.pack(fill="x", padx=18, pady=5)

        # Manuelle Uebernahme eines bereits vorhandenen (extern bearbeiteten)
        # Bildes per eingetipptem Dateinamen - im Unterschied zu "Bild
        # einfuegen (Datei)" unten wird hier NICHTS kopiert, nur eine
        # bereits in bilder_szenen liegende Datei ausgewaehlt.
        bv_manuell_zeile = ttk.Frame(bilder_rahmen)
        bv_manuell_zeile.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(bv_manuell_zeile, text="Dateiname:").pack(side="left", padx=(0, 4))
        self.entry_bild_dateiname = ttk.Entry(bv_manuell_zeile, width=30)
        self.entry_bild_dateiname.pack(side="left", padx=(0, 6))
        self.entry_bild_dateiname.bind("<Return>", lambda e: self._bild_manuell_einfuegen())
        ttk.Button(bv_manuell_zeile, text="Bild einfuegen",
                  command=self._bild_manuell_einfuegen).pack(side="left")

        bv_knopfzeile = ttk.Frame(bilder_rahmen)
        bv_knopfzeile.pack(fill="x", padx=8, pady=(2, 4))
        ttk.Button(bv_knopfzeile, text="\U0001F4C1 Bild einfuegen (Datei)",
                   command=self._bild_einfuegen_datei).pack(side="left", padx=3)
        ttk.Button(bv_knopfzeile, text="\U0001F4F7 Bild einfuegen (Screenshot)",
                   command=self._bild_einfuegen_screenshot).pack(side="left", padx=3)
        ttk.Button(bv_knopfzeile, text="\U0001F504 Bild aktualisieren",
                   command=self._bild_verwaltung_aktualisieren).pack(side="left", padx=3)
        ttk.Button(bv_knopfzeile, text="\U0001F5D1 Bild loeschen", style="Danger.TButton",
                   command=self._bild_loeschen).pack(side="left", padx=3)

        self.lbl_bild_ausgewaehlt = ttk.Label(bilder_rahmen, text="Ausgewaehlt: -", foreground=MUTED)
        self.lbl_bild_ausgewaehlt.pack(anchor="w", padx=8, pady=(0, 4))

        bv_liste_aussen = ttk.Frame(bilder_rahmen)
        bv_liste_aussen.pack(fill="x", padx=8, pady=(0, 8))
        self.bilder_liste_canvas = tk.Canvas(bv_liste_aussen, bg=BG2, highlightthickness=0, height=140)
        bv_scroll = ttk.Scrollbar(bv_liste_aussen, orient="vertical",
                                  command=self.bilder_liste_canvas.yview)
        self.bilder_liste_innen = ttk.Frame(self.bilder_liste_canvas)
        self.bilder_liste_innen.bind(
            "<Configure>",
            lambda e: self.bilder_liste_canvas.configure(scrollregion=self.bilder_liste_canvas.bbox("all")))
        self.bilder_liste_canvas.create_window((0, 0), window=self.bilder_liste_innen, anchor="nw")
        self.bilder_liste_canvas.configure(yscrollcommand=bv_scroll.set)
        self.bilder_liste_canvas.pack(side="left", fill="both", expand=True)
        bv_scroll.pack(side="right", fill="y")

        # ---- Aktions-Buttons (fuegen einen neuen Schritt hinzu) ----
        # Mehrzeiliges Grid (SPALTEN_PRO_ZEILE Buttons pro Zeile, umbrechend)
        # statt einer einzelnen, nur horizontal scrollenden Zeile - bei
        # mittlerweile 16 Buttons (15 Aktions-Typen + Endlos-Schleife-
        # Schnellbutton, siehe unten) sind so auf einen Blick deutlich mehr
        # Buttons gleichzeitig sichtbar/erreichbar. Ein (jetzt vertikaler)
        # Scroller bleibt als Sicherheitsnetz bestehen, falls spaeter weitere
        # Aktions-Typen dazukommen und die feste Hoehe nicht mehr reicht.
        SPALTEN_PRO_ZEILE = 5
        aktionen_frame = ttk.LabelFrame(inhalt, text="Schritt hinzufuegen")
        aktionen_frame.pack(fill="x", padx=18, pady=5)

        aktionen_aussen = ttk.Frame(aktionen_frame)
        aktionen_aussen.pack(fill="x", padx=8, pady=8)
        aktionen_gesamt = len(AKTIONS_BUTTONS) + 1  # +1 fuer den Endlos-Schleife-Schnellbutton
        zeilen_anzahl = (aktionen_gesamt + SPALTEN_PRO_ZEILE - 1) // SPALTEN_PRO_ZEILE
        canvas_hoehe = min(zeilen_anzahl, 4) * 32  # ab 4 sichtbaren Zeilen wird gescrollt
        self.aktionen_canvas = tk.Canvas(aktionen_aussen, bg=BG, highlightthickness=0, height=canvas_hoehe)
        aktionen_vscroll = ttk.Scrollbar(aktionen_aussen, orient="vertical",
                                         command=self.aktionen_canvas.yview)
        aktionen_innen = ttk.Frame(self.aktionen_canvas)
        aktionen_innen.bind(
            "<Configure>",
            lambda e: self.aktionen_canvas.configure(scrollregion=self.aktionen_canvas.bbox("all")))
        self.aktionen_canvas.create_window((0, 0), window=aktionen_innen, anchor="nw")
        self.aktionen_canvas.configure(yscrollcommand=aktionen_vscroll.set)
        self.aktionen_canvas.pack(side="left", fill="x", expand=True)
        aktionen_vscroll.pack(side="right", fill="y")

        for i, aktion in enumerate(AKTIONS_BUTTONS):
            ttk.Button(aktionen_innen, text="+ " + aktion, style="Kompakt.TButton",
                      command=lambda a=aktion: self._aktion_hinzufuegen(a)).grid(
                row=i // SPALTEN_PRO_ZEILE, column=i % SPALTEN_PRO_ZEILE,
                padx=2, pady=2, sticky="w")

        # Endlos-Schleife-Schnellbutton: fuegt in EINEM Klick ein fertiges
        # SCHLEIFE_START(endlos=1)+SCHLEIFE_ENDE-Paar hinzu, statt
        # SCHLEIFE_START -> "endlos"-Haekchen setzen -> SCHLEIFE_ENDE einzeln
        # hinzufuegen zu muessen (siehe _endlosschleife_hinzufuegen()).
        letzter_index = len(AKTIONS_BUTTONS)
        ttk.Button(aktionen_innen, text="\U0001F501 SCHLEIFE ENDLOS", style="Danger.TButton",
                  command=self._endlosschleife_hinzufuegen).grid(
            row=letzter_index // SPALTEN_PRO_ZEILE, column=letzter_index % SPALTEN_PRO_ZEILE,
            padx=2, pady=2, sticky="w")

        # Mausrad ueber der Leiste scrollt vertikal (dieselbe <Enter>/
        # <Leave>-Technik wie beim Schritt-/Seiten-Scrollen weiter unten -
        # "letzte bind_all() gewinnt", solange der Zeiger hier steht).
        def _aktionen_mausrad(event):
            self.aktionen_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.aktionen_canvas.bind(
            "<Enter>", lambda e: self.aktionen_canvas.bind_all("<MouseWheel>", _aktionen_mausrad))
        self.aktionen_canvas.bind(
            "<Leave>", lambda e: self.aktionen_canvas.unbind_all("<MouseWheel>"))

        # ---- Schritt-Liste (scrollbar, Zeilen mit Inline-Feldern) ----
        # Zeilen mit vielen Feldern (z.B. BILD_KLICKEN_BIS + Bei-Fehler-
        # Override) koennen deutlich breiter werden als das Fenster - die
        # Liste bleibt deshalb bewusst SCHMAL (feste Breite statt fill="x"
        # ueber die ganze Seite) und bekommt einen horizontalen Scroller,
        # statt Felder abzuschneiden oder die ganze Seite in die Breite zu
        # ziehen: alles bleibt erreichbar/einstellbar, nur eben per Scrollen.
        ttk.Label(inhalt, text="Schritte:").pack(anchor="w", padx=18, pady=(8, 2))
        liste_aussen = ttk.Frame(inhalt)
        liste_aussen.pack(fill="x", padx=18)
        liste_canvas_rahmen = ttk.Frame(liste_aussen)
        liste_canvas_rahmen.pack(side="left", fill="both", expand=True)
        # Deutlich groesser als frueher (war 260px, oft nur 6-8 Schritte
        # sichtbar) - die AEUSSERE Seite (self.seiten_canvas) scrollt ohnehin
        # schon ueber die ganze Tab-Seite, das doppelte verschachtelte
        # Scrollen (winzige innere Box UND aeussere Seite) war die eigentliche
        # Ursache der Enge, nicht fehlender Platz im Fenster.
        self.liste_canvas = tk.Canvas(liste_canvas_rahmen, bg=BG2, highlightthickness=0,
                                      height=560, width=760)
        vscroll = ttk.Scrollbar(liste_aussen, orient="vertical", command=self.liste_canvas.yview)
        hscroll = ttk.Scrollbar(liste_canvas_rahmen, orient="horizontal", command=self.liste_canvas.xview)
        self.liste_innen = ttk.Frame(self.liste_canvas)
        self.liste_innen.bind(
            "<Configure>",
            lambda e: self.liste_canvas.configure(scrollregion=self.liste_canvas.bbox("all")))
        self.liste_canvas.create_window((0, 0), window=self.liste_innen, anchor="nw")
        self.liste_canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        self.liste_canvas.pack(side="top", fill="both", expand=True)
        hscroll.pack(side="bottom", fill="x")
        vscroll.pack(side="right", fill="y")

        # Mausrad-Scrollen: <MouseWheel> ist nur global (bind_all) zuverlaessig,
        # da die Zeilen als Kind-Fenster im Canvas eingebettet sind (Entries/
        # Comboboxes/Buttons je Zeile) - ein reines bind() auf den Canvas
        # selbst wuerde bei Mausposition ueber einem dieser Kind-Widgets nicht
        # ausgeloest. Ueber <Enter>/<Leave> wird die globale Bindung nur aktiv
        # gehalten, waehrend der Mauszeiger tatsaechlich ueber der Schritt-
        # Liste ist, damit andere Bereiche (z.B. die Bilder-Liste oben oder
        # die restliche Seite) davon unberuehrt bleiben. Normales Rad = vertikal,
        # Shift+Rad = horizontal (uebliche Konvention).
        self.liste_canvas.bind("<Enter>", self._schritte_mausrad_aktivieren)
        self.liste_canvas.bind("<Leave>", self._schritte_mausrad_deaktivieren)

        # ---- Ausfuehrung ----
        lauf = ttk.LabelFrame(inhalt, text="Ausfuehrung")
        lauf.pack(fill="x", padx=18, pady=8)
        row3 = ttk.Frame(lauf)
        row3.pack(fill="x", padx=10, pady=8)

        ttk.Label(row3, text="Bei Fehler:").pack(side="left")
        self.combo_bei_fehler = ttk.Combobox(row3, state="readonly", width=12,
                                             values=aktion_skript.BEI_FEHLER_OPTIONEN)
        self.combo_bei_fehler.pack(side="left", padx=5)
        self.combo_bei_fehler.set("ABBRECHEN")
        self.combo_bei_fehler.bind("<<ComboboxSelected>>", self._bei_fehler_umschalten)

        # Nur bei bei_fehler=="SPRUNG" relevant (siehe
        # aktion_skript.skript_ausfuehren()/_sprung_ziel_index()): 1-basierte
        # Schrittnummer, zu der bei einem fehlgeschlagenen Schritt gesprungen
        # wird, statt abzubrechen oder einfach weiterzumachen - "1" = Anfang.
        self.lbl_sprung_ziel = ttk.Label(row3, text="Sprung zu Schritt:")
        self.entry_sprung_ziel = ttk.Entry(row3, width=5, state="disabled")
        self.entry_sprung_ziel.insert(0, "1")
        self.lbl_sprung_ziel.pack(side="left", padx=(10, 2))
        self.entry_sprung_ziel.pack(side="left", padx=(0, 5))

        self.btn_ausfuehren = ttk.Button(row3, text="Ablauf Ausfuehren (F8)",
                                        style="Success.TButton",
                                        command=self._ausfuehren_start)
        self.btn_ausfuehren.pack(side="left", padx=12)
        self.btn_stopp = ttk.Button(row3, text="Stopp", style="Danger.TButton",
                                   command=self._ausfuehren_stop, state="disabled")
        self.btn_stopp.pack(side="left", padx=3)

        # Zusaetzlicher Speichern-Button direkt neben der Ausfuehrung (der
        # urspruengliche Speichern-Button oben bei der Skript-Auswahl bleibt
        # bestehen) - ruft bewusst _skript_speichern_als() auf (fragt IMMER
        # nach einem Namen), nicht das stille _skript_speichern() (das den
        # aktuellen Namen ohne Nachfrage ueberschreiben wuerde): direkt nach
        # dem Testen eines Ablaufs soll man bewusst einen (ggf. neuen) Namen
        # vergeben, unter dem das Skript danach bei Fish-Bot/MAKRO TOOLS
        # ausgewaehlt und ausgefuehrt werden kann (siehe on_save_callback).
        ttk.Button(row3, text="Speichern als...", style="Success.TButton",
                  command=self._skript_speichern_als).pack(side="left", padx=(20, 3))

        self.lbl_status = ttk.Label(lauf, text="Ablauf: bereit", foreground=MUTED)
        self.lbl_status.pack(anchor="w", padx=10, pady=(0, 8))

        # ---- Bild-Waechter (uebergreifender Hintergrund-Sprung) ----
        # Im Gegensatz zu "Bei Fehler"/den Pro-Schritt-Overrides (die NUR bei
        # einem tatsaechlich fehlgeschlagenen Schritt greifen) laeuft dieser
        # Waechter WAEHREND DER GESAMTEN AUSFUEHRUNG im Hintergrund mit und
        # springt, SOBALD das gewaehlte Bild irgendwo erscheint, sofort zum
        # Sprungziel - egal welcher Schritt gerade laeuft (auch mitten in
        # einer laufenden Wartezeit). Cooldown verhindert, dass ein weiterhin
        # sichtbares Bild sofort wieder denselben Sprung ausloest (siehe
        # aktion_skript.BildWaechter).
        waechter_frame = ttk.LabelFrame(inhalt, text="Bild-Waechter (uebergreifend, im Hintergrund)")
        waechter_frame.pack(fill="x", padx=18, pady=8)
        row4 = ttk.Frame(waechter_frame)
        row4.pack(fill="x", padx=10, pady=8)

        self.var_waechter_aktiv = tk.BooleanVar(value=False)
        chk_waechter = ttk.Checkbutton(row4, text="Aktiv:", variable=self.var_waechter_aktiv,
                                       command=self._waechter_umschalten)
        chk_waechter.pack(side="left")

        ttk.Label(row4, text="Bild:").pack(side="left", padx=(10, 2))
        self.combo_waechter_bild = ttk.Combobox(row4, state="disabled", width=18,
                                                values=bild_erkennung.verfuegbare_bilder())
        self.combo_waechter_bild.pack(side="left", padx=2)
        self.combo_waechter_bild.bind(
            "<Button-1>",
            lambda e: self.combo_waechter_bild.configure(values=bild_erkennung.verfuegbare_bilder()))

        self.lbl_waechter_sprung_ziel = ttk.Label(row4, text="Sprung zu Schritt:")
        self.entry_waechter_sprung_ziel = ttk.Entry(row4, width=5, state="disabled")
        self.entry_waechter_sprung_ziel.insert(0, "1")
        self.lbl_waechter_sprung_ziel.pack(side="left", padx=(10, 2))
        self.entry_waechter_sprung_ziel.pack(side="left", padx=(0, 5))

        self.lbl_waechter_cooldown = ttk.Label(row4, text="Cooldown (s):")
        self.entry_waechter_cooldown = ttk.Entry(row4, width=6, state="disabled")
        self.entry_waechter_cooldown.insert(0, "5")
        self.lbl_waechter_cooldown.pack(side="left", padx=(10, 2))
        self.entry_waechter_cooldown.pack(side="left", padx=(0, 5))

        # ---- Log ----
        ttk.Label(inhalt, text="Log:").pack(anchor="w", padx=18, pady=(5, 2))
        self.log = scrolledtext.ScrolledText(inhalt, height=6, bg=BG2, fg=GRUEN,
                                            font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=18, pady=(0, 15))

    # ================= Bilder-Liste (bilder_szenen) =================

    def _bilder_liste_neu_zeichnen(self):
        """Baut die Thumbnail-Liste komplett neu auf (analog zu
        _liste_aktualisieren() fuer die Schritt-Liste) - einzige Quelle der
        Wahrheit ist bild_erkennung.verfuegbare_bilder()."""
        for kind in self.bilder_liste_innen.winfo_children():
            kind.destroy()
        self._bilder_foto_refs = []
        bilder = bild_erkennung.verfuegbare_bilder()
        for name in bilder:
            self._bild_zeile_bauen(self.bilder_liste_innen, name)
        if not bilder:
            ttk.Label(self.bilder_liste_innen,
                     text="(keine Bilder - mit einem der Knoepfe oben hinzufuegen)",
                     foreground=MUTED).pack(anchor="w", padx=4, pady=4)

    def _thumbnail_erzeugen(self, name, groesse=(48, 36)):
        try:
            pfad = os.path.join(bild_erkennung.BILDER_ORDNER, name)
            bild = Image.open(pfad).convert("RGB")
            bild.thumbnail(groesse, Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(bild)
        except Exception as e:
            self._log("Konnte Vorschau fuer '%s' nicht erzeugen: %s" % (name, e))
            return None

    def _bild_zeile_bauen(self, container, name):
        ausgewaehlt = (name == self._bild_ausgewaehlt)
        stil = "ZeileAktiv" if ausgewaehlt else "Zeile"
        zeile = ttk.Frame(container, style="%s.TFrame" % stil)
        zeile.pack(fill="x", pady=1, padx=2)

        foto = self._thumbnail_erzeugen(name)
        if foto is not None:
            self._bilder_foto_refs.append(foto)
            lbl_bild = tk.Label(zeile, image=foto, bg=(ACCENT if ausgewaehlt else BG3),
                                bd=0, highlightthickness=0)
        else:
            lbl_bild = ttk.Label(zeile, text="[?]", style="%s.TLabel" % stil, width=8)
        lbl_bild.pack(side="left", padx=4, pady=2)

        lbl_name = ttk.Label(zeile, text=name, style="%s.TLabel" % stil)
        lbl_name.pack(side="left", padx=8)

        for widget in (zeile, lbl_bild, lbl_name):
            widget.bind("<Button-1>", lambda e, n=name: self._bild_zeile_klick(n))

    def _bild_zeile_klick(self, name):
        """Klick auf eine Bild-Zeile: waehlt sie aus (fuer 'Bild loeschen')
        UND oeffnet direkt den Hitbox/Masken-Editor dafuer."""
        self._bild_ausgewaehlt = name
        self.lbl_bild_ausgewaehlt.config(text="Ausgewaehlt: %s" % name)
        self._bilder_liste_neu_zeichnen()
        HitboxEditor(self, bild_name=name, on_save_callback=self._bild_verwaltung_aktualisieren)

    def _bild_verwaltung_aktualisieren(self):
        """Liest bilder_szenen/ neu ein (Bilder-Liste UND alle bild-Dropdowns
        in den Schritt-Zeilen, per Rebuild der Schritt-Liste) - gemeinsame
        Quelle fuer beide: bild_erkennung.verfuegbare_bilder()."""
        if self._bild_ausgewaehlt not in bild_erkennung.verfuegbare_bilder():
            self._bild_ausgewaehlt = None
            self.lbl_bild_ausgewaehlt.config(text="Ausgewaehlt: -")
        self._bilder_liste_neu_zeichnen()
        self._liste_aktualisieren()

    def _bild_manuell_einfuegen(self):
        """Uebernimmt einen per Hand eingetippten Dateinamen (z.B. eines
        bereits extern bearbeiteten Bildes, das schon in bilder_szenen
        liegt) als ausgewaehltes Bild - im Unterschied zu
        _bild_einfuegen_datei()/_bild_einfuegen_screenshot() wird hier
        NICHTS kopiert oder aufgenommen, nur eine bereits vorhandene Datei
        ausgewaehlt/hervorgehoben (gleiches Ziel wie ein Klick auf die
        Bild-Zeile in der Liste, siehe _bild_zeile_klick())."""
        name = self.entry_bild_dateiname.get().strip()
        if not name:
            messagebox.showwarning("Hinweis", "Bitte einen Dateinamen eingeben.")
            return
        if not name.lower().endswith(".png"):
            name += ".png"
        pfad = os.path.join(bild_erkennung.BILDER_ORDNER, name)
        if not os.path.isfile(pfad):
            messagebox.showerror(
                "Fehler", "Datei '%s' wurde nicht in bilder_szenen gefunden." % name, parent=self)
            return
        self._bild_ausgewaehlt = name
        self.lbl_bild_ausgewaehlt.config(text="Ausgewaehlt: %s" % name)
        self._bilder_liste_neu_zeichnen()
        self.entry_bild_dateiname.delete(0, "end")
        self._log("Bild uebernommen: %s" % name)

    def _bild_einfuegen_datei(self):
        pfad = filedialog.askopenfilename(
            title="Bild auswaehlen", filetypes=[("PNG-Bilder", "*.png")])
        if not pfad:
            return
        ziel = os.path.join(bild_erkennung.BILDER_ORDNER, os.path.basename(pfad))
        try:
            shutil.copy(pfad, ziel)
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte Bild nicht kopieren:\n%s" % e)
            return
        self._bild_verwaltung_aktualisieren()
        self._log("Bild eingefuegt: %s" % os.path.basename(pfad))

    def _bild_einfuegen_screenshot(self):
        name = simpledialog.askstring(
            "Screenshot einfuegen", "Name der neuen Bilddatei (ohne .png):", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        dateiname = name if name.lower().endswith(".png") else name + ".png"
        ziel = os.path.join(bild_erkennung.BILDER_ORDNER, dateiname)
        if os.path.exists(ziel) and not messagebox.askyesno(
                "Ueberschreiben?", "'%s' existiert bereits - ueberschreiben?" % dateiname):
            return

        bild = screenshot_tool.screenshot_auswahl_bereich(self)
        if bild is None:
            self._log("Screenshot-Auswahl abgebrochen.")
            return
        try:
            bild.save(ziel)
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte Screenshot nicht speichern:\n%s" % e)
            return
        self._bild_verwaltung_aktualisieren()
        self._log("Bild aus Screenshot eingefuegt: %s" % dateiname)

    def _bild_loeschen(self):
        name = self._bild_ausgewaehlt
        if not name:
            messagebox.showwarning("Hinweis", "Kein Bild ausgewaehlt (auf ein Bild in der Liste klicken).")
            return
        if not messagebox.askyesno(
                "Loeschen",
                "Bild '%s' (und ALLE zugehoerigen Hitbox-/Masken-Varianten) wirklich loeschen?" % name):
            return
        try:
            os.remove(os.path.join(bild_erkennung.BILDER_ORDNER, name))
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte nicht loeschen:\n%s" % e)
            return
        bild_erkennung.alle_varianten_entfernen(name)
        self._bild_ausgewaehlt = None
        self._bild_verwaltung_aktualisieren()
        self._log("Bild geloescht: %s" % name)

    # ================= Schritt-Zeilen (Inline-Editor) =================

    def _seite_mausrad_aktivieren(self, event=None):
        self.seiten_canvas.bind_all("<MouseWheel>", self._seite_mausrad_scrollen)

    def _seite_mausrad_deaktivieren(self, event=None):
        self.seiten_canvas.unbind_all("<MouseWheel>")

    def _seite_mausrad_scrollen(self, event):
        self.seiten_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _schritte_mausrad_aktivieren(self, event=None):
        self.liste_canvas.bind_all("<MouseWheel>", self._schritte_mausrad_scrollen)
        self.liste_canvas.bind_all("<Shift-MouseWheel>", self._schritte_mausrad_scrollen_horizontal)

    def _schritte_mausrad_deaktivieren(self, event=None):
        self.liste_canvas.unbind_all("<MouseWheel>")
        self.liste_canvas.unbind_all("<Shift-MouseWheel>")

    def _schritte_mausrad_scrollen(self, event):
        # Windows liefert in event.delta ein Vielfaches von 120 pro Rastschritt
        # des Mausrads; positiv = nach oben, negativ = nach unten drehen -
        # daher das Vorzeichen umkehren, damit "Rad nach unten" die Liste nach
        # unten scrollt (natuerliche Scrollrichtung).
        self.liste_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _schritte_mausrad_scrollen_horizontal(self, event):
        # Shift+Rad = horizontal scrollen (uebliche Konvention) - noetig, da
        # breite Zeilen (viele Felder, siehe BILD_KLICKEN_BIS) jetzt per
        # horizontalem Scroller statt abgeschnitten/seitenverbreiternd
        # dargestellt werden (siehe _build_ui()).
        self.liste_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

    def _aktion_hinzufuegen(self, aktion):
        self.schritte.append(aktion_skript.neuer_schritt(aktion))
        self._liste_aktualisieren()
        self._log("Schritt hinzugefuegt: %s" % aktion)

    def _endlosschleife_hinzufuegen(self):
        """Fuegt in EINEM Klick ein fertiges, endlos laufendes Schleifen-Paar
        an (SCHLEIFE_START mit endlos=1, direkt gefolgt von SCHLEIFE_ENDE) -
        Kurzform fuer den haeufigen Fall "diese Schritte immer wiederholen",
        ohne SCHLEIFE_START -> "endlos"-Haekchen -> SCHLEIFE_ENDE einzeln
        hinzufuegen zu muessen. Der Schleifenkoerper selbst bleibt leer -
        eigene Schritte werden danach normal per +Button angehaengt und mit
        den ▲/▼-Pfeilen zwischen START und ENDE einsortiert."""
        start = aktion_skript.neuer_schritt("SCHLEIFE_START")
        start["parameter"]["endlos"] = 1
        self.schritte.append(start)
        self.schritte.append(aktion_skript.neuer_schritt("SCHLEIFE_ENDE"))
        self._liste_aktualisieren()
        self._log("Endlos-Schleife hinzugefuegt (SCHLEIFE_START endlos=1 + SCHLEIFE_ENDE)")

    def _liste_aktualisieren(self):
        for kind in self.liste_innen.winfo_children():
            kind.destroy()
        self._zeilen_frames = []
        for i, schritt in enumerate(self.schritte):
            frame = self._zeile_bauen(self.liste_innen, i, schritt)
            self._zeilen_frames.append(frame)
        self._aktiver_zeilen_index = None

    def _zeile_hoch(self, i):
        if i <= 0 or i >= len(self.schritte):
            return
        self.schritte[i - 1], self.schritte[i] = self.schritte[i], self.schritte[i - 1]
        self._liste_aktualisieren()

    def _zeile_runter(self, i):
        if i < 0 or i >= len(self.schritte) - 1:
            return
        self.schritte[i + 1], self.schritte[i] = self.schritte[i], self.schritte[i + 1]
        self._liste_aktualisieren()

    def _zeile_loeschen(self, i):
        if 0 <= i < len(self.schritte):
            del self.schritte[i]
            self._liste_aktualisieren()

    # ---- Feld-Helfer: siehe die modulweiten Funktionen entry_feld()/
    # bild_combo_feld()/hitbox_info_setzen()/parameter_felder_bauen() oben -
    # die werden auch von gewichtet_editor.py wiederverwendet.

    def _gewichtet_bearbeiten(self, schritt):
        # Lokaler Import: vermeidet einen Modul-Ladezyklus, da
        # gewichtet_editor.py seinerseits (auf Modulebene) aktion_editor
        # importiert, um parameter_felder_bauen()/AKTIONS_BUTTONS/Stilfarben
        # wiederzuverwenden.
        import gewichtet_editor
        gewichtet_editor.GewichtetEditor(self, schritt, on_save_callback=self._liste_aktualisieren)

    # Aktionen mit so vielen Feldern, dass eine einzelne Zeile beliebig breit
    # wuerde - werden stattdessen als EIN zusammenhaengender, aber
    # ZWEIZEILIGER Block dargestellt (siehe _zeile_bauen()).
    _MEHRZEILIGE_AKTIONEN = ("BILD_KLICKEN", "BILD_KLICKEN_WENN_WEG", "BILD_KLICKEN_BIS")

    def _zeile_bauen(self, container, index, schritt):
        aktion = schritt.get("aktion", "?")
        p = schritt.setdefault("parameter", {})

        # Aeusserer Rahmen umschliesst 1-2 Zeilen DESSELBEN Schritts als ein
        # zusammenhaengender Block (gleiche Hintergrundfarbe, enger Abstand
        # dazwischen) - lange Aktionen wachsen dadurch nach UNTEN statt nach
        # rechts ueber den sichtbaren Bereich hinaus.
        aussen = ttk.Frame(container, style="Zeile.TFrame")
        aussen.pack(fill="x", pady=2, padx=2)

        zeile = ttk.Frame(aussen, style="Zeile.TFrame")
        zeile.pack(fill="x")

        ttk.Label(zeile, text="%2d" % (index + 1), width=3, style="Zeile.TLabel").pack(side="left")
        ttk.Label(zeile, text=aktion, width=20, style="Zeile.TLabel",
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))

        zeile2 = None
        if aktion in self._MEHRZEILIGE_AKTIONEN:
            zeile2 = ttk.Frame(aussen, style="Zeile.TFrame")
            zeile2.pack(fill="x", pady=(2, 0), padx=(24, 0))

        if aktion == "GEWICHTET":
            ttk.Label(zeile, text="\U0001F3B2 " + aktion_skript.gewichtet_kompakt(p),
                     style="Zeile.TLabel").pack(side="left", padx=4)
            ttk.Button(zeile, text="Bearbeiten...",
                      command=lambda s=schritt: self._gewichtet_bearbeiten(s)).pack(side="left", padx=4)
        else:
            parameter_felder_bauen(zeile, aktion, schritt, zeile2=zeile2)

        # Pro-Schritt Bei-Fehler-Override - gilt fuer JEDEN Aktions-Typ
        # (auch GEWICHTET), deshalb hier generisch statt in
        # parameter_felder_bauen()/dem GEWICHTET-Sonderfall oben. Landet bei
        # zweizeiligen Aktionen auf der zweiten Zeile (mehr Platz), sonst
        # wie bisher auf der einzigen Zeile.
        fehler_override_feld(zeile2 if zeile2 is not None else zeile, schritt)

        rechts = ttk.Frame(zeile, style="Zeile.TFrame")
        rechts.pack(side="right", padx=4)
        ttk.Button(rechts, text="▲", width=3,
                  command=lambda i=index: self._zeile_hoch(i)).pack(side="left", padx=1)
        ttk.Button(rechts, text="▼", width=3,
                  command=lambda i=index: self._zeile_runter(i)).pack(side="left", padx=1)
        ttk.Button(rechts, text="✖", width=3, style="Danger.TButton",
                  command=lambda i=index: self._zeile_loeschen(i)).pack(side="left", padx=1)

        return aussen

    # ================= Skript laden/speichern =================

    def _skripte_aktualisieren(self):
        namen = aktion_skript.verfuegbare_skripte()
        self.combo_skript["values"] = namen
        if self.aktueller_name in namen:
            self.combo_skript.set(self.aktueller_name)
        elif namen:
            self.combo_skript.set(namen[0])

    def _on_skript_gewaehlt(self, event):
        name = self.combo_skript.get()
        if name:
            self._skript_laden(name)

    def _skript_laden(self, name):
        try:
            self.schritte = aktion_skript.skript_laden(name)
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte '%s' nicht laden: %s" % (name, e))
            return
        self.aktueller_name = name
        self._liste_aktualisieren()
        self._skripte_aktualisieren()
        self._log("Skript geladen: %s (%d Schritte)" % (name, len(self.schritte)))

    def _skript_neu(self):
        name = simpledialog.askstring("Neues Skript", "Name des neuen Skripts:", parent=self)
        if not name:
            return
        self.schritte = []
        self.aktueller_name = name.strip()
        self._liste_aktualisieren()
        self._log("Neues (leeres) Skript: %s" % self.aktueller_name)

    def _tasten_validieren(self):
        """Prueft alle TASTE-Schritte (auch verschachtelt in GEWICHTET-
        Pfaden) gegen hid_maus.TASTEN_ERLAUBT - dieselbe Menge, die
        taste_druecken() intern akzeptiert, damit ein hier gueltiger Name
        zur Laufzeit garantiert nicht an _taste_gueltig() scheitert.
        Zeigt bei Verstoessen eine Warnung und gibt False zurueck (Speichern
        wird dann vom Aufrufer nicht durchgefuehrt); True wenn alles ok ist."""
        ungueltig = []
        for stelle, taste in _alle_taste_schritte(self.schritte):
            wert = (taste or "").strip()
            if not wert or wert not in hid_maus.TASTEN_ERLAUBT:
                ungueltig.append("%s: %r" % (stelle, taste))
        if ungueltig:
            messagebox.showwarning(
                "Ungueltige Tastennamen",
                "Folgende TASTE-Schritte haben einen leeren oder ungueltigen "
                "Tastennamen und wuerden zur Laufzeit fehlschlagen:\n\n"
                + "\n".join(ungueltig) +
                "\n\nErlaubt: a-z, A-Z, 0-9, F1-F12, SPACE, ENTER, TAB, ESC, "
                "BACKSPACE, DEL, SHIFT, CTRL, ALT, UP, DOWN, LEFT, RIGHT "
                "(Gross-/Kleinschreibung beachten).",
                parent=self)
            return False
        return True

    def _skript_speichern(self):
        if not self.aktueller_name:
            self._skript_speichern_als()
            return
        if not self._tasten_validieren():
            return
        if not _schleifen_balanciert(self.schritte):
            messagebox.showwarning(
                "Unbalancierte Schleife",
                "Es gibt SCHLEIFE_START-Schritte ohne passendes SCHLEIFE_ENDE "
                "(oder umgekehrt) - bitte pruefen, bevor gespeichert wird.",
                parent=self)
            return
        aktion_skript.skript_speichern(self.aktueller_name, self.schritte)
        self._skripte_aktualisieren()
        self._log("Skript gespeichert: %s (%d Schritte)" % (self.aktueller_name, len(self.schritte)))
        if self.on_save_callback:
            self.on_save_callback()

    def _skript_speichern_als(self):
        name = simpledialog.askstring("Speichern als", "Name des Skripts:", parent=self)
        if not name:
            return
        self.aktueller_name = name.strip()
        self._skript_speichern()

    # ================= Ausfuehrung =================

    def hotkey_f8(self):
        """Globaler Start/Stop-Toggle fuer den Ablauf (an <F8> gebunden)."""
        if self._lauf_aktiv:
            self._ausfuehren_stop()
        else:
            self._ausfuehren_start()

    def _ausfuehren_start(self):
        if self._lauf_aktiv:
            return
        if self.fremd_aktiv_getter and self.fremd_aktiv_getter():
            messagebox.showwarning("Bot-Skript",
                                   "Der Fisch-Bot laeuft gerade und nutzt dieselbe HID-Verbindung - "
                                   "bitte zuerst stoppen.")
            return
        if not self.schritte:
            messagebox.showwarning("Hinweis", "Das Skript hat keine Schritte.")
            return
        if not _schleifen_balanciert(self.schritte):
            messagebox.showwarning(
                "Unbalancierte Schleife",
                "Es gibt SCHLEIFE_START-Schritte ohne passendes SCHLEIFE_ENDE "
                "(oder umgekehrt) - bitte pruefen, bevor der Ablauf gestartet wird.")
            return
        maus = self.hid_maus_getter()
        if maus is None:
            messagebox.showwarning("HID-Maus", "Keine HID-Maus verbunden (siehe Config-Tab).")
            return

        self._lauf_aktiv = True
        self.btn_ausfuehren.config(state="disabled")
        self.btn_stopp.config(state="normal")
        self.lbl_status.config(text="Ablauf: laeuft...", foreground=GELB)
        self._log("Ablauf gestartet: %s (%d Schritte)" % (self.aktueller_name, len(self.schritte)))

        schritte_kopie = [dict(s, parameter=dict(s.get("parameter", {}))) for s in self.schritte]
        bei_fehler = self.combo_bei_fehler.get()
        sprung_ziel = self.entry_sprung_ziel.get().strip() or "1"

        waechter_bild = None
        waechter_sprung_ziel = None
        waechter_cooldown = 5.0
        if self.var_waechter_aktiv.get():
            waechter_bild = self.combo_waechter_bild.get().strip() or None
            waechter_sprung_ziel = self.entry_waechter_sprung_ziel.get().strip() or "1"
            try:
                waechter_cooldown = float(self.entry_waechter_cooldown.get().strip() or "5")
            except ValueError:
                waechter_cooldown = 5.0
            if not waechter_bild:
                messagebox.showwarning("Bild-Waechter", "Bitte ein Bild fuer den Bild-Waechter waehlen.")
                self._lauf_aktiv = False
                self.btn_ausfuehren.config(state="normal")
                self.btn_stopp.config(state="disabled")
                self.lbl_status.config(text="Ablauf: bereit", foreground=MUTED)
                return

        def lauf():
            # Fenster-Eckpruefung (siehe fish_bot.fenster_eckpruefung_bestehen())
            # - derselbe Check wie beim Fisch-Bot-Start UND bei MAKRO TOOLS
            # (makro_manager.MakroManager.starte_makro()), damit er auch hier
            # greift: dieser direkte Ablauf-Start laeuft OHNE MakroManager,
            # haette den Check sonst gar nicht durchlaufen. 'fish_bot' ueber
            # aktion_skript durchgereicht (das importiert es bereits selbst -
            # ist AKTION_OK True, ist also auch fish_bot verfuegbar).
            fenster = aktion_skript.fish_bot.fenster_finden(aktion_skript.fish_bot.FENSTER_TITEL)
            if fenster is not None and not fenster.get("fenster_fest"):
                if not aktion_skript.fish_bot.fenster_eckpruefung_bestehen(fenster):
                    self._log_marshalled("Fenster-Eckpruefung fehlgeschlagen - Ablauf nicht gestartet")
                    self.after(0, lambda: self._ausfuehren_fertig("FENSTERPRUEFUNG_FEHLGESCHLAGEN"))
                    return

            ergebnis = aktion_skript.skript_ausfuehren(
                schritte_kopie, maus, bei_fehler=bei_fehler, sprung_ziel=sprung_ziel,
                log=self._log_marshalled, status=self._status_marshalled,
                waechter_bild=waechter_bild, waechter_sprung_ziel=waechter_sprung_ziel,
                waechter_cooldown=waechter_cooldown,
            )
            self.after(0, lambda: self._ausfuehren_fertig(ergebnis))

        threading.Thread(target=lauf, daemon=True).start()

    def _bei_fehler_umschalten(self, event=None):
        """Aktiviert/deaktiviert das 'Sprung zu Schritt'-Feld je nachdem, ob
        'SPRUNG' als Bei-Fehler-Verhalten gewaehlt ist (siehe
        aktion_skript.skript_ausfuehren(sprung_ziel=...))."""
        aktiv = self.combo_bei_fehler.get() == "SPRUNG"
        self.entry_sprung_ziel.config(state="normal" if aktiv else "disabled")

    def _waechter_umschalten(self):
        """Aktiviert/deaktiviert die Bild-Waechter-Felder je nachdem, ob die
        'Aktiv'-Checkbox gesetzt ist (siehe aktion_skript.BildWaechter)."""
        aktiv = self.var_waechter_aktiv.get()
        self.combo_waechter_bild.config(state="readonly" if aktiv else "disabled")
        self.entry_waechter_sprung_ziel.config(state="normal" if aktiv else "disabled")
        self.entry_waechter_cooldown.config(state="normal" if aktiv else "disabled")

    def _ausfuehren_stop(self):
        aktion_skript.ausfuehrung_stoppen()
        self.lbl_status.config(text="Ablauf: stoppt...", foreground=GELB)

    def _ausfuehren_fertig(self, ergebnis):
        self._lauf_aktiv = False
        self.btn_ausfuehren.config(state="normal")
        self.btn_stopp.config(state="disabled")
        farbe = {"FERTIG": GRUEN, "GESTOPPT": MUTED, "ABGEBROCHEN": ROT,
                "FENSTERPRUEFUNG_FEHLGESCHLAGEN": ROT}.get(ergebnis, MUTED)
        self.lbl_status.config(text="Ablauf: %s" % ergebnis, foreground=farbe)
        self._zeile_hervorheben(None)
        self._log("Ablauf beendet: %s" % ergebnis)

    def _status_marshalled(self, index, gesamt, schritt):
        try:
            self.after(0, lambda: self._on_status(index, gesamt, schritt))
        except Exception:
            pass

    def _on_status(self, index, gesamt, schritt):
        self.lbl_status.config(
            text="Ablauf: laeuft (Schritt %d/%d: %s)" %
                 (index, gesamt, aktion_skript.schritt_beschreibung(schritt)),
            foreground=GELB,
        )
        self._zeile_hervorheben(index - 1)

    def _zeile_hervorheben(self, index):
        """Markiert Zeile 'index' (0-basiert) farblich als aktuell ausgefuehrt
        und setzt die vorherige Markierung zurueck. index=None hebt nur auf."""
        if (self._aktiver_zeilen_index is not None
                and 0 <= self._aktiver_zeilen_index < len(self._zeilen_frames)):
            self._alte_zeile_zuruecksetzen(self._zeilen_frames[self._aktiver_zeilen_index])
        self._aktiver_zeilen_index = index
        if index is not None and 0 <= index < len(self._zeilen_frames):
            frame = self._zeilen_frames[index]
            self._zeile_markieren(frame)
            self.liste_canvas.update_idletasks()
            self.liste_canvas.yview_moveto(max(0, index - 2) / max(1, len(self._zeilen_frames)))

    def _zeile_markieren(self, frame):
        frame.configure(style="ZeileAktiv.TFrame")
        for kind in frame.winfo_children():
            self._widget_stil_setzen(kind, "ZeileAktiv")

    def _alte_zeile_zuruecksetzen(self, frame):
        frame.configure(style="Zeile.TFrame")
        for kind in frame.winfo_children():
            self._widget_stil_setzen(kind, "Zeile")

    def _widget_stil_setzen(self, widget, praefix):
        if isinstance(widget, ttk.Frame):
            widget.configure(style="%s.TFrame" % praefix)
        elif isinstance(widget, ttk.Label):
            widget.configure(style="%s.TLabel" % praefix)
        for kind in widget.winfo_children():
            self._widget_stil_setzen(kind, praefix)

    # ================= Log =================

    def _log_marshalled(self, msg):
        try:
            self.after(0, lambda: self._log(msg))
        except Exception:
            pass

    def _log(self, msg):
        try:
            self.log.config(state="normal")
            self.log.insert("end", str(msg) + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        except Exception:
            pass
        if self.ext_log:
            try:
                self.ext_log("[Bot-Skript] %s" % msg)
            except Exception:
                pass
