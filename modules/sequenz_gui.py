# -*- coding: utf-8 -*-
"""sequenz_gui.py - Tkinter-Tab "Sequenzen" (Baukasten-Layout).

Drei Spalten:
    LINKS   Bausteine  : alle Ablaeufe + Pixel-Trigger + "Warten" als
                         anklickbare Listen. Klick/Doppelklick oder "Einfuegen"
                         setzt den Baustein an der markierten Stelle der Kette.
    MITTE   Sequenz     : die zusammengesetzte Kette, farbige Schritt-Karten
                         (gruen=Ablauf, blau=Trigger, gelb=Warten) + Hoch/Runter/Del.
    RECHTS  Eigenschaften: markierter Schritt (Wartezeit/Zufall/Goto), Schleife,
                         Steuerung (Start/Pause/Stop/Not-Aus), Statistik, Log.

Die Engine (SequenzManager) bleibt unveraendert - hier aendert sich nur die UI.

Einhaengen:
    tab = SequenzTab(notebook, basis_dir, log_callback)
    notebook.add(tab, text="Sequenzen")
"""

import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

try:
    from .sequenz_manager import (SequenzManager, SequenzPool, Sequenz,
                                  SequenzSchritt,
                                  TYP_TRIGGER, TYP_ABLAUF, TYP_WARTEN)
    from .export_manager import ExportManager
    from .statistic_manager import StatistikManager
except ImportError:  # Standalone-Import (ohne Package)
    from sequenz_manager import (SequenzManager, SequenzPool, Sequenz,
                                 SequenzSchritt,
                                 TYP_TRIGGER, TYP_ABLAUF, TYP_WARTEN)
    from export_manager import ExportManager
    from statistic_manager import StatistikManager

# Farben (Catppuccin Mocha)
BG = "#1e1e2e"
BG2 = "#11111b"
BG3 = "#313244"
FG = "#cdd6f4"
MUTED = "#a6adc8"
FAINT = "#7f849c"
ACCENT = "#89b4fa"
GRUEN = "#a6e3a1"   # Ablauf
BLAU = "#89dceb"    # Trigger
GELB = "#f9e2af"    # Warten
ROT = "#f38ba8"

# Farbe je Schritt-Typ (fuer Karten in der Kette)
TYP_FARBE = {TYP_ABLAUF: GRUEN, TYP_TRIGGER: BLAU, TYP_WARTEN: GELB}


