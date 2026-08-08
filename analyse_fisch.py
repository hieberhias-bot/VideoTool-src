import cv2
import numpy as np

img = cv2.imread(r"C:\Users\vm1\Desktop\projekt\popup2.webp.png")
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# Der Kreis (Ring) ist hellgrau (. in der Map): S<50 und V>200
ring_mask = (hsv[:,:,1] < 50) & (hsv[:,:,2] > 200)
print("=== Ring (hellgrau) ===")
if ring_mask.any():
    ys, xs = np.where(ring_mask)
    cx = (xs.min()+xs.max())//2
    cy = (ys.min()+ys.max())//2
    radius = (xs.max()-xs.min())//2
    print(f"Ring-Zentrum: ({cx},{cy})")
    print(f"Ring-Radius: {radius}px")
    print(f"Ring-Bereich: x={xs.min()}-{xs.max()} y={ys.min()}-{ys.max()}")

# Der Fisch ist der dunkle Fleck INNERHALB des Rings
# Dunkel: V<120 und S<100 (aber nicht der Rahmen @)
# Rahmen ist ganz außen (x<5 oder x>280 oder y<5 oder y>256)
innen_mask = (hsv[:,:,2] < 120) & (hsv[:,:,1] < 100)
innen_mask[0:5, :] = False    # oberer Rand weg
innen_mask[-5:, :] = False    # unterer Rand weg
innen_mask[:, 0:5] = False    # linker Rand weg
innen_mask[:, -5:] = False    # rechter Rand weg

print("\n=== Dunkle Flecken INNEN (Fisch) ===")
# Konturen finden
mask_u8 = innen_mask.astype(np.uint8) * 255
konturen, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
for i, k in enumerate(konturen):
    x, y, w, h = cv2.boundingRect(k)
    flaeche = cv2.contourArea(k)
    if flaeche > 20:  # nur große Flecken
        print(f"Fleck {i}: x={x}-{x+w} y={y}-{y+h} ({w}x{h}px, {flaeche}px²)")

# Zeige nur den Innenbereich als Map
print("\n=== Innenbereich (nur dunkle Pixel) ===")
for yy in range(5, 257, 4):
    zeile = ""
    for xx in range(5, 281, 3):
        v = hsv[yy, xx, 2]
        s = hsv[yy, xx, 1]
        if s < 100 and v < 120:
            zeile += "#"  # dunkel (Fisch?)
        elif s < 100 and v < 180:
            zeile += "+"  # mittel
        else:
            zeile += "."  # hell
    print(zeile)
