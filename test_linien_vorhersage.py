import csv, math

def klickpunkt_auf_linie(A, B, ABSTAND=15):
    dx = B[0] - A[0]
    dy = B[1] - A[1]
    laenge = (dx*dx + dy*dy) ** 0.5
    if laenge < 1:
        return B
    einheit_x = dx / laenge
    einheit_y = dy / laenge
    return (B[0] + einheit_x * ABSTAND, B[1] + einheit_y * ABSTAND)

zeilen = []
with open('fish_daten.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        zeilen.append(row)

print(f"Geladene Zeilen: {len(zeilen)}")

treffer = 0
fehler = 0
for i in range(2, len(zeilen)):
    try:
        A = (float(zeilen[i-2]['fisch_x']), float(zeilen[i-2]['fisch_y']))
        B = (float(zeilen[i-1]['fisch_x']), float(zeilen[i-1]['fisch_y']))
        aktuell = (float(zeilen[i]['fisch_x']), float(zeilen[i]['fisch_y']))
        distanz_aktuell = float(zeilen[i]['distanz_zum_ring'])
        C = klickpunkt_auf_linie(A, B, ABSTAND=15)
        dx_c = C[0] - aktuell[0]
        dy_c = C[1] - aktuell[1]
        distanz_vorhersage = math.sqrt(dx_c*dx_c + dy_c*dy_c)
        if distanz_vorhersage < abs(distanz_aktuell):
            treffer += 1
        else:
            fehler += 1
    except (KeyError, ValueError):
        continue

print(f"Linien-Vorhersage besser: {treffer}")
print(f"Linien-Vorhersage schlechter: {fehler}")
if treffer + fehler > 0:
    print(f"Erfolgsrate: {treffer/(treffer+fehler)*100:.1f}%")
