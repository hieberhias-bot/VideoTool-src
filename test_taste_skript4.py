import time
import win32gui
from hid_maus import HIDMaus

m = HIDMaus('COM6')
m.verbinden()

# EXAKT wie in test_taste_skript.py (das funktioniert hat)
hwnd = win32gui.FindWindow(None, "METIN2")
print("HWND:", hwnd)
if hwnd:
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(1.0)

print("SPACE 1...")
print(m.taste_druecken('SPACE'))
time.sleep(1.0)

m.schliessen()
print("Fertig.")
