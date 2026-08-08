import cv2
import numpy as np

img = cv2.imread(r"C:\Users\vm1\Desktop\projekt\popup2.webp.png")
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# Der Fisch: mittelgrau (100-170) INNERHALB des hellen Wassers (>180)
# Das Wasser ist der helle Kreis, der Fisch ist der mittelgraue Fleck darin
fisch_mask = (gray > 100) & (gray < 170)

# Nur innerhalb des inneren Bereichs (nicht der Rahmen)
# Der Rahmen ist außen, der Ring ist bei ~150-200
# Begrenze auf den Innenbereich: x=40-245, y=40-220
innen = fisch_mask.copy()
innen[:40, :] = False
innen[220:, :] = False
innen[:, :40] = False
innen[:, 245:] = False

# Konturen finden
mask_u8 = innen.astype(np.uint8) * 255
konturen, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

print("=== Fisch-Kandidaten (mittelgrau im Wasser) ===")
for i, k in enumerate(konturen):
    x, y, w, h = cv2.boundingRect(k)
    flaeche = cv2.contourArea(k)
    if flaeche > 30:  # nur große Flecken
        cx = x + w//2
        cy = y + h//2
        print(f"Kandidat {i}: x={x}-{x+w} y={y}-{y+h} ({w}x{h}px, {flaeche}px²)")
        print(f"   Zentrum: ({cx},{cy})")

# Zeige die Fisch-Map
print("\n=== Fisch-Map (# = Fisch-Kandidat) ===")
for yy in range(40, 220, 4):
    zeile = ""
    for xx in range(40, 245, 4):
        v = gray[yy, xx]
        if 100 < v < 170:
            zeile += "#"
        elif v >= 170:
            zeile += "."
        else:
            zeile += " "
    print(zeile)
