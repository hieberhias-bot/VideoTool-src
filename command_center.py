#!/usr/bin/env python3
"""Bot Command Center - zentrale Steuerungs-App mit Ablauf-Editor"""

import os, sys, json, time, subprocess, threading, random, copy
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

try:
    from config import ToolConfig
    CONFIG_OK = True
except Exception:
    CONFIG_OK = False
    ToolConfig = None

# Sequenz-Modul (modules/) - optional, App laeuft auch ohne
try:
    from modules.sequenz_gui import SequenzTab
    from modules.sequenz_manager import SequenzManager
    SEQ_OK = True
    SEQ_IMPORT_ERR = None
except Exception as _seq_err:
    SEQ_OK = False
    SEQ_IMPORT_ERR = _seq_err
    SequenzTab = None
    SequenzManager = None

# Fenster-Erkennung (fuer fenster-relative Aufnahmen) - optional
try:
    from modules import fenster as fenster_util
    FENSTER_OK = getattr(fenster_util, "verfuegbar", False)
except Exception:
    FENSTER_OK = False
    fenster_util = None


class BotStatus:
    fishbot_laeuft = False
    fishbot_pausiert = False
    aufnahme_laeuft = False
    arduino_verbunden = False
    gefischt = 0
    klicks = 0
    fehlversuche = 0
    startzeit = None
    pausen_start = None
    pausen_gesamt = 0.0


