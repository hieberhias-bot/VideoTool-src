import cv2
import numpy as np

# Zeige das Wasser-Bereich als Text-Art, um den Fisch zu sehen
# Versuche verschiedene Helligkeitsbereiche
img = cv2.imread("live_popup_005.png")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

print("=== live_popup_005.png - Graustufen-Karte ===")
print("Zeichen: # = sehr hell, . = hell, + = mittel, leer = dunkel")
print()
for y in range(0, 639, 4):
    zeile = ""
    for x in range(0, 816, 3):
        v = gray[y, x]
        if v > 235:
            zeile += "#"
        elif v > 200:
            zeile += "."
        elif v > 150:
            zeile += "+"
        elif v > 100:
            zeile += "o"
        else:
            zeile += " "
    print(zeile)
