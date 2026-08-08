import time
import win32gui
from hid_maus import HIDMaus

m = HIDMaus('COM6')
m.verbinden()

hwnd = win32gui.FindWindow(None, 'METIN2')
print('HWND:', hwnd)
win32gui.SetForegroundWindow(hwnd)
time.sleep(3.0)

# ENTER, dann 1-9, dann ENTER, dann 1
for taste in ['ENTER', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'ENTER', '1']:
    print(taste, 'druecken...')
    print(m.taste_druecken(taste))
    time.sleep(0.1)
    print(taste, 'loslassen...')
    print(m.taste_loslassen(taste))
    time.sleep(0.5)

m.schliessen()
print('Fertig.')
