import time
import win32gui
from hid_maus import HIDMaus

m = HIDMaus('COM6')
m.verbinden()

hwnd = win32gui.FindWindow(None, "METIN2")
if hwnd:
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(1.0)

print("Druecke SPACE in 2 Sekunden...")
time.sleep(2.0)

print(m.taste_druecken('SPACE'))
time.sleep(1.0)

print(m.taste_druecken('SPACE'))
time.sleep(1.0)

m.schliessen()
print("Fertig.")
