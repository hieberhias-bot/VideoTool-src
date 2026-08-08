import cv2
import numpy as np
import glob

# Frame-Differenz-Analyse über alle Screenshots
# Der Fisch bewegt sich → er erscheint als Bewegung zwischen Bildern
dateien = sorted(glob.glob("live_popup_*.png"))
bilder = []
for d in dateien:
    img = cv2.imread(d)
    if img is not None:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bilder.append(gray)

print(f"Geladen: {len(bilder)} Bilder\n")

# Finde das Popup-Zentrum (Wasser-Kreis)
# Das Wasser ist der helle Kreis. Finde seinen Mittelpunkt.
# Nimm Bild 5 als Referenz (sauberes Popup)
ref = bilder[4]
wasser = ref > 180
# Finde Kontur des Wassers
mask_u8 = wasser.astype(np.uint8) * 255
konturen, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
if konturen:
    groesste = max(konturen, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(groesste)
    cx, cy = x + w//2, y + h//2
    radius = min(w, h) // 2
    print(f"Popup-Zentrum: ({cx},{cy}), Radius: {radius}")
    
    # Sammle Bewegungs-Punkte über alle Bildpaare
    bewegungs_punkte = []
    for i in range(len(bilder) - 1):
        diff = cv2.absdiff(bilder[i], bilder[i+1])
        
        # Nur im Wasser-Kreis
        yy, xx = np.ogrid[:diff.shape[0], :diff.shape[1]]
        kreis = (xx - cx)**2 + (yy - cy)**2 <= radius**2
        
        # Bewegung im Wasser
        diff_kreis = diff * kreis
        ys, xs = np.where(diff_kreis > 30)
        if len(xs) > 0:
            # Cluster finden (zusammenhängende Bewegungen)
            for xp, yp in zip(xs, ys):
                bewegungs_punkte.append((xp, yp))
    
    print(f"Gesamt-Bewegungspunkte: {len(bewegungs_punkte)}")
    
    if len(bewegungs_punkte) > 0:
        # Heatmap der Bewegung
        heat = np.zeros((diff.shape[0], diff.shape[1]))
        for xp, yp in bewegungs_punkte:
            heat[yp, xp] += 1
        
        # Zeige die Bewegungskarte
        print("\n=== Bewegungskarte (wo sich der Fisch bewegt) ===")
        for yy in range(cy - radius, cy + radius, 8):
            zeile = ""
            for xx in range(cx - radius, cx + radius, 8):
                v = heat[yy, xx]
                if v > 5:
                    zeile += "#"
                elif v > 2:
                    zeile += "+"
                elif v > 0:
                    zeile += "."
                else:
                    zeile += " "
            print(zeile)
        
        # Zentrum der Bewegung
        ys, xs = np.where(heat > 2)
        if len(xs) > 0:
            print(f"\nFisch-Bewegungszentrum: ({xs.mean():.0f},{ys.mean():.0f})")
