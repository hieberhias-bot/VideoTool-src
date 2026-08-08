import time
from hid_maus import HIDMaus

m = HIDMaus("COM6")
print("Verbinden:", m.verbinden())
time.sleep(1)

print("a:", m.taste_druecken("a"))
time.sleep(0.3)
print("ENTER:", m.taste_druecken("ENTER"))
time.sleep(0.3)
print("F:", m.taste_druecken("F"))
time.sleep(0.3)
print("DOWN:", m.taste_druecken("DOWN"))
time.sleep(0.3)
print("SPACE:", m.taste_druecken("SPACE"))
time.sleep(0.5)

m.schliessen()
print("FERTIG")
