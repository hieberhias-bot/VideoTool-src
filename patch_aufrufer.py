import io

pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\fish_bot.py"
with io.open(pfad, "r", encoding="utf-8") as f:
    code = f.read()

# Aufrufer 1 (Wurm-Klick, Zeile 427)
alt1 = "    maus_bewegen(bildschirm_x, bildschirm_y)\n    if not maus.klick_rechts():"
neu1 = "    maus_bewegen(bildschirm_x, bildschirm_y, maus)\n    if not maus.klick_rechts():"

# Aufrufer 2 (Ring-Klick, Zeile 614)
alt2 = "        maus_bewegen(bildschirm_x, bildschirm_y)\n        klick_gesendet = True"
neu2 = "        maus_bewegen(bildschirm_x, bildschirm_y, maus)\n        klick_gesendet = True"

anzahl = 0
if alt1 in code:
    code = code.replace(alt1, neu1)
    anzahl += 1
if alt2 in code:
    code = code.replace(alt2, neu2)
    anzahl += 1

if anzahl == 2:
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(code)
    print("PATCH_OK - beide Aufrufer uebergeben maus")
else:
    print("PATCH_FEHLER - nur %d/2 Bloecke gefunden" % anzahl)
