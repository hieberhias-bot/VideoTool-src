import sys, os
sys.path.insert(0, r"C:\Users\vm1\Desktop\VideoTool-src")
os.chdir(r"C:\Users\vm1\Desktop\VideoTool-src")
from hid_maus import HIDMaus
m = HIDMaus("COM6")
print("Verbinde...")
m.verbinden()
print("Verbunden:", m.verbunden)
