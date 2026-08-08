import io
for name in ["aktion_skript.py", "fish_bot.py"]:
    pfad = r"C:\Users\vm1\Desktop\VideoTool-src" + "\\" + name
    with io.open(pfad, "r", encoding="utf-8") as f:
        lines = f.readlines()
    print("===", name, "===")
    for i, l in enumerate(lines, 1):
        if "maus_bewegen(" in l:
            print("Zeile %d: %s" % (i, l.rstrip()))
            for j in range(max(1, i-3), min(len(lines)+1, i+4)):
                print("  %d: %s" % (j, lines[j-1].rstrip()))
            print("---")
