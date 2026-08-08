import time
import win32gui
from hid_maus import HIDMaus

m = HIDMaus('COM6')
m.verbinden()

hwnd = win32gui.FindWindow(None, 'METIN2')
print('HWND:', hwnd)
win32gui.SetForegroundWindow(hwnd)
time.sleep(3.0)

print('SPACE...')
print(m.taste_druecken('SPACE'))
time.sleep(0.5)
print('SPACE loslassen...')
print(m.taste_loslassen('SPACE'))
time.sleep(0.5)

m.schliessen()
print('Fertig.')
