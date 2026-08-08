import sys
sys.path.insert(0, r"C:\Users\vm1\Desktop\VideoTool-src")
from hid_maus import HIDMaus

m = HIDMaus("COM6")
print("Verbunden:", m.verbinden())

print("Taste druecken (a):", m.taste_druecken("a"))
print("Taste druecken (ENTER):", m.taste_druecken("ENTER"))
print("F-Taste:", m.taste_druecken("F5"))
print("Pfeil unten:", m.taste_druecken("DOWN"))
