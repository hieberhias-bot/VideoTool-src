import cv2
import numpy as np
import glob

# Analysiere alle Live-Screenshots, um den Fisch zu finden
dateien = sorted(glob.glob("live_popup_*.png"))
print(f"Analysiere {len(dateien)} Screenshots...\n")

for datei in dateien:
    img = cv2.imread(datei)
    if img is None:
        continue
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Wasser = heller Kreis
    wasser = gray > 180
    
    # Fisch = mittelgrauer Fleck IM Wasser (nicht der Ring)
    # Der Ring ist um das Wasser herum, der Fisch ist INNEN
    fisch_kandidat = (gray > 90) & (gray < 170) & wasser
    
    # Nur innerhalb des Wassers
    fisch_kandidat = fisch_kandidat & wasser
    
    # Größte Kontur im Wasser finden
    mask_u8 = fisch_kandidat.astype(np.uint8) * 255
    konturen, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    groesste = None
    for k in konturen:
        x, y, bw, bh = cv2.boundingRect(k)
        flaeche = cv2.contourArea(k)
        if flaeche > 100:  # großer Fleck
            if groesste is None or flaeche > groesste[0]:
                groesste = (flaeche, x, y, bw, bh)
    
    # Wasser-Größe
    wasser_px = wasser.sum()
    
    if groesste:
        flaeche, x, y, bw, bh = groesste
        cx = x + bw//2
        cy = y + bh//2
        print(f"{datei}: Wasser={wasser_px}px, Fisch bei ({cx},{cy}) {bw}x{bh}px ({flaeche}px²)")
    else:
        print(f"{datei}: Wasser={wasser_px}px, KEIN Fisch")
