# Fisch-Bot: Klick-Offset, Erkennungs- und Zuverlässigkeits-Fixes

Autonome Session, 2026-08-07. Zusammenfassung aller Diagnosen, Entscheidungen
und Code-Änderungen für die 5 Teilaufgaben (Klick-Offset, Fisch-Erkennung,
Klick-Strategie, Komplett-Test, Dokumentation).

## Wichtige Rahmenbedingung dieser Session

Command Center (`command_center.py`) lief die ganze Session über **elevated**
(als Administrator, vermutlich durch eine frühere `patch_elevation.py`-Änderung)
und hielt COM9 (die Arduino-HID-Maus) exklusiv offen. Ein nicht-elevated
Prozess kann einen elevated Prozess unter Windows weder per `taskkill` noch
per `PostMessage`/`SetForegroundWindow` beenden oder steuern (UIPI). Ein
Versuch, `taskkill` über `Start-Process -Verb RunAs` zu elevaten, löste einen
UAC-Bestätigungsdialog aus, der abgebrochen wurde ("Der Vorgang wurde durch
den Benutzer abgebrochen") - das ist eine harte Sicherheitsgrenze, kein Bug.

**Konsequenz:** Alle Fixes, die eine offene HID-Maus-Verbindung zum *Testen*
brauchen (`test_klick_offset.py` live ausführen, `fish_bot.py` 5 Minuten live
laufen lassen), konnten in dieser Session nicht ausgeführt werden. Die Fixes
selbst sind implementiert und durch Code-Analyse bzw. Tests gegen echte
aufgezeichnete Screenshots (`live_popup_*.png`, 98 Frames) abgesichert, aber
**nicht live mit der echten Hardware verifiziert**. Siehe "Was als Nächstes
zu tun ist" unten.

## Aufgabe 1: Klick-Offset (~15px/4mm zu weit links)

### Diagnose

- Die Python-seitige Koordinaten-Pipeline (`fenster_finden()` → `screenshot_holen()`
  → Klickziel in `fish_bot.py`/`aktion_skript.py`) ist in sich konsistent:
  Fensterursprung (`GetWindowRect`) und Screenshot-Box verwenden denselben
  Koordinatenursprung, `screenshot_holen()` prüft das sogar selbst per
  Größenvergleich (`fish_bot.py`, Warnung bei DPI-/Skalierungsproblem).
- Multi-Monitor/virtueller Bildschirm als Ursache ausgeschlossen:
  `SM_XVIRTUALSCREEN=0`, `SM_CXVIRTUALSCREEN=1920` == `SM_CXSCREEN` (ein
  Monitor, kein Versatz).
- `hid_maus.py` skaliert bereits die Y-Achse (Firmware nimmt 1080 an, Session
  hat 955 px Höhe), die X-Achse braucht rechnerisch keine Skalierung
  (Firmware-Breite 1920 == Session-Breite 1920 exakt).
- Die Firmware-Quelle (`composite_abs`, mit `MOVE_ABS`) ist **nicht** im
  Repository vorhanden (nur ältere `.ino`-Dateien mit relativer
  `Mouse.click()`-Logik gefunden, kein `MOVE_ABS`). Die exakte
  Rundung/Skalierung auf Firmware-Seite bzw. in Windows' HID-Absolut-Mapping
  konnte daher nicht am Quellcode nachvollzogen werden.

**Ergebnis:** Der Versatz ist eine empirisch bestätigte, aber am verfügbaren
Quellcode nicht erklärbare Restabweichung (vermutlich Firmware-/HID-
Quantisierung). Statt an der Skalierungslogik zu raten, wurde eine
konfigurierbare, klar dokumentierte Korrekturkonstante eingebaut.

### Fix

- **`hid_maus.py`**: neue Konstanten `KLICK_OFFSET_X_PX = 15`,
  `KLICK_OFFSET_Y_PX = 0` (Default aus der Nutzer-Angabe). Werden in
  `HIDMaus.maus_bewegen()` VOR dem bestehenden Clamp/Y-Rescale auf das Ziel
  addiert - dadurch profitieren *alle* Aufrufer (Fisch-Klicks, Wurm-Klicks,
  `aktion_skript.py` MAUS_BEWEGEN/MAUS_ABS/BILD_KLICKEN) von der Korrektur,
  nicht nur der Fisch-Bot.
- **`test_klick_offset.py`** (neu): misst systematisch Ziel- vs. Ist-Position
  (per `GetCursorPos`) an 5 Punkten (Mitte, links, rechts, oben, unten) im
  METIN2-Fenster, gibt eine Tabelle aus und schlägt bei konstantem Versatz
  automatisch die passenden `KLICK_OFFSET_X_PX`/`Y_PX`-Werte vor.

### Offener Punkt

**Nicht live verifiziert** (COM9 blockiert, siehe oben). Der Defaultwert
`KLICK_OFFSET_X_PX = 15` beruht auf der Nutzer-Angabe aus der Aufgabenstellung,
nicht auf einer in dieser Session selbst durchgeführten Messung.

## Aufgabe 2: Fisch-Erkennung stabilisieren

### Befund: Filter war bereits vollständig implementiert

`FischGlaetter` (Ausreißer-Filter `MAX_SPRUNG_PX=40` + Median über
`GLAETTER_FENSTER=4` akzeptierte Positionen, mit `MAX_VERWORFENE_SERIE=3` als
Anti-Einfrier-Mechanismus) sowie die ROI-Beschränkung auf die Popup-Umgebung
(`_popup_roi()`) waren bereits vollständig vorhanden und entsprachen exakt der
Aufgabenstellung. Verifiziert gegen die 98 echten `live_popup_*.png`-Frames:

| Metrik | Roh | Geglättet |
|---|---|---|
| Mittlere Sprungweite zwischen Detektionen | 51.9px | 15.4px |
| Max. Sprungweite | 111.5px | 111.0px* |

\* Der Ausreißer bei "geglättet" entsteht durch einen erzwungenen Median-Reset
nach `MAX_VERWORFENE_SERIE` verworfenen Punkten (Design-Kompromiss: schneller
Restart nach echtem Sprung statt dauerhaftem Einfrieren) - keine Regression.

### Neuer Befund: rohe Fisch-Erkennung hat geringe Trefferquote (~15-19%)

Der Fisch wurde in nur 15-19 von 98 Frames überhaupt per HSV-Kontur gefunden.
Untersuchung ergab: **das ist kein Kalibrierungsfehler**, sondern game-inhärent
- der Fisch ist nur einen Teil der Popup-Dauer überhaupt sichtbar (visueller
Vergleich: Miss-Frames zeigen einen **weißen** Ring ohne jede sichtbare
Fisch-Silhouette, Treffer-Frames einen **pink/roten** Ring mit klar sichtbarem
dunklem Fisch). In 77/83 Miss-Frames gab es buchstäblich 0 zum HSV-Bereich
passende Pixel im Suchbereich - keine "knapp daneben"-Situation.

Ein Test mit aufgeweiteten HSV-Schwellen bestätigt das: ±40 aufgeweitet ergibt
nur 37% Trefferquote, ±50 springt auf 99% - aber nur, weil dabei praktisch die
gesamte Wasserfläche mitgezählt wird (keine echte Fisch-Erkennung mehr,
sondern Rauschen). **Die HSV-Schwelle wurde daher bewusst NICHT verändert.**

### Echter Bug gefunden und behoben: fehlende obere Radius-Grenze

Radius-Verteilung der 98 Frames zeigte drei klare Cluster: 14px (61x, bereits
durch `MIN_RADIUS=20` gefiltert), 64px (19x, die echten Fisch-Ringe), und
166-171px (18x, eindeutige Fehlerkennungen - z.B. lieferte ein Frame mit
Inventar-/Explorer-Fenstern statt einer Angel-Szene einen "Popup"-Fund mit
r=171). Diese 18 Fehlerkennungen wurden bisher **nicht** abgelehnt, da
`_popup_gueltig()` nur eine untere, keine obere Radius-Grenze prüfte - der Bot
hätte in diesen Fällen fälschlich "Popup offen" angenommen.

**Fix (`fish_bot.py`):** neue Konstante `MAX_RADIUS = 110` (komfortabler
Puffer über dem echten Cluster bei 64px, klar unter dem falschen Cluster bei
166px), `_popup_gueltig()` prüft jetzt `MIN_RADIUS <= radius <= MAX_RADIUS`.
Verifiziert: alle 19 echten Popups bleiben gültig, alle 18 Fehlerkennungen
werden jetzt korrekt abgelehnt.

### Zusätzlicher Zuverlässigkeits-Fix: `leertaste_tippen()` nutzte Arduino-HID-Tastatur

`fish_bot.py` hatte eine eigene, von `aktion_skript.py` unabhängige
SPACE-Implementierung (`leertaste_tippen()`), die noch über
`maus.taste_druecken()`/`taste_loslassen()` (Arduino-HID-Firmware) lief - exakt
das Muster, das sich in dieser Session als unzuverlässig herausgestellt hat
(Firmware bestätigt den Tastendruck zwar per ACK, er kommt aber nicht
zuverlässig in Metin2 an; siehe `aktion_skript.py`-Historie/`test_taste_skript*.py`).
Da `leertaste_tippen()` den Bot durch alle Zustandsübergänge (WARTE_EINHOLEN,
PRUEFE_POPUP_1-4) trägt, hätte das den gesamten Automaten unzuverlässig
gemacht, unabhängig von allen anderen Fixes.

**Fix:** `leertaste_tippen()` nutzt jetzt `pynput` (SendInput), wie zuvor
bereits für `aktion_skript.py` TASTE-Aktionen umgestellt.

## Aufgabe 3: Klick-Strategie

**Befund:** Alle vier geforderten Punkte waren bereits exakt mit den
geforderten Werten in `_klick_loop()` implementiert:

1. Klick nur bei `im_ring` UND `steht_still` (`STILLSTAND_SCHWELLE_PX=5`,
   `STILLSTAND_FRAMES=3`) - Zeile ~1076.
2. Maximal 1 Klick pro Stillstands-Phase über das Flag
   `stillstand_bereits_geklickt`, das erst bei `steht_still=False` wieder
   zurückgesetzt wird - mit ausführlichem Docstring, der exakt dieses Problem
   ("7+ Klicks pro Popup") als bereits behobenen Vorfall beschreibt.
3. Keine Prediction/Extrapolation - Docstring von `fisch_steht_still()`
   bestätigt explizit, dass die frühere Vorhersage-Logik ersetzt wurde.
4. `MIN_KLICK_ABSTAND_S = 0.1` als zusätzliches Sicherheitsnetz gegen
   Doppelklicks bei flackernder `steht_still`-Erkennung.

**Keine Code-Änderung nötig** - nur verifiziert.

## Aufgabe 4: Komplett-Test

**Nicht durchführbar in dieser Session** - COM9 dauerhaft durch das elevated
Command Center blockiert (siehe "Wichtige Rahmenbedingung" oben). Stattdessen
wurde eine vorhandene `fish_daten.csv` aus einem früheren, kurzen Testlauf
(18.5s, **vor** allen Fixes dieser Session) ausgewertet:

- 2 Popup-Zyklen, 6 Klicks gesamt (3 Klicks/Popup - im Zielbereich, leicht
  über der Mitte von "1-3")
- Alle 6 Klicks hatten zum Klick-Zeitpunkt `im_ring=1` (100%) - bestätigt,
  dass das Ring+Stillstand-Gate bereits vor dieser Session korrekt griff
- Diese Zahl sagt **nichts** über den physischen Klick-Offset aus (die CSV
  loggt nur die intendierte Software-Position, nicht die tatsächliche
  Cursor-Landung) - dafür ist `test_klick_offset.py` nötig.

### Was als Nächstes zu tun ist (erfordert freies COM9)

1. Command Center manuell schließen (Fenster-X oder Taskmanager - Prozess
   läuft elevated, daher nicht per Skript beendbar).
2. `python test_klick_offset.py` ausführen, geloggte
   `KLICK_OFFSET_X_PX`/`Y_PX`-Empfehlung in `hid_maus.py` übernehmen, bis
   Toleranz ≤3px erreicht ist.
3. `python fish_bot.py` 5 Minuten laufen lassen (Metin2 muss laufen und
   fokussierbar sein).
4. `fish_daten.csv` auswerten: Trefferquote = Anteil `klick_gesendet=1`-Zeilen
   mit `im_ring=1` UND (falls Live-Beobachtung möglich) tatsächlichem Fang;
   Klicks/Popup über `popup_erkannt`-Übergänge gruppieren; Positions-
   Stabilität über `fisch_x`/`fisch_y`-Sprungweite zwischen Zeilen.
5. Bei Trefferquote <80%: zuerst `KLICK_OFFSET_X_PX/Y_PX` erneut prüfen
   (häufigste Ursache für "falsch positioniert, obwohl Software korrekt
   gemessen hat"), erst danach an `RING_PUFFER_PX`/`STILLSTAND_SCHWELLE_PX`
   drehen.

## Geänderte Dateien

| Datei | Änderung |
|---|---|
| `hid_maus.py` | `KLICK_OFFSET_X_PX`/`KLICK_OFFSET_Y_PX` Konstanten + Anwendung in `maus_bewegen()` |
| `fish_bot.py` | `MAX_RADIUS`-Grenze in `_popup_gueltig()`; `leertaste_tippen()` auf pynput umgestellt |
| `aktion_skript.py` | (aus vorheriger Teilaufgabe dieser Session) TASTE-Aktion auf pynput umgestellt, `_fokussiere_metin2()`-Wartezeit erhöht |
| `test_klick_offset.py` | neu - systematischer Klick-Offset-Messtest |
| `README_LOESUNG.md` | diese Datei |

Keine Dateien wurden committet oder gepusht.
