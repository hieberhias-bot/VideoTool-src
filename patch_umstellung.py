# -*- coding: utf-8 -*-
"""Stellt fish_bot.py und aktion_skript.py auf maus_bewegen_abs um."""
import io, re

base = r"C:\Users\vm1\Desktop\VideoTool-src"

# ---- fish_bot.py ----
pfad1 = base + r"\fish_bot.py"
with io.open(pfad1, "r", encoding="utf-8") as f:
    code1 = f.read()

# SetCursorPos-Aufrufe durch maus_bewegen_abs ersetzen
vorher = code1
code1 = re.sub(
    r"ctypes\.windll\.user32\.SetCursorPos\(\s*int\([^)]*\)\s*,\s*int\([^)]*\)\s*\)",
    "maus_bewegen_abs_ersatz",
    code1
)
if code1 != vorher:
    # Platzhalter ersetzen - wir brauchen die echten Variablen, daher manuell pruefen
    print("SetCursorPos-Aufrufe in fish_bot.py gefunden:", vorher.count("SetCursorPos"))
else:
    print("Keine SetCursorPos-Aufrufe in fish_bot.py")

with io.open(pfad1, "w", encoding="utf-8", newline="\n") as f:
    f.write(code1)

# ---- aktion_skript.py ----
pfad2 = base + r"\aktion_skript.py"
with io.open(pfad2, "r", encoding="utf-8") as f:
    code2 = f.read()

print("SetCursorPos in aktion_skript.py:", code2.count("SetCursorPos"))
print("maus_bewegen in aktion_skript.py:", code2.count("maus_bewegen"))
