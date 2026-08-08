import cv2
import numpy as np

img = cv2.imread(r"C:\Users\vm1\Desktop\projekt\popup2.webp.png")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# Zeige Graustufen-Bild als ASCII
print("=== Graustufen-Bild (Helligkeit 0-255) ===")
print("@=sehr dunkel  #=dunkel  +=mittel  .=hell  ' '=sehr hell")
for y in range(0, 262, 3):
    zeile = ""
    for x in range(0, 286, 3):
        v = gray[y, x]
        if v < 60: zeile += "@"
        elif v < 110: zeile += "#"
        elif v < 160: zeile += "+"
        elif v < 210: zeile += "."
        else: zeile += " "
    print(zeile)

# Histogramm der Helligkeit
print("\n=== Helligkeits-Histogramm ===")
hist, bins = np.histogram(gray, bins=10, range=(0,255))
for i in range(10):
    bar = "#" * (hist[i] // 50)
    print(f"{bins[i]:3.0f}-{bins[i+1]:3.0f}: {hist[i]:6d} {bar}")
