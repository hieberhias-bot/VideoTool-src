import io
pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\hid_maus.py"
with io.open(pfad, "r", encoding="utf-8") as f:
    code = f.read()

alt = """            x = max(0, min(1919, int(dx)))
            y = max(0, min(1079, int(dy)))"""
neu = """            x = max(0, min(1919, int(dx)))
            y = max(0, min(1079, int(dy)))
            # Firmware klemmt auf 1920x1080, aber die Session ist nur screen_h
            # hoch (z.B. 955). Windows skaliert das gesendete Y dann herunter:
            # 191 -> 191*955/1080 = 169 (die konstanten ~22px Abweichung).
            # Deshalb Y vorab in den 1080er-Raum hochskalieren, damit es im
            # screen_h-Raum korrekt ankommt.
            if self.screen_h and self.screen_h != 1080:
                y = int(round(y * (1080.0 / self.screen_h)))"""
if alt in code:
    code = code.replace(alt, neu)
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(code)
    print("PATCH_OK - Y-Skalierung eingefuegt")
else:
    print("PATCH_FEHLER - Basis-String nicht gefunden")
