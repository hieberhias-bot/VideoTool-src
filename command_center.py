import threading
#!/usr/bin/env python3
"""Bot Command Center - zentrale Steuerungs-App mit Ablauf-Editor"""

import os, sys, json, time, subprocess, threading, random, copy, logging
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

# HID-Maus (serielles Text-Protokoll) - optional, App laeuft auch ohne
try:
    from hid_maus import HIDMaus
    HID_OK = True
    HID_IMPORT_ERR = None
except Exception as _hid_err:
    HID_OK = False
    HID_IMPORT_ERR = _hid_err
    HIDMaus = None

# Fischbot (Erkennung + State-Machine) - optional, App laeuft auch ohne
try:
    import fish_bot
    FISH_BOT_OK = True
    FISH_BOT_IMPORT_ERR = None
except Exception as _fb_err:
    FISH_BOT_OK = False
    FISH_BOT_IMPORT_ERR = _fb_err
    fish_bot = None

# Bild-Erkennung (fuer die Bildauswahl der Fenster-Eckpruefung im Fisch-Bot-
# Tab, siehe fish_bot.eckpruefung_laden()/_eckpruefung_bauen()) - optional
try:
    import bild_erkennung
    BILD_ERKENNUNG_OK = True
except Exception:
    BILD_ERKENNUNG_OK = False
    bild_erkennung = None

# Aktionsbasierte Bot-Skripte (getrennt vom aelteren ablauf_*.json-System) -
# optional, App laeuft auch ohne
try:
    from aktion_editor import AktionsSkriptTab
    AKTION_OK = True
    AKTION_IMPORT_ERR = None
except Exception as _ak_err:
    AKTION_OK = False
    AKTION_IMPORT_ERR = _ak_err
    AktionsSkriptTab = None

# Paralleles Makro-System (mehrere Bot-Skripte gleichzeitig + Fisch-Bot ueber
# einen gemeinsamen MausDispatcher, siehe maus_dispatcher.py/makro_manager.py)
# - optional, App laeuft auch ohne (MAKRO TOOLS-Reiter zeigt dann nur einen
# Hinweis statt der Skript-Liste).
try:
    import aktion_skript
    import modules.fenster as fenster_modul
    from maus_dispatcher import MausDispatcher, PRIORITAET_HOCH, PRIORITAET_MITTEL, PRIORITAET_NIEDRIG
    from makro_manager import MakroManager, MakroManagerFehler, FISCHBOT_NAME
    MAKRO_OK = True
    MAKRO_IMPORT_ERR = None
except Exception as _makro_err:
    MAKRO_OK = False
    MAKRO_IMPORT_ERR = _makro_err
    MausDispatcher = None
    MakroManager = None
    MakroManagerFehler = Exception
    fenster_modul = None
    PRIORITAET_HOCH, PRIORITAET_MITTEL, PRIORITAET_NIEDRIG = "HOCH", "MITTEL", "NIEDRIG"
    FISCHBOT_NAME = "__fischbot__"

# "Alle Fenster" ist die Standard-Auswahl im Fenster-Dropdown jeder
# MAKRO-TOOLS-Zeile (siehe _makro_zeile_bauen()) - startet bei mehreren
# offenen Spielfenstern automatisch je EINE isolierte Instanz pro Fenster
# (siehe makro_manager.MakroManager.starte_makro_alle_fenster()).
FENSTER_AUSWAHL_ALLE = "Alle Fenster"

# Nur im Fisch-Tab-Dropdown (siehe _fish_fenster_liste_aktualisieren()):
# manuell per Maus aufgezogener Bildschirmbereich (siehe modules.fenster.
# bereich_manuell_auswaehlen()) statt automatischer GetWindowRect()-Erkennung
# - fuer den Fall, dass andere Fenster das Zielfenster ueberlappen und die
# automatische Erkennung dadurch falschen Bildschirminhalt einfangen wuerde
# (siehe live_erkennung_vorschau.py, wo dasselbe Problem zuerst auftrat).
FENSTER_AUSWAHL_MANUELL = "Manueller Bereich..."


