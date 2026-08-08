import io
pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\fish_bot.py"
with io.open(pfad, "r", encoding="utf-8") as f:
    lines = f.readlines()
# Zeilen 270-300 (Funktion maus_bewegen)
print("=== Funktion maus_bewegen (270-300) ===")
for j in range(270, min(300, len(lines)+1)):
    print("%d: %s" % (j, lines[j-1].rstrip()))
# Zeilen 420-435 und 605-620 (Aufrufer)
print("=== Aufrufer 1 (420-435) ===")
for j in range(420, min(435, len(lines)+1)):
    print("%d: %s" % (j, lines[j-1].rstrip()))
print("=== Aufrufer 2 (605-620) ===")
for j in range(605, min(620, len(lines)+1)):
    print("%d: %s" % (j, lines[j-1].rstrip()))