class SequenzTab(ttk.Frame):
    def __init__(self, master, basis_dir, log_callback=None):
        super().__init__(master)
        self.basis_dir = basis_dir
        self.ext_log = log_callback

        # mgr = nur fuer Datei-Operationen (laden/speichern/Namen)
        self.mgr = SequenzManager(basis_dir, log_callback=self._log_marshalled)
        # pool = fuehrt beliebig viele Laeufe gleichzeitig aus
        self.pool = SequenzPool(basis_dir,
                                log_callback=self._log_marshalled,
                                status_callback=self._pool_status_marshalled)
        self.export = ExportManager(basis_dir)
        self.stats = StatistikManager(basis_dir)

        self.aktuelle_sequenz = None
        # Palette-Daten: Listen von (anzeige_name, meta_text)
        self._abl = []
        self._trg = []
        # laufende Sequenzen: run_id -> Statustext, plus Index->run_id-Mapping
        self._run_text = {}
        self._run_ids = []

        self._build_ui()
        self._refresh_seq_liste()
        self._refresh_palette()

    # =================================================================
    #  UI-Aufbau
    # =================================================================
    def _build_ui(self):
        kopf = ttk.Frame(self)
        kopf.pack(fill="x", padx=18, pady=(14, 0))
        ttk.Label(kopf, text="SEQUENZEN", style="Header.TLabel").pack(side="left")
        ttk.Label(kopf, text="  Bausteine per Klick zu Ablaeufen verketten",
                  foreground=MUTED).pack(side="left", padx=8)

        # Sequenz-Auswahlleiste
        leiste = ttk.Frame(self)
        leiste.pack(fill="x", padx=18, pady=8)
        ttk.Label(leiste, text="Sequenz:").pack(side="left")
        self.seq_combo = ttk.Combobox(leiste, state="readonly", width=24)
        self.seq_combo.pack(side="left", padx=6)
        self.seq_combo.bind("<<ComboboxSelected>>", lambda e: self._laden())
        ttk.Button(leiste, text="Neu", command=self._neu).pack(side="left", padx=2)
        ttk.Button(leiste, text="Duplizieren", command=self._duplizieren).pack(side="left", padx=2)
        ttk.Button(leiste, text="Loeschen", style="Danger.TButton",
                   command=self._loeschen).pack(side="left", padx=2)
        ttk.Button(leiste, text="Aktualisieren",
                   command=self._refresh_alles).pack(side="left", padx=2)

        # 3-Spalten-Bereich
        haupt = ttk.Frame(self)
        haupt.pack(fill="both", expand=True, padx=15, pady=(2, 12))

        self._build_bausteine(haupt)
        self._build_kette(haupt)
        self._build_eigenschaften(haupt)

    # ---------- LINKS: Bausteine ----------
    def _build_bausteine(self, parent):
        col = ttk.Frame(parent, width=270)
        col.pack(side="left", fill="y", padx=(0, 10))
        col.pack_propagate(False)

        ttk.Label(col, text="BAUSTEINE", foreground=FAINT,
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(col, text="Klick markiert, Doppelklick fuegt ein",
                  foreground=FAINT, font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))

        such = ttk.Frame(col)
        such.pack(fill="x", pady=(0, 8))
        self.such_var = tk.StringVar()
        self.such_var.trace_add("write", lambda *a: self._render_palette())
        ent = tk.Entry(such, textvariable=self.such_var, bg=BG2, fg=FG,
                       insertbackground=FG, relief="flat",
                       font=("Segoe UI", 10))
        ent.pack(fill="x", ipady=5)
        ent.insert(0, "")

        # Ablaeufe
        ttk.Label(col, text="Ablaeufe (Aufnahmen)", foreground=GRUEN,
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.abl_liste = tk.Listbox(col, bg=BG2, fg=GRUEN, height=7,
                                    selectbackground=BG3, selectforeground=FG,
                                    font=("Consolas", 9), activestyle="none",
                                    exportselection=False, relief="flat",
                                    highlightthickness=0)
        self.abl_liste.pack(fill="x", pady=(2, 2))
        self.abl_liste.bind("<Double-Button-1>", lambda e: self._einfuegen_ablauf())
        ttk.Button(col, text="Ablauf einfuegen  >>",
                   command=self._einfuegen_ablauf).pack(fill="x", pady=(0, 10))

        # Trigger
        ttk.Label(col, text="Pixel-Trigger", foreground=BLAU,
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.trg_liste = tk.Listbox(col, bg=BG2, fg=BLAU, height=6,
                                    selectbackground=BG3, selectforeground=FG,
                                    font=("Consolas", 9), activestyle="none",
                                    exportselection=False, relief="flat",
                                    highlightthickness=0)
        self.trg_liste.pack(fill="x", pady=(2, 2))
        self.trg_liste.bind("<Double-Button-1>", lambda e: self._einfuegen_trigger())
        ttk.Button(col, text="Trigger einfuegen  >>",
                   command=self._einfuegen_trigger).pack(fill="x", pady=(0, 10))

        # Warten
        ttk.Label(col, text="Warten", foreground=GELB,
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        wf = ttk.Frame(col)
        wf.pack(fill="x", pady=(2, 0))
        ttk.Label(wf, text="ms:").pack(side="left")
        self.warten_ms = ttk.Spinbox(wf, from_=0, to=3600000, width=8)
        self.warten_ms.set(1000)
        self.warten_ms.pack(side="left", padx=4)
        ttk.Button(wf, text="Warten einfuegen  >>",
                   command=self._einfuegen_warten).pack(side="left")

    # ---------- MITTE: Kette ----------
    def _build_kette(self, parent):
        col = ttk.Frame(parent)
        col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        kopf = ttk.Frame(col)
        kopf.pack(fill="x")
        ttk.Label(kopf, text="SEQUENZ", foreground=FAINT,
                  font=("Segoe UI", 9, "bold")).pack(side="left")
        self.lbl_kette_info = ttk.Label(kopf, text="0 Schritte", foreground=MUTED)
        self.lbl_kette_info.pack(side="right")

        self.lbl_einfuege = ttk.Label(col, text="Einfuegen: ans Ende",
                                      foreground=ACCENT, font=("Segoe UI", 9))
        self.lbl_einfuege.pack(anchor="w", pady=(2, 4))

        box = ttk.Frame(col)
        box.pack(fill="both", expand=True)
        self.kette = tk.Listbox(box, bg=BG2, fg=FG,
                                selectbackground=BG3, selectforeground=FG,
                                font=("Consolas", 10), activestyle="none",
                                exportselection=False, relief="flat",
                                highlightthickness=1, highlightcolor=BG3)
        self.kette.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.kette.yview)
        sb.pack(side="right", fill="y")
        self.kette.config(yscrollcommand=sb.set)
        self.kette.bind("<<ListboxSelect>>", self._on_kette_select)

        werk = ttk.Frame(col)
        werk.pack(fill="x", pady=6)
        ttk.Button(werk, text="^ Hoch", command=lambda: self._verschieben(-1)).pack(side="left", padx=2)
        ttk.Button(werk, text="v Runter", command=lambda: self._verschieben(1)).pack(side="left", padx=2)
        ttk.Button(werk, text="Loeschen", style="Danger.TButton",
                   command=self._schritt_loeschen).pack(side="left", padx=2)
        ttk.Button(werk, text="Alles leeren",
                   command=self._kette_leeren).pack(side="left", padx=2)

    # ---------- RECHTS: Eigenschaften ----------
    def _build_eigenschaften(self, parent):
        col = ttk.Frame(parent, width=290)
        col.pack(side="left", fill="y")
        col.pack_propagate(False)

        ttk.Label(col, text="EIGENSCHAFTEN", foreground=FAINT,
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")

        # Name
        nf = ttk.Frame(col)
        nf.pack(fill="x", pady=(6, 8))
        ttk.Label(nf, text="Name:").pack(side="left")
        self.name_entry = ttk.Entry(nf, width=20)
        self.name_entry.pack(side="left", padx=5, fill="x", expand=True)

        # Markierter Schritt
        sf = ttk.LabelFrame(col, text="Markierter Schritt")
        sf.pack(fill="x", pady=4)
        self.lbl_schritt = ttk.Label(sf, text="(keiner ausgewaehlt)",
                                     foreground=MUTED, font=("Segoe UI", 9, "bold"))
        self.lbl_schritt.pack(anchor="w", padx=10, pady=(6, 4))

        r1 = ttk.Frame(sf); r1.pack(fill="x", padx=10, pady=2)
        ttk.Label(r1, text="Wartezeit (ms):", width=16).pack(side="left")
        self.sp_warte = ttk.Spinbox(r1, from_=0, to=3600000, width=9)
        self.sp_warte.set(0)
        self.sp_warte.pack(side="left")

        r2 = ttk.Frame(sf); r2.pack(fill="x", padx=10, pady=2)
        ttk.Label(r2, text="+ Zufall (ms):", width=16).pack(side="left")
        self.sp_zufall = ttk.Spinbox(r2, from_=0, to=600000, width=9)
        self.sp_zufall.set(0)
        self.sp_zufall.pack(side="left")

        r3 = ttk.Frame(sf); r3.pack(fill="x", padx=10, pady=2)
        ttk.Label(r3, text="Goto b. Fehler:", width=16).pack(side="left")
        self.sp_goto = ttk.Spinbox(r3, from_=0, to=9999, width=9)
        self.sp_goto.set(0)
        self.sp_goto.pack(side="left")
        ttk.Label(sf, text="(0 = kein Sprung, sonst Schritt-Nr.)",
                  foreground=FAINT, font=("Segoe UI", 8)).pack(anchor="w", padx=10)
        ttk.Button(sf, text="Uebernehmen", command=self._schritt_uebernehmen).pack(
            anchor="e", padx=10, pady=(4, 8))

        # Schleife
        lf = ttk.LabelFrame(col, text="Schleife")
        lf.pack(fill="x", pady=4)
        lr = ttk.Frame(lf); lr.pack(fill="x", padx=10, pady=6)
        self.var_endlos = tk.BooleanVar(value=False)
        ttk.Checkbutton(lr, text="Endlos", variable=self.var_endlos,
                        command=self._toggle_endlos).pack(side="left")
        ttk.Label(lr, text="  oder").pack(side="left", padx=4)
        self.spin_x = ttk.Spinbox(lr, from_=1, to=99999, width=7)
        self.spin_x.set(1)
        self.spin_x.pack(side="left", padx=4)
        ttk.Label(lr, text="x").pack(side="left")

        # Speichern
        spf = ttk.Frame(col)
        spf.pack(fill="x", pady=6)
        ttk.Button(spf, text="Speichern", style="Success.TButton",
                   command=self._speichern).pack(side="left", padx=2)
        ttk.Button(spf, text="Speichern unter...",
                   command=self._speichern_unter).pack(side="left", padx=2)

        # Steuerung - mehrere Laeufe gleichzeitig
        st = ttk.LabelFrame(col, text="Steuerung (parallele Laeufe)")
        st.pack(fill="x", pady=4)
        row = ttk.Frame(st); row.pack(fill="x", padx=8, pady=6)
        self.btn_start = ttk.Button(row, text="Start (neuer Lauf)",
                                    style="Success.TButton", command=self._start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_notaus = ttk.Button(row, text="NOT-AUS (alle)",
                                     style="Danger.TButton", command=self._notaus_alle)
        self.btn_notaus.pack(side="left", padx=2)

        self.lbl_laeufe = ttk.Label(st, text="Laufende Sequenzen: 0", foreground=MUTED)
        self.lbl_laeufe.pack(anchor="w", padx=10, pady=(2, 0))
        rl = ttk.Frame(st); rl.pack(fill="x", padx=8, pady=2)
        self.run_liste = tk.Listbox(rl, bg=BG2, fg=FG, height=4,
                                    selectbackground=BG3, selectforeground=FG,
                                    font=("Consolas", 9), activestyle="none",
                                    exportselection=False, relief="flat",
                                    highlightthickness=0)
        self.run_liste.pack(side="left", fill="x", expand=True)
        rsb = ttk.Scrollbar(rl, orient="vertical", command=self.run_liste.yview)
        rsb.pack(side="right", fill="y")
        self.run_liste.config(yscrollcommand=rsb.set)
        rb = ttk.Frame(st); rb.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(rb, text="Pause / Weiter", command=self._pause_sel).pack(side="left", padx=2)
        ttk.Button(rb, text="Stop (markiert)", command=self._stop_sel).pack(side="left", padx=2)
        self.lbl_status = ttk.Label(st, text="Bereit.", foreground=MUTED)
        self.lbl_status.pack(anchor="w", padx=10, pady=(0, 6))

        # Export/Import
        ex = ttk.Frame(col)
        ex.pack(fill="x", pady=4)
        ttk.Button(ex, text="Export ZIP", command=self._export_seq).pack(side="left", padx=2)
        ttk.Button(ex, text="Backup", command=self._export_backup).pack(side="left", padx=2)
        ttk.Button(ex, text="Import", command=self._importieren).pack(side="left", padx=2)

        # Statistik + Mini-Log
        self.lbl_stat = ttk.Label(col, text="Noch keine Laeufe.", foreground=GRUEN,
                                  font=("Segoe UI", 8))
        self.lbl_stat.pack(anchor="w", pady=(6, 2))
        self.log = tk.Text(col, height=5, bg=BG2, fg=GRUEN,
                           font=("Consolas", 8), wrap="word", relief="flat",
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True, pady=(0, 4))
        self.log.insert("end", "Sequenz-Modul bereit.\n")
        self.log.config(state="disabled")

    # =================================================================
    #  Palette (links)
    # =================================================================
    def _ablauf_meta(self, name):
        pfad = os.path.join(self.basis_dir, "ablauf_%s.json" % name)
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                daten = json.load(f)
            events = daten if isinstance(daten, list) else daten.get("events", [])
            ms = sum(e.get("zeit_bis_naechster_ms", 0) for e in events)
            return "%d Klicks, ~%.1fs" % (len(events), ms / 1000.0)
        except Exception:
            return "?"

    def _trigger_meta(self, name):
        pfad = os.path.join(self.basis_dir, "trigger_%s.json" % name)
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                daten = json.load(f)
            pix = daten.get("pixel", [])
            farbe = pix[0].get("farbe", "") if pix else ""
            return "%d Pixel %s" % (len(pix), farbe)
        except Exception:
            return "?"

    def _refresh_palette(self):
        self._abl = [(n, self._ablauf_meta(n)) for n in self.mgr.get_ablauf_namen()]
        self._trg = [(n, self._trigger_meta(n)) for n in self.mgr.get_trigger_namen()]
        self._render_palette()

    def _render_palette(self):
        filt = (self.such_var.get() or "").lower()
        self.abl_liste.delete(0, "end")
        for name, meta in self._abl:
            if filt and filt not in name.lower():
                continue
            self.abl_liste.insert("end", "%-16s %s" % (name[:16], meta))
        self.trg_liste.delete(0, "end")
        for name, meta in self._trg:
            if filt and filt not in name.lower():
                continue
            self.trg_liste.insert("end", "%-16s %s" % (name[:16], meta))

    def _sichtbare_namen(self, quelle):
        filt = (self.such_var.get() or "").lower()
        return [n for n, _ in quelle if not filt or filt in n.lower()]

    # =================================================================
    #  Einfuegen von Bausteinen
    # =================================================================
    def _einfuege_index(self):
        """Position, an der neue Schritte eingefuegt werden (nach Auswahl)."""
        sel = self.kette.curselection()
        if not sel:
            return None  # ans Ende
        return sel[0] + 1

    def _sequenz_sicherstellen(self):
        if self.aktuelle_sequenz is None:
            self.aktuelle_sequenz = Sequenz(name="neue_sequenz")
            self.name_entry.delete(0, "end")
            self.name_entry.insert(0, self.aktuelle_sequenz.name)
        return self.aktuelle_sequenz

    def _baustein_einfuegen(self, schritt):
        seq = self._sequenz_sicherstellen()
        idx = self._einfuege_index()
        seq.hinzufuegen(schritt, idx)
        self._refresh_kette()
        neu = idx if idx is not None else len(seq.schritte) - 1
        self.kette.selection_clear(0, "end")
        self.kette.selection_set(neu)
        self.kette.see(neu)
        self._on_kette_select()

    def _einfuegen_ablauf(self):
        sel = self.abl_liste.curselection()
        namen = self._sichtbare_namen(self._abl)
        if not sel or sel[0] >= len(namen):
            messagebox.showinfo("Hinweis", "Bitte links einen Ablauf markieren.", parent=self)
            return
        name = namen[sel[0]]
        self._baustein_einfuegen(
            SequenzSchritt(typ=TYP_ABLAUF, name=name, wert=name))

    def _einfuegen_trigger(self):
        sel = self.trg_liste.curselection()
        namen = self._sichtbare_namen(self._trg)
        if not sel or sel[0] >= len(namen):
            messagebox.showinfo("Hinweis", "Bitte links einen Trigger markieren.", parent=self)
            return
        name = namen[sel[0]]
        self._baustein_einfuegen(
            SequenzSchritt(typ=TYP_TRIGGER, name=name, wert=name))

    def _einfuegen_warten(self):
        try:
            ms = int(float(self.warten_ms.get() or 0))
        except ValueError:
            ms = 0
        self._baustein_einfuegen(
            SequenzSchritt(typ=TYP_WARTEN, name="Pause", warte_ms=ms))

    # =================================================================
    #  Kette (Mitte)
    # =================================================================
    def _refresh_kette(self):
        self.kette.delete(0, "end")
        seq = self.aktuelle_sequenz
        n = len(seq.schritte) if seq else 0
        if seq:
            for i, s in enumerate(seq.schritte, 1):
                self.kette.insert("end", self._kette_zeile(i, s))
                self.kette.itemconfig(i - 1, foreground=TYP_FARBE.get(s.typ, FG))
        self.lbl_kette_info.config(text="%d Schritte  (~%.1fs)"
                                   % (n, seq.geschaetzte_dauer_s() if seq else 0.0))
        self._update_einfuege_hinweis()

    def _kette_zeile(self, i, s):
        ziel = s.wert or s.name or "-"
        if s.typ == TYP_WARTEN:
            timing = "%dms" % s.warte_ms
            if s.zufall_ms:
                timing += " +%d" % s.zufall_ms
            ziel = "-"
        else:
            timing = "warte %dms" % s.warte_ms
            if s.zufall_ms:
                timing += " +%d" % s.zufall_ms
        goto = ""
        if s.goto_step is not None and s.goto_step >= 0:
            goto = "  -> #%d b.Fehler" % (s.goto_step + 1)
        return "%2d  %-7s %-16s %s%s" % (i, s.typ, ziel[:16], timing, goto)

    def _update_einfuege_hinweis(self):
        idx = self._einfuege_index()
        if idx is None:
            self.lbl_einfuege.config(text="Einfuegen: ans Ende")
        else:
            self.lbl_einfuege.config(text="Einfuegen: nach Schritt %d" % idx)

    def _on_kette_select(self, event=None):
        self._update_einfuege_hinweis()
        sel = self.kette.curselection()
        if not sel or not self.aktuelle_sequenz:
            return
        s = self.aktuelle_sequenz.schritte[sel[0]]
        ziel = s.wert or s.name or "-"
        self.lbl_schritt.config(
            text="#%d  %s  %s" % (sel[0] + 1, s.typ, "" if s.typ == TYP_WARTEN else ziel),
            foreground=TYP_FARBE.get(s.typ, FG))
        self.sp_warte.set(s.warte_ms)
        self.sp_zufall.set(s.zufall_ms)
        self.sp_goto.set(s.goto_step + 1 if s.goto_step >= 0 else 0)

    def _schritt_uebernehmen(self):
        sel = self.kette.curselection()
        if not sel or not self.aktuelle_sequenz:
            messagebox.showinfo("Hinweis", "Kein Schritt markiert.", parent=self)
            return
        s = self.aktuelle_sequenz.schritte[sel[0]]
        try:
            s.warte_ms = int(float(self.sp_warte.get() or 0))
            s.zufall_ms = int(float(self.sp_zufall.get() or 0))
            goto_nr = int(float(self.sp_goto.get() or 0))
        except ValueError:
            messagebox.showwarning("Hinweis", "Ungueltige Zahl.", parent=self)
            return
        s.goto_step = goto_nr - 1 if goto_nr > 0 else -1
        self._refresh_kette()
        self.kette.selection_set(sel[0])

    def _verschieben(self, richtung):
        sel = self.kette.curselection()
        if not sel or not self.aktuelle_sequenz:
            return
        neu = self.aktuelle_sequenz.verschieben(sel[0], richtung)
        self._refresh_kette()
        self.kette.selection_set(neu)
        self.kette.see(neu)

    def _schritt_loeschen(self):
        sel = self.kette.curselection()
        if not sel or not self.aktuelle_sequenz:
            return
        self.aktuelle_sequenz.entfernen(sel[0])
        self._refresh_kette()

    def _kette_leeren(self):
        if not self.aktuelle_sequenz or not self.aktuelle_sequenz.schritte:
            return
        if messagebox.askyesno("Leeren", "Alle Schritte entfernen?", parent=self):
            self.aktuelle_sequenz.schritte = []
            self._refresh_kette()

    def _toggle_endlos(self):
        self.spin_x.config(state="disabled" if self.var_endlos.get() else "normal")

    # =================================================================
    #  Sequenz-Verwaltung
    # =================================================================
    def _refresh_seq_liste(self):
        namen = self.mgr.get_sequenz_namen()
        self.seq_combo["values"] = namen
        if self.aktuelle_sequenz and self.aktuelle_sequenz.name in namen:
            self.seq_combo.set(self.aktuelle_sequenz.name)

    def _refresh_alles(self):
        self._refresh_seq_liste()
        self._refresh_palette()

    def _neu(self):
        name = simpledialog.askstring("Neue Sequenz", "Name:", parent=self)
        if not name:
            return
        self.aktuelle_sequenz = Sequenz(name=name.strip().replace(" ", "_"))
        self._lade_in_ui()
        self._log("Neue Sequenz '%s' angelegt." % self.aktuelle_sequenz.name)

    def _laden(self):
        name = self.seq_combo.get()
        if not name:
            return
        seq = self.mgr.laden(name)
        if seq:
            self.aktuelle_sequenz = seq
            self._lade_in_ui()

    def _loeschen(self):
        name = self.seq_combo.get()
        if not name:
            return
        if messagebox.askyesno("Loeschen", "Sequenz '%s' loeschen?" % name, parent=self):
            self.mgr.loeschen(name)
            self.stats.delete_stats(name)
            self.aktuelle_sequenz = None
            self.seq_combo.set("")
            self._lade_in_ui()
            self._refresh_seq_liste()

    def _duplizieren(self):
        name = self.seq_combo.get()
        if not name:
            return
        seq = self.mgr.laden(name)
        if not seq:
            return
        neu = simpledialog.askstring("Duplizieren", "Name der Kopie:",
                                     initialvalue="%s_kopie" % name, parent=self)
        if not neu:
            return
        seq.name = neu.strip().replace(" ", "_")
        seq.erstellt = None
        self.mgr.speichern(seq)
        self._refresh_seq_liste()

    def _lade_in_ui(self):
        seq = self.aktuelle_sequenz
        self.name_entry.delete(0, "end")
        self.var_endlos.set(False)
        self.spin_x.set(1)
        if seq:
            self.name_entry.insert(0, seq.name)
            self.var_endlos.set(seq.schleife_endlos)
            self.spin_x.set(seq.schleife_x)
        self._toggle_endlos()
        self._refresh_kette()
        self._refresh_stat_anzeige()

    def _refresh_stat_anzeige(self):
        seq = self.aktuelle_sequenz
        if not seq:
            self.lbl_stat.config(text="")
            return
        st = self.stats.get_stats(seq.name)
        if st.get("ausfuehrungen"):
            self.lbl_stat.config(
                text="Laeufe: %d | Erfolg: %.0f%% | Letzter: %s"
                % (st["ausfuehrungen"], self.stats.get_erfolgsquote(seq.name),
                   st.get("letzter_lauf") or "-"))
        else:
            self.lbl_stat.config(text="Noch keine Laeufe.")

    # =================================================================
    #  Speichern
    # =================================================================
    def _ui_in_sequenz(self):
        if not self.aktuelle_sequenz:
            return False
        name = self.name_entry.get().strip().replace(" ", "_")
        if not name:
            messagebox.showwarning("Hinweis", "Bitte einen Namen angeben.", parent=self)
            return False
        self.aktuelle_sequenz.name = name
        self.aktuelle_sequenz.schleife_endlos = self.var_endlos.get()
        try:
            self.aktuelle_sequenz.schleife_x = max(1, int(float(self.spin_x.get())))
        except ValueError:
            self.aktuelle_sequenz.schleife_x = 1
        return True

    def _speichern(self):
        if not self.aktuelle_sequenz:
            messagebox.showinfo("Hinweis", "Keine Sequenz vorhanden.", parent=self)
            return
        if not self._ui_in_sequenz():
            return
        if self.mgr.speichern(self.aktuelle_sequenz):
            self._refresh_seq_liste()
            self._refresh_stat_anzeige()

    def _speichern_unter(self):
        if not self.aktuelle_sequenz:
            return
        neu = simpledialog.askstring("Speichern unter", "Neuer Name:", parent=self)
        if not neu:
            return
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, neu.strip().replace(" ", "_"))
        self.aktuelle_sequenz.erstellt = None
        self._speichern()

    # =================================================================
    #  Steuerung - mehrere Laeufe parallel (Pool)
    # =================================================================
    def _start(self):
        if not self.aktuelle_sequenz or not self.aktuelle_sequenz.schritte:
            messagebox.showinfo("Hinweis", "Keine Schritte zum Ausfuehren.", parent=self)
            return
        self._ui_in_sequenz()
        rid = self.pool.start(self.aktuelle_sequenz)
        if rid:
            self._run_text[rid] = "%s  startet..." % self.aktuelle_sequenz.name
            self._render_runs()
            self.lbl_status.config(text="Lauf #%d gestartet." % rid, foreground=ACCENT)

    def _selected_rid(self):
        sel = self.run_liste.curselection()
        if not sel or sel[0] >= len(self._run_ids):
            return None
        return self._run_ids[sel[0]]

    def _pause_sel(self):
        rid = self._selected_rid()
        if rid is None:
            messagebox.showinfo("Hinweis", "Bitte einen laufenden Lauf markieren.", parent=self)
            return
        self.pool.pause(rid)
        self._render_runs()

    def _stop_sel(self):
        rid = self._selected_rid()
        if rid is None:
            messagebox.showinfo("Hinweis", "Bitte einen laufenden Lauf markieren.", parent=self)
            return
        self.pool.stop(rid, hart=False)
        self.lbl_status.config(text="Lauf #%d wird gestoppt..." % rid, foreground=GELB)

    def _notaus_alle(self):
        if self.pool.anzahl() == 0:
            return
        self.pool.stop_all(hart=True)
        self.lbl_status.config(text="NOT-AUS: alle Laeufe gestoppt.", foreground=ROT)

    def _render_runs(self):
        self.run_liste.delete(0, "end")
        self._run_ids = []
        for r in self.pool.aktive():
            rid = r["run_id"]
            txt = self._run_text.get(rid, r["name"])
            marker = "  [PAUSE]" if r["pausiert"] else ""
            self.run_liste.insert("end", "#%d  %s%s" % (rid, txt, marker))
            self._run_ids.append(rid)
        self.lbl_laeufe.config(text="Laufende Sequenzen: %d" % self.pool.anzahl())

    # =================================================================
    #  Export / Import
    # =================================================================
    def _export_seq(self):
        name = (self.aktuelle_sequenz.name if self.aktuelle_sequenz
                else self.seq_combo.get())
        if not name:
            messagebox.showinfo("Hinweis", "Keine Sequenz gewaehlt.", parent=self)
            return
        ziel = filedialog.asksaveasfilename(
            parent=self, defaultextension=".zip",
            initialfile="sequenz_%s.zip" % name,
            filetypes=[("ZIP-Archiv", "*.zip")])
        if not ziel:
            return
        try:
            dateien = self.export.export_sequenz(name, ziel)
            messagebox.showinfo("Export", "Exportiert: %d Datei(en)." % len(dateien),
                                parent=self)
            self._log("Sequenz '%s' exportiert (%d Dateien)." % (name, len(dateien)))
        except Exception as e:
            messagebox.showerror("Fehler", "%s" % e, parent=self)

    def _export_backup(self):
        ziel = filedialog.asksaveasfilename(
            parent=self, defaultextension=".zip", initialfile="backup_alles.zip",
            filetypes=[("ZIP-Archiv", "*.zip")])
        if not ziel:
            return
        try:
            dateien = self.export.export_backup(ziel)
            messagebox.showinfo("Backup", "Backup mit %d Datei(en)." % len(dateien),
                                parent=self)
            self._log("Backup erstellt (%d Dateien)." % len(dateien))
        except Exception as e:
            messagebox.showerror("Fehler", "%s" % e, parent=self)

    def _importieren(self):
        quelle = filedialog.askopenfilename(parent=self,
                                            filetypes=[("ZIP-Archiv", "*.zip")])
        if not quelle:
            return
        try:
            res = self.export.importieren(quelle, ueberschreiben=True)
            self._refresh_alles()
            messagebox.showinfo("Import", "Importiert: %d Datei(en)."
                                % len(res["importiert"]), parent=self)
            self._log("Import: %d Dateien." % len(res["importiert"]))
        except Exception as e:
            messagebox.showerror("Fehler", "%s" % e, parent=self)

    # =================================================================
    #  Logging / Status (thread-sicher via after)
    # =================================================================
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
                self.ext_log("[Sequenz] %s" % msg)
            except Exception:
                pass

    def _pool_status_marshalled(self, rid, name, idx, gesamt, durchlauf):
        try:
            self.after(0, lambda: self._on_pool_status(rid, name, idx, gesamt, durchlauf))
        except Exception:
            pass

    def _on_pool_status(self, rid, name, idx, gesamt, durchlauf):
        if idx == 0 and durchlauf == 0:
            # Lauf beendet
            self._run_text.pop(rid, None)
            self.lbl_status.config(text="Lauf #%d beendet." % rid, foreground=GRUEN)
            self._refresh_stat_anzeige()
        else:
            self._run_text[rid] = "%s  Schritt %d/%d  D%d" % (name, idx, gesamt, durchlauf)
        self._render_runs()


# ---------------------------------------------------------------------
#  Standalone-Test (python modules/sequenz_gui.py)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Sequenz-Tab (Test)")
    root.geometry("1150x760")
    root.configure(bg=BG)
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
    style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground=ACCENT)
    style.configure("TButton", background=ACCENT, foreground=BG2,
                    font=("Segoe UI", 9, "bold"), padding=[6, 4])
    style.configure("Success.TButton", background=GRUEN, foreground=BG2)
    style.configure("Pause.TButton", background=GELB, foreground=BG2)
    style.configure("Danger.TButton", background=ROT, foreground=BG2)
    style.configure("TLabelframe", background=BG, foreground=ACCENT)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT)
    style.configure("TCheckbutton", background=BG, foreground=FG)

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tab = SequenzTab(root, base)
    tab.pack(fill="both", expand=True)
    root.mainloop()
