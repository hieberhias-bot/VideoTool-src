import cv2
import numpy as np

# ROI-Bild laden und vergroessert anzeigen (zum Analysieren der Pixel)
roi = cv2.imread("roi_test.png")
print("ROI-Groesse:", roi.shape)

# Das alte Template
tpl = cv2.imread(r"resources\wurm_icon.png")
print("Altes Template:", tpl.shape)

# Das ROI-Bild speichern wir schon. Jetzt die Frage: Wo sind die Wurm-Slots?
# Inventar-Slots sind normalerweise 32x32px. Schauen wir uns den ROI an.
# Wir speichern eine vergroesserte Version zum Anschauen
roi_gross = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
cv2.imwrite("roi_gross.png", roi_gross)
print("ROI vergroessert gespeichert: roi_gross.png")