class _TkLogHandler(logging.Handler):
    """Leitet Log-Eintraege eines Python-logging-Loggers (z.B. fish_bot's
    "FishBot"-Logger) thread-sicher per root.after() in eine Callback-Funktion
    (z.B. CommandCenter._log_fish) um. Der Bot laeuft in einem Hintergrund-
    Thread, Tkinter-Widgets duerfen aber nur aus dem Hauptthread angefasst
    werden - daher niemals direkt callback() aufrufen, immer ueber after()."""

    def __init__(self, root, callback):
        super().__init__()
        self.root = root
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        try:
            self.root.after(0, lambda: self.callback(msg))
        except Exception:
            pass


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
        # HID-Maus (serielles Text-Protokoll)
        self.hid_maus = None            # HIDMaus-Instanz oder None
        self.hid_port = ""  # leer = Auto-Detect          # Standard-Port fuer die HID-Maus

        # Paralleles Makro-System (mehrere Bot-Skripte + Fisch-Bot gleich-
        # zeitig ueber einen gemeinsamen MausDispatcher, siehe MAKRO
        # TOOLS-Reiter/_build_fish_tab()-Erweiterung). maus_getter greift
        # lazy auf self.hid_maus zu - zum Zeitpunkt dieser Zuweisung ist die
        # HID-Maus noch nicht verbunden (_hid_maus_init() laeuft erst
        # danach), das ist unproblematisch, da der Getter erst bei einem
        # tatsaechlichen Makro-Start ausgewertet wird.
        self.makro_manager = MakroManager(
            maus_getter=lambda: self.hid_maus, log=self._log_makro) if MAKRO_OK else None

        self._setup_style()
        self._setup_tabs()
        self._hid_maus_init()
        self._setup_statusbar()
        self._update_status()

    def _hid_maus_init(self):
        """Instanziiert die HID-Maus beim Start.

        Ein leerer/nicht gesetzter Port loest ueber HIDMaus(port="") die
        Auto-Erkennung (_port_auto_finden() in hid_maus.py, VID/PID-Suche)
        aus, statt die HID-Maus einfach zu deaktivieren - vorher wurde hier
        bei leerem Port frueh abgebrochen, wodurch die Auto-Erkennung nie
        zum Zug kam und andere Aufrufer (z.B. fish_bot.bot_starten) auf den
        veralteten, hart verdrahteten Port COM7 zurueckfielen.

        Schlaegt die Verbindung fehl (kein Geraet gefunden, Port belegt),
        bleibt ``self.hid_maus`` auf ``None`` und die App laeuft normal weiter.
        """
        if not HID_OK:
            self._log_fish("HID-Maus-Modul nicht verfuegbar: %s" % HID_IMPORT_ERR)
            return
        # Port bevorzugt aus dem Config-Feld, sonst der Standardwert
        if hasattr(self, "hid_port_entry"):
            port = self.hid_port_entry.get().strip()
        else:
            port = (self.hid_port or "").strip()
        try:
            maus = HIDMaus(port)
            if not maus.port:
                self.hid_maus = None
                self._log_fish(
                    "Kein Arduino gefunden (weder Port angegeben noch per "
                    "Auto-Erkennung erkannt) - HID-Maus deaktiviert.")
                self._set_hid_status("Nicht verbunden", "#f38ba8")
                return
            if maus.verbinden():
                self.hid_maus = maus
                self.hid_port = maus.port
                self._log_fish("HID-Maus verbunden auf %s." % maus.port)
                self._set_hid_status("Verbunden (%s)" % maus.port, "#a6e3a1")
            else:
                self.hid_maus = None
                self._log_fish("HID-Maus nicht verbunden (%s)." % maus.port)
                self._set_hid_status("Nicht verbunden", "#f38ba8")
        except Exception as e:
            self.hid_maus = None
            self._log_fish("HID-Maus Fehler (%s): %s" % (port or "auto", e))
            self._set_hid_status("Nicht verbunden", "#f38ba8")

    def _set_hid_status(self, text, farbe):
        """Aktualisiert die HID-Status-Anzeige im Config-Tab (falls vorhanden)."""
        if hasattr(self, "lbl_hid_status"):
            self.lbl_hid_status.config(text=text, foreground=farbe)

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

        # Bot-Skripte-Tab (aktionsbasierte Ablaeufe, siehe aktion_editor.py) -
        # bewusst anders benannt als das aeltere "Skripte"/"Sequenzen"-System,
        # das koordinatenbasiert (pyautogui) arbeitet.
        if AKTION_OK:
            self.tab_bot_skripte = AktionsSkriptTab(
                self.notebook, BASE_DIR, lambda: self.hid_maus, self._log_fish,
                fremd_aktiv_getter=lambda: BotStatus.fishbot_laeuft,
                on_save_callback=self._makro_skriptlisten_aktualisieren)
            self.notebook.add(self.tab_bot_skripte, text="Bot-Skripte")
        else:
            self.tab_bot_skripte = None
            platzhalter = ttk.Frame(self.notebook)
            self.notebook.add(platzhalter, text="Bot-Skripte")
            ttk.Label(platzhalter,
                      text="Bot-Skripte-Modul konnte nicht geladen werden:\n%s"
                      % AKTION_IMPORT_ERR,
                      foreground="#f38ba8").pack(padx=20, pady=20, anchor="w")

        # MAKRO TOOLS-Tab (paralleles Makro-System, siehe makro_manager.py) -
        # mehrere Bot-Skripte GLEICHZEITIG, im Gegensatz zum "nur ein Ablauf"-
        # Verhalten des Bot-Skripte-Tabs oben.
        self.tab_makro = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_makro, text="MAKRO TOOLS")
        if not MAKRO_OK:
            ttk.Label(self.tab_makro,
                      text="Makro-System konnte nicht geladen werden:\n%s"
                      % MAKRO_IMPORT_ERR,
                      foreground="#f38ba8").pack(padx=20, pady=20, anchor="w")

        self.notebook.add(self.tab_config, text="Config / Arduino")

        # Fenster-Ecken-Tab (siehe fish_bot.fenster_eckpruefung_bestehen()) -
        # EIN zentraler Ort fuer die Eckbereich-Bild-Zuordnung + -Groesse,
        # bewusst NICHT im Fisch-Tab versteckt: die Pruefung greift bei JEDEM
        # automatischen Fenster-Start (Fisch-Bot, MAKRO TOOLS, Bot-Skripte),
        # nicht nur beim Fisch-Bot.
        self.tab_ecken = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_ecken, text="Fenster-Ecken")

        self._build_fish_tab()
        self._build_aufnahme_tab()
        self._build_skripte_tab()
        self._build_makro_tab()
        self._build_config_tab()
        self._build_ecken_tab()

        # Frueh (nicht erst beim ersten Fisch-Bot-Start) verdrahten: die
        # Fenster-Eckpruefung (siehe fish_bot.fenster_eckpruefung_bestehen())
        # laeuft jetzt auch bei MAKRO TOOLS/Bot-Skripten OHNE dass der Fisch-
        # Bot je gestartet wurde - deren Log-Zeilen (welche Ecke fehlschlug)
        # sollen trotzdem im Fisch-Tab-Log sichtbar sein, nicht erst danach.
        if FISH_BOT_OK:
            self._fish_bot_log_verdrahten()

        self.root.bind("<F5>", lambda e: self._fish_start())
        self.root.bind("<F6>", lambda e: self._fish_pause())
        self.root.bind("<F7>", lambda e: self._fish_stop())
        if self.tab_bot_skripte is not None:
            self.root.bind("<F8>", lambda e: self.tab_bot_skripte.hotkey_f8())

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

        # Paralleles Bot-Skript (laeuft GLEICHZEITIG mit dem Fisch-Bot ueber
        # den gemeinsamen MausDispatcher, siehe MAKRO TOOLS-Reiter/
        # makro_manager.py - im Gegensatz zu "Vor-Start Ablaeufe"/"Sequenz
        # vor Automation" oben, die VOR dem Fisch-Bot-Start einmalig laufen).
        if MAKRO_OK:
            makro_frame = ttk.LabelFrame(frame, text="Paralleles Skript (waehrend Fisch-Bot laeuft)")
            makro_frame.pack(fill="x", padx=20, pady=5)

            self.var_fish_makro_parallel = tk.BooleanVar(value=False)
            ttk.Checkbutton(makro_frame, text="Skript parallel zum Fish-Bot starten",
                            variable=self.var_fish_makro_parallel,
                            command=self._toggle_fish_makro_parallel).grid(
                row=0, column=0, columnspan=4, padx=10, pady=5, sticky="w")

            ttk.Label(makro_frame, text="Skript:").grid(row=1, column=0, padx=10, pady=3, sticky="w")
            self.combo_fish_makro_skript = ttk.Combobox(makro_frame, state="disabled", width=25)
            self.combo_fish_makro_skript.grid(row=1, column=1, padx=5, sticky="w")

            ttk.Label(makro_frame, text="Prioritaet:").grid(row=1, column=2, padx=10, sticky="w")
            self.var_fish_makro_prioritaet = tk.StringVar(value=PRIORITAET_MITTEL)
            self.combo_fish_makro_prioritaet = ttk.Combobox(
                makro_frame, textvariable=self.var_fish_makro_prioritaet, state="disabled", width=9,
                values=[PRIORITAET_HOCH, PRIORITAET_MITTEL, PRIORITAET_NIEDRIG])
            self.combo_fish_makro_prioritaet.grid(row=1, column=3, padx=5, sticky="w")

            ttk.Label(makro_frame,
                      text="Fisch-Bot selbst laeuft dabei mit Prioritaet HOCH.",
                      foreground="#a6adc8").grid(row=2, column=0, columnspan=4, padx=10, pady=(0, 5), sticky="w")

            self._refresh_fish_makro_combo()
        else:
            self.var_fish_makro_parallel = None

        # Fenster
        fenster_frame = ttk.LabelFrame(frame, text="Ziel-Fenster")
        fenster_frame.pack(fill="x", padx=20, pady=5)
        ttk.Label(fenster_frame, text="Fenster:").grid(row=0, column=0, padx=10, pady=5)
        self.fish_fenster = ttk.Entry(fenster_frame, width=20)
        self.fish_fenster.grid(row=0, column=1, padx=5)
        self.fish_fenster.insert(0, "Metin2")
        ttk.Label(fenster_frame, text="  (Hotkey: F5=Start, F6=Pause, F7=Stop)",
                  foreground="#a6adc8").grid(row=0, column=2, padx=10)

        # Mehrfenster-Unterstuetzung (siehe MAKRO TOOLS-Reiter/makro_manager.
        # MakroManager.fischbot_starten_alle_fenster()) - genau dieselbe
        # Fenster-Auswahl wie bei den Bot-Skripten: "Alle Fenster" (Standard)
        # startet bei mehreren offenen Spielfenstern automatisch je EINEN
        # isolierten Fisch-Bot pro Fenster, eine konkrete "Fenster N"-Auswahl
        # isoliert eine einzelne Instanz auf genau dieses Fenster.
        if MAKRO_OK:
            ttk.Label(fenster_frame, text="Mehrere Fenster:").grid(
                row=1, column=0, padx=10, pady=5, sticky="w")
            self.var_fish_fenster_wahl = tk.StringVar(value=FENSTER_AUSWAHL_ALLE)
            self.combo_fish_fenster_wahl = ttk.Combobox(
                fenster_frame, textvariable=self.var_fish_fenster_wahl, state="readonly", width=14,
                values=[FENSTER_AUSWAHL_ALLE])
            self.combo_fish_fenster_wahl.grid(row=1, column=1, padx=5, sticky="w")
            ttk.Button(fenster_frame, text="Aktualisieren",
                       command=self._fish_fenster_liste_aktualisieren).grid(row=1, column=2, padx=10)
            self.lbl_fish_fenster_status = ttk.Label(fenster_frame, text="", foreground="#f9e2af")
            self.lbl_fish_fenster_status.grid(row=2, column=0, columnspan=3, padx=10, pady=(0, 5), sticky="w")
            self._fish_fenster_liste_aktualisieren()
        else:
            self.var_fish_fenster_wahl = None

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

    def _toggle_fish_makro_parallel(self):
        state = "readonly" if self.var_fish_makro_parallel.get() else "disabled"
        self.combo_fish_makro_skript.config(state=state)
        self.combo_fish_makro_prioritaet.config(state=state)

    def _refresh_fish_makro_combo(self):
        namen = aktion_skript.verfuegbare_skripte() if MAKRO_OK else []
        aktuell = self.combo_fish_makro_skript.get()
        self.combo_fish_makro_skript["values"] = namen
        if aktuell not in namen:
            self.combo_fish_makro_skript.set(namen[0] if namen else "")

    _ECKEN_LABELS = [("oben_links", "Oben-Links:"), ("oben_rechts", "Oben-Rechts:"),
                     ("unten_links", "Unten-Links:"), ("unten_rechts", "Unten-Rechts:")]

    def _build_ecken_tab(self):
        """Baut den eigenstaendigen "Fenster-Ecken"-Tab: je Ecke ein Dropdown
        mit einem bilder_szenen-Bild (siehe fish_bot.eckpruefung_laden()/
        _speichern()) - EIN zentraler, dauerhaft gespeicherter Ort fuer diese
        Zuordnung, bewusst NICHT in einem der Werkzeug-Tabs versteckt: der
        Check (siehe fish_bot.fenster_eckpruefung_bestehen()) laeuft bei
        JEDEM automatischen (NICHT manuellen) Fenster-Start durch ALLE drei
        Werkzeuge - Fisch-Bot (fish_bot.bot_starten()), MAKRO TOOLS
        (makro_manager.MakroManager.starte_makro()) UND Bot-Skripte
        (aktion_editor.AktionsSkriptTab._ausfuehren_start()) - bevor
        irgendetwas losklickt/-tippt. Schuetzt vor einem faelschlich/falsch
        positioniert erkannten Fenster (z.B. durch ein DPI-/Skalierungsproblem,
        siehe fish_bot.screenshot_holen()-Diagnose)."""
        frame = self.tab_ecken
        ttk.Label(frame, text="FENSTER-ECKEN", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(15, 5))
        ttk.Label(frame,
                  text="Gilt fuer JEDEN automatischen Fenster-Start - Fisch-Bot, MAKRO TOOLS und "
                       "Bot-Skripte - bis hier wieder etwas geaendert wird.",
                  foreground="#a6adc8").pack(anchor="w", padx=20)

        self._eck_combos = {}
        if not (FISH_BOT_OK and BILD_ERKENNUNG_OK):
            ttk.Label(frame, text="Fisch-Bot- und/oder Bild-Erkennungs-Modul nicht verfuegbar - "
                                  "Fenster-Eckpruefung deaktiviert.",
                      foreground="#f38ba8").pack(padx=20, pady=20, anchor="w")
            return

        eck_frame = ttk.LabelFrame(frame, text="Fenster-Pruefung (Ecken)")
        eck_frame.pack(fill="x", padx=20, pady=15)

        zuordnung = fish_bot.eckpruefung_laden()
        bilder_werte = [""] + bild_erkennung.verfuegbare_bilder()

        for i, (key, text) in enumerate(self._ECKEN_LABELS):
            row, col = divmod(i, 2)
            ttk.Label(eck_frame, text=text).grid(row=row, column=col * 2, padx=10, pady=5, sticky="w")
            combo = ttk.Combobox(eck_frame, state="readonly", width=20, values=bilder_werte)
            combo.set(zuordnung.get(key, ""))
            combo.grid(row=row, column=col * 2 + 1, padx=5, pady=5, sticky="w")
            combo.bind("<<ComboboxSelected>>", lambda e, k=key: self._eckpruefung_geaendert(k))
            self._eck_combos[key] = combo

        ttk.Label(eck_frame,
                  text="Mind. 2 der konfigurierten Ecken muessen beim automatischen Start erkannt "
                       "werden (Fisch-Bot, MAKRO TOOLS, Bot-Skripte), sonst Abbruch (gilt NICHT fuer "
                       "'Manueller Bereich'). Leer = keine Pruefung.",
                  foreground="#a6adc8", wraplength=600, justify="left").grid(
            row=2, column=0, columnspan=4, padx=10, pady=(0, 5), sticky="w")

        # Eckbereich-Groesse (Anteil der Fensterbreite/-hoehe, der je Ecke
        # durchsucht wird, siehe fish_bot._eckbereich_koordinaten()) - EINMAL
        # hier eingestellt, dauerhaft in derselben Datei wie die Bild-
        # Zuordnung gespeichert (siehe fish_bot.eckpruefung_speichern()) und
        # gilt GLOBAL fuer JEDEN Aufrufer der Eckpruefung (Fisch-Bot, MAKRO
        # TOOLS UND Bot-Skripte), bis sie hier wieder geaendert wird.
        ttk.Label(eck_frame, text="Eckbereich-Groesse:").grid(
            row=3, column=0, padx=10, pady=5, sticky="w")
        self.var_eck_anteil = tk.DoubleVar(value=round(zuordnung["anteil"] * 100))
        self.scale_eck_anteil = ttk.Scale(
            eck_frame, from_=fish_bot.ECKBEREICH_ANTEIL_MIN * 100, to=fish_bot.ECKBEREICH_ANTEIL_MAX * 100,
            variable=self.var_eck_anteil, command=self._eckpruefung_anteil_vorschau, length=150)
        self.scale_eck_anteil.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        self.lbl_eck_anteil = ttk.Label(eck_frame, text="%d%% der Fenstergroesse je Ecke"
                                        % round(zuordnung["anteil"] * 100))
        self.lbl_eck_anteil.grid(row=3, column=2, columnspan=2, padx=5, pady=5, sticky="w")
        self.scale_eck_anteil.bind("<ButtonRelease-1>", lambda e: self._eckpruefung_anteil_speichern())

    def _eckpruefung_geaendert(self, key):
        zuordnung = fish_bot.eckpruefung_laden()
        zuordnung[key] = self._eck_combos[key].get()
        fish_bot.eckpruefung_speichern(zuordnung)

    def _eckpruefung_anteil_vorschau(self, wert):
        """Aktualisiert nur die %-Anzeige waehrend des Ziehens am Regler -
        das eigentliche Speichern (siehe _eckpruefung_anteil_speichern())
        passiert erst beim Loslassen, damit nicht bei jedem Pixel Bewegung
        auf die Festplatte geschrieben wird."""
        self.lbl_eck_anteil.config(text="%d%% der Fenstergroesse je Ecke" % round(float(wert)))

    def _eckpruefung_anteil_speichern(self):
        zuordnung = fish_bot.eckpruefung_laden()
        zuordnung["anteil"] = self.var_eck_anteil.get() / 100.0
        fish_bot.eckpruefung_speichern(zuordnung)

    def _fish_fenster_liste_aktualisieren(self):
        """Aktualisiert die "X Spielfenster gefunden"-Anzeige + das Fenster-
        Dropdown im Fisch-Tab (siehe modules.fenster.alle_spielfenster_finden())
        - dasselbe Muster wie CommandCenter._makro_fenster_liste_aktualisieren()
        im MAKRO TOOLS-Reiter."""
        if not MAKRO_OK or self.var_fish_fenster_wahl is None:
            return []
        fenster_liste = fenster_modul.alle_spielfenster_finden()
        n = len(fenster_liste)
        text = "%d Spielfenster gefunden" % n if n != 1 else "1 Spielfenster gefunden"
        self.lbl_fish_fenster_status.config(text=text)

        werte = [FENSTER_AUSWAHL_ALLE, FENSTER_AUSWAHL_MANUELL] + \
            ["Fenster %d" % f["nummer"] for f in fenster_liste]
        self.combo_fish_fenster_wahl["values"] = werte
        if self.var_fish_fenster_wahl.get() not in werte:
            self.var_fish_fenster_wahl.set(FENSTER_AUSWAHL_ALLE)
        return fenster_liste

    def _fish_fenster_hwnd_aus_wahl(self, fenster_wahl):
        """Loest eine "Fenster N"-Auswahl (siehe combo_fish_fenster_wahl) zum
        aktuellen hwnd auf (frisch abgefragt - eine zuvor angezeigte Nummer
        koennte inzwischen einem anderen Fenster gehoeren, wenn sich die
        Fensterliste zwischenzeitlich geaendert hat). None fuer
        FENSTER_AUSWAHL_ALLE oder wenn das gewaehlte Fenster nicht mehr
        gefunden wird."""
        if fenster_wahl == FENSTER_AUSWAHL_ALLE:
            return None
        try:
            nummer = int(fenster_wahl.replace("Fenster", "").strip())
        except ValueError:
            return None
        treffer = next((f for f in fenster_modul.alle_spielfenster_finden() if f["nummer"] == nummer),
                       None)
        return treffer["hwnd"] if treffer else None

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

    def _fish_bot_log_verdrahten(self):
        """Haengt einmalig einen Handler an fish_bot's "FishBot"-Logger, der
        dessen Log-Ausgaben in self.fish_log umleitet. Idempotent (mehrfacher
        Aufruf haengt den Handler nicht mehrfach an)."""
        if getattr(self, "_fish_bot_log_handler", None) is not None:
            return
        handler = _TkLogHandler(self.root, self._log_fish)
        handler.setLevel(logging.INFO)  # DEBUG-Zeilen (pro Tick) waeren zu viel fuers GUI-Log
        logging.getLogger("FishBot").addHandler(handler)
        self._fish_bot_log_handler = handler

    def _start_fishbot(self):
        if BotStatus.fishbot_laeuft:
            return
        if not FISH_BOT_OK:
            messagebox.showerror("Fisch-Bot",
                                 "fish_bot.py konnte nicht geladen werden:\n%s" % FISH_BOT_IMPORT_ERR)
            return
        # Beide Systeme teilen sich dieselbe serielle HID-Verbindung - gleich-
        # zeitig laufen wuerde die Kommandos auf der Leitung durcheinander
        # bringen (nicht thread-sicher).
        if self.tab_bot_skripte is not None and self.tab_bot_skripte.laeuft:
            messagebox.showwarning("Fisch-Bot",
                                   "Es laeuft gerade ein Bot-Skript-Ablauf - bitte zuerst stoppen.")
            return

        self._fish_bot_log_verdrahten()

        BotStatus.fishbot_laeuft = True
        BotStatus.fishbot_pausiert = False
        BotStatus.startzeit = time.time()
        BotStatus.pausen_gesamt = 0.0
        self.btn_fish_start.config(state="disabled")
        # Der echte Fischbot (State-Machine in fish_bot.py) unterstuetzt kein
        # Pausieren - der Button bleibt daher deaktiviert (siehe _fish_pause()).
        self.btn_fish_pause.config(state="disabled", text="Pause (F6)")
        self.btn_fish_stop.config(state="normal")
        self._log_fish("Fisch-Bot gestartet (HID-Port %s)." % self.hid_port)

        fenster_wahl = (self.var_fish_fenster_wahl.get()
                        if MAKRO_OK and self.var_fish_fenster_wahl is not None
                        else FENSTER_AUSWAHL_ALLE)
        parallel_aktiv = (MAKRO_OK and self.var_fish_makro_parallel is not None
                          and self.var_fish_makro_parallel.get())
        parallel_skript = self.combo_fish_makro_skript.get().strip() if parallel_aktiv else ""

        if MAKRO_OK and fenster_wahl == FENSTER_AUSWAHL_MANUELL:
            if parallel_aktiv and parallel_skript:
                messagebox.showwarning(
                    "Fisch-Bot",
                    "'Manueller Bereich' laesst sich nicht mit einem 'Parallelen Skript' "
                    "kombinieren. Bitte entweder ein festes Fenster waehlen oder das "
                    "parallele Skript deaktivieren.")
                self._fishbot_beendet("GESTOPPT")
                return
            self._start_fishbot_manueller_bereich()
            return

        # "Alle Fenster" + MEHRERE offene Spielfenster -> Fan-out (ein
        # isolierter Fisch-Bot je Fenster, siehe makro_manager.
        # MakroManager.fischbot_starten_alle_fenster()). Ist zusaetzlich ein
        # "Paralleles Skript" aktiviert, laeuft dieses PRO Fenster ebenfalls
        # mit (siehe MakroManager.fischbot_und_makro_starten_alle_fenster()) -
        # also Fisch-Bot UND paralleles Skript je einmal pro Fenster, nicht
        # nur der Fisch-Bot alleine.
        if MAKRO_OK and fenster_wahl == FENSTER_AUSWAHL_ALLE:
            fenster_liste = fenster_modul.alle_spielfenster_finden()
            if len(fenster_liste) > 1:
                if parallel_aktiv and parallel_skript:
                    self._start_fishbot_alle_fenster_mit_makro(parallel_skript,
                                                                self.var_fish_makro_prioritaet.get())
                    return
                self._start_fishbot_alle_fenster()
                return

        if parallel_aktiv and parallel_skript:
            self._start_fishbot_als_makro(parallel_skript, self.var_fish_makro_prioritaet.get(), fenster_wahl)
            return

        if MAKRO_OK and fenster_wahl != FENSTER_AUSWAHL_ALLE:
            self._start_fishbot_isoliert(fenster_wahl)
            return

        # "Alle Fenster" mit hoechstens einem gefundenen Fenster (oder
        # MAKRO_OK nicht verfuegbar): bisheriges Verhalten unveraendert -
        # direkte HID-Verbindung, kein MakroManager noetig.
        # Bereits verbundene HID-Maus (Config-Tab) wiederverwenden, statt eine
        # zweite Verbindung auf denselben COM-Port zu versuchen (schlaegt
        # sonst i.d.R. fehl, da ein Port nur eine offene Verbindung erlaubt).
        maus = self.hid_maus
        port = self.hid_port

        def lauf():
            if maus is not None:
                ergebnis = fish_bot.bot_starten(maus=maus)
            else:
                ergebnis = fish_bot.bot_starten(port=port)
            self.root.after(0, lambda: self._fishbot_beendet(ergebnis))

        self._fishbot_thread = threading.Thread(target=lauf, daemon=True)
        self._fishbot_thread.start()

    def _start_fishbot_isoliert(self, fenster_wahl):
        """Startet EINE Fisch-Bot-Instanz, isoliert auf das per 'fenster_wahl'
        ausgewaehlte Fenster (z.B. "Fenster 2") - ueber den MakroManager,
        da nur der einen fenster_provider an fish_bot.bot_starten()
        durchreichen kann (siehe makro_manager.MakroManager.fish_bot_starten())."""
        hwnd = self._fish_fenster_hwnd_aus_wahl(fenster_wahl)
        if hwnd is None:
            messagebox.showerror("Fisch-Bot", "'%s' ist gerade nicht (mehr) offen." % fenster_wahl)
            self._fishbot_beendet("VERBINDUNGSFEHLER")
            return
        try:
            self.makro_manager.fish_bot_starten(prioritaet=PRIORITAET_HOCH, fenster_hwnd=hwnd,
                                                 fenster_label=fenster_wahl)
        except MakroManagerFehler as e:
            self._log_fish("Fisch-Bot konnte nicht gestartet werden: %s" % e)
            self._fishbot_beendet("VERBINDUNGSFEHLER")
            return
        self._warte_auf_fischbot_ende()

    def _start_fishbot_manueller_bereich(self):
        """Startet EINE Fisch-Bot-Instanz auf einen manuell aufgezogenen
        Bildschirmbereich isoliert (siehe modules.fenster.
        bereich_manuell_auswaehlen()) - Alternative zu _start_fishbot_isoliert()
        fuer den Fall, dass die automatische hwnd-basierte Fenstererkennung
        falsch liegt (z.B. weil ein anderes Fenster das Zielfenster
        ueberlappt). Wird bei JEDEM Start neu abgefragt statt gespeichert, da
        sich Fensterpositionen zwischen Bot-Starts aendern koennen."""
        self._log_fish("Manueller Bereich: bitte im Overlay den zu beobachtenden Bereich aufziehen...")
        bereich = fenster_modul.bereich_manuell_auswaehlen(master=self.root)
        if bereich is None:
            self._log_fish("Manueller Bereich abgebrochen - Fisch-Bot nicht gestartet.")
            self._fishbot_beendet("GESTOPPT")
            return
        try:
            self.makro_manager.fish_bot_starten(prioritaet=PRIORITAET_HOCH, fenster_bereich=bereich,
                                                 fenster_label=FENSTER_AUSWAHL_MANUELL)
        except MakroManagerFehler as e:
            self._log_fish("Fisch-Bot konnte nicht gestartet werden: %s" % e)
            self._fishbot_beendet("VERBINDUNGSFEHLER")
            return
        self._warte_auf_fischbot_ende()

    def _start_fishbot_alle_fenster(self):
        """Startet je EINE isolierte Fisch-Bot-Instanz PRO offenem
        Spielfenster (siehe Aufgabenstellung "separat fuer jedes Fenster")."""
        try:
            gestartet = self.makro_manager.fischbot_starten_alle_fenster(prioritaet=PRIORITAET_HOCH)
        except MakroManagerFehler as e:
            self._log_fish("Fisch-Bot konnte nicht gestartet werden: %s" % e)
            self._fishbot_beendet("VERBINDUNGSFEHLER")
            return
        self._log_fish("Fisch-Bot auf %d Fenster verteilt gestartet." % len(gestartet))
        self._warte_auf_fischbot_ende()

    def _start_fishbot_als_makro(self, skript_name, prioritaet, fenster_wahl=FENSTER_AUSWAHL_ALLE):
        """Startet Fisch-Bot UND das gewaehlte parallele Skript ueber den
        gemeinsamen MakroManager/MausDispatcher, statt fish_bot.py direkt mit
        der rohen HID-Maus zu verbinden - noetig, damit sich beide beim
        Maus-Zugriff tatsaechlich korrekt abwechseln, statt sich auf der
        seriellen Leitung zu ueberschneiden (siehe makro_manager.DispatcherMaus,
        ein fuer fish_bot.py transparenter Wrapper). Fisch-Bot laeuft dabei
        immer mit Prioritaet HOCH (siehe Aufgabenstellung), unabhaengig von
        der fuer das parallele Skript gewaehlten Prioritaet.

        Ist 'fenster_wahl' ein konkretes Fenster (nicht "Alle Fenster"),
        werden BEIDE - Fisch-Bot UND das parallele Skript - auf dasselbe
        Fenster isoliert (konsistent zu "alles fuer EIN Fenster")."""
        hwnd = None
        fenster_label = None
        if fenster_wahl != FENSTER_AUSWAHL_ALLE:
            hwnd = self._fish_fenster_hwnd_aus_wahl(fenster_wahl)
            if hwnd is None:
                self._log_fish("'%s' ist gerade nicht (mehr) offen - Fisch-Bot nicht gestartet." % fenster_wahl)
                self._fishbot_beendet("VERBINDUNGSFEHLER")
                return
            fenster_label = fenster_wahl

        try:
            self.makro_manager.fish_bot_starten(prioritaet=PRIORITAET_HOCH, fenster_hwnd=hwnd,
                                                 fenster_label=fenster_label)
        except MakroManagerFehler as e:
            self._log_fish("Fisch-Bot (als Makro) konnte nicht gestartet werden: %s" % e)
            self._fishbot_beendet("VERBINDUNGSFEHLER")
            return

        try:
            self.makro_manager.starte_makro(skript_name, prioritaet, fenster_hwnd=hwnd,
                                             instanz_key=skript_name, fenster_label=fenster_label)
        except MakroManagerFehler as e:
            self._log_fish("Paralleles Skript '%s' konnte nicht gestartet werden: %s" % (skript_name, e))

        self._warte_auf_fischbot_ende()

    def _warte_auf_fischbot_ende(self):
        """Wartet (in einem Hintergrund-Thread), bis KEINE Fisch-Bot-Instanz
        mehr laeuft - egal ob eine einzelne (isolierte oder nicht-isolierte)
        Instanz oder ein Mehrfenster-Fan-out (siehe _start_fishbot_alle_fenster()),
        makro_manager.makro_laeuft(FISCHBOT_NAME) prueft ueber basis_name
        ALLE Instanzen gemeinsam."""
        def warten():
            while self.makro_manager.makro_laeuft(FISCHBOT_NAME):
                time.sleep(0.2)
            eintraege = [e for e in self.makro_manager.laufende_makros()
                        if e["basis_name"] == FISCHBOT_NAME]
            status = eintraege[-1]["status"] if eintraege else "GESTOPPT"
            self.root.after(0, lambda: self._fishbot_beendet(status))

        self._fishbot_thread = threading.Thread(target=warten, daemon=True)
        self._fishbot_thread.start()

    def _fishbot_beendet(self, ergebnis):
        """Wird aufgerufen, sobald der Bot-Thread sich tatsaechlich beendet
        hat (Fehler, Stopp-Anforderung oder Verbindungsfehler)."""
        BotStatus.fishbot_laeuft = False
        BotStatus.fishbot_pausiert = False
        self.btn_fish_start.config(state="normal")
        self.btn_fish_pause.config(state="disabled", text="Pause (F6)")
        self.btn_fish_stop.config(state="disabled")
        text = {
            "GESTOPPT": "gestoppt",
            "FEHLER": "mit Fehler beendet (kein Popup mehr gefunden trotz aller Versuche)",
            "VERBINDUNGSFEHLER": "HID-Maus-Verbindungsfehler (siehe Config-Tab)",
            "FENSTERPRUEFUNG_FEHLGESCHLAGEN": "nicht gestartet - Fenster-Eckpruefung fehlgeschlagen "
                                              "(siehe Log/Fisch-Tab 'Fenster-Pruefung')",
        }.get(ergebnis, ergebnis)
        self._log_fish("Fisch-Bot beendet: %s" % text)

    def _fish_pause(self):
        if not BotStatus.fishbot_laeuft:
            return
        self._log_fish("Pause wird vom echten Fisch-Bot aktuell nicht unterstuetzt - "
                       "zum Anhalten bitte Stop (F7) verwenden.")

    def _fish_stop(self):
        if not BotStatus.fishbot_laeuft:
            return
        # Ueber MakroManager gestartete Instanzen (isoliert und/oder Fan-out,
        # siehe _start_fishbot_isoliert()/_start_fishbot_alle_fenster()/
        # _start_fishbot_als_makro()) haben ihr EIGENES, vom MakroManager
        # verwaltetes stop_event - das globale fish_bot.bot_anhalten() (ohne
        # Kontext) wuerde dort ins Leere laufen bzw. bei einer NICHT darueber
        # gestarteten Instanz die falsche/gar keine Instanz stoppen.
        if MAKRO_OK and self.makro_manager.makro_laeuft(FISCHBOT_NAME):
            gestoppt = self.makro_manager.stoppe_alle_instanzen(FISCHBOT_NAME)
            self._log_fish("Fisch-Bot: Stopp angefordert (%d Instanz(en))..." % len(gestoppt))
        elif FISH_BOT_OK:
            fish_bot.bot_anhalten()
            self._log_fish("Fisch-Bot: Stopp angefordert...")
        self.btn_fish_stop.config(state="disabled")
        # BotStatus und die uebrigen Buttons werden final in _fishbot_beendet()
        # zurueckgesetzt, sobald sich der Bot-Thread tatsaechlich beendet hat -
        # das kann (z.B. bei WARTEN-Schritten) bis zu ~100ms dauern.

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
                "Fenster-Modul nicht verfuegbar. Nutze absolute Koordinaten.")
            return
        if self._rec_listener is not None:
            return
        # Automatische Suche nach Metin2-Fenster (kein Klick noetig)
        such = self.trig_fenster.get().strip() or "Metin2"
        info = fenster_util.fenster_finden(such)
        if not info:
            self.lbl_rec_status.config(
                text="Fenster '%s' nicht gefunden - ist es offen?" % such,
                foreground="#f38ba8")
            self._log_fish("Fenster '%s' nicht gefunden." % such)
            return
        self._fenster_erfasst({"titel": such, **info})

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

    def _rec_start(self):
        self._log_fish('DEBUG: _rec_start aufgerufen')
        if BotStatus.aufnahme_laeuft:
            self._log_fish('DEBUG: laeuft schon, return')
            return
        # Zielfenster-Position frisch holen
        if self.erfasstes_fenster and FENSTER_OK:
            such = self.trig_fenster.get().strip()
            neu = fenster_util.fenster_finden(such) if such else None
            if neu:
                self.erfasstes_fenster = {'titel': such,
                                          'x': neu['x'], 'y': neu['y'],
                                          'w': neu['w'], 'h': neu['h']}
                self._log_fish('Zielfenster %s aktualisiert @ %d,%d (%dx%d)'
                               % (such, neu['x'], neu['y'], neu['w'], neu['h']))
            else:
                self._log_fish('Zielfenster %s nicht gefunden - nutze erfasste Position.' % such)
        BotStatus.aufnahme_laeuft = True
        self.aufnahme_events = []
        self.aufnahme_letzter_zeit = time.time()
        self.btn_rec_start.config(state='disabled')
        self.btn_rec_stop.config(state='normal')
        self.btn_fenster_erfassen.config(state='disabled')
        if self.erfasstes_fenster:
            self.lbl_rec_status.config(
                text='AUFNAHME... Klicke im Fenster %s!' % (self.erfasstes_fenster.get('titel') or '?')[:20],
                foreground='#f38ba8')
        else:
            self.lbl_rec_status.config(text='AUFNAHME (absolut)... Klicke ins Spiel!',
                                       foreground='#f38ba8')
        self.detail_liste.delete(0, 'end')
        self._log_fish('Aufnahme gestartet - klicke die Aktionen aus.')
        # COM4 statt pynput (umgeht UIPI)
        if not self._rec_com4_start():
            # Fallback: pynput
            try:
                from pynput import mouse
                self._rec_listener = mouse.Listener(on_click=self._on_global_click)
                self._rec_listener.start()
            except Exception:
                BotStatus.aufnahme_laeuft = False
                self.btn_rec_start.config(state='normal')
                self.btn_rec_stop.config(state='disabled')
                messagebox.showerror('Fehler', 'Weder COM4 noch pynput verfuegbar.')


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

        # Klick zusaetzlich ueber die HID-Maus ausloesen (falls verbunden)
        if self.hid_maus:
            try:
                if not self.hid_maus.klick_links():
                    self._log_fish("HID-Maus: keine Klick-Bestaetigung erhalten.")
            except ConnectionError as e:
                self._log_fish("HID-Maus Fehler beim Klick: %s" % e)

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
        self._rec_com4_stop_listener()
        self.btn_rec_start.config(state="normal")
        self.btn_rec_stop.config(state="disabled")
        self.btn_fenster_erfassen.config(state="normal")
        self.lbl_rec_status.config(text="Bereit", foreground="#a6adc8")

        # HID-Maus-Verbindung nach der Aufnahme schliessen
        if self.hid_maus:
            self.hid_maus.schliessen()
            self.hid_maus = None
            self._log_fish("HID-Maus getrennt (Aufnahme beendet).")
            self._set_hid_status("Nicht verbunden", "#f38ba8")

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


    # --- COM4 Klick-Erkennung (ersetzt pynput, umgeht UIPI) ---
    def _rec_com4_start(self):
        try:
            import serial
        except ImportError:
            messagebox.showerror('Fehler', 'pyserial nicht installiert (pip install pyserial).')
            return False
        port = 'COM4'  # HART auf COM4 - Arduino-Klick-Erkennung
        try:
            self._rec_ser = serial.Serial(port, 115200, timeout=0.1)
            self._rec_ser.setDTR(False)
            self._rec_ser.setRTS(False)
        except Exception as e:
            messagebox.showerror('COM4', 'Konnte %s nicht oeffnen: %s' % (port, e))
            return False
        self._rec_com4_stop = False
        self._rec_com4_thread = threading.Thread(target=self._rec_com4_loop, daemon=True)
        self._rec_com4_thread.start()
        self._log_fish('COM4-Klick-Erkennung aktiv auf %s' % port)
        return True

    def _rec_com4_loop(self):
        import serial
        while not getattr(self, '_rec_com4_stop', False):
            try:
                line = self._rec_ser.readline()
            except Exception:
                break
            if not line:
                continue
            txt = line.decode(errors='ignore').strip()
            if txt == 'CLICK':
                # Klick im COM4-Thread -> GUI via after()
                try:
                    self.root.after(0, self._rec_com4_klick)
                except Exception:
                    pass

    def _rec_com4_klick(self):
        if not BotStatus.aufnahme_laeuft:
            return
        try:
            import pyautogui
            x, y = pyautogui.position()
        except Exception:
            x, y = 0, 0
        win = self.erfasstes_fenster
        if win:
            rx, ry = x - win['x'], y - win['y']
        else:
            rx, ry = x, y
        self._rec_add_click(rx, ry, x, y)

    def _rec_com4_stop_listener(self):
        self._rec_com4_stop = True
        if getattr(self, '_rec_ser', None):
            try:
                self._rec_ser.close()
            except Exception:
                pass
            self._rec_ser = None

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

    # ---------- MAKRO TOOLS ----------
    def _build_makro_tab(self):
        """Baut den MAKRO TOOLS-Reiter: Liste aller aktion_*.json-Skripte
        mit Prioritaet/Start/Stop/Status, "Stoppe alle", "Neues Skript" und
        "Speichern unter" - siehe makro_manager.py fuer die eigentliche
        Ausfuehrungslogik (paralleler Start mehrerer Skripte ueber einen
        gemeinsamen MausDispatcher). Ohne verfuegbares Makro-System (siehe
        MAKRO_OK) zeigt der Tab bereits in _setup_tabs() nur einen
        Fehlerhinweis - hier dann nichts weiter aufbauen."""
        frame = self.tab_makro
        if not MAKRO_OK:
            return

        ttk.Label(frame, text="MAKRO TOOLS", style="Header.TLabel").pack(
            anchor="w", padx=20, pady=(15, 5))
        ttk.Label(frame,
                  text="Mehrere Bot-Skripte gleichzeitig - hoehere Prioritaet gewinnt bei Maus-Konflikten",
                  foreground="#a6adc8").pack(anchor="w", padx=20)

        # Live-Anzeige der aktuell erkannten Spielfenster (siehe
        # modules.fenster.alle_spielfenster_finden()) - wird zusammen mit der
        # Skript-Liste aktualisiert (siehe _makro_liste_neu_aufbauen()), da
        # sich beides (verfuegbare Skripte, offene Fenster) unabhaengig
        # voneinander waehrend der Laufzeit aendern kann.
        self.lbl_makro_fenster = ttk.Label(frame, text="", foreground="#f9e2af")
        self.lbl_makro_fenster.pack(anchor="w", padx=20, pady=(2, 0))

        steuerung = ttk.Frame(frame)
        steuerung.pack(fill="x", padx=20, pady=10)
        ttk.Button(steuerung, text="Neues Skript",
                   command=self._makro_neues_skript).pack(side="left", padx=5)
        ttk.Button(steuerung, text="Speichern unter",
                   command=self._makro_speichern_unter).pack(side="left", padx=5)
        ttk.Button(steuerung, text="Aktualisieren",
                   command=self._makro_liste_neu_aufbauen).pack(side="left", padx=5)
        ttk.Button(steuerung, text="Stoppe alle", style="Danger.TButton",
                   command=self._makro_stoppe_alle).pack(side="left", padx=20)

        kopf = ttk.Frame(frame)
        kopf.pack(fill="x", padx=25, pady=(10, 0))
        ttk.Label(kopf, text="Skript", foreground="#89b4fa", width=28).pack(side="left", padx=5)
        ttk.Label(kopf, text="Prioritaet", foreground="#89b4fa", width=10).pack(side="left", padx=5)
        ttk.Label(kopf, text="Fenster", foreground="#89b4fa", width=12).pack(side="left", padx=5)
        ttk.Label(kopf, text="", width=8).pack(side="left", padx=5)
        ttk.Label(kopf, text="", width=8).pack(side="left", padx=5)
        ttk.Label(kopf, text="Status", foreground="#89b4fa", width=22).pack(side="left", padx=5)

        # Scrollbarer Container fuer die Skript-Zeilen (Canvas + Frame - die
        # Anzahl der Skripte kann variieren, jede Zeile braucht echte
        # Start/Stop-Button-Widgets statt nur Text wie in einem Treeview).
        container = ttk.Frame(frame)
        container.pack(fill="both", expand=False, padx=20, pady=5)
        canvas = tk.Canvas(container, bg="#1e1e2e", highlightthickness=0, height=220)
        vscroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.makro_zeilen_frame = ttk.Frame(canvas)
        self.makro_zeilen_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.makro_zeilen_frame, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        self._makro_prioritaet_vars = {}   # skript_name -> tk.StringVar
        self._makro_fenster_vars = {}      # skript_name -> tk.StringVar ("Alle Fenster"/"Fenster N")
        self._makro_zeilen_widgets = {}    # skript_name -> {"btn_start","btn_stop","status_label"}

        ttk.Label(frame, text="Log:").pack(anchor="w", padx=20, pady=(10, 2))
        self.makro_log = scrolledtext.ScrolledText(frame, height=8,
                                                    bg="#11111b", fg="#a6e3a1",
                                                    font=("Consolas", 9))
        self.makro_log.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.makro_log.insert("end", "MAKRO TOOLS bereit.\n")

        self._makro_liste_neu_aufbauen()
        self._makro_status_polling()

    def _makro_skriptlisten_aktualisieren(self):
        """Aktualisiert JEDE Stelle im Command Center, die eine Liste der
        aktion_*.json-Skripte anzeigt (MAKRO TOOLS-Liste + Fisch-Bot-
        Skriptauswahl) - als on_save_callback an AktionsSkriptTab (Bot-
        Skripte-Reiter) verdrahtet, damit ein dort gespeichertes Skript
        sofort in MAKRO TOOLS/beim Fisch-Bot startbar/waehlbar ist, ohne
        manuell 'Aktualisieren' klicken zu muessen.

        hasattr()-Guards, da diese Methode theoretisch (wenn auch praktisch
        nie, da die GUI erst nach dem vollstaendigen Aufbau interaktiv wird)
        schon waehrend des Aufbaus selbst greifen koennte."""
        if hasattr(self, "makro_zeilen_frame"):
            self._makro_liste_neu_aufbauen()
        if hasattr(self, "combo_fish_makro_skript"):
            self._refresh_fish_makro_combo()

    def _makro_fenster_liste_aktualisieren(self):
        """Fragt die aktuell offenen Spielfenster ab (siehe
        modules.fenster.alle_spielfenster_finden()) und aktualisiert das
        "X Spielfenster gefunden"-Label - wird VOR jedem Neuaufbau der
        Skript-Zeilen aufgerufen (siehe _makro_liste_neu_aufbauen()), damit
        alle Zeilen dieselbe, konsistente Fenster-Liste fuer ihr Dropdown
        verwenden (statt jede Zeile einzeln neu zu enumerieren).

        Returns:
            list[dict]: siehe modules.fenster.alle_spielfenster_finden().
        """
        fenster_liste = fenster_modul.alle_spielfenster_finden()
        n = len(fenster_liste)
        text = "%d Spielfenster gefunden" % n if n != 1 else "1 Spielfenster gefunden"
        if n == 0:
            text += " - Skripte laufen ohne Fenster-Isolation (bisheriges Verhalten)."
        self.lbl_makro_fenster.config(text=text)
        return fenster_liste

    def _makro_liste_neu_aufbauen(self):
        """Baut die Skript-Zeilen komplett neu auf (z.B. nach 'Aktualisieren'
        oder einem neu angelegten/duplizierten Skript) - einfacher und fuer
        die erwartete kleine Anzahl Skripte voellig ausreichend, statt einen
        Diff der vorhandenen Widgets zu pflegen."""
        fenster_liste = self._makro_fenster_liste_aktualisieren()

        for w in self.makro_zeilen_frame.winfo_children():
            w.destroy()
        self._makro_zeilen_widgets = {}

        namen = aktion_skript.verfuegbare_skripte()
        if not namen:
            ttk.Label(self.makro_zeilen_frame,
                      text="Keine Skripte vorhanden - 'Neues Skript' zum Anlegen.",
                      foreground="#a6adc8").pack(anchor="w", padx=5, pady=10)
            return
        for name in namen:
            self._makro_zeile_bauen(name, fenster_liste)

    def _makro_zeile_bauen(self, name, fenster_liste=()):
        zeile = ttk.Frame(self.makro_zeilen_frame)
        zeile.pack(fill="x", pady=2)

        ttk.Label(zeile, text=name, width=28).pack(side="left", padx=5)

        prio_var = self._makro_prioritaet_vars.get(name)
        if prio_var is None:
            prio_var = tk.StringVar(value=PRIORITAET_MITTEL)
            self._makro_prioritaet_vars[name] = prio_var
        ttk.Combobox(zeile, textvariable=prio_var, state="readonly", width=9,
                     values=[PRIORITAET_HOCH, PRIORITAET_MITTEL, PRIORITAET_NIEDRIG]).pack(
            side="left", padx=5)

        # Fenster-Zuordnung (siehe FENSTER-ZUORDNUNG in der Aufgabenstellung):
        # "Alle Fenster" (Standard) startet bei mehreren offenen Fenstern
        # automatisch je eine isolierte Instanz pro Fenster (siehe
        # makro_manager.starte_makro_alle_fenster()), eine konkrete "Fenster
        # N"-Auswahl isoliert eine einzelne Instanz auf genau dieses Fenster.
        fenster_var = self._makro_fenster_vars.get(name)
        if fenster_var is None:
            fenster_var = tk.StringVar(value=FENSTER_AUSWAHL_ALLE)
            self._makro_fenster_vars[name] = fenster_var
        fenster_werte = [FENSTER_AUSWAHL_ALLE] + ["Fenster %d" % f["nummer"] for f in fenster_liste]
        if fenster_var.get() not in fenster_werte:
            fenster_var.set(FENSTER_AUSWAHL_ALLE)
        ttk.Combobox(zeile, textvariable=fenster_var, state="readonly", width=11,
                     values=fenster_werte).pack(side="left", padx=5)

        btn_start = ttk.Button(zeile, text="Start", style="Success.TButton", width=8,
                                command=lambda n=name: self._makro_start(n))
        btn_start.pack(side="left", padx=5)
        btn_stop = ttk.Button(zeile, text="Stop", style="Danger.TButton", width=8,
                               state="disabled", command=lambda n=name: self._makro_stop(n))
        btn_stop.pack(side="left", padx=5)

        btn_bearbeiten = ttk.Button(zeile, text="Bearbeiten", width=10,
                                    command=lambda n=name: self._makro_bearbeiten(n))
        btn_bearbeiten.pack(side="left", padx=5)

        btn_loeschen = ttk.Button(zeile, text="Löschen", style="Danger.TButton", width=9,
                                  command=lambda n=name: self._makro_loeschen(n))
        btn_loeschen.pack(side="left", padx=5)

        status_label = ttk.Label(zeile, text="gestoppt", foreground="#a6adc8", width=24)
        status_label.pack(side="left", padx=5)

        self._makro_zeilen_widgets[name] = {
            "btn_start": btn_start, "btn_stop": btn_stop, "btn_bearbeiten": btn_bearbeiten,
            "btn_loeschen": btn_loeschen, "status_label": status_label,
        }

    def _makro_bearbeiten(self, name):
        """Laedt 'name' in den vollstaendigen Bot-Skripte-Editor (siehe
        aktion_editor.AktionsSkriptTab._skript_laden()) und wechselt dorthin
        - MAKRO TOOLS selbst hat keinen eigenen Schritt-Editor (bewusst, um
        ihn nicht zu duplizieren), sondern startet/verwaltet nur. Funktioniert
        auch, waehrend das Skript gerade laeuft: die laufende Instanz hat
        ihre Schritte bereits beim Start geladen (siehe
        makro_manager.MakroManager.starte_makro()) und ist von spaeteren
        Bearbeitungen/dem naechsten Speichern unberuehrt, bis sie neu
        gestartet wird."""
        if self.tab_bot_skripte is None:
            messagebox.showwarning("Bearbeiten", "Bot-Skripte-Editor nicht verfuegbar.")
            return
        self.tab_bot_skripte._skript_laden(name)
        self.notebook.select(self.tab_bot_skripte)

    def _makro_start(self, name):
        """Startet 'name' mit der in der Zeile gewaehlten Prioritaet/
        Fenster-Zuordnung. Bei "Alle Fenster" (Standard) UND mehreren gerade
        offenen Spielfenstern startet makro_manager.starte_makro_alle_fenster()
        automatisch je EINE isolierte Instanz PRO Fenster (siehe
        Aufgabenstellung "VERHALTEN BEI MEHREREN FENSTERN + GLEICHEM
        SKRIPT") - bei hoechstens einem gefundenen Fenster ist das Ergebnis
        identisch zu einer einzelnen, nicht isolierten Instanz (bisheriges
        Verhalten)."""
        prioritaet = self._makro_prioritaet_vars[name].get()
        fenster_wahl = self._makro_fenster_vars[name].get()
        schritt_log = lambda makro_name, zeile: self.root.after(0, lambda: self._log_fish(zeile))
        try:
            if fenster_wahl == FENSTER_AUSWAHL_ALLE:
                self.makro_manager.starte_makro_alle_fenster(name, prioritaet, schritt_log=schritt_log)
            else:
                fenster_liste = fenster_modul.alle_spielfenster_finden()
                nummer = int(fenster_wahl.replace("Fenster", "").strip())
                treffer = next((f for f in fenster_liste if f["nummer"] == nummer), None)
                if treffer is None:
                    messagebox.showerror(
                        "Makro starten",
                        "'%s' ist gerade nicht (mehr) offen - bitte 'Aktualisieren' klicken." % fenster_wahl)
                    return
                self.makro_manager.starte_makro(
                    name, prioritaet, schritt_log=schritt_log,
                    fenster_hwnd=treffer["hwnd"], instanz_key=name, fenster_label=fenster_wahl)
        except MakroManagerFehler as e:
            messagebox.showerror("Makro starten", str(e))

    def _makro_stop(self, name):
        """Stoppt ALLE laufenden Instanzen von 'name' - bei "Alle Fenster"-
        Fan-out (siehe _makro_start()) i.d.R. mehrere gleichzeitig laufende,
        je fenster-isolierte Instanzen (siehe
        makro_manager.stoppe_alle_instanzen())."""
        if not self.makro_manager.stoppe_alle_instanzen(name):
            self._log_makro("Makro '%s' laeuft gerade nicht." % name)

    def _makro_loeschen(self, name):
        """Loescht ein Skript unwiderruflich (aktion_<name>.json) - blockiert,
        waehrend es gerade laeuft (Datei unter einem laufenden Makro
        wegzuziehen waere verwirrend, auch wenn es technisch nicht abstuerzen
        wuerde - die Schritte sind zu Laufzeitbeginn bereits eingelesen)."""
        if self.makro_manager.makro_laeuft(name):
            messagebox.showwarning("Skript loeschen",
                                   "'%s' laeuft gerade - bitte zuerst stoppen." % name)
            return
        if not messagebox.askyesno("Skript loeschen",
                                   "Skript '%s' wirklich unwiderruflich loeschen?" % name):
            return
        aktion_skript.skript_loeschen(name)
        self._log_makro("Skript geloescht: %s" % name)
        self._makro_skriptlisten_aktualisieren()

    def _makro_stoppe_alle(self):
        gestoppt = self.makro_manager.stoppe_alle()
        self._log_makro("Alle Makros gestoppt: %s" % ", ".join(gestoppt) if gestoppt
                        else "Kein Makro lief gerade.")

    def _makro_neues_skript(self):
        """Legt ein neues, LEERES Skript an und wechselt zum Bot-Skripte-
        Reiter, wo die vorhandene Editor-Oberflaeche (aktion_editor.py) die
        eigentlichen Schritte bearbeiten laesst - MAKRO TOOLS dupliziert
        diesen Editor bewusst nicht, sondern startet/verwaltet nur."""
        name = simpledialog.askstring("Neues Skript", "Name des neuen Skripts:")
        if not name:
            return
        name = name.strip()
        if not name or any(z in name for z in ("/", "\\", "..")):
            messagebox.showerror("Neues Skript", "Ungueltiger Name.")
            return
        if name in aktion_skript.verfuegbare_skripte():
            messagebox.showerror("Neues Skript", "Ein Skript mit diesem Namen existiert bereits.")
            return
        aktion_skript.skript_speichern(name, [])
        self._log_makro("Neues (leeres) Skript angelegt: %s" % name)
        self._makro_liste_neu_aufbauen()
        self._refresh_fish_makro_combo()
        if self.tab_bot_skripte is not None:
            self.notebook.select(self.tab_bot_skripte)
        messagebox.showinfo("Neues Skript",
                            "Leeres Skript '%s' angelegt - Schritte jetzt im Bot-Skripte-Reiter "
                            "bearbeiten." % name)

    def _makro_speichern_unter(self):
        """Dupliziert ein vorhandenes Skript unter einem neuen Namen - nutzt
        dieselbe Lade-/Speicherlogik wie der Bot-Skripte-Editor
        (aktion_skript.skript_laden()/skript_speichern())."""
        namen = aktion_skript.verfuegbare_skripte()
        if not namen:
            messagebox.showwarning("Speichern unter", "Keine Skripte vorhanden.")
            return
        quelle = simpledialog.askstring(
            "Speichern unter", "Vorhandenes Skript (Quelle):\n%s" % ", ".join(namen))
        if not quelle:
            return
        if quelle not in namen:
            messagebox.showerror("Speichern unter", "Skript '%s' nicht gefunden." % quelle)
            return
        ziel = simpledialog.askstring("Speichern unter", "Neuer Name:")
        if not ziel:
            return
        ziel = ziel.strip()
        if not ziel or any(z in ziel for z in ("/", "\\", "..")):
            messagebox.showerror("Speichern unter", "Ungueltiger Name.")
            return
        try:
            schritte = aktion_skript.skript_laden(quelle)
        except Exception as e:
            messagebox.showerror("Speichern unter", "Konnte '%s' nicht laden: %s" % (quelle, e))
            return
        aktion_skript.skript_speichern(ziel, schritte)
        self._log_makro("Skript '%s' als '%s' gespeichert." % (quelle, ziel))
        self._makro_liste_neu_aufbauen()
        self._refresh_fish_makro_combo()

    def _makro_status_polling(self):
        """Aktualisiert alle Status-Labels/Buttons periodisch (1x/s) anhand
        von makro_manager.laufende_makros() - laeuft dauerhaft ueber
        self.root.after() weiter (die Zeilen existieren fuer die gesamte
        Lebensdauer des Fensters, kein Abschalten noetig).

        Gruppiert nach 'basis_name' statt 'name' (instanz_key), da bei einem
        "Alle Fenster"-Fan-out (siehe _makro_start()/
        makro_manager.starte_makro_alle_fenster()) MEHRERE Instanzen
        DESSELBEN Skripts gleichzeitig laufen koennen, aber genau EINE Zeile
        im MAKRO TOOLS-Reiter dafuer existiert - die Zeile zeigt in dem Fall
        alle laufenden Fenster-Instanzen zusammengefasst an."""
        instanzen_je_skript = {}
        for e in self.makro_manager.laufende_makros():
            instanzen_je_skript.setdefault(e["basis_name"], []).append(e)

        for name, widgets in self._makro_zeilen_widgets.items():
            instanzen = instanzen_je_skript.get(name, [])
            laufende = [e for e in instanzen if e["laeuft"]]

            if not laufende:
                if instanzen:
                    text = instanzen[-1]["status"].lower()
                else:
                    text = "gestoppt"
                widgets["status_label"].config(text=text, foreground="#a6adc8")
                widgets["btn_start"].config(state="normal")
                widgets["btn_stop"].config(state="disabled")
                widgets["btn_loeschen"].config(state="normal")
            else:
                if len(laufende) == 1 and laufende[0]["fenster_label"] is None:
                    text = "laeuft (%s, %.0fs)" % (laufende[0]["prioritaet"], laufende[0]["laufzeit_s"])
                else:
                    text = "laeuft: " + ", ".join(
                        "%s (%.0fs)" % (e["fenster_label"] or "?", e["laufzeit_s"]) for e in laufende)
                widgets["status_label"].config(text=text, foreground="#a6e3a1")
                widgets["btn_start"].config(state="disabled")
                widgets["btn_stop"].config(state="normal")
                widgets["btn_loeschen"].config(state="disabled")
        self.root.after(1000, self._makro_status_polling)

    def _log_makro(self, msg):
        """Schreibt eine Zeile ins MAKRO TOOLS-Log. Muss aufrufbar sein,
        BEVOR die GUI-Widgets existieren (self.makro_manager wird in
        __init__() bereits mit dieser Methode als log-Callback erzeugt,
        lange vor _build_makro_tab()) UND aus einem Nicht-GUI-Thread heraus
        (Makro-Threads in makro_manager.py) - deshalb hasattr()-Fallback auf
        print() plus root.after()-Marshalling fuer den Widget-Zugriff."""
        zeile = "[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg)
        if not hasattr(self, "makro_log"):
            print(zeile, end="")
            return

        def schreiben():
            self.makro_log.insert("end", zeile)
            self.makro_log.see("end")
        self.root.after(0, schreiben)

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

        # HID-Maus (serielles Text-Protokoll, Klick-Bestaetigung)
        hid = ttk.LabelFrame(frame, text="HID-Maus (serielles Text-Protokoll)")
        hid.pack(fill="x", padx=20, pady=10)

        ttk.Label(hid, text="Port:").grid(row=0, column=0, padx=10, pady=8)
        self.hid_port_entry = ttk.Entry(hid, width=12)
        self.hid_port_entry.grid(row=0, column=1, padx=5)
        # Leer lassen (nicht "COM6" hart vorbelegen) - ein leeres Feld loest
        # in _hid_maus_init()/_hid_verbinden() die Auto-Erkennung ueber
        # HIDMaus(port="") aus (siehe hid_maus._port_auto_finden()).
        self.hid_port_entry.insert(0, self.hid_port)

        ttk.Button(hid, text="Verbinden", command=self._hid_verbinden).grid(row=0, column=2, padx=(10, 3))
        ttk.Button(hid, text="Trennen", command=self._hid_trennen).grid(row=0, column=3, padx=3)
        # Status spiegelt eine evtl. schon beim Start aufgebaute Verbindung
        if self.hid_maus:
            start_txt, start_farbe = "Verbunden (%s)" % self.hid_port, "#a6e3a1"
        else:
            start_txt, start_farbe = "Nicht verbunden", "#f38ba8"
        self.lbl_hid_status = ttk.Label(hid, text=start_txt, foreground=start_farbe)
        self.lbl_hid_status.grid(row=0, column=4, padx=10)

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

    def _hid_verbinden(self):
        """Verbindet (oder verbindet neu) die HID-Maus mit dem Port aus dem
        Feld - leeres Feld loest wie in _hid_maus_init() die Auto-Erkennung
        aus, statt einen Port zu verlangen."""
        if not HID_OK:
            messagebox.showwarning("HID-Maus", "HID-Maus-Modul nicht verfuegbar:\n%s" % HID_IMPORT_ERR)
            return
        port = self.hid_port_entry.get().strip()
        # bestehende Verbindung zuerst sauber schliessen
        if self.hid_maus:
            self.hid_maus.schliessen()
            self.hid_maus = None
        try:
            maus = HIDMaus(port)
            if not maus.port:
                self._set_hid_status("Nicht verbunden", "#f38ba8")
                self._log_fish("Kein Arduino gefunden (weder Port angegeben "
                               "noch per Auto-Erkennung erkannt).")
                messagebox.showwarning(
                    "HID-Maus",
                    "Kein Arduino gefunden (weder Port angegeben noch per "
                    "Auto-Erkennung erkannt).")
                return
            if maus.verbinden():
                self.hid_maus = maus
                self.hid_port = maus.port
                self._set_hid_status("Verbunden (%s)" % maus.port, "#a6e3a1")
                self._log_fish("HID-Maus verbunden auf %s." % maus.port)
                messagebox.showinfo("HID-Maus", "Verbunden auf %s" % maus.port)
            else:
                self.hid_maus = None
                self._set_hid_status("Nicht verbunden", "#f38ba8")
                self._log_fish("HID-Maus nicht verbunden (%s)." % maus.port)
                messagebox.showwarning("HID-Maus", "Nicht verbunden auf %s." % maus.port)
        except Exception as e:
            self.hid_maus = None
            self._set_hid_status("Nicht verbunden", "#f38ba8")
            self._log_fish("HID-Maus Fehler (%s): %s" % (port or "auto", e))
            messagebox.showwarning("HID-Maus", "Fehler: %s" % e)

    def _hid_trennen(self):
        """Trennt die HID-Maus-Verbindung (falls verbunden)."""
        if self.hid_maus:
            self.hid_maus.schliessen()
            self.hid_maus = None
            self._log_fish("HID-Maus getrennt.")
        self._set_hid_status("Nicht verbunden", "#f38ba8")

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

def _report_callback(exc, val, tb):
    with open("tk_error.log", "a") as f:
        f.write("".join(traceback.format_exception(exc, val, tb)))
        f.write("\n---\n")

if __name__ == "__main__":
    import tkinter as tk
    try:
        from tkinter import Tk
        Tk.report_callback_exception = _report_callback
    except Exception:
        pass
    main()


def _ensure_admin():
    import ctypes, sys, os
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
    except:
        return True
    script = os.path.abspath(sys.argv[0]) if sys.argv and os.path.exists(sys.argv[0]) else os.path.abspath(__file__)
    ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, '"%s"' % script, None, 1)
    return False

if __name__ == '__main__':
    if not _ensure_admin():
        sys.exit()
