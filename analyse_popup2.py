import cv2
import numpy as np

# popup2.webp laden
img = cv2.imread(r"C:\Users\vm1\Desktop\projekt\popup2.webp")
if img is None:
    print("KANN NICHT LADEN - versuche .png")
    img = cv2.imread(r"C:\Users\vm1\Desktop\projekt\popup2.webp.png")
if img is None:
    print("FEHLER: Bild nicht gefunden")
else:
    h, w = img.shape[:2]
    print(f"Größe: {w}x{h} Pixel")
    
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Zeige das Bild als Text-Art (HSV-Map)
    print("\n=== Sättigungs-Map (Fisch = hohe Sättigung) ===")
    for y in range(0, h, max(1, h//20)):
        zeile = ""
        for x in range(0, w, max(1, w//40)):
            s = hsv[y, x, 1]
            if s > 120: zeile += "#"      # sehr gesättigt (Fisch)
            elif s > 60: zeile += "+"     # mittel
            elif s > 30: zeile += "."     # leicht
            else: zeile += " "            # ungesättigt (Wasser)
        print(zeile)
    
    # Finde die gesättigten Bereiche (Fisch)
    mask = hsv[:,:,1] > 100
    if mask.any():
        ys, xs = np.where(mask)
        print(f"\nFisch-Bereich: x={xs.min()}-{xs.max()} y={ys.min()}-{ys.max()}")
        print(f"Fisch-Größe: {xs.max()-xs.min()+1}x{ys.max()-ys.min()+1} Pixel")
        
        # HSV-Werte des Fisches
        fisch_hsv = hsv[mask]
        h_werte = fisch_hsv[:,0]
        s_werte = fisch_hsv[:,1]
        v_werte = fisch_hsv[:,2]
        print(f"\nFisch HSV:")
        print(f"  H: {h_werte.min()} - {h_werte.max()} (meistens: {np.median(h_werte):.0f})")
        print(f"  S: {s_werte.min()} - {s_werte.max()} (meistens: {np.median(s_werte):.0f})")
        print(f"  V: {v_werte.min()} - {v_werte.max()} (meistens: {np.median(v_werte):.0f})")