class AblaufEditor(tk.Toplevel):
    """Editor fuer einen einzelnen Ablauf mit Event-Bearbeitung."""

    def __init__(self, parent, ablauf_name, events, on_save_callback):
        super().__init__(parent)
        self.ablauf_name = ablauf_name
        self.events = copy.deepcopy(events)
        self.on_save_callback = on_save_callback
        self.title("Ablauf-Editor: %s" % ablauf_name)
        self.geometry("1050x700")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)
        self._setup_ui()
        self._refresh_liste()

    def _setup_ui(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=15, pady=10)
        ttk.Label(header, text="Ablauf-Editor", font=("Segoe UI", 14, "bold"),
                  foreground="#89b4fa").pack(side="left")
        ttk.Label(header, text="  %s  (%d Events)" % (self.ablauf_name, len(self.events)),
                  foreground="#a6adc8").pack(side="left", padx=10)

        tab_frame = ttk.Frame(self)
        tab_frame.pack(fill="both", expand=True, padx=15, pady=5)

        kopf = ttk.Frame(tab_frame)
        kopf.pack(fill="x")
        spalten = ["#", "Typ", "X", "Y", "Wartezeit(ms)", "Zufall(ms)", "Unschaerfe(px)", "Taste"]
        breiten = [4, 10, 8, 8, 14, 14, 16, 10]
        for sp, br in zip(spalten, breiten):
            ttk.Label(kopf, text=sp, width=br, foreground="#89b4fa",
                     font=("Consolas", 9, "bold")).pack(side="left")

        list_container = ttk.Frame(tab_frame)
        list_container.pack(fill="both", expand=True)
        self.event_liste = tk.Listbox(list_container, bg="#11111b", fg="#cdd6f4",
                                     selectbackground="#89b4fa",
                                     selectforeground="#11111b",
                                     font=("Consolas", 9), height=12)
        self.event_liste.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_container, orient="vertical", command=self.event_liste.yview)
        scroll.pack(side="right", fill="y")
        self.event_liste.config(yscrollcommand=scroll.set)
        self.event_liste.bind("<<ListboxSelect>>", self._on_select)

        edit_frame = ttk.LabelFrame(self, text="Event bearbeiten")
        edit_frame.pack(fill="x", padx=15, pady=10)

        # Zeile 1: Typ / Position
        row1 = ttk.Frame(edit_frame)
        row1.pack(fill="x", padx=10, pady=5)

        ttk.Label(row1, text="Typ:").pack(side="left")
        self.edit_typ = ttk.Combobox(row1, values=["click", "move", "ldown", "lup", "key"], width=10)
        self.edit_typ.pack(side="left", padx=5)

        ttk.Label(row1, text="X:").pack(side="left", padx=(15, 3))
        self.edit_x = ttk.Entry(row1, width=8)
        self.edit_x.pack(side="left")

        ttk.Label(row1, text="Y:").pack(side="left", padx=(10, 3))
        self.edit_y = ttk.Entry(row1, width=8)
        self.edit_y.pack(side="left")

        ttk.Label(row1, text="Taste:").pack(side="left", padx=(15, 3))
        self.edit_key = ttk.Entry(row1, width=10)
        self.edit_key.pack(side="left")

        # Zeile 2: Wartezeit / Zufall / Pixel-Unschaerfe
        row2 = ttk.Frame(edit_frame)
        row2.pack(fill="x", padx=10, pady=5)

        ttk.Label(row2, text="Feste Wartezeit (ms):").pack(side="left")
        self.edit_wartezeit = ttk.Entry(row2, width=8)
        self.edit_wartezeit.pack(side="left", padx=5)

        ttk.Label(row2, text="+ Zufall bis (ms):").pack(side="left", padx=(15, 3))
        self.edit_zufall = ttk.Entry(row2, width=8)
        self.edit_zufall.pack(side="left")
        ttk.Label(row2, text="ms").pack(side="left", padx=3)

        ttk.Label(row2, text="Pixel-Unschaerfe +/-:").pack(side="left", padx=(15, 3))
        self.edit_pixel_unscharfe = ttk.Entry(row2, width=6)
        self.edit_pixel_unscharfe.pack(side="left")
        ttk.Label(row2, text="px").pack(side="left", padx=3)

        # Buttons
        btn_frame = ttk.Frame(edit_frame)
        btn_frame.pack(fill="x", padx=10, pady=10)

        self.btn_update = ttk.Button(btn_frame, text="Event aktualisieren", command=self._event_update)
        self.btn_update.pack(side="left", padx=5)

        self.btn_delete = ttk.Button(btn_frame, text="Event loeschen",
                                    style="Danger.TButton", command=self._event_delete)
        self.btn_delete.pack(side="left", padx=5)

        self.btn_add = ttk.Button(btn_frame, text="Event hinzufuegen", command=self._event_add)
        self.btn_add.pack(side="left", padx=5)

        global_btn = ttk.Frame(self)
        global_btn.pack(fill="x", padx=15, pady=10)

        self.btn_save = ttk.Button(global_btn, text="Speichern", style="Success.TButton",
                                  command=self._save)
        self.btn_save.pack(side="left", padx=5)

        self.btn_close = ttk.Button(global_btn, text="Schliessen", command=self.destroy)
        self.btn_close.pack(side="left", padx=5)

        self.lbl_status = ttk.Label(global_btn, text="", foreground="#a6e3a1")
        self.lbl_status.pack(side="left", padx=15)

    def _refresh_liste(self):
        self.event_liste.delete(0, "end")
        for i, ev in enumerate(self.events, 1):
            typ = ev.get("typ", "click")
            x = ev.get("x", 0)
            y = ev.get("y", 0)
            wartezeit = ev.get("zeit_bis_naechster_ms", ev.get("delay", 0))
            zufall = ev.get("zufall_ms", 0)
            pu = ev.get("pixel_unscharfe", 3)
            taste = ev.get("key", "-")
            self.event_liste.insert("end", "%-4d %-10s %-8d %-8d %-14d %-14d %-16d %s" %
                                   (i, typ, x, y, wartezeit, zufall, pu, taste))

    def _on_select(self, event):
        sel = self.event_liste.curselection()
        if not sel or sel[0] >= len(self.events):
            return
        ev = self.events[sel[0]]
        self.edit_typ.set(ev.get("typ", "click"))
        self.edit_x.delete(0, "end"); self.edit_x.insert(0, str(ev.get("x", 0)))
        self.edit_y.delete(0, "end"); self.edit_y.insert(0, str(ev.get("y", 0)))
        wartezeit = ev.get("zeit_bis_naechster_ms", ev.get("delay", 0))
        self.edit_wartezeit.delete(0, "end"); self.edit_wartezeit.insert(0, str(wartezeit))
        zufall = ev.get("zufall_ms", 0)
        self.edit_zufall.delete(0, "end"); self.edit_zufall.insert(0, str(zufall))
        pu = ev.get("pixel_unscharfe", 3)
        self.edit_pixel_unscharfe.delete(0, "end"); self.edit_pixel_unscharfe.insert(0, str(pu))
        self.edit_key.delete(0, "end"); self.edit_key.insert(0, ev.get("key", ""))

    def _event_update(self):
        sel = self.event_liste.curselection()
        if not sel or sel[0] >= len(self.events):
            messagebox.showwarning("Hinweis", "Bitte ein Event auswaehlen!")
            return
        try:
            ev = self.events[sel[0]]
            ev["typ"] = self.edit_typ.get() or "click"
            ev["x"] = int(self.edit_x.get() or 0)
            ev["y"] = int(self.edit_y.get() or 0)
            ev["zeit_bis_naechster_ms"] = int(self.edit_wartezeit.get() or 0)
            ev["zufall_ms"] = int(self.edit_zufall.get() or 0)
            ev["pixel_unscharfe"] = int(self.edit_pixel_unscharfe.get() or 3)
            key_val = self.edit_key.get().strip()
            if key_val:
                ev["key"] = key_val
            elif "key" in ev:
                del ev["key"]
            self._refresh_liste()
            self.event_liste.selection_set(sel[0])
            self.lbl_status.config(text="Event %d aktualisiert!" % (sel[0]+1), foreground="#a6e3a1")
        except ValueError as e:
            messagebox.showerror("Fehler", "Ungueltige Zahl: %s" % e)

    def _event_delete(self):
        sel = self.event_liste.curselection()
        if not sel or sel[0] >= len(self.events):
            return
        if messagebox.askyesno("Loeschen", "Event %d wirklich loeschen?" % (sel[0]+1)):
            del self.events[sel[0]]
            self._refresh_liste()
            self.lbl_status.config(text="Event geloescht!", foreground="#f38ba8")

    def _event_add(self):
        neues_event = {"typ": "click", "x": 0, "y": 0,
                       "zeit_bis_naechster_ms": 1000, "zufall_ms": 0,
                       "pixel_unscharfe": 3}
        sel = self.event_liste.curselection()
        if sel and sel[0] < len(self.events):
            self.events.insert(sel[0]+1, neues_event)
        else:
            self.events.append(neues_event)
        self._refresh_liste()
        self.lbl_status.config(text="Event hinzugefuegt!", foreground="#a6e3a1")

    def _save(self):
        try:
            datei = os.path.join(BASE_DIR, "ablauf_%s.json" % self.ablauf_name)
            if os.path.exists(datei):
                with open(datei, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data["events"] = self.events
                else:
                    data = {"name": self.ablauf_name, "events": self.events}
            else:
                data = {"name": self.ablauf_name, "events": self.events}
            with open(datei, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self.lbl_status.config(text="Gespeichert! (%d Events)" % len(self.events), foreground="#a6e3a1")
            if self.on_save_callback:
                self.on_save_callback()
            messagebox.showinfo("Gespeichert", "Ablauf '%s' mit %d Events gespeichert!" %
                               (self.ablauf_name, len(self.events)))
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte nicht speichern: %s" % e)


class CommandCenter:
    def __init__(self, root):
        self.root = root
        self.root.title("Bot Command Center")
        self.root.geometry("1100x900")
        self.root.configure(bg="#1e1e2e")

        self.config = ToolConfig() if CONFIG_OK else None
        self.pixel_aufnahme_aktiv = False
        self.pixel_aufnahme_punkte = []
        self.trigger_job = None
        self.aufnahme_events = []
        self.aufnahme_letzter_zeit = None
        # fenster-relative Aufnahme
        self.erfasstes_fenster = None   # {"titel","x","y","w","h"} oder None
        self._rec_listener = None       # pynput-Listener waehrend Aufnahme
        self._erfass_listener = None    # pynput-Listener beim Fenster-Erfassen

        self._setup_style()
        self._setup_tabs()
        self._setup_statusbar()
        self._update_status()

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#1e1e2e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#313244", foreground="#cdd6f4",
                        padding=[15, 8], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#89b4fa")],
                  foreground=[("selected", "#11111b")])
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4",
                        font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"),
                        foreground="#89b4fa")
        style.configure("TButton", background="#89b4fa", foreground="#11111b",
                        font=("Segoe UI", 10, "bold"), padding=[10, 6])
        style.map("TButton", background=[("active", "#a6c8ff")])
        style.configure("Danger.TButton", background="#f38ba8", foreground="#11111b")
        style.configure("Success.TButton", background="#a6e3a1", foreground="#11111b")
        style.configure("Pause.TButton", background="#f9e2af", foreground="#11111b")

    def _setup_tabs(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_fish = ttk.Frame(self.notebook)
        self.tab_aufnahme = ttk.Frame(self.notebook)
        self.tab_skripte = ttk.Frame(self.notebook)
        self.tab_config = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_fish, text="Fish-Bot")
        self.notebook.add(self.tab_aufnahme, text="Aufzeichnung / Trigger")

        # Sequenzen-Tab (aus modules/sequenz_gui.py)
        if SEQ_OK:
            self.tab_sequenzen = SequenzTab(self.notebook, BASE_DIR, self._log_fish)
            self.notebook.add(self.tab_sequenzen, text="Sequenzen")
        else:
            self.tab_sequenzen = ttk.Frame(self.notebook)
            self.notebook.add(self.tab_sequenzen, text="Sequenzen")
            ttk.Label(self.tab_sequenzen,
                      text="Sequenz-Modul konnte nicht geladen werden:\n%s"
                      % SEQ_IMPORT_ERR,
                      foreground="#f38ba8").pack(padx=20, pady=20, anchor="w")

        self.notebook.add(self.tab_skripte, text="Skripte")
        self.notebook.add(self.tab_config, text="Config / Arduino")

        self._build_fish_tab()
        self._build_aufnahme_tab()
        self._build_skripte_tab()
        self._build_config_tab()

        self.root.bind("<F5>", lambda e: self._fish_start())
        self.root.bind("<F6>", lambda e: self._fish_pause())
        self.root.bind("<F7>", lambda e: self._fish_stop())

    # ---------- FISH-BOT ----------
    def _build_fish_tab(self):
        frame = self.tab_fish
        ttk.Label(frame, text="FISH-BOT", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(15, 5))
        ttk.Label(frame, text="Automatische Fischerkennung, Tracking & Fang",
                  foreground="#a6adc8").pack(anchor="w", padx=20)

        steuerung = ttk.Frame(frame)
        steuerung.pack(fill="x", padx=20, pady=15)

        self.btn_fish_start = ttk.Button(steuerung, text="Start (F5)",
                                        style="Success.TButton",
                                        command=self._fish_start)
        self.btn_fish_start.pack(side="left", padx=5)

        self.btn_fish_pause = ttk.Button(steuerung, text="Pause (F6)",
                                        style="Pause.TButton",
                                        command=self._fish_pause, state="disabled")
        self.btn_fish_pause.pack(side="left", padx=5)

        self.btn_fish_stop = ttk.Button(steuerung, text="Stop (F7)",
                                       style="Danger.TButton",
                                       command=self._fish_stop, state="disabled")
        self.btn_fish_stop.pack(side="left", padx=5)

        # Vor-Start Ablaeufe
        vorstart_frame = ttk.LabelFrame(frame, text="Vor-Start Ablaeufe (Vorbereitung)")
        vorstart_frame.pack(fill="x", padx=20, pady=5)

        self.var_vorstart_aktiv = tk.BooleanVar(value=False)
        self.chk_vorstart = ttk.Checkbutton(vorstart_frame, text="Ablauf(e) vor Fish-Bot-Start ausfuehren",
                                           variable=self.var_vorstart_aktiv,
                                           command=self._toggle_vorstart)
        self.chk_vorstart.grid(row=0, column=0, columnspan=3, padx=10, pady=5, sticky="w")

        ttk.Label(vorstart_frame, text="Ablauf 1:").grid(row=1, column=0, padx=10, pady=3, sticky="w")
        self.vorstart_combo1 = ttk.Combobox(vorstart_frame, state="disabled", width=30)
        self.vorstart_combo1.grid(row=1, column=1, padx=5, sticky="w")
        self.vorstart_combo1.set("(keiner)")

        ttk.Label(vorstart_frame, text="Ablauf 2:").grid(row=2, column=0, padx=10, pady=3, sticky="w")
        self.vorstart_combo2 = ttk.Combobox(vorstart_frame, state="disabled", width=30)
        self.vorstart_combo2.grid(row=2, column=1, padx=5, sticky="w")
        self.vorstart_combo2.set("(keiner)")

        ttk.Label(vorstart_frame, text="Ablauf 3:").grid(row=3, column=0, padx=10, pady=3, sticky="w")
        self.vorstart_combo3 = ttk.Combobox(vorstart_frame, state="disabled", width=30)
        self.vorstart_combo3.grid(row=3, column=1, padx=5, sticky="w")
        self.vorstart_combo3.set("(keiner)")

        self.btn_refresh_ablaeufe = ttk.Button(vorstart_frame, text="Aktualisieren",
                                              command=self._refresh_vorstart_ablaeufe)
        self.btn_refresh_ablaeufe.grid(row=1, column=2, rowspan=3, padx=10)

        self._refresh_vorstart_ablaeufe()

        # Aktive Sequenz (aus dem Sequenzen-Tab)
        seq_frame = ttk.LabelFrame(frame, text="Sequenz vor Automation")
        seq_frame.pack(fill="x", padx=20, pady=5)

        self.var_seq_vor_start = tk.BooleanVar(value=False)
        ttk.Checkbutton(seq_frame, text="Sequenz vor Fish-Bot-Start einmal ausfuehren",
                        variable=self.var_seq_vor_start,
                        command=self._toggle_seq_vor_start).grid(
            row=0, column=0, columnspan=3, padx=10, pady=5, sticky="w")

        ttk.Label(seq_frame, text="Aktive Sequenz:").grid(
            row=1, column=0, padx=10, pady=3, sticky="w")
        self.combo_aktive_sequenz = ttk.Combobox(seq_frame, state="disabled", width=30)
        self.combo_aktive_sequenz.grid(row=1, column=1, padx=5, sticky="w")
        self.combo_aktive_sequenz.set("(keine)")
        ttk.Button(seq_frame, text="Aktualisieren",
                   command=self._refresh_sequenz_combo).grid(row=1, column=2, padx=10)

        self._refresh_sequenz_combo()

        # Fenster
        fenster_frame = ttk.LabelFrame(frame, text="Ziel-Fenster")
        fenster_frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(fenster_frame, text="Fenster:").grid(row=0, column=0, padx=10, pady=5)
        self.fish_fenster = ttk.Entry(fenster_frame, width=20)
        self.fish_fenster.grid(row=0, column=1, padx=5)
        self.fish_fenster.insert(0, "Metin2")
        ttk.Label(fenster_frame, text="  (Hotkey: F5=Start, F6=Pause, F7=Stop)",
                  foreground="#a6adc8").grid(row=0, column=2, padx=10)

        # Erkennung
        erk_frame = ttk.LabelFrame(frame, text="Erkennung")
        erk_frame.pack(fill="x", padx=20, pady=5)

        ttk.Label(erk_frame, text="Empfindlichkeit:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.erk_empfind = ttk.Scale(erk_frame, from_=1, to=100, value=50)
        self.erk_empfind.grid(row=0, column=1, padx=5, sticky="w")
        self.lbl_empfind = ttk.Label(erk_frame, text="50")
        self.lbl_empfind.grid(row=0, column=2, padx=5)
        self.erk_empfind.configure(command=lambda v: self.lbl_empfind.config(text=str(int(float(v)))))

        ttk.Label(erk_frame, text="Erkennungsbereich X:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.erk_x = ttk.Entry(erk_frame, width=8)
        self.erk_x.grid(row=1, column=1, padx=5, sticky="w")
        self.erk_x.insert(0, "400")
        ttk.Label(erk_frame, text="Y:").grid(row=1, column=2, padx=5)
        self.erk_y = ttk.Entry(erk_frame, width=8)
        self.erk_y.grid(row=1, column=3, padx=5)
        self.erk_y.insert(0, "400")
        ttk.Label(erk_frame, text="Breite:").grid(row=1, column=4, padx=5)
        self.erk_w = ttk.Entry(erk_frame, width=8)
        self.erk_w.grid(row=1, column=5, padx=5)
        self.erk_w.insert(0, "200")
        ttk.Label(erk_frame, text="Hoehe:").grid(row=1, column=6, padx=5)
        self.erk_h = ttk.Entry(erk_frame, width=8)
        self.erk_h.grid(row=1, column=7, padx=5)
        self.erk_h.insert(0, "200")

        # Timing
        timing_frame = ttk.LabelFrame(frame, text="Timing")
        timing_frame.pack(fill="x", padx=20, pady=5)

        ttk.Label(timing_frame, text="Fang-Verzoegerung (ms):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.timing_fang = ttk.Entry(timing_frame, width=8)
        self.timing_fang.grid(row=0, column=1, padx=5)
        self.timing_fang.insert(0, "200")

        ttk.Label(timing_frame, text="Wurf-Intervall (s):").grid(row=0, column=2, padx=10)
        self.timing_wurf = ttk.Entry(timing_frame, width=8)
        self.timing_wurf.grid(row=0, column=3, padx=5)
        self.timing_wurf.insert(0, "5")

        ttk.Label(timing_frame, text="Max. Wartezeit (s):").grid(row=0, column=4, padx=10)
        self.timing_warten = ttk.Entry(timing_frame, width=8)
        self.timing_warten.grid(row=0, column=5, padx=5)
        self.timing_warten.insert(0, "30")

        # Statistik
        stat = ttk.LabelFrame(frame, text="Statistik")
        stat.pack(fill="x", padx=20, pady=5)

        self.lbl_fisch_count = ttk.Label(stat, text="Gefischt: 0")
        self.lbl_fisch_count.pack(side="left", padx=15, pady=10)
        self.lbl_klick_count = ttk.Label(stat, text="Klicks: 0")
        self.lbl_klick_count.pack(side="left", padx=15)
        self.lbl_fehl_count = ttk.Label(stat, text="Fehlversuche: 0")
        self.lbl_fehl_count.pack(side="left", padx=15)
        self.lbl_quote = ttk.Label(stat, text="Erfolgsrate: -")
        self.lbl_quote.pack(side="left", padx=15)
        self.lbl_laufzeit = ttk.Label(stat, text="Laufzeit: 00:00:00")
        self.lbl_laufzeit.pack(side="left", padx=15)

        # Log
        ttk.Label(frame, text="Log:").pack(anchor="w", padx=20, pady=(10, 2))
        self.fish_log = scrolledtext.ScrolledText(frame, height=6,
                                                 bg="#11111b", fg="#a6e3a1",
                                                 font=("Consolas", 9))
        self.fish_log.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.fish_log.insert("end", "Fish-Bot bereit. Druecke Start (F5).\n")

    def _refresh_vorstart_ablaeufe(self):
        ablaeufe = self._get_ablaeufe()
        for combo in [self.vorstart_combo1, self.vorstart_combo2, self.vorstart_combo3]:
            aktuell = combo.get()
            combo["values"] = ["(keiner)"] + ablaeufe
            if aktuell not in combo["values"]:
                combo.set("(keiner)")

    def _get_ablaeufe(self):
        result = []
        for f in os.listdir(BASE_DIR):
            if f.startswith("ablauf_") and f.endswith(".json"):
                result.append(f.replace("ablauf_", "").replace(".json", ""))
        return sorted(result)

    def _toggle_vorstart(self):
        state = "normal" if self.var_vorstart_aktiv.get() else "disabled"
        for combo in [self.vorstart_combo1, self.vorstart_combo2, self.vorstart_combo3]:
            combo.config(state=state)

    def _toggle_seq_vor_start(self):
        state = "readonly" if self.var_seq_vor_start.get() else "disabled"
        self.combo_aktive_sequenz.config(state=state)

    def _get_sequenz_namen(self):
        result = []
        for f in os.listdir(BASE_DIR):
            if f.startswith("sequenz_") and f.endswith(".json"):
                result.append(f.replace("sequenz_", "").replace(".json", ""))
        return sorted(result)

    def _refresh_sequenz_combo(self):
        namen = self._get_sequenz_namen()
        aktuell = self.combo_aktive_sequenz.get()
        self.combo_aktive_sequenz["values"] = ["(keine)"] + namen
        if aktuell not in self.combo_aktive_sequenz["values"]:
            self.combo_aktive_sequenz.set("(keine)")

    def _fish_start(self):
        if BotStatus.fishbot_laeuft:
            return
        # Optional: eine Sequenz vor dem eigentlichen Start ausfuehren
        if getattr(self, "var_seq_vor_start", None) and self.var_seq_vor_start.get():
            seq_name = self.combo_aktive_sequenz.get()
            if seq_name and seq_name != "(keine)":
                self.btn_fish_start.config(state="disabled")
                self._log_fish("Starte Sequenz vor Automation: %s" % seq_name)
                self._run_sequenz_vor_start(seq_name)
                return
        self._fish_start_nach_sequenz()

    def _fish_start_nach_sequenz(self):
        if self.var_vorstart_aktiv.get():
            self._log_fish("Starte Vorbereitung...")
            self.btn_fish_start.config(state="disabled")
            self._run_vorstart_ablaeufe()
        else:
            self._start_fishbot()

    def _run_sequenz_vor_start(self, seq_name):
        if not SEQ_OK:
            self._log_fish("Sequenz-Modul nicht verfuegbar - ueberspringe.")
            self._fish_start_nach_sequenz()
            return
        mgr = SequenzManager(
            BASE_DIR,
            log_callback=lambda m: self.root.after(0, lambda: self._log_fish(m)))
        seq = mgr.laden(seq_name)
        if not seq:
            self._log_fish("Sequenz nicht gefunden: %s" % seq_name)
            self._fish_start_nach_sequenz()
            return
        # Fuer die Vorbereitung nur ein Durchlauf
        seq.schleife_endlos = False
        seq.schleife_x = 1
        if not mgr.start(seq):
            self._fish_start_nach_sequenz()
            return

        def warte_auf_ende():
            t = mgr._thread
            if t:
                t.join()
            self.root.after(0, self._fish_start_nach_sequenz)

        threading.Thread(target=warte_auf_ende, daemon=True).start()

    def _run_vorstart_ablaeufe(self):
        def run_next(idx):
            combos = [self.vorstart_combo1, self.vorstart_combo2, self.vorstart_combo3]
            if idx >= len(combos):
                self._start_fishbot()
                return
            ablauf_name = combos[idx].get()
            if not ablauf_name or ablauf_name == "(keiner)":
                run_next(idx + 1)
                return
            ablauf_datei = "ablauf_%s.json" % ablauf_name
            self._log_fish("Fuehre Vorbereitung aus: %s" % ablauf_datei)
            self.root.after(500, lambda: self._spiele_ablauf(ablauf_datei, lambda: run_next(idx + 1)))
        run_next(0)

    def _spiele_ablauf(self, ablauf_name_or_datei, on_done):
        if ablauf_name_or_datei.startswith("ablauf_"):
            pfad = os.path.join(BASE_DIR, ablauf_name_or_datei)
            anzeige_name = ablauf_name_or_datei
        else:
            pfad = os.path.join(BASE_DIR, "ablauf_%s.json" % ablauf_name_or_datei)
            anzeige_name = "ablauf_%s.json" % ablauf_name_or_datei

        try:
            with open(pfad, "r", encoding="utf-8") as f:
                ablauf = json.load(f)
            events = ablauf if isinstance(ablauf, list) else ablauf.get("events", [])
            if not events:
                self._log_fish("Keine Events in %s" % anzeige_name)
                on_done()
                return
        except Exception as e:
            self._log_fish("FEHLER beim Laden von %s: %s" % (anzeige_name, e))
            on_done()
            return

        def run():
            try:
                import pyautogui
                # Fenster-relative Basis bestimmen
                base_x, base_y = 0, 0
                if (isinstance(ablauf, dict) and ablauf.get("fenster_relativ")
                        and isinstance(ablauf.get("fenster"), dict)):
                    finfo = ablauf["fenster"]
                    win = fenster_util.fenster_finden(finfo.get("titel")) if FENSTER_OK else None
                    if win:
                        base_x, base_y = win["x"], win["y"]
                        self._log_fish("Fenster '%s' gefunden @ %d,%d - Klicks fenster-relativ."
                                       % (finfo.get("titel"), base_x, base_y))
                    else:
                        base_x, base_y = finfo.get("x", 0), finfo.get("y", 0)
                        self._log_fish("Fenster '%s' nicht gefunden - nutze Aufnahme-Position %d,%d."
                                       % (finfo.get("titel"), base_x, base_y))
                for i, ev in enumerate(events):
                    typ = ev.get("typ") or ev.get("type")
                    x = base_x + ev.get("x", 0)
                    y = base_y + ev.get("y", 0)

                    # Pixel-Unschaerfe (Standard 3px)
                    pixel_unscharfe = ev.get("pixel_unscharfe", 3)
                    if pixel_unscharfe > 0:
                        x += random.randint(-pixel_unscharfe, pixel_unscharfe)
                        y += random.randint(-pixel_unscharfe, pixel_unscharfe)

                    if typ in ("move", "mousemove"):
                        pyautogui.moveTo(x, y)
                    elif typ in ("click", "klick"):
                        pyautogui.click(x, y)
                    elif typ in ("ldown", "mousedown"):
                        pyautogui.mouseDown(x, y)
                    elif typ in ("lup", "mouseup"):
                        pyautogui.mouseUp(x, y)
                    elif typ in ("key", "taste"):
                        pyautogui.press(ev.get("key", ""))

                    # Wartezeit bis naechstes Event (feste Zeit + Zufall)
                    if i < len(events) - 1:
                        feste_ms = ev.get("zeit_bis_naechster_ms", ev.get("delay", 1000))
                        zufall_ms = ev.get("zufall_ms", 0)
                        gesamt_ms = feste_ms + random.randint(0, zufall_ms)
                        if gesamt_ms > 0:
                            time.sleep(gesamt_ms / 1000.0)

                self._log_fish("Ablauf abgeschlossen: %s" % anzeige_name)
            except ImportError:
                self._log_fish("pyautogui nicht installiert!")
            except Exception as e:
                self._log_fish("FEHLER beim Abspielen: %s" % e)
            self.root.after(0, on_done)

        threading.Thread(target=run, daemon=True).start()

    def _start_fishbot(self):
        BotStatus.fishbot_laeuft = True
        BotStatus.fishbot_pausiert = False
        BotStatus.startzeit = time.time()
        BotStatus.pausen_gesamt = 0.0
        self.btn_fish_start.config(state="disabled")
        self.btn_fish_pause.config(state="normal", text="Pause (F6)")
        self.btn_fish_stop.config(state="normal")
        self._log_fish("Fish-Bot gestartet!")

    def _fish_pause(self):
        if not BotStatus.fishbot_laeuft:
            return
        if BotStatus.fishbot_pausiert:
            BotStatus.fishbot_pausiert = False
            BotStatus.pausen_gesamt += time.time() - BotStatus.pausen_start
            self.btn_fish_pause.config(text="Pause (F6)")
            self._log_fish("Fish-Bot fortgesetzt.")
        else:
            BotStatus.fishbot_pausiert = True
            BotStatus.pausen_start = time.time()
            self.btn_fish_pause.config(text="Weiter (F6)")
            self._log_fish("Fish-Bot pausiert.")

    def _fish_stop(self):
        BotStatus.fishbot_laeuft = False
        BotStatus.fishbot_pausiert = False
        self.btn_fish_start.config(state="normal")
        self.btn_fish_pause.config(state="disabled", text="Pause (F6)")
        self.btn_fish_stop.config(state="disabled")
        self._log_fish("Fish-Bot gestoppt.")

    def _log_fish(self, msg):
        self.fish_log.insert("end", "[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
        self.fish_log.see("end")

    # ---------- AUFZEICHNUNG / TRIGGER ----------
    def _build_aufnahme_tab(self):
        frame = self.tab_aufnahme
        ttk.Label(frame, text="AUFZEICHNUNG & MULTI-PIXEL-TRIGGER", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(15, 5))
        ttk.Label(frame, text="Ablaeufe aufnehmen & bearbeiten | Pixel-Trigger automatisch starten",
                  foreground="#a6adc8").pack(anchor="w", padx=20)

        # Aufnahme-Steuerung
        steuerung = ttk.LabelFrame(frame, text="Ablauf-Aufnahme & Verwaltung")
        steuerung.pack(fill="x", padx=20, pady=10)

        btn_rec_frame = ttk.Frame(steuerung)
        btn_rec_frame.pack(fill="x", padx=10, pady=5)

        self.btn_fenster_erfassen = ttk.Button(btn_rec_frame, text="1. Fenster erfassen",
                                               command=self._fenster_erfassen)
        self.btn_fenster_erfassen.pack(side="left", padx=5)

        self.btn_rec_start = ttk.Button(btn_rec_frame, text="2. Aufnehmen",
                                        style="Danger.TButton",
                                        command=self._rec_start)
        self.btn_rec_start.pack(side="left", padx=5)

        self.btn_rec_stop = ttk.Button(btn_rec_frame, text="3. Stopp & Speichern",
                                       style="Success.TButton",
                                       command=self._rec_stop, state="disabled")
        self.btn_rec_stop.pack(side="left", padx=5)

        ttk.Label(btn_rec_frame, text="Fenster-Titel:").pack(side="left", padx=(20, 3))
        self.trig_fenster = ttk.Entry(btn_rec_frame, width=14)
        self.trig_fenster.pack(side="left")
        self.trig_fenster.insert(0, "Metin2")

        self.lbl_rec_status = ttk.Label(btn_rec_frame, text="Bereit", foreground="#a6adc8")
        self.lbl_rec_status.pack(side="right", padx=15)

        # Anzeige des erfassten Fensters
        self.lbl_fenster = ttk.Label(steuerung,
                                     text="Kein Fenster erfasst - Klicks werden absolut gespeichert.",
                                     foreground="#a6adc8")
        self.lbl_fenster.pack(anchor="w", padx=12, pady=(0, 4))

        # Ablauf-Liste mit Buttons
        list_frame = ttk.Frame(steuerung)
        list_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        list_left = ttk.Frame(list_frame)
        list_left.pack(side="left", fill="both", expand=True)

        ttk.Label(list_left, text="Gespeicherte Ablaeufe:", foreground="#89b4fa").pack(anchor="w")

        ablauf_container = ttk.Frame(list_left)
        ablauf_container.pack(fill="both", expand=True)

        self.ablauf_liste = tk.Listbox(ablauf_container, bg="#11111b", fg="#cdd6f4",
                                       selectbackground="#89b4fa",
                                       selectforeground="#11111b",
                                       font=("Consolas", 10), height=6)
        self.ablauf_liste.pack(side="left", fill="both", expand=True)
        scroll_a = ttk.Scrollbar(ablauf_container, orient="vertical", command=self.ablauf_liste.yview)
        scroll_a.pack(side="right", fill="y")
        self.ablauf_liste.config(yscrollcommand=scroll_a.set)

        list_right = ttk.Frame(list_frame)
        list_right.pack(side="left", fill="y", padx=(10, 0))

        btn_w = 20
        ttk.Button(list_right, text="Bearbeiten (Editor)", width=btn_w,
                   command=self._ablauf_bearbeiten).pack(pady=3)
        ttk.Button(list_right, text="Abspielen (mit Unschaerfe)", width=btn_w,
                   style="Success.TButton",
                   command=self._play).pack(pady=3)
        ttk.Button(list_right, text="Details ansehen", width=btn_w,
                   command=self._ablauf_details).pack(pady=3)
        ttk.Button(list_right, text="Ablauf loeschen", width=btn_w,
                   style="Danger.TButton",
                   command=self._ablauf_loeschen).pack(pady=3)
        ttk.Button(list_right, text="Aktualisieren", width=btn_w,
                   command=self._refresh_ablaeufe).pack(pady=3)

        # Detailansicht
        detail_frame = ttk.LabelFrame(frame, text="Event-Detailansicht")
        detail_frame.pack(fill="both", expand=True, padx=20, pady=10)

        kopf = ttk.Frame(detail_frame)
        kopf.pack(fill="x", padx=10, pady=(5, 0))
        spalten = ["#", "Typ", "X", "Y", "Wartezeit(ms)", "Zufall(ms)", "Unschaerfe(px)", "Taste"]
        breiten = [4, 10, 8, 8, 14, 14, 16, 10]
        for sp, br in zip(spalten, breiten):
            ttk.Label(kopf, text=sp, width=br, foreground="#89b4fa",
                     font=("Consolas", 9, "bold")).pack(side="left")

        detail_container = ttk.Frame(detail_frame)
        detail_container.pack(fill="both", expand=True)
        self.detail_liste = tk.Listbox(detail_container, bg="#11111b", fg="#cdd6f4",
                                       selectbackground="#89b4fa",
                                       selectforeground="#11111b",
                                       font=("Consolas", 9), height=5)
        self.detail_liste.pack(side="left", fill="both", expand=True)
        scroll_d = ttk.Scrollbar(detail_container, orient="vertical", command=self.detail_liste.yview)
        scroll_d.pack(side="right", fill="y")
        self.detail_liste.config(yscrollcommand=scroll_d.set)

        # Pixel-Aufzeichnung
        pixel_frame = ttk.LabelFrame(frame, text="Pixel-Aufzeichnung (Multi-Pixel-Trigger)")
        pixel_frame.pack(fill="x", padx=20, pady=10)

        ttk.Label(pixel_frame,
                  text="1. 'Pixel aufzeichnen' druecken  2. Auf Spiel klicken (jeder Klick = ein Pixel)  3. 'Pixel-Aufnahme beenden' und Namen eingeben",
                  foreground="#f9e2af").pack(anchor="w", padx=10, pady=(5, 0))

        btn_frame = ttk.Frame(pixel_frame)
        btn_frame.pack(fill="x", padx=10, pady=5)

        self.btn_pixel_start = ttk.Button(btn_frame, text="Pixel aufzeichnen",
                                          style="Success.TButton",
                                          command=self._pixel_aufnahme_start)
        self.btn_pixel_start.pack(side="left", padx=5)

        self.btn_pixel_stop = ttk.Button(btn_frame, text="Pixel-Aufnahme beenden",
                                         style="Danger.TButton",
                                         command=self._pixel_aufnahme_stop, state="disabled")
        self.btn_pixel_stop.pack(side="left", padx=5)

        self.btn_pixel_leeren = ttk.Button(btn_frame, text="Aktuelle Pixel leeren",
                                           command=self._pixel_leeren)
        self.btn_pixel_leeren.pack(side="left", padx=5)

        self.lbl_pixel_status = ttk.Label(btn_frame, text="Pixel: 0", foreground="#a6adc8")
        self.lbl_pixel_status.pack(side="right", padx=15)

        pixel_bottom = ttk.Frame(pixel_frame)
        pixel_bottom.pack(fill="x", padx=10, pady=(0, 10))

        pixel_list_container = ttk.Frame(pixel_bottom)
        pixel_list_container.pack(side="left", fill="both", expand=True)

        ttk.Label(pixel_list_container, text="Aktive Pixel:", foreground="#89b4fa",
                  font=("Consolas", 9)).pack(anchor="w")

        pixel_list_inner = ttk.Frame(pixel_list_container)
        pixel_list_inner.pack(fill="both", expand=True)

        self.pixel_liste = tk.Listbox(pixel_list_inner, bg="#11111b", fg="#cdd6f4",
                                      selectbackground="#89b4fa",
                                      selectforeground="#11111b",
                                      font=("Consolas", 9), height=3)
        self.pixel_liste.pack(side="left", fill="both", expand=True)
        scroll_p = ttk.Scrollbar(pixel_list_inner, orient="vertical", command=self.pixel_liste.yview)
        scroll_p.pack(side="right", fill="y")
        self.pixel_liste.config(yscrollcommand=scroll_p.set)

        # Trigger rechts
        trig_right = ttk.Frame(pixel_bottom)
        trig_right.pack(side="left", fill="y", padx=(15, 0))

        trig_row1 = ttk.Frame(trig_right)
        trig_row1.pack(fill="x")
        ttk.Label(trig_row1, text="Toleranz:").pack(side="left")
        self.trig_toleranz_spin = ttk.Spinbox(trig_row1, from_=0, to=50, width=5)
        self.trig_toleranz_spin.pack(side="left", padx=(3, 10))
        self.trig_toleranz_spin.set(10)

        ttk.Label(trig_row1, text="Intervall(ms):").pack(side="left")
        self.trig_intervall_spin = ttk.Spinbox(trig_row1, from_=100, to=10000, increment=100, width=6)
        self.trig_intervall_spin.pack(side="left", padx=(3, 10))
        self.trig_intervall_spin.set(500)

        trig_row2 = ttk.Frame(trig_right)
        trig_row2.pack(fill="x", pady=5)

        ttk.Label(trig_row2, text="Ablauf:").pack(side="left")
        self.trig_ablauf_combo = ttk.Combobox(trig_row2, width=20)
        self.trig_ablauf_combo.pack(side="left", padx=5)

        trig_row3 = ttk.Frame(trig_right)
        trig_row3.pack(fill="x")

        self.btn_trig_start = ttk.Button(trig_row3, text="Trigger starten",
                                        style="Success.TButton",
                                        command=self._trigger_start)
        self.btn_trig_start.pack(side="left", padx=3)
        self.btn_trig_stop = ttk.Button(trig_row3, text="Stop",
                                       style="Danger.TButton",
                                       command=self._trigger_stop, state="disabled")
        self.btn_trig_stop.pack(side="left", padx=3)

        # Gespeicherte Trigger
        gesp_frame = ttk.LabelFrame(frame, text="Gespeicherte Pixel-Trigger")
        gesp_frame.pack(fill="x", padx=20, pady=5)

        gesp_list_frame = ttk.Frame(gesp_frame)
        gesp_list_frame.pack(fill="x", padx=10, pady=5)
        self.trigger_liste = tk.Listbox(gesp_list_frame, bg="#11111b", fg="#cdd6f4",
                                       selectbackground="#89b4fa",
                                       selectforeground="#11111b",
                                       font=("Consolas", 10), height=2)
        self.trigger_liste.pack(side="left", fill="both", expand=True)
        scroll_t = ttk.Scrollbar(gesp_list_frame, orient="vertical", command=self.trigger_liste.yview)
        scroll_t.pack(side="right", fill="y")
        self.trigger_liste.config(yscrollcommand=scroll_t.set)

        gesp_btn_frame = ttk.Frame(gesp_frame)
        gesp_btn_frame.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Button(gesp_btn_frame, text="Trigger laden", command=self._trigger_laden).pack(side="left", padx=5)
        ttk.Button(gesp_btn_frame, text="Trigger loeschen", command=self._trigger_loeschen).pack(side="left", padx=5)

        self._refresh_trigger_liste()
        self._refresh_trig_ablaeufe()

    # --- Ablauf-Verwaltung ---
    def _ablauf_bearbeiten(self):
        sel = self.ablauf_liste.curselection()
        if not sel:
            messagebox.showwarning("Hinweis", "Bitte einen Ablauf auswaehlen!")
            return
        ablauf_name = self.ablauf_liste.get(sel[0])
        datei = os.path.join(BASE_DIR, "ablauf_%s.json" % ablauf_name)
        try:
            with open(datei, "r", encoding="utf-8") as f:
                data = json.load(f)
            events = data if isinstance(data, list) else data.get("events", [])
            editor = AblaufEditor(self.root, ablauf_name, events,
                                 lambda: self._refresh_ablaeufe())
            editor.grab_set()
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte Ablauf nicht laden: %s" % e)

    def _ablauf_details(self):
        sel = self.ablauf_liste.curselection()
        if not sel:
            messagebox.showwarning("Hinweis", "Bitte einen Ablauf auswaehlen!")
            return
        ablauf_name = self.ablauf_liste.get(sel[0])
        datei = os.path.join(BASE_DIR, "ablauf_%s.json" % ablauf_name)
        try:
            with open(datei, "r", encoding="utf-8") as f:
                data = json.load(f)
            events = data if isinstance(data, list) else data.get("events", [])
            self.detail_liste.delete(0, "end")
            for i, ev in enumerate(events, 1):
                typ = ev.get("typ", "click")
                x = ev.get("x", 0)
                y = ev.get("y", 0)
                wartezeit = ev.get("zeit_bis_naechster_ms", ev.get("delay", 0))
                zufall = ev.get("zufall_ms", 0)
                pu = ev.get("pixel_unscharfe", 3)
                taste = ev.get("key", "-")
                self.detail_liste.insert("end", "%-4d %-10s %-8d %-8d %-14d %-14d %-16d %s" %
                                       (i, typ, x, y, wartezeit, zufall, pu, taste))
            self._log_fish("Details geladen: %s (%d Events)" % (ablauf_name, len(events)))
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte Details nicht laden: %s" % e)

    def _ablauf_loeschen(self):
        sel = self.ablauf_liste.curselection()
        if not sel:
            messagebox.showwarning("Hinweis", "Bitte einen Ablauf auswaehlen!")
            return
        ablauf_name = self.ablauf_liste.get(sel[0])
        datei = os.path.join(BASE_DIR, "ablauf_%s.json" % ablauf_name)
        if messagebox.askyesno("Loeschen", "Ablauf '%s' wirklich loeschen?" % ablauf_name):
            try:
                os.remove(datei)
                self._refresh_ablaeufe()
                self._refresh_vorstart_ablaeufe()
                self.detail_liste.delete(0, "end")
                self._log_fish("Ablauf geloescht: %s" % ablauf_name)
            except Exception as e:
                messagebox.showerror("Fehler", "Konnte nicht loeschen: %s" % e)

    # --- Fenster erfassen (fuer fenster-relative Aufnahme) ---
    def _fenster_erfassen(self):
        if not FENSTER_OK:
            messagebox.showinfo("Hinweis",
                                "Fenster-Erkennung ist nur unter Windows verfuegbar.\n"
                                "Ohne sie werden Klicks absolut gespeichert.")
            return
        try:
            from pynput import mouse
        except ImportError:
            messagebox.showerror("Fehler", "pynput ist nicht installiert (pip install pynput).")
            return
        self.lbl_rec_status.config(text="Klicke jetzt in das ZIELFENSTER...", foreground="#f9e2af")
        self._log_fish("Fenster erfassen: bitte einmal ins Zielfenster klicken.")

        def on_click(x, y, button, pressed):
            if pressed and getattr(button, "name", "") == "left":
                info = fenster_util.fenster_unter_cursor()
                self.root.after(0, lambda: self._fenster_erfasst(info))
                return False  # Listener nach erstem Klick beenden

        self._erfass_listener = mouse.Listener(on_click=on_click)
        self._erfass_listener.start()

    def _fenster_erfasst(self, info):
        self._erfass_listener = None
        if not info or not info.get("w"):
            self.lbl_rec_status.config(text="Kein Fenster erkannt", foreground="#f38ba8")
            self._log_fish("Kein Fenster erkannt - bitte erneut versuchen.")
            return
        self.erfasstes_fenster = info
        titel = info.get("titel") or "(ohne Titel)"
        # Stabilen Such-Titel vorschlagen. Bei VirtualBox wechselt der volle
        # Titel ("<VM> [wird ausgefuehrt] - Oracle VirtualBox") -> nur VM-Name.
        such = titel
        if "VirtualBox" in titel:
            such = titel.split(" [")[0].split(" - ")[0].strip() or titel
        self.trig_fenster.delete(0, "end")
        self.trig_fenster.insert(0, such[:40])
        hinweis = "  (Titel wird zum Wiederfinden genutzt - Feld anpassbar)"
        self.lbl_fenster.config(
            text="Erfasst: '%s'  [%dx%d @ %d,%d]%s"
            % (titel[:28], info["w"], info["h"], info["x"], info["y"], hinweis),
            foreground="#a6e3a1")
        self.lbl_rec_status.config(text="Fenster erfasst - jetzt '2. Aufnehmen'", foreground="#a6e3a1")
        self._log_fish("Fenster erfasst: '%s' (%dx%d @ %d,%d)"
                       % (titel, info["w"], info["h"], info["x"], info["y"]))

    # --- Aufnahme (global, ueber pynput) ---
    def _rec_start(self):
        if BotStatus.aufnahme_laeuft:
            return
        try:
            from pynput import mouse
        except ImportError:
            messagebox.showerror("Fehler", "pynput ist nicht installiert (pip install pynput).")
            return
        # Zielfenster-Position frisch holen (Fenster koennte verschoben sein)
        if self.erfasstes_fenster and FENSTER_OK:
            such = self.trig_fenster.get().strip()
            neu = fenster_util.fenster_finden(such) if such else None
            if neu:
                self.erfasstes_fenster = {"titel": such,
                                          "x": neu["x"], "y": neu["y"],
                                          "w": neu["w"], "h": neu["h"]}
                self._log_fish("Zielfenster '%s' aktualisiert @ %d,%d (%dx%d)"
                               % (such, neu["x"], neu["y"], neu["w"], neu["h"]))
            else:
                self._log_fish("Zielfenster '%s' nicht gefunden - nutze erfasste Position." % such)
        BotStatus.aufnahme_laeuft = True
        self.aufnahme_events = []
        self.aufnahme_letzter_zeit = time.time()
        self.btn_rec_start.config(state="disabled")
        self.btn_rec_stop.config(state="normal")
        self.btn_fenster_erfassen.config(state="disabled")
        if self.erfasstes_fenster:
            self.lbl_rec_status.config(
                text="AUFNAHME... Klicke im Fenster '%s'!" % (self.erfasstes_fenster.get("titel") or "?")[:20],
                foreground="#f38ba8")
        else:
            self.lbl_rec_status.config(text="AUFNAHME (absolut)... Klicke ins Spiel!",
                                       foreground="#f38ba8")
        self.detail_liste.delete(0, "end")
        self._log_fish("Aufnahme gestartet - klicke die Aktionen aus.")
        self._rec_listener = mouse.Listener(on_click=self._on_global_click)
        self._rec_listener.start()

    def _on_global_click(self, x, y, button, pressed):
        # laeuft im pynput-Thread -> nur Daten sammeln, GUI via after()
        if not BotStatus.aufnahme_laeuft or not pressed:
            return
        if getattr(button, "name", "") != "left":
            return
        win = self.erfasstes_fenster
        if win:
            # nur Klicks INNERHALB des Zielfensters aufnehmen
            if not (win["x"] <= x < win["x"] + win["w"] and
                    win["y"] <= y < win["y"] + win["h"]):
                return
            rx, ry = x - win["x"], y - win["y"]
        else:
            rx, ry = x, y
        self.root.after(0, lambda: self._rec_add_click(rx, ry, x, y))

    def _rec_add_click(self, rx, ry, absx, absy):
        if not BotStatus.aufnahme_laeuft:
            return
        jetzt = time.time()
        zeit_abstand = int((jetzt - self.aufnahme_letzter_zeit) * 1000) if self.aufnahme_letzter_zeit else 0
        self.aufnahme_letzter_zeit = jetzt
        ev = {"typ": "click", "x": rx, "y": ry,
              "zeit_bis_naechster_ms": zeit_abstand, "zufall_ms": 0,
              "pixel_unscharfe": 3}
        self.aufnahme_events.append(ev)
        n = len(self.aufnahme_events)
        self.detail_liste.insert("end", "%-4d %-10s %-8d %-8d %-14d %-14d %-16d %s" %
                               (n, "click", rx, ry, zeit_abstand, 0, 3, "-"))
        if self.erfasstes_fenster:
            self._log_fish("Klick %d: fenster-rel (%d, %d) [abs %d,%d] Warte: %dms"
                           % (n, rx, ry, absx, absy, zeit_abstand))
        else:
            self._log_fish("Klick %d: (%d, %d) Warte: %dms" % (n, rx, ry, zeit_abstand))

    def _rec_stop(self):
        if not BotStatus.aufnahme_laeuft:
            return
        BotStatus.aufnahme_laeuft = False
        if self._rec_listener:
            try:
                self._rec_listener.stop()
            except Exception:
                pass
            self._rec_listener = None
        self.btn_rec_start.config(state="normal")
        self.btn_rec_stop.config(state="disabled")
        self.btn_fenster_erfassen.config(state="normal")
        self.lbl_rec_status.config(text="Bereit", foreground="#a6adc8")

        if not self.aufnahme_events:
            self._log_fish("Keine Events aufgenommen.")
            return

        name = simpledialog.askstring("Ablauf speichern",
                                      "Name fuer den Ablauf (z.B. 'wuermer_kaufen'):",
                                      parent=self.root)
        if not name:
            self._log_fish("Speichern abgebrochen.")
            return

        name = name.strip().replace(" ", "_")
        if self.erfasstes_fenster:
            win = self.erfasstes_fenster
            such_titel = self.trig_fenster.get().strip() or win.get("titel", "")
            data = {"name": name,
                    "fenster": {"titel": such_titel,
                                "x": win["x"], "y": win["y"],
                                "w": win["w"], "h": win["h"]},
                    "fenster_relativ": True,
                    "erstellt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "events": self.aufnahme_events}
        else:
            fenster = self.trig_fenster.get().strip() or "Metin2"
            data = {"name": name, "fenster": fenster,
                    "fenster_relativ": False,
                    "erstellt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "events": self.aufnahme_events}
        datei = os.path.join(BASE_DIR, "ablauf_%s.json" % name)
        try:
            with open(datei, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log_fish("Gespeichert: %s (%d Events)" % (datei, len(self.aufnahme_events)))
            messagebox.showinfo("Gespeichert", "Ablauf '%s' mit %d Events gespeichert!" %
                               (name, len(self.aufnahme_events)))
            self._refresh_ablaeufe()
            self._refresh_vorstart_ablaeufe()
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte nicht speichern: %s" % e)

    def _play(self):
        sel = self.ablauf_liste.curselection()
        if not sel:
            messagebox.showwarning("Hinweis", "Bitte einen Ablauf auswaehlen!")
            return
        ablauf_name = self.ablauf_liste.get(sel[0])
        datei = "ablauf_%s.json" % ablauf_name
        self._log_fish("Spiele ab: %s" % datei)
        self._spiele_ablauf(datei, lambda: self._log_fish("Fertig: %s" % datei))

    # --- Pixel-Aufnahme ---
    def _pixel_aufnahme_start(self):
        try:
            import pyautogui
        except ImportError:
            messagebox.showwarning("pyautogui", "pyautogui nicht installiert!\nBitte: pip install pyautogui")
            return
        self.pixel_aufnahme_aktiv = True
        self.pixel_aufnahme_punkte = []
        self.btn_pixel_start.config(state="disabled")
        self.btn_pixel_stop.config(state="normal")
        self.pixel_liste.delete(0, "end")
        self.lbl_pixel_status.config(text="Pixel: 0 - Klicke auf das Spiel!", foreground="#f9e2af")
        self._log_fish("Pixel-Aufnahme AKTIV - Klicke auf die Pixel im Spiel...")
        self.root.bind("<Button-1>", self._pixel_klick, add="+")

    def _pixel_klick(self, event):
        if not self.pixel_aufnahme_aktiv:
            return
        try:
            import pyautogui
            x, y = pyautogui.position()
            farbe = pyautogui.pixel(x, y)
            hex_farbe = "#%02x%02x%02x" % farbe
            self.pixel_aufnahme_punkte.append({"x": x, "y": y, "farbe": hex_farbe})
            n = len(self.pixel_aufnahme_punkte)
            self.pixel_liste.insert("end", "Pixel %d: X=%d Y=%d Farbe=%s" % (n, x, y, hex_farbe))
            self.lbl_pixel_status.config(text="Pixel: %d" % n, foreground="#a6e3a1")
            self._log_fish("Pixel %d: (%d,%d) = %s" % (n, x, y, hex_farbe))
        except Exception as e:
            self._log_fish("Fehler: %s" % e)

    def _pixel_aufnahme_stop(self):
        if not self.pixel_aufnahme_aktiv:
            return
        self.pixel_aufnahme_aktiv = False
        self.root.unbind("<Button-1>")
        if not self.pixel_aufnahme_punkte:
            self.btn_pixel_start.config(state="normal")
            self.btn_pixel_stop.config(state="disabled")
            self.lbl_pixel_status.config(text="Pixel: 0", foreground="#a6adc8")
            return

        name = simpledialog.askstring("Trigger speichern",
                                      "Name fuer den Pixel-Trigger (z.B. 'haendler'):",
                                      parent=self.root)
        if not name:
            self.btn_pixel_start.config(state="normal")
            self.btn_pixel_stop.config(state="disabled")
            return

        name = name.strip().replace(" ", "_")
        fenster = self.trig_fenster.get().strip() or "Metin2"
        data = {"name": name, "fenster": fenster, "pixel": self.pixel_aufnahme_punkte}
        datei = os.path.join(BASE_DIR, "trigger_%s.json" % name)
        try:
            with open(datei, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._log_fish("Trigger gespeichert: %s (%d Pixel)" % (datei, len(self.pixel_aufnahme_punkte)))
            messagebox.showinfo("Gespeichert", "Trigger '%s' mit %d Pixeln gespeichert!" %
                               (name, len(self.pixel_aufnahme_punkte)))
            self._refresh_trigger_liste()
        except Exception as e:
            messagebox.showerror("Fehler", "Konnte nicht speichern: %s" % e)

        self.btn_pixel_start.config(state="normal")
        self.btn_pixel_stop.config(state="disabled")
        self.lbl_pixel_status.config(text="Pixel: 0", foreground="#a6adc8")

    def _pixel_leeren(self):
        self.pixel_aufnahme_punkte = []
        self.pixel_liste.delete(0, "end")
        self.lbl_pixel_status.config(text="Pixel: 0", foreground="#a6adc8")

    # --- Trigger ---
    def _get_trigger_dateien(self):
        return sorted([f for f in os.listdir(BASE_DIR) if f.startswith("trigger_") and f.endswith(".json")])

    def _refresh_trigger_liste(self):
        self.trigger_liste.delete(0, "end")
        for f in self._get_trigger_dateien():
            self.trigger_liste.insert("end", f)

    def _trigger_laden(self):
        sel = self.trigger_liste.curselection()
        if not sel:
            return
        pfad = os.path.join(BASE_DIR, self.trigger_liste.get(sel[0]))
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.pixel_aufnahme_punkte = data.get("pixel", [])
            self.pixel_liste.delete(0, "end")
            for i, p in enumerate(self.pixel_aufnahme_punkte, 1):
                self.pixel_liste.insert("end", "Pixel %d: X=%d Y=%d Farbe=%s" % (i, p["x"], p["y"], p["farbe"]))
            self.lbl_pixel_status.config(text="Pixel: %d (geladen)" % len(self.pixel_aufnahme_punkte), foreground="#a6e3a1")
            self.trig_fenster.delete(0, "end")
            self.trig_fenster.insert(0, data.get("fenster", "Metin2"))
            self._log_fish("Trigger geladen: %s (%d Pixel)" % (self.trigger_liste.get(sel[0]), len(self.pixel_aufnahme_punkte)))
        except Exception as e:
            messagebox.showerror("Fehler", "%s" % e)

    def _trigger_loeschen(self):
        sel = self.trigger_liste.curselection()
        if not sel:
            return
        datei = self.trigger_liste.get(sel[0])
        if messagebox.askyesno("Loeschen", "Trigger '%s' loeschen?" % datei):
            try:
                os.remove(os.path.join(BASE_DIR, datei))
                self._refresh_trigger_liste()
                self._log_fish("Trigger geloescht: %s" % datei)
            except Exception as e:
                messagebox.showerror("Fehler", "%s" % e)

    def _get_aktive_pixel(self):
        pixel = []
        for p in self.pixel_aufnahme_punkte:
            h = p["farbe"]
            pixel.append((p["x"], p["y"], (int(h[1:3],16), int(h[3:5],16), int(h[5:7],16))))
        return pixel

    def _alle_pixel_passen(self):
        try:
            import pyautogui
        except ImportError:
            return False
        pixel = self._get_aktive_pixel()
        if not pixel:
            return False
        toleranz = int(self.trig_toleranz_spin.get())
        for x, y, (r2,g2,b2) in pixel:
            try:
                r1,g1,b1 = pyautogui.pixel(x,y)
            except:
                return False
            if abs(r1-r2)>toleranz or abs(g1-g2)>toleranz or abs(b1-b2)>toleranz:
                return False
        return True

    def _trigger_start(self):
        if not self._get_aktive_pixel():
            messagebox.showwarning("Hinweis", "Keine Pixel geladen!")
            return
        if not self.trig_ablauf_combo.get():
            messagebox.showwarning("Hinweis", "Bitte Ablauf waehlen!")
            return
        self.btn_trig_start.config(state="disabled")
        self.btn_trig_stop.config(state="normal")
        self._log_fish("Trigger gestartet - pruefe Pixel alle %sms..." % self.trig_intervall_spin.get())
        self._trigger_loop()

    def _trigger_loop(self):
        if self._alle_pixel_passen():
            ablauf_name = self.trig_ablauf_combo.get()
            if ablauf_name:
                datei = "ablauf_%s.json" % ablauf_name
                self._log_fish("ALLE Pixel passen! Starte: %s" % datei)
                self._spiele_ablauf(datei, lambda: None)
            else:
                self._log_fish("Pixel passen, aber kein Ablauf gewaehlt!")
        intervall = int(self.trig_intervall_spin.get())
        self.trigger_job = self.root.after(intervall, self._trigger_loop)

    def _trigger_stop(self):
        if self.trigger_job:
            self.root.after_cancel(self.trigger_job)
            self.trigger_job = None
        self.btn_trig_start.config(state="normal")
        self.btn_trig_stop.config(state="disabled")
        self._log_fish("Trigger gestoppt.")

    def _refresh_trig_ablaeufe(self):
        ablaeufe = self._get_ablaeufe()
        aktuell = self.trig_ablauf_combo.get()
        self.trig_ablauf_combo["values"] = ablaeufe
        if aktuell not in ablaeufe and ablaeufe:
            self.trig_ablauf_combo.set(ablaeufe[0])

    def _refresh_ablaeufe(self):
        self.ablauf_liste.delete(0, "end")
        for name in self._get_ablaeufe():
            self.ablauf_liste.insert("end", name)
        self._refresh_trig_ablaeufe()
        self._refresh_vorstart_ablaeufe()

    # ---------- SKRIPTE ----------
    def _build_skripte_tab(self):
        frame = self.tab_skripte
        ttk.Label(frame, text="SKRIPTE", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(15, 5))
        ttk.Label(frame, text="Eigene Python-Skripte starten & verwalten",
                  foreground="#a6adc8").pack(anchor="w", padx=20)

        steuerung = ttk.Frame(frame)
        steuerung.pack(fill="x", padx=20, pady=15)

        self.btn_open_ordner = ttk.Button(steuerung, text="Ordner oeffnen",
                                         command=self._open_ordner)
        self.btn_open_ordner.pack(side="left", padx=5)
        self.btn_skript_start = ttk.Button(steuerung, text="Skript starten",
                                          style="Success.TButton",
                                          command=self._skript_start)
        self.btn_skript_start.pack(side="left", padx=5)
        self.btn_skript_stop = ttk.Button(steuerung, text="Stopp",
                                         style="Danger.TButton",
                                         command=self._skript_stop, state="disabled")
        self.btn_skript_stop.pack(side="left", padx=5)

        ttk.Label(frame, text="Python-Dateien:").pack(anchor="w", padx=20, pady=(10, 2))
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.skript_liste = tk.Listbox(list_frame, bg="#11111b", fg="#cdd6f4",
                                      selectbackground="#89b4fa",
                                      selectforeground="#11111b",
                                      font=("Consolas", 10))
        self.skript_liste.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, orient="vertical",
                              command=self.skript_liste.yview)
        scroll.pack(side="right", fill="y")
        self.skript_liste.config(yscrollcommand=scroll.set)
        self._refresh_skripte()

    def _refresh_skripte(self):
        self.skript_liste.delete(0, "end")
        for f in sorted(os.listdir(BASE_DIR)):
            if f.endswith(".py") and f != "command_center.py":
                self.skript_liste.insert("end", f)

    def _open_ordner(self):
        os.startfile(BASE_DIR)

    def _skript_start(self):
        sel = self.skript_liste.curselection()
        if not sel:
            messagebox.showwarning("Hinweis", "Bitte ein Skript auswaehlen!")
            return
        skript = self.skript_liste.get(sel[0])
        pfad = os.path.join(BASE_DIR, skript)
        self.skript_prozess = subprocess.Popen([sys.executable, pfad], cwd=BASE_DIR)
        self.btn_skript_start.config(state="disabled")
        self.btn_skript_stop.config(state="normal")

    def _skript_stop(self):
        if hasattr(self, 'skript_prozess') and self.skript_prozess:
            self.skript_prozess.terminate()
        self.btn_skript_start.config(state="normal")
        self.btn_skript_stop.config(state="disabled")

    # ---------- CONFIG / ARDUINO ----------
    def _build_config_tab(self):
        frame = self.tab_config
        ttk.Label(frame, text="CONFIG / ARDUINO", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(15, 5))

        ard = ttk.LabelFrame(frame, text="Arduino-HID")
        ard.pack(fill="x", padx=20, pady=10)

        ttk.Label(ard, text="COM-Port:").grid(row=0, column=0, padx=10, pady=8)
        self.com_port = ttk.Combobox(ard, values=["COM3","COM4","COM5","COM6"], width=10)
        self.com_port.grid(row=0, column=1, padx=5)
        self.com_port.set("COM6")

        ttk.Button(ard, text="Verbinden", command=self._ard_verbinden).grid(row=0, column=2, padx=10)
        self.lbl_ard_status = ttk.Label(ard, text="Nicht verbunden", foreground="#f38ba8")
        self.lbl_ard_status.grid(row=0, column=3, padx=10)

        einst = ttk.LabelFrame(frame, text="Einstellungen (ToolConfig)")
        einst.pack(fill="both", expand=True, padx=20, pady=10)
        self.config_text = scrolledtext.ScrolledText(einst, height=10,
                                                    bg="#11111b", fg="#cdd6f4",
                                                    font=("Consolas", 9))
        self.config_text.pack(fill="both", expand=True, padx=10, pady=10)
        if self.config:
            try:
                self.config_text.insert("end", json.dumps(self.config.__dict__, indent=2, default=str))
            except Exception:
                self.config_text.insert("end", "Config nicht lesbar.")
        else:
            self.config_text.insert("end", "ToolConfig nicht verfuegbar.")

    def _ard_verbinden(self):
        port = self.com_port.get()
        try:
            from arduino_steuerung import ArduinoSteuerung
            ard = ArduinoSteuerung(port)
            if ard.verbinde():
                BotStatus.arduino_verbunden = True
                self.lbl_ard_status.config(text="Verbunden (%s)" % port, foreground="#a6e3a1")
                messagebox.showinfo("Arduino", "Verbunden auf %s" % port)
            else:
                self.lbl_ard_status.config(text="Software-Modus", foreground="#f9e2af")
        except Exception as e:
            messagebox.showwarning("Arduino", "Nicht verbunden: %s\nSoftware-Modus aktiv." % e)
            self.lbl_ard_status.config(text="Software-Modus", foreground="#f9e2af")

    # ---------- STATUS ----------
    def _setup_statusbar(self):
        self.statusbar = ttk.Frame(self.root)
        self.statusbar.pack(fill="x", side="bottom")
        self.lbl_status = ttk.Label(self.statusbar, text="Bereit", foreground="#a6e3a1")
        self.lbl_status.pack(side="left", padx=10, pady=5)
        self.lbl_ard = ttk.Label(self.statusbar, text="Arduino: aus", foreground="#f38ba8")
        self.lbl_ard.pack(side="right", padx=10)

    def _update_status(self):
        if BotStatus.fishbot_laeuft and BotStatus.startzeit:
            dauer = time.time() - BotStatus.startzeit - BotStatus.pausen_gesamt
            if BotStatus.fishbot_pausiert:
                dauer -= (time.time() - BotStatus.pausen_start)
            mm, ss = divmod(int(dauer), 60)
            hh, mm = divmod(mm, 60)
            self.lbl_laufzeit.config(text="Laufzeit: %02d:%02d:%02d" % (hh, mm, ss))
            if BotStatus.fishbot_pausiert:
                self.lbl_status.config(text="Pausiert", foreground="#f9e2af")
            else:
                self.lbl_status.config(text="Laeuft", foreground="#a6e3a1")
            gesamt = BotStatus.gefischt + BotStatus.fehlversuche
            if gesamt > 0:
                quote = BotStatus.gefischt * 100.0 / gesamt
                self.lbl_quote.config(text="Erfolgsrate: %.0f%%" % quote)
        elif not BotStatus.fishbot_laeuft:
            self.lbl_status.config(text="Bereit", foreground="#a6e3a1")
        if BotStatus.arduino_verbunden:
            self.lbl_ard.config(text="Arduino: an", foreground="#a6e3a1")
        self.root.after(1000, self._update_status)


def main():
    root = tk.Tk()
    CommandCenter(root)
    root.mainloop()

if __name__ == "__main__":
    main()
