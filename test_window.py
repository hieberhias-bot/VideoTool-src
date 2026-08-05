import pygetwindow as gw

windows = gw.getAllTitles()
print("=== Alle Fenster-Titel ===")
for w in windows:
    if w:
        print(w)
print("=== Ende ===")
