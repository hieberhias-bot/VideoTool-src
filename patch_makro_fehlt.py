# -*- coding: utf-8 -*-
pfad = r"command_center.py"
with open(pfad, "r", encoding="utf-8") as f:
    code = f.read()
if "def _start_fishbot_alle_fenster_mit_makro" in code:
    print("Methode existiert bereits - nichts zu tun")
else:
    anker = "    def _start_fishbot_als_makro("
    if anker not in code:
        print("ANKER NICHT GEFUNDEN")
    else:
        neue_methode = "    def _start_fishbot_alle_fenster_mit_makro(self, skript_name, prioritaet=PRIORITAET_MITTEL):\n" \
            "        try:\n" \
            "            gestartet = self.makro_manager.fischbot_und_makro_starten_alle_fenster(\n" \
            "                skript_name, prioritaet=prioritaet, fischbot_prioritaet=PRIORITAET_HOCH)\n" \
            "        except MakroManagerFehler as e:\n" \
            "            self._log_fish('Fisch-Bot + paralleles Skript konnten nicht gestartet werden: %s' % e)\n" \
            "            self._fishbot_beendet('VERBINDUNGSFEHLER')\n" \
            "            return\n" \
            "        self._log_fish('Fisch-Bot + paralleles Skript '%s' auf %d Fenster verteilt gestartet.'\n" \
            "                       % (skript_name, len(gestartet)))\n" \
            "        self._warte_auf_fischbot_ende()\n" \
            "\n"
        code = code.replace(anker, neue_methode + anker, 1)
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(code)
        print("PATCH_OK - Methode eingefuegt")
