import time
import win32gui
from hid_maus import HIDMaus
from aktion_skript import _fokussiere_metin2

m = HIDMaus('COM6')
m.verbinden()

_fokussiere_metin2()
time.sleep(2.0)  # Die 2.0s, die funktioniert haben

print("SPACE 1...")
print(m.taste_druecken('SPACE'))
time.sleep(1.0)

print("SPACE 2...")
print(m.taste_druecken('SPACE'))
time.sleep(1.0)

m.schliessen()
print("Fertig.")
