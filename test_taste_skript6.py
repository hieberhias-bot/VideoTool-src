import time
import win32gui
from hid_maus import HIDMaus

m = HIDMaus('COM6')
m.verbinden()

hwnd = win32gui.FindWindow(None, 'METIN2')
print('HWND:', hwnd)
win32gui.SetForegroundWindow(hwnd)
time.sleep(0.2)  # Exakt wie _fokussiere_metin2()

print('SPACE 1...')
print(m.taste_druecken('SPACE'))
time.sleep(1.0)

m.schliessen()
print('Fertig.')
