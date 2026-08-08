import io

pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\fish_bot.py"
with io.open(pfad, "r", encoding="utf-8") as f:
    code = f.read()

alt = '''def maus_bewegen(x, y):
    """Bewegt den Cursor per Windows-API an eine Bildschirmposition.

    hid_maus.py bietet fuer den Klick-Anwendungsfall keinen eigenen
    Bewegungsbefehl, daher erfolgt die Bewegung ueber SetCursorPos; der
    eigentliche Klick laeuft weiterhin ueber die hardware-verifizierte HIDMaus.
    """
    user32.SetCursorPos(int(x), int(y))'''

neu = '''def maus_bewegen(x, y, maus=None):
    """Bewegt den Cursor an eine absolute Bildschirmposition.

    Nutzt die HID-Maus (maus.maus_bewegen -> MOVE_ABS), da SetCursorPos in
    dieser Session nicht funktioniert. Falls keine HID-Maus uebergeben wird,
    faellt die Funktion auf die Windows-API zurueck.
    """
    if maus is not None:
        maus.maus_bewegen(int(x), int(y))
    else:
        user32.SetCursorPos(int(x), int(y))'''

if alt in code:
    code = code.replace(alt, neu)
    with io.open(pfad, "w", encoding="utf-8") as f:
        f.write(code)
    print("PATCH_OK - lokale maus_bewegen nutzt jetzt HID-Maus")
else:
    print("PATCH_FEHLER - Block nicht gefunden")
    print("Enthalten?", "def maus_bewegen(x, y):" in code)
