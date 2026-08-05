# -*- coding: utf-8 -*-
"""sequenz_gui.py - Tkinter-Tab "Sequenzen" fuer das Command Center.

Aufbau:
    Links   : Liste aller Sequenzen + Verwaltungs-Buttons + Export/Import
    Rechts  : Sequenz-Info, Schleifen-Einstellung, Schritt-Editor, Steuerung

Wird als ttk.Frame in ein Notebook eingehaengt:
    tab = SequenzTab(notebook, basis_dir, log_callback)
    notebook.add(tab, text="Sequenzen")
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

try:
    from .sequenz_manager import (SequenzManager, Sequenz, SequenzSchritt,
                                  SCHRITT_TYPEN, TYP_TRIGGER, TYP_ABLAUF, TYP_WARTEN)
    from .export_manager import ExportManager
    from .statistic_manager import StatistikManager
except ImportError:  # Standalone-Import (ohne Package)
    from sequenz_manager import (SequenzManager, Sequenz, SequenzSchritt,
                                 SCHRITT_TYPEN, TYP_TRIGGER, TYP_ABLAUF, TYP_WARTEN)
    from export_manager import ExportManager
    from statistic_manager import StatistikManager

# Farben (dunkles Theme)
BG = "#1e1e2e"
BG2 = "#11111b"
BG3 = "#313244"
FG = "#cdd6f4"
MUTED = "#a6adc8"
ACCENT = "#89b4fa"
OK = "#a6e3a1"
WARN = "#f9e2af"
DANGER = "#f38ba8"


class SequenzTab(ttk.Frame):
    def __init__(self, master, basis_dir, log_callback=None):
        super().__init__(master)
        self.basis_dir = basis_dir
        self.ext_log = log_callback

        self.mgr = SequenzManager(basis_dir,
                                  log_callback=self._log_marshalled,
                                  status_callback=self._status_marshalled)
        self.export = ExportManager(basis_dir)
        self.stats = StatistikManager(basis_dir)

        self.aktuelle_sequenz = None
        self._poll_job = None

        self._build_ui()
        self._refresh_seq_liste()
        self._refresh_ressourcen()

    # =================================================================
    #  UI-Aufbau
    # =================================================================
    def _build_ui(self):
        kopf = ttk.Label(self, text="SEQUENZEN", style="Header.TLabel")
        kopf.pack(anchor="w", padx=20, pady=(15, 0))
        ttk.Label(self, text="Trigger + Ablaeufe + Wartezeiten zu Ablaeufen "
                             "verketten", foreground=MUTED).pack(anchor="w", padx=20)

        haupt = ttk.Frame(self)
        haupt.pack(fill="both", expand=True, padx=15, pady=10)

        self._build_links(haupt)
        self._build_rechts(haupt)

    # ---------- Linke Spalte ----------
    def _build_links(self, parent):
        links = ttk.Frame(parent, width=250)
        links.pack(side="left", fill="y", padx=(0, 12))
        links.pack_propagate(False)

        ttk.Label(links, text="Gespeicherte Sequenzen",
                  foreground=ACCENT, font=("Segoe UI", 10, "bold")).pack(anchor="w")

        list_box = ttk.Frame(links)
        list_box.pack(fill="both", expand=True, pady=5)
        self.seq_liste = tk.Listbox(list_box, bg=BG2, fg=FG,
                                    selectbackground=ACCENT, selectforeground=BG2,
                                    font=("Consolas", 10), activestyle="none",
                                    exportselection=False)
        self.seq_liste.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_box, orient="vertical", command=self.seq_liste.yview)
        sb.pack(side="right", fill="y")
        self.seq_liste.config(yscrollcommand=sb.set)
        self.seq_liste.bind("<<ListboxSelect>>", lambda e: None)
        self.seq_liste.bind("<Double-Button-1>", lambda e: self._laden())

        btns = ttk.Frame(links)
        btns.pack(fill="x")
        for txt, cmd in [("Neu", self._neu), ("Laden", self._laden),
                         ("Loeschen", self._loeschen),
                         ("Duplizieren", self._duplizieren),
                         ("Aktualisieren", self._refresh_seq_liste)]:
            ttk.Button(btns, text=txt, command=cmd).pack(fill="x", pady=2)

        ttk.Separator(links, orient="horizontal").pack(fill="x", pady=8)
        ttk.Label(links, text="Export / Import", foreground=ACCENT,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ex = ttk.Frame(links)
        ex.pack(fill="x", pady=3)
        ttk.Button(ex, text="Sequenz exportieren (ZIP)",
                   command=self._export_seq).pack(fill="x", pady=2)
        ttk.Button(ex, text="Alles als Backup (ZIP)",
                   command=self._export_backup).pack(fill="x", pady=2)
        ttk.Button(ex, text="Importieren...",
                   command=self._importieren).pack(fill="x", pady=2)

    # ---------- Rechte Spalte ----------
    def _build_rechts(self, parent):
        rechts = ttk.Frame(parent)
        rechts.pack(side="left", fill="both", expand=True)

        # --- Info ---
        info = ttk.LabelFrame(rechts, text="Sequenz-Info")
        info.pack(fill="x", pady=(0, 8))
        zeile = ttk.Frame(info)
        zeile.pack(fill="x", padx=10, pady=6)
        ttk.Label(zeile, text="Name:").pack(side="left")
        self.name_entry = ttk.Entry(zeile, width=24)
        self.name_entry.pack(side="left", padx=6)
        self.lbl_info = ttk.Label(zeile, text="0 Schritte  |  ~0.0s",
                                  foreground=MUTED)
        self.lbl_info.pack(side="left", padx=15)
        zeile2 = ttk.Frame(info)
        zeile2.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_meta = ttk.Label(zeile2, text="Erstellt: -   Geaendert: -",
                                  foreground=MUTED)
        self.lbl_meta.pack(side="left")
        self.lbl_stat = ttk.Label(zeile2, text="", foreground=OK)
        self.lbl_stat.pack(side="left", padx=15)

        # --- Schleife ---
        schleife = ttk.LabelFrame(rechts, text="Schleife")
        schleife.pack(fill="x", pady=(0, 8))
        sf = ttk.Frame(schleife)
        sf.pack(fill="x", padx=10, pady=6)
        self.var_endlos = tk.BooleanVar(value=False)
        ttk.Checkbutton(sf, text="Endlos wiederholen", variable=self.var_endlos,
                        command=self._toggle_endlos).pack(side="left")
        ttk.Label(sf, text="   oder Anzahl:").pack(side="left", padx=(15, 4))
        self.spin_x = ttk.Spinbox(sf, from_=1, to=99999, width=7)
        self.spin_x.set(1)
        self.spin_x.pack(side="left")
        ttk.Label(sf, text="x").pack(side="left", padx=3)

        # --- Schritt-Editor ---
        editor = ttk.LabelFrame(rechts, text="Schritte")
        editor.pack(fill="both", expand=True, pady=(0, 8))

        kopf = ttk.Frame(editor)
        kopf.pack(fill="x", padx=10, pady=(6, 0))
        ttk.Label(kopf, text="#  Typ       Ziel/Wert         Warte    Zufall  Goto",
                  foreground=ACCENT, font=("Consolas", 9, "bold")).pack(anchor="w")

        lc = ttk.Frame(editor)
        lc.pack(fill="both", expand=True, padx=10, pady=4)
        self.schritt_liste = tk.Listbox(lc, bg=BG2, fg=FG, height=8,
                                        selectbackground=ACCENT, selectforeground=BG2,
                                        font=("Consolas", 9), activestyle="none",
                                        exportselection=False)
        self.schritt_liste.pack(side="left", fill="both", expand=True)
        sb2 = ttk.Scrollbar(lc, orient="vertical", command=self.schritt_liste.yview)
        sb2.pack(side="right", fill="y")
        self.schritt_liste.config(yscrollcommand=sb2.set)
        self.schritt_liste.bind("<<ListboxSelect>>", self._on_schritt_select)

        # Schritt-Aktionen
        akt = ttk.Frame(editor)
        akt.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(akt, text="Hoch", command=lambda: self._verschieben(-1)).pack(side="left", padx=2)
        ttk.Button(akt, text="Runter", command=lambda: self._verschieben(1)).pack(side="left", padx=2)
        ttk.Button(akt, text="Loeschen", style="Danger.TButton",
                   command=self._schritt_loeschen).pack(side="left", padx=2)

        # Editor-Felder
        felder = ttk.Frame(editor)
        felder.pack(fill="x", padx=10, pady=6)

        ttk.Label(felder, text="Typ:").grid(row=0, column=0, sticky="w", pady=3)
        self.cb_typ = ttk.Combobox(felder, values=SCHRITT_TYPEN, width=10,
                                   state="readonly")
        self.cb_typ.set(TYP_WARTEN)
        self.cb_typ.grid(row=0, column=1, padx=5)
        self.cb_typ.bind("<<ComboboxSelected>>", self._on_typ_change)

        ttk.Label(felder, text="Ziel:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.cb_wert = ttk.Combobox(felder, width=20, state="disabled")
        self.cb_wert.grid(row=0, column=3, padx=5)

        ttk.Label(felder, text="Wartezeit (ms):").grid(row=1, column=0, sticky="w", pady=3)
        self.sp_warte = ttk.Spinbox(felder, from_=0, to=3600000, width=10)
        self.sp_warte.set(0)
        self.sp_warte.grid(row=1, column=1, padx=5)

        ttk.Label(felder, text="+ Zufall (ms):").grid(row=1, column=2, sticky="w", padx=(12, 0))
        self.sp_zufall = ttk.Spinbox(felder, from_=0, to=600000, width=10)
        self.sp_zufall.set(0)
        self.sp_zufall.grid(row=1, column=3, padx=5)

        ttk.Label(felder, text="Goto bei Fehler:").grid(row=2, column=0, sticky="w", pady=3)
        self.sp_goto = ttk.Spinbox(felder, from_=0, to=9999, width=10)
        self.sp_goto.set(0)
        self.sp_goto.grid(row=2, column=1, padx=5)
        ttk.Label(felder, text="(0 = kein Sprung, sonst Schritt-Nr.)",
                  foreground=MUTED).grid(row=2, column=2, columnspan=2, sticky="w", padx=(12, 0))

        add_frame = ttk.Frame(editor)
        add_frame.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(add_frame, text="+ Schritt hinzufuegen", style="Success.TButton",
                   command=self._schritt_hinzufuegen).pack(side="left", padx=2)
        ttk.Button(add_frame, text="Auswahl uebernehmen",
                   command=self._schritt_uebernehmen).pack(side="left", padx=2)

        # --- Speichern + Steuerung ---
        unten = ttk.Frame(rechts)
        unten.pack(fill="x")

        speich = ttk.Frame(unten)
        speich.pack(fill="x", pady=(0, 6))
        ttk.Button(speich, text="Speichern", command=self._speichern).pack(side="left", padx=2)
        ttk.Button(speich, text="Speichern unter...",
                   command=self._speichern_unter).pack(side="left", padx=2)

        steuer = ttk.LabelFrame(unten, text="Steuerung")
        steuer.pack(fill="x")
        sr = ttk.Frame(steuer)
        sr.pack(fill="x", padx=10, pady=8)
        self.btn_start = ttk.Button(sr, text="Start", style="Success.TButton",
                                    command=self._start)
        self.btn_start.pack(side="left", padx=3)
        self.btn_pause = ttk.Button(sr, text="Pause", style="Pause.TButton",
                                    command=self._pause, state="disabled")
        self.btn_pause.pack(side="left", padx=3)
        self.btn_stop = ttk.Button(sr, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=3)
        self.btn_notaus = ttk.Button(sr, text="NOT-AUS", style="Danger.TButton",
                                     command=self._notaus, state="disabled")
        self.btn_notaus.pack(side="left", padx=3)
        self.lbl_status = ttk.Label(sr, text="Bereit.", foreground=MUTED)
        self.lbl_status.pack(side="left", padx=15)

        # Mini-Log
        self.log = tk.Text(steuer, height=5, bg=BG2, fg=OK,
                           font=("Consolas", 9), wrap="word")
        self.log.pack(fill="x", padx=10, pady=(0, 8))
        self.log.insert("end", "Sequenz-Modul bereit.\n")
        self.log.config(state="disabled")

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

    def _status_marshalled(self, name, idx, gesamt, durchlauf):
        try:
            self.after(0, lambda: self._render_status(name, idx, gesamt, durchlauf))
        except Exception:
            pass

    def _render_status(self, name, idx, gesamt, durchlauf):
        if idx == 0 and durchlauf == 0:
            # Abschluss-Signal
            self.lbl_status.config(text="Fertig.", foreground=OK)
            self._set_laufend(False)
            self._refresh_info()
            return
        self.lbl_status.config(
            text="Laeuft: Schritt %d/%d  (Durchlauf %d)" % (idx, gesamt, durchlauf),
            foreground=ACCENT)

    # =================================================================
    #  Sequenz-Verwaltung (links)
    # =================================================================
    def _refresh_seq_liste(self):
        self.seq_liste.delete(0, "end")
        for name in self.mgr.get_sequenz_namen():
            self.seq_liste.insert("end", name)

    def _refresh_ressourcen(self):
        self._trigger_namen = self.mgr.get_trigger_namen()
        self._ablauf_namen = self.mgr.get_ablauf_namen()

    def _gewaehlter_name(self):
        sel = self.seq_liste.curselection()
        if not sel:
            return None
        return self.seq_liste.get(sel[0])

    def _neu(self):
        name = simpledialog.askstring("Neue Sequenz", "Name der Sequenz:", parent=self)
        if not name:
            return
        name = name.strip().replace(" ", "_")
        self.aktuelle_sequenz = Sequenz(name=name)
        self._lade_in_ui()
        self._log("Neue Sequenz '%s' angelegt (noch nicht gespeichert)." % name)

    def _laden(self):
        name = self._gewaehlter_name()
        if not name:
            messagebox.showinfo("Hinweis", "Bitte eine Sequenz auswaehlen.", parent=self)
            return
        seq = self.mgr.laden(name)
        if seq:
            self.aktuelle_sequenz = seq
            self._lade_in_ui()

    def _loeschen(self):
        name = self._gewaehlter_name()
        if not name:
            return
        if messagebox.askyesno("Loeschen", "Sequenz '%s' loeschen?" % name, parent=self):
            self.mgr.loeschen(name)
            if self.aktuelle_sequenz and self.aktuelle_sequenz.name == name:
                self.aktuelle_sequenz = None
                self._lade_in_ui()
            self._refresh_seq_liste()

    def _duplizieren(self):
        name = self._gewaehlter_name()
        if not name:
            return
        seq = self.mgr.laden(name)
        if not seq:
            return
        neuer_name = simpledialog.askstring(
            "Duplizieren", "Name der Kopie:", initialvalue="%s_kopie" % name, parent=self)
        if not neuer_name:
            return
        seq.name = neuer_name.strip().replace(" ", "_")
        seq.erstellt = None
        self.mgr.speichern(seq)
        self._refresh_seq_liste()

    # =================================================================
    #  UI <-> Sequenz
    # =================================================================
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
        self._refresh_schritt_liste()
        self._refresh_info()

    def _refresh_schritt_liste(self):
        self.schritt_liste.delete(0, "end")
        if not self.aktuelle_sequenz:
            return
        for i, s in enumerate(self.aktuelle_sequenz.schritte, 1):
            ziel = s.wert or s.name or ""
            if s.typ == TYP_WARTEN:
                ziel = "-"
            goto = str(s.goto_step + 1) if s.goto_step is not None and s.goto_step >= 0 else "-"
            self.schritt_liste.insert(
                "end",
                "%2d %-9s %-16s %6dms %+5dms  %s"
                % (i, s.typ, ziel[:16], s.warte_ms, s.zufall_ms, goto))

    def _refresh_info(self):
        seq = self.aktuelle_sequenz
        if not seq:
            self.lbl_info.config(text="0 Schritte  |  ~0.0s")
            self.lbl_meta.config(text="Erstellt: -   Geaendert: -")
            self.lbl_stat.config(text="")
            return
        self.lbl_info.config(text="%d Schritte  |  ~%.1fs (+ Trigger/Ablaeufe)"
                             % (len(seq.schritte), seq.geschaetzte_dauer_s()))
        self.lbl_meta.config(text="Erstellt: %s   Geaendert: %s"
                             % (seq.erstellt or "-", seq.geaendert or "-"))
        st = self.stats.get_stats(seq.name)
        if st.get("ausfuehrungen"):
            self.lbl_stat.config(
                text="Laeufe: %d  |  Erfolg: %.0f%%  |  Letzter: %s"
                % (st["ausfuehrungen"], self.stats.get_erfolgsquote(seq.name),
                   st.get("letzter_lauf") or "-"))
        else:
            self.lbl_stat.config(text="Noch keine Laeufe.")

    def _toggle_endlos(self):
        if self.var_endlos.get():
            self.spin_x.config(state="disabled")
        else:
            self.spin_x.config(state="normal")

    # =================================================================
    #  Schritt-Editor
    # =================================================================
    def _on_typ_change(self, event=None):
        typ = self.cb_typ.get()
        if typ == TYP_TRIGGER:
            self.cb_wert.config(state="readonly", values=self._trigger_namen)
            if self._trigger_namen and not self.cb_wert.get():
                self.cb_wert.set(self._trigger_namen[0])
        elif typ == TYP_ABLAUF:
            self.cb_wert.config(state="readonly", values=self._ablauf_namen)
            if self._ablauf_namen and not self.cb_wert.get():
                self.cb_wert.set(self._ablauf_namen[0])
        else:  # WARTEN
            self.cb_wert.set("")
            self.cb_wert.config(state="disabled", values=[])

    def _felder_zu_schritt(self):
        typ = self.cb_typ.get()
        wert = self.cb_wert.get() if typ != TYP_WARTEN else ""
        if typ in (TYP_TRIGGER, TYP_ABLAUF) and not wert:
            messagebox.showwarning("Hinweis",
                                   "Bitte ein Ziel (%s) waehlen." % typ, parent=self)
            return None
        try:
            warte = int(float(self.sp_warte.get() or 0))
            zufall = int(float(self.sp_zufall.get() or 0))
            goto_nr = int(float(self.sp_goto.get() or 0))
        except ValueError:
            messagebox.showwarning("Hinweis", "Ungueltige Zahl im Editor.", parent=self)
            return None
        goto_step = goto_nr - 1 if goto_nr > 0 else -1
        return SequenzSchritt(typ=typ, name=wert, wert=wert,
                              warte_ms=warte, zufall_ms=zufall, goto_step=goto_step)

    def _schritt_hinzufuegen(self):
        if not self.aktuelle_sequenz:
            messagebox.showinfo("Hinweis", "Zuerst eine Sequenz anlegen/laden.", parent=self)
            return
        schritt = self._felder_zu_schritt()
        if not schritt:
            return
        self.aktuelle_sequenz.hinzufuegen(schritt)
        self._refresh_schritt_liste()
        self._refresh_info()

    def _schritt_uebernehmen(self):
        if not self.aktuelle_sequenz:
            return
        sel = self.schritt_liste.curselection()
        if not sel:
            messagebox.showinfo("Hinweis", "Kein Schritt ausgewaehlt.", parent=self)
            return
        schritt = self._felder_zu_schritt()
        if not schritt:
            return
        self.aktuelle_sequenz.schritte[sel[0]] = schritt
        self._refresh_schritt_liste()
        self.schritt_liste.selection_set(sel[0])
        self._refresh_info()

    def _on_schritt_select(self, event=None):
        sel = self.schritt_liste.curselection()
        if not sel or not self.aktuelle_sequenz:
            return
        s = self.aktuelle_sequenz.schritte[sel[0]]
        self.cb_typ.set(s.typ)
        self._on_typ_change()
        if s.typ != TYP_WARTEN:
            self.cb_wert.set(s.wert or s.name)
        self.sp_warte.set(s.warte_ms)
        self.sp_zufall.set(s.zufall_ms)
        self.sp_goto.set(s.goto_step + 1 if s.goto_step >= 0 else 0)

    def _schritt_loeschen(self):
        sel = self.schritt_liste.curselection()
        if not sel or not self.aktuelle_sequenz:
            return
        self.aktuelle_sequenz.entfernen(sel[0])
        self._refresh_schritt_liste()
        self._refresh_info()

    def _verschieben(self, richtung):
        sel = self.schritt_liste.curselection()
        if not sel or not self.aktuelle_sequenz:
            return
        neu = self.aktuelle_sequenz.verschieben(sel[0], richtung)
        self._refresh_schritt_liste()
        self.schritt_liste.selection_set(neu)

    # =================================================================
    #  Speichern
    # =================================================================
    def _ui_in_sequenz(self):
        """Uebertraegt Name + Schleifen-Einstellung aus der UI in die Sequenz."""
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
            messagebox.showinfo("Hinweis", "Keine Sequenz geladen.", parent=self)
            return
        if not self._ui_in_sequenz():
            return
        if self.mgr.speichern(self.aktuelle_sequenz):
            self._refresh_seq_liste()
            self._refresh_info()

    def _speichern_unter(self):
        if not self.aktuelle_sequenz:
            return
        name = simpledialog.askstring("Speichern unter", "Neuer Name:", parent=self)
        if not name:
            return
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, name.strip().replace(" ", "_"))
        self.aktuelle_sequenz.erstellt = None
        self._speichern()

    # =================================================================
    #  Steuerung
    # =================================================================
    def _set_laufend(self, laeuft):
        if laeuft:
            self.btn_start.config(state="disabled")
            self.btn_pause.config(state="normal", text="Pause")
            self.btn_stop.config(state="normal")
            self.btn_notaus.config(state="normal")
        else:
            self.btn_start.config(state="normal")
            self.btn_pause.config(state="disabled", text="Pause")
            self.btn_stop.config(state="disabled")
            self.btn_notaus.config(state="disabled")

    def _start(self):
        if not self.aktuelle_sequenz or not self.aktuelle_sequenz.schritte:
            messagebox.showinfo("Hinweis", "Keine Schritte zum Ausfuehren.", parent=self)
            return
        self._ui_in_sequenz()
        if self.mgr.start(self.aktuelle_sequenz):
            self._set_laufend(True)
            self.lbl_status.config(text="Gestartet...", foreground=ACCENT)

    def _pause(self):
        self.mgr.pause()
        if self.mgr.pausiert:
            self.btn_pause.config(text="Weiter")
            self.lbl_status.config(text="Pausiert.", foreground=WARN)
        else:
            self.btn_pause.config(text="Pause")

    def _stop(self):
        self.mgr.stop(hart=False)
        self.lbl_status.config(text="Stoppe...", foreground=WARN)

    def _notaus(self):
        self.mgr.stop(hart=True)
        self.lbl_status.config(text="NOT-AUS!", foreground=DANGER)
        self._set_laufend(False)

    # =================================================================
    #  Export / Import
    # =================================================================
    def _export_seq(self):
        name = self._gewaehlter_name() or (
            self.aktuelle_sequenz.name if self.aktuelle_sequenz else None)
        if not name:
            messagebox.showinfo("Hinweis", "Bitte eine Sequenz auswaehlen.", parent=self)
            return
        ziel = filedialog.asksaveasfilename(
            parent=self, defaultextension=".zip",
            initialfile="sequenz_%s.zip" % name,
            filetypes=[("ZIP-Archiv", "*.zip")])
        if not ziel:
            return
        try:
            dateien = self.export.export_sequenz(name, ziel)
            messagebox.showinfo("Export", "Exportiert: %d Datei(en)\n%s"
                                % (len(dateien), "\n".join(dateien)), parent=self)
            self._log("Sequenz '%s' exportiert -> %s" % (name, ziel))
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
            messagebox.showinfo("Backup", "Backup mit %d Datei(en) erstellt."
                                % len(dateien), parent=self)
            self._log("Backup erstellt -> %s (%d Dateien)" % (ziel, len(dateien)))
        except Exception as e:
            messagebox.showerror("Fehler", "%s" % e, parent=self)

    def _importieren(self):
        quelle = filedialog.askopenfilename(
            parent=self, filetypes=[("ZIP-Archiv", "*.zip")])
        if not quelle:
            return
        try:
            ergebnis = self.export.importieren(quelle, ueberschreiben=True)
            self._refresh_seq_liste()
            self._refresh_ressourcen()
            messagebox.showinfo(
                "Import", "Importiert: %d Datei(en).\nUebersprungen: %d."
                % (len(ergebnis["importiert"]), len(ergebnis["uebersprungen"])),
                parent=self)
            self._log("Import aus %s: %d Dateien"
                      % (quelle, len(ergebnis["importiert"])))
        except Exception as e:
            messagebox.showerror("Fehler", "%s" % e, parent=self)


# ---------------------------------------------------------------------
#  Standalone-Test (python modules/sequenz_gui.py)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Sequenz-Tab (Test)")
    root.geometry("1050x820")
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
    style.configure("Success.TButton", background=OK, foreground=BG2)
    style.configure("Pause.TButton", background=WARN, foreground=BG2)
    style.configure("Danger.TButton", background=DANGER, foreground=BG2)
    style.configure("TLabelframe", background=BG, foreground=ACCENT)
    style.configure("TLabelframe.Label", background=BG, foreground=ACCENT)
    style.configure("TCheckbutton", background=BG, foreground=FG)

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tab = SequenzTab(root, base)
    tab.pack(fill="both", expand=True)
    root.mainloop()
