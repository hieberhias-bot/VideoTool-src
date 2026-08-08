import io
pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\hid_maus.py"
with io.open(pfad, "r", encoding="utf-8") as f:
    code = f.read()

alt = "def maus_bewegen_abs(self, x, y, toleranz=15, max_versuche=10):"
neu = "def maus_bewegen_abs(self, x, y, toleranz=30, max_versuche=6):"
if alt in code:
    code = code.replace(alt, neu)
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(code)
    print("PATCH_OK - toleranz 15->30, max_versuche 10->6")
else:
    print("PATCH_FEHLER")
