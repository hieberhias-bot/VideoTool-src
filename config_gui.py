"""
Simple desktop GUI (tkinter) to view and change the tool settings.

Run with:  python config_gui.py  [--config tool_config.json]
Or without a console window:  pythonw config_gui.py

Each config section (GENERAL, DETECTION, ...) gets its own scrollable tab in a
notebook, so the growing number of settings stays readable. Every setting uses
a fitting widget:
  - choice  -> dropdown
  - bool    -> checkbox
  - int/float -> spinbox with min/max
  - str     -> text field

Values are validated through ToolConfig on save, so out-of-range or wrong
input is rejected with a message instead of being written to disk. The Save /
Defaults / Close buttons and the status bar are shared across all tabs.
"""

import argparse
import tkinter as tk
from tkinter import ttk, messagebox

from config import ToolConfig


class ConfigGUI:
    """
    A small tkinter window that edits a ToolConfig configuration.
    """

    def __init__(self, root: tk.Tk, config: ToolConfig):
        """
        Builds the GUI.

        Args:
            root (tk.Tk): The tkinter root window.
            config (ToolConfig): The configuration object to edit.
        """
        self.root = root
        self.config = config
        # Maps setting key -> (tk variable, widget type) so we can read the
        # user input back on save.
        self.__vars = {}

        root.title("Video-Tool  -  Einstellungen")
        root.geometry("780x560")
        root.minsize(640, 480)

        self.__build_header()
        self.__build_sections()
        self.__build_buttons()
        self.__build_statusbar()

        self.__load_into_widgets()

    def __build_header(self) -> None:
        """Builds the title header of the window."""
        header = ttk.Frame(self.root, padding=(16, 12, 16, 4))
        header.pack(fill="x")
        ttk.Label(header, text="Video-Tool Einstellungen",
                  font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(header,
                  text="Werte anpassen und unten auf \"Speichern\" klicken.",
                  foreground="#555").pack(anchor="w")

    def __build_sections(self) -> None:
        """Builds a notebook with one scrollable tab per config section."""
        body = ttk.Frame(self.root, padding=(16, 4))
        body.pack(fill="both", expand=True)

        notebook = ttk.Notebook(body)
        notebook.pack(fill="both", expand=True)

        for section, settings in self.config.SCHEMA.items():
            tab = self.__build_scrollable_tab(notebook, section)
            tab.columnconfigure(1, weight=1)
            for row, (key, spec) in enumerate(settings.items()):
                self.__add_setting_row(tab, row, key, spec)

    @staticmethod
    def __pretty(section: str) -> str:
        """Turns a section key like 'COLOR_DETECTION' into 'Color Detection'."""
        return section.replace("_", " ").title()

    def __build_scrollable_tab(self, notebook: ttk.Notebook, section: str) -> ttk.Frame:
        """
        Adds a vertically scrollable tab to the notebook and returns the inner
        frame that setting rows should be placed into.

        Args:
            notebook (ttk.Notebook): The notebook to add the tab to.
            section (str): The section key (used as the tab label).

        Returns:
            ttk.Frame: The scrollable content frame.
        """
        outer = ttk.Frame(notebook)
        notebook.add(outer, text=self.__pretty(section))

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(12, 8))

        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Keep the scroll region in sync with the content size, and stretch the
        # inner frame to the canvas width so widgets align to the right edge.
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(inner_id, width=e.width))

        # Mouse wheel scrolls whichever tab the pointer is currently over.
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        return inner

    def __add_setting_row(self, parent: ttk.Frame, row: int, key: str, spec: dict) -> None:
        """
        Places one setting (name + description + input widget) into a tab.

        Args:
            parent (ttk.Frame): The tab content frame.
            row (int): The logical row index within the tab.
            key (str): The setting name.
            spec (dict): The schema entry.
        """
        # Left: setting name + description underneath.
        label = ttk.Label(parent, text=key, font=("Segoe UI", 10, "bold"))
        label.grid(row=row * 2, column=0, sticky="w", pady=(6, 0))
        desc = ttk.Label(parent, text=self.__hint(spec),
                         foreground="#777", font=("Segoe UI", 8))
        desc.grid(row=row * 2 + 1, column=0, sticky="w", padx=(0, 16))

        # Right: the input widget.
        widget = self.__make_widget(parent, key, spec)
        widget.grid(row=row * 2, column=1, rowspan=2, sticky="e", padx=(12, 0))

    def __hint(self, spec: dict) -> str:
        """
        Builds the small grey hint line under a setting name.

        Args:
            spec (dict): The schema entry of the setting.

        Returns:
            str: description plus allowed range/choices.
        """
        if spec["type"] == "choice":
            allowed = " / ".join(spec["choices"])
            return f"{spec['desc']}  -  Auswahl: {allowed}"
        if spec["type"] in ("int", "float"):
            return f"{spec['desc']}  -  Bereich: {spec['min']} bis {spec['max']}"
        return spec["desc"]

    def __make_widget(self, parent, key: str, spec: dict):
        """
        Creates the correct input widget for a setting and stores its variable.

        Args:
            parent: The parent frame.
            key (str): The setting name.
            spec (dict): The schema entry.

        Returns:
            The created tkinter widget.
        """
        vtype = spec["type"]

        if vtype == "bool":
            var = tk.BooleanVar()
            widget = ttk.Checkbutton(parent, variable=var, text="aktiv")
            self.__vars[key] = (var, vtype)
            return widget

        if vtype == "choice":
            var = tk.StringVar()
            widget = ttk.Combobox(parent, textvariable=var, state="readonly",
                                  values=spec["choices"], width=18)
            self.__vars[key] = (var, vtype)
            return widget

        if vtype in ("int", "float"):
            var = tk.StringVar()
            step = 1 if vtype == "int" else 0.01
            widget = ttk.Spinbox(parent, textvariable=var, width=18,
                                 from_=spec["min"], to=spec["max"],
                                 increment=step)
            self.__vars[key] = (var, vtype)
            return widget

        # Plain string.
        var = tk.StringVar()
        widget = ttk.Entry(parent, textvariable=var, width=20)
        self.__vars[key] = (var, vtype)
        return widget

    def __build_buttons(self) -> None:
        """Builds the action buttons at the bottom."""
        bar = ttk.Frame(self.root, padding=(16, 4, 16, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Speichern",
                   command=self.on_save).pack(side="right", padx=4)
        ttk.Button(bar, text="Standardwerte",
                   command=self.on_reset).pack(side="right", padx=4)
        ttk.Button(bar, text="Schliessen",
                   command=self.root.destroy).pack(side="right", padx=4)

    def __build_statusbar(self) -> None:
        """Builds the status line at the very bottom."""
        self.__status = tk.StringVar(value=f"Datei: {self.config._ToolConfig__path}")
        status = ttk.Label(self.root, textvariable=self.__status,
                           relief="sunken", anchor="w", padding=(8, 3))
        status.pack(fill="x", side="bottom")

    def __load_into_widgets(self) -> None:
        """Copies the current config values into the widgets."""
        for key, (var, vtype) in self.__vars.items():
            value = self.config.get(key)
            if vtype == "bool":
                var.set(bool(value))
            else:
                var.set(str(value))

    def on_save(self) -> None:
        """
        Reads all widgets, validates them through ToolConfig and saves to disk.
        On the first invalid value a message box is shown and nothing is saved.
        """
        # Validate everything first into a temp config so a bad value in the
        # middle never leaves a half-applied state.
        for key, (var, vtype) in self.__vars.items():
            try:
                self.config.set(key, var.get())
            except (ValueError, TypeError) as e:
                messagebox.showerror(
                    "Ungueltiger Wert",
                    f"Einstellung '{key}':\n{e}")
                self.__status.set(f"Nicht gespeichert - Fehler bei '{key}'")
                return

        try:
            self.config.save()
        except ValueError as e:
            messagebox.showerror(
                "Unplausible Werte",
                f"Bitte korrigieren:\n{e}")
            self.__status.set("Nicht gespeichert - unplausible Werte")
            return
        except OSError as e:
            messagebox.showerror("Fehler beim Speichern", str(e))
            return

        self.__load_into_widgets()  # reflect any coercion (e.g. "0.85" float)
        self.__status.set("Gespeichert.")
        messagebox.showinfo("Gespeichert", "Einstellungen wurden gespeichert.")

    def on_reset(self) -> None:
        """Resets all settings to their defaults (after a confirmation)."""
        if not messagebox.askyesno(
                "Zuruecksetzen",
                "Alle Einstellungen auf Standardwerte zuruecksetzen?"):
            return
        self.config.reset()
        self.__load_into_widgets()
        self.__status.set("Auf Standardwerte zurueckgesetzt "
                          "(noch nicht gespeichert).")


def main():
    parser = argparse.ArgumentParser(
        description="GUI zum Bearbeiten der Video-Tool-Einstellungen")
    parser.add_argument("--config", default="tool_config.json",
                        help="Pfad zur Konfigurationsdatei")
    args = parser.parse_args()

    config = ToolConfig(args.config)

    root = tk.Tk()
    try:
        # Use a slightly nicer theme if available.
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    ConfigGUI(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
