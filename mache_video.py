import cv2
import numpy as np
import glob

# Erstelle ein Video aus den Screenshots, um den Fisch zu sehen
dateien = sorted(glob.glob("live_popup_*.png"))
bilder = []
for d in dateien:
    img = cv2.imread(d)
    if img is not None:
        bilder.append(img)

print(f"Geladen: {len(bilder)} Bilder")

if bilder:
    h, w = bilder[0].shape[:2]
    
    # Video erstellen
    video = cv2.VideoWriter("popup_video.avi", cv2.VideoWriter_fourcc(*'MJPG'), 10, (w, h))
    for img in bilder:
        video.write(img)
    video.release()
    print("Video erstellt: popup_video.avi")
    
    # Auch ein Bild mit allen Screenshots als Grid
    print("\nErstelle Übersichts-Grid...")
    n = len(bilder)
    cols = 5
    rows = (n + cols - 1) // cols
    zellen_w, zellen_h = 160, 120
    grid = np.zeros((rows * zellen_h, cols * zellen_w, 3), dtype=np.uint8)
    
    for i, img in enumerate(bilder):
        r, c = i // cols, i % cols
        klein = cv2.resize(img, (zellen_w, zellen_h))
        grid[r*zellen_h:(r+1)*zellen_h, c*zellen_w:(c+1)*zellen_w] = klein
    
    cv2.imwrite("popup_grid.png", grid)
    print("Grid erstellt: popup_grid.png")
    
    # Zeige das Grid
    cv2.imshow("Alle Popup-Screenshots", grid)
    print("\nDrücke eine Taste im Fenster, dann Enter im Terminal")
    cv2.waitKey(0)
    cv2.destroyAllWindows()
