import re
p = r"C:\Users\vm1\Desktop\VideoTool-src\hid_maus.py"
s = open(p, encoding="utf-8").read()
start = s.index("    def maus_bewegen_abs")
end = s.index("    def ", start + 10)
neu = """    def maus_bewegen_abs(self, x, y):
        \"\"\"Absolute Bewegung - delegiert an maus_bewegen (praezise, ohne Korrekturschleife).\"\"\"
        return self.maus_bewegen(x, y)

"""
s = s[:start] + neu + s[end:]
open(p, "w", encoding="utf-8").write(s)
print("PATCH_OK")
