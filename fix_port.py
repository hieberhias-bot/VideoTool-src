import re
pfad = r"C:\Users\vm1\Desktop\VideoTool-src\hid_maus.py"
text = open(pfad, encoding="utf-8").read()
text = text.replace('COM5', 'COM6')
open(pfad, "w", encoding="utf-8").write(text)
print("Port auf COM6 geaendert")
