import cv2
import numpy as np

img = cv2.imread(r"C:\Users\vm1\Desktop\projekt\popup2.webp.png")
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# Graue Pixel finden (niedrige Sättigung)
grau_mask = hsv[:,:,1] < 50

print("=== Graue Bereiche (Fisch?) ===")
if grau_mask.any():
    ys, xs = np.where(grau_mask)
    print(f"Grau-Bereich: x={xs.min()}-{xs.max()} y={ys.min()}-{ys.max()}")
    print(f"Größe: {xs.max()-xs.min()+1}x{ys.max()-ys.min()+1} Pixel")
    # Helligkeit der grauen Pixel
    v_grau = hsv[:,:,2][grau_mask]
    print(f"V (Helligkeit): {v_grau.min()}-{v_grau.max()} (mittel {v_grau.mean():.0f})")

# ASCII-Map: Grau nach Helligkeit
print("\n=== Grau-Map (Fisch = dunkler Grau, Wasser = hell) ===")
for y in range(0, 262, 5):
    zeile = ""
    for x in range(0, 286, 4):
        s = hsv[y, x, 1]
        v = hsv[y, x, 2]
        if s < 50:  # grau
            if v < 80: zeile += "@"    # dunkelgrau
            elif v < 140: zeile += "#" # mittelgrau
            elif v < 200: zeile += "+" # hellgrau
            else: zeile += "."         # fast weiß
        else:
            zeile += " "  # farbig
    print(zeile)

# Der Fisch ist ein dunkler/grauer Umriss im hellen Wasser
# Finde dunkle Pixel (Fisch-Umriss)
print("\n=== Dunkle Pixel (Fisch-Umriss?) ===")
dunkel = (hsv[:,:,2] < 120) & (hsv[:,:,1] < 100)
if dunkel.any():
    ys, xs = np.where(dunkel)
    print(f"Dunkel-Bereich: x={xs.min()}-{xs.max()} y={ys.min()}-{ys.max()}")
    print(f"Größe: {xs.max()-xs.min()+1}x{ys.max()-ys.min()+1} Pixel")
