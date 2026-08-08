# -*- coding: utf-8 -*-
pfad = r"command_center.py"
with open(pfad, "r", encoding="utf-8") as f:
    code = f.read()
kaputt = "self._log_fish('Fisch-Bot + paralleles Skript '%s' auf %d Fenster verteilt gestartet.'\n                       % (skript_name, len(gestartet)))"
gut = "self._log_fish('Fisch-Bot + paralleles Skript \"%s\" auf %d Fenster verteilt gestartet.'\n                       % (skript_name, len(gestartet)))"
if kaputt in code:
    code = code.replace(kaputt, gut, 1)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(code)
    print("REPARIERT")
else:
    print("Kaputte Zeile nicht gefunden - pruefe manuell")
