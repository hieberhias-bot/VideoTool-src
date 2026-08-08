import io
pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\fish_bot.py"
with io.open(pfad, "r", encoding="utf-8") as f:
    code = f.read()

alt = "        klick_gesendet = True\n        klick_erfolg = maus.klick_links()"
neu = "        klick_gesendet = True\n        klick_erfolg = maus.klick_links()\n        _logger.info(\"KLICK GESENDET: ziel=(%d, %d) erfolg=%s\", bildschirm_x, bildschirm_y, klick_erfolg)"

if alt in code:
    code = code.replace(alt, neu)
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(code)
    print("PATCH_OK - Klick-Log hinzugefuegt")
else:
    print("PATCH_FEHLER - Block nicht gefunden")
