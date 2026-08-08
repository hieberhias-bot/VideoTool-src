import cv2
import numpy as np

# Vergleiche zwei aufeinanderfolgende Screenshots
# Der Fisch BEWEGT sich → die Differenz zeigt ihn!
img1 = cv2.imread("live_popup_005.png")
img2 = cv2.imread("live_popup_006.png")

gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

# Differenz berechnen
diff = cv2.absdiff(gray1, gray2)

# Wasser-Bereich finden (hell)
wasser = gray1 > 180

# Differenz NUR im Wasser
diff_wasser = diff.copy()
diff_wasser[~wasser] = 0

print("=== Differenz zwischen Screenshot 5 und 6 (nur Wasser) ===")
print("Zeigt, wo sich etwas bewegt hat (der Fisch!)")
for y in range(0, 639, 6):
    zeile = ""
    for x in range(0, 816, 5):
        d = diff_wasser[y, x]
        if d > 40:
            zeile += "#"  # große Bewegung
        elif d > 15:
            zeile += "+"  # mittlere Bewegung
        elif d > 5:
            zeile += "."  # kleine Bewegung
        else:
            zeile += " "  # keine Bewegung
    print(zeile)

# Wo ist die größte Bewegung?
ys, xs = np.where(diff_wasser > 40)
if len(xs) > 0:
    print(f"\nGrößte Bewegung: x={xs.min()}-{xs.max()} y={ys.min()}-{ys.max()}")
    cx = (xs.min()+xs.max())//2
    cy = (ys.min()+ys.max())//2
    print(f"Zentrum der Bewegung: ({cx},{cy})")
else:
    print("\nKeine große Bewegung gefunden")
