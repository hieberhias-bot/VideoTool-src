# -*- coding: utf-8 -*-
"""statistic_manager.py - Lauf-Statistiken fuer Sequenzen.

Speichert pro Sequenz eine Datei ``stats_<name>.json`` neben den anderen
Projektdateien. Erfasst Anzahl der Ausfuehrungen, Erfolge/Fehler,
Erfolgsquote und den letzten Lauf.
"""

import os
import json
from datetime import datetime

# Basisordner = Projekt-Hauptordner (eine Ebene ueber modules/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _standard_stats(name):
    return {
        "name": name,
        "ausfuehrungen": 0,
        "erfolge": 0,
        "fehler": 0,
        "letzter_lauf": None,
        "letzter_status": None,
        "letzte_dauer_s": None,
    }


class StatistikManager:
    """Liest und schreibt ``stats_<name>.json``."""

    def __init__(self, basis_dir=None):
        self.basis_dir = basis_dir or BASE_DIR

    # ---------- Pfad-Helfer ----------
    def _pfad(self, name):
        return os.path.join(self.basis_dir, "stats_%s.json" % name)

    # ---------- Lesen ----------
    def get_stats(self, name):
        """Gibt das Statistik-Dict einer Sequenz zurueck (mit Defaults)."""
        pfad = self._pfad(name)
        stats = _standard_stats(name)
        if os.path.exists(pfad):
            try:
                with open(pfad, "r", encoding="utf-8") as f:
                    daten = json.load(f)
                if isinstance(daten, dict):
                    stats.update(daten)
                    stats["name"] = name
            except Exception:
                pass
        return stats

    def get_all_stats(self):
        """Alle vorhandenen Statistiken als ``{name: stats}``."""
        ergebnis = {}
        try:
            dateien = os.listdir(self.basis_dir)
        except OSError:
            return ergebnis
        for f in sorted(dateien):
            if f.startswith("stats_") and f.endswith(".json"):
                name = f[len("stats_"):-len(".json")]
                ergebnis[name] = self.get_stats(name)
        return ergebnis

    # ---------- Schreiben ----------
    def _speichern(self, stats):
        pfad = self._pfad(stats["name"])
        try:
            with open(pfad, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    def update_stats(self, name, erfolg, dauer_s=None, status=None):
        """Verbucht einen abgeschlossenen Lauf.

        erfolg  -- True bei erfolgreichem Durchlauf, sonst False
        dauer_s -- Laufdauer in Sekunden (optional)
        status  -- Freitext-Status (z.B. "ok", "abgebrochen", Fehlertext)
        """
        stats = self.get_stats(name)
        stats["ausfuehrungen"] += 1
        if erfolg:
            stats["erfolge"] += 1
        else:
            stats["fehler"] += 1
        stats["letzter_lauf"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if status is not None:
            stats["letzter_status"] = status
        else:
            stats["letzter_status"] = "ok" if erfolg else "fehler"
        if dauer_s is not None:
            try:
                stats["letzte_dauer_s"] = round(float(dauer_s), 2)
            except (TypeError, ValueError):
                pass
        self._speichern(stats)
        return stats

    def delete_stats(self, name):
        """Loescht die Statistik-Datei einer Sequenz."""
        pfad = self._pfad(name)
        if os.path.exists(pfad):
            try:
                os.remove(pfad)
                return True
            except OSError:
                return False
        return False

    # ---------- Abgeleitete Werte ----------
    def get_erfolgsquote(self, name):
        """Erfolgsquote in Prozent (0..100). 0.0 wenn keine Laeufe."""
        stats = self.get_stats(name)
        ausf = stats.get("ausfuehrungen", 0)
        if not ausf:
            return 0.0
        return round(100.0 * stats.get("erfolge", 0) / ausf, 1)

    def get_letzter_lauf(self, name):
        """Zeitstempel des letzten Laufs oder None."""
        return self.get_stats(name).get("letzter_lauf")
