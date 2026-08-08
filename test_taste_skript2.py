import time
import win32gui
from hid_maus import HIDMaus
from aktion_skript import _fokussiere_metin2

m = HIDMaus('COM6')
m.verbinden()

# Genau wie im Bot-Skript
_fokussiere_metin2()
time.sleep(1.0)

print("SPACE 1...")
print(m.taste_druecken('SPACE'))
time.sleep(1.0)

print("SPACE 2...")
print(m.taste_druecken('SPACE'))
time.sleep(1.0)

m.schliessen()
print("Fertig.")
