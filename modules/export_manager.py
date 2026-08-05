# -*- coding: utf-8 -*-
"""export_manager.py - Export/Import von Sequenzen als ZIP.

Drei Funktionen:
    export_sequenz(name, ziel_zip)  -- eine Sequenz + referenzierte
                                       trigger_/ablauf_/stats_-Dateien
    export_backup(ziel_zip)         -- alle Projekt-JSONs als Backup
    importieren(quell_zip)          -- JSON-Dateien aus einem ZIP zurueckspielen
"""

import os
import json
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Praefixe der Projektdateien, die zum Backup gehoeren
BACKUP_PRAEFIXE = ("sequenz_", "ablauf_", "trigger_", "stats_")
EXTRA_DATEIEN = ("tool_config.json",)


class ExportManager:
    def __init__(self, basis_dir=None):
        self.basis_dir = basis_dir or BASE_DIR

    # ---------- Helfer ----------
    def _pfad(self, dateiname):
        return os.path.join(self.basis_dir, dateiname)

    def _referenzierte_dateien(self, sequenz_name):
        """Ermittelt trigger_/ablauf_-Dateien, die eine Sequenz benutzt."""
        dateien = set()
        seq_datei = "sequenz_%s.json" % sequenz_name
        pfad = self._pfad(seq_datei)
        if not os.path.exists(pfad):
            return dateien
        dateien.add(seq_datei)
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                daten = json.load(f)
        except Exception:
            return dateien
        for schritt in daten.get("schritte", []):
            typ = (schritt.get("typ") or "").upper()
            wert = schritt.get("wert") or schritt.get("name") or ""
            if not wert:
                continue
            if typ == "TRIGGER":
                dateien.add("trigger_%s.json" % wert)
            elif typ == "ABLAUF":
                dateien.add("ablauf_%s.json" % wert)
        # Statistik mitnehmen, falls vorhanden
        stats_datei = "stats_%s.json" % sequenz_name
        if os.path.exists(self._pfad(stats_datei)):
            dateien.add(stats_datei)
        return dateien

    # ---------- Export: einzelne Sequenz ----------
    def export_sequenz(self, sequenz_name, ziel_zip):
        """Exportiert eine Sequenz samt referenzierter Dateien in ein ZIP."""
        dateien = self._referenzierte_dateien(sequenz_name)
        if not dateien:
            raise FileNotFoundError("Sequenz '%s' nicht gefunden." % sequenz_name)
        geschrieben = []
        with zipfile.ZipFile(ziel_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(dateien):
                pfad = self._pfad(name)
                if os.path.exists(pfad):
                    zf.write(pfad, arcname=name)
                    geschrieben.append(name)
        return geschrieben

    # ---------- Export: komplettes Backup ----------
    def export_backup(self, ziel_zip):
        """Exportiert alle Projekt-JSONs (Sequenzen, Ablaeufe, Trigger, Stats)."""
        geschrieben = []
        try:
            alle = os.listdir(self.basis_dir)
        except OSError:
            alle = []
        with zipfile.ZipFile(ziel_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(alle):
                ist_projekt = (name.endswith(".json") and
                               name.startswith(BACKUP_PRAEFIXE))
                if ist_projekt or name in EXTRA_DATEIEN:
                    pfad = self._pfad(name)
                    if os.path.isfile(pfad):
                        zf.write(pfad, arcname=name)
                        geschrieben.append(name)
        return geschrieben

    # ---------- Import ----------
    def importieren(self, quell_zip, ueberschreiben=True):
        """Spielt JSON-Dateien aus einem ZIP in den Basisordner zurueck.

        Gibt die Liste der importierten Dateinamen zurueck. Nur .json-Dateien
        werden akzeptiert; Pfad-Bestandteile werden aus Sicherheitsgruenden
        entfernt (kein Ausbruch aus dem Zielordner).
        """
        if not os.path.exists(quell_zip):
            raise FileNotFoundError("ZIP nicht gefunden: %s" % quell_zip)
        importiert = []
        uebersprungen = []
        with zipfile.ZipFile(quell_zip, "r") as zf:
            for eintrag in zf.namelist():
                basis = os.path.basename(eintrag)
                if not basis.endswith(".json"):
                    continue
                ziel = self._pfad(basis)
                if os.path.exists(ziel) and not ueberschreiben:
                    uebersprungen.append(basis)
                    continue
                with zf.open(eintrag) as quelle:
                    inhalt = quelle.read()
                with open(ziel, "wb") as f:
                    f.write(inhalt)
                importiert.append(basis)
        return {"importiert": importiert, "uebersprungen": uebersprungen}
