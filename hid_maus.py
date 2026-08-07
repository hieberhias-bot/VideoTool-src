import serial
import time
import ctypes
import subprocess
from ctypes import wintypes

VK_LBUTTON = 0x01

# Empirisch ermittelter, systematischer Versatz zwischen angepeilter und
# tatsaechlich angefahrener Cursor-Position (siehe test_klick_offset.py):
# Klicks landeten wiederholt ~15px (~4mm) zu weit LINKS vom Ziel, unabhaengig
# davon, wo im Fenster geklickt wurde; die Y-Achse war nicht auffaellig. Die
# Python-seitige Koordinaten-Pipeline (fenster_finden -> screenshot_holen ->
# Klickziel) ist in sich konsistent - der Versatz entsteht vermutlich in der
# Firmware-seitigen USB-HID-Skalierung bzw. in Windows' Zuordnung des
# HID-Absolutbereichs auf den Bildschirm (Firmware-Quelle nicht in diesem
# Repository vorhanden, daher hier nur kompensiert statt an der Wurzel
# behoben). Nach einem Firmware-Flash oder einer Aufloesungsaenderung mit
# test_klick_offset.py neu validieren/anpassen.
KLICK_OFFSET_X_PX = 15
KLICK_OFFSET_Y_PX = 0

# Gueltige Namen fuer taste_druecken()/taste_halten()/taste_loslassen().
_TASTEN_ERLAUBT = set(
    list("abcdefghijklmnopqrstuvwxyz")
    + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    + [str(i) for i in range(10)]
    + [f"F{i}" for i in range(1, 13)]
    + ["SPACE", "ENTER", "TAB", "ESC", "BACKSPACE", "DEL",
       "SHIFT", "CTRL", "ALT", "UP", "DOWN", "LEFT", "RIGHT"]
)

# Oeffentlicher Alias fuer externe Validierung (z.B. aktion_editor.py, bevor
# ein TASTE-Schritt gespeichert wird) - dieselbe Menge, die taste_druecken()
# etc. intern pruefen, damit beide Stellen niemals auseinanderlaufen koennen.
TASTEN_ERLAUBT = _TASTEN_ERLAUBT




_BEKANNTE_VID_PID = (
    (0x2341, 0x8037),
    (0x2341, 0x8036),
    (0x1B4F, 0x9206),
    (0x046D, 0xC33F),
)


def _port_auto_finden():
    """Findet den Arduino Micro (HID-Maus) automatisch anhand VID/PID.

    Fallback: Ist kein bekanntes Geraet dabei, aber genau EIN COM-Port
    vorhanden, wird dieser angenommen (z.B. wenn VID/PID vom Bootloader
    abweichen oder der Treiber sie nicht meldet).
    """
    try:
        import serial.tools.list_ports as lp
        ports = list(lp.comports())
        for p in ports:
            if (p.vid, p.pid) in _BEKANNTE_VID_PID:
                return p.device
        if len(ports) == 1:
            return ports[0].device
    except Exception:
        pass
    return None


# Gecachte InstanceId der virtuellen PS/2-Maus (siehe _ps2_maus_instance_id_ermitteln).
_PS2_MAUS_INSTANCE_ID = None


def _ps2_maus_instance_id_ermitteln():
    """Ermittelt die tatsaechliche PnP-InstanceId der virtuellen PS/2-Maus
    dynamisch per Get-PnpDevice, statt eine feste Hardware-ID zu raten.

    Wichtig: Die urspruenglich angenommene ID "ACPI\\PNP0F13*" stimmt auf
    dieser VM NICHT - die vorherige Diagnose (Get-PnpDevice) hat gezeigt,
    dass das Geraet hier tatsaechlich "ACPI\\PNP0F03\\..." ist. Da die
    genaue Hardware-ID je nach Windows-/VirtualBox-Version variieren kann,
    wird sie hier ueber Class=Mouse + FriendlyName~"PS/2" gesucht statt
    hartkodiert - und einmalig pro Prozess gecacht (aendert sich zur
    Laufzeit nicht).
    """
    global _PS2_MAUS_INSTANCE_ID
    if _PS2_MAUS_INSTANCE_ID:
        return _PS2_MAUS_INSTANCE_ID
    ps_cmd = (
        "(Get-PnpDevice -Class Mouse -PresentOnly | "
        "Where-Object { $_.FriendlyName -match 'PS/2' } | "
        "Select-Object -First 1 -ExpandProperty InstanceId)"
    )
    try:
        ergebnis = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        instance_id = ergebnis.stdout.strip()
        if instance_id:
            _PS2_MAUS_INSTANCE_ID = instance_id
            return instance_id
        print("[HIDMaus] PS/2-Maus-Geraet nicht gefunden (Get-PnpDevice lieferte nichts).")
    except Exception as e:
        print(f"[HIDMaus] Fehler beim Ermitteln der PS/2-Maus-InstanceId: {e}")
    return None


def _pnp_geraet_status(instance_id):
    """Liest den aktuellen Status ('OK', 'Error', ...) eines PnP-Geraets -
    dient als Erfolgs-Verifikation fuer _pnp_geraet_umschalten(), da sich
    der Exit-Code von PowerShell/pnputil dafuer NICHT verlassen liefert
    (siehe dort)."""
    ps_cmd = f'(Get-PnpDevice -InstanceId "{instance_id}").Status'
    try:
        ergebnis = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        return ergebnis.stdout.strip() or None
    except Exception as e:
        print(f"[HIDMaus] Fehler beim Lesen des Geraetestatus: {e}")
        return None


def _pnp_geraet_umschalten(instance_id, aktivieren):
    """Schaltet ein PnP-Geraet per PowerShell (Enable-/Disable-PnpDevice) um.
    Faellt bei Fehlschlag auf pnputil zurueck (aeltere/robustere CLI).

    WICHTIG: Weder der PowerShell- noch der pnputil-Exit-Code sind hier
    verlaesslich - pnputil liefert Exit-Code 0 zurueck, SELBST WENN das
    Geraet nicht deaktiviert werden konnte (z.B. "Das erforderliche
    Systemgeraet kann nicht deaktiviert werden" landet nur im stdout-Text,
    nicht im Exit-Code). Der Erfolg wird deshalb ausschliesslich durch
    erneutes Abfragen des tatsaechlichen Geraetestatus (_pnp_geraet_status())
    verifiziert.

    Beide Wege brauchen ausserdem einen ELEVATED Prozess - ohne Adminrechte
    schlaegt die Aenderung fehl und diese Funktion gibt False zurueck.
    """
    ziel_status = "OK" if aktivieren else "Error"
    cmdlet = "Enable-PnpDevice" if aktivieren else "Disable-PnpDevice"
    ps_cmd = f'{cmdlet} -InstanceId "{instance_id}" -Confirm:$false'
    try:
        ergebnis = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        if ergebnis.returncode != 0:
            print(f"[HIDMaus] {cmdlet} fehlgeschlagen: {ergebnis.stderr.strip()}")
    except Exception as e:
        print(f"[HIDMaus] Fehler bei {cmdlet}: {e}")

    if _pnp_geraet_status(instance_id) == ziel_status:
        return True

    # PowerShell hat den Status nicht geaendert - pnputil als Fallback
    # versuchen (dessen Exit-Code wird bewusst ignoriert, siehe Docstring).
    aktion = "enable-device" if aktivieren else "disable-device"
    try:
        ergebnis = subprocess.run(
            ["pnputil", f"/{aktion}", instance_id],
            capture_output=True, text=True, timeout=10,
        )
        if "nicht" in ergebnis.stdout.lower() or "cannot" in ergebnis.stdout.lower() \
                or "not" in ergebnis.stdout.lower():
            print(f"[HIDMaus] pnputil /{aktion}: {ergebnis.stdout.strip()}")
    except Exception as e:
        print(f"[HIDMaus] Fehler bei pnputil /{aktion}: {e}")

    if _pnp_geraet_status(instance_id) == ziel_status:
        return True

    print(f"[HIDMaus] {'Aktivieren' if aktivieren else 'Deaktivieren'} von "
          f"{instance_id} fehlgeschlagen. Laeuft der Prozess als "
          "Administrator? Manche Systeme verweigern zusaetzlich das "
          "Deaktivieren des einzigen Zeigegeraets als 'erforderliches "
          "Systemgeraet', unabhaengig von Adminrechten.")
    return False


class HIDMaus:
    """Schnittstelle zum Arduino HID-Maus-Emulator (Text-Protokoll)."""

    def __init__(self, port="COM6", baud=115200, timeout=1.0):
        self.port = port or _port_auto_finden()
        self.baud = baud
        self.timeout = timeout
        self.ser = None
        self.verbunden = False
        self.screen_w = None
        self.screen_h = None

    def verbinden(self):
        """Öffnet die serielle Verbindung zum Arduino."""
        try:
            if not self.port:
                self.port = _port_auto_finden()
                if not self.port:
                    print("[HIDMaus] Kein Arduino Micro gefunden (COM-Port).")
                    self.verbunden = False
                    return False
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            time.sleep(2)  # Arduino-Reset abwarten
            self.verbunden = True
            # Echte Bildschirmaufloesung ermitteln - die Firmware klemmt
            # MOVE_ABS intern fix auf 1920x1080, unabhaengig davon, ob der
            # tatsaechliche Bildschirm davon abweicht (siehe maus_bewegen_abs()).
            self.screen_w = ctypes.windll.user32.GetSystemMetrics(0)
            self.screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            print(f"[HIDMaus] Verbunden mit {self.port} "
                  f"(Bildschirm {self.screen_w}x{self.screen_h})")
            return True
        except Exception as e:
            print(f"[HIDMaus] Fehler beim Verbinden: {e}")
            self.verbunden = False
            return False

    def _senden(self, cmd, erwartete_antwort):
        """Sendet einen Befehl und wartet auf die firmwarespezifische Bestätigung."""
        if not self.verbunden or self.ser is None:
            return False
        try:
            self.ser.reset_input_buffer()
            self.ser.write((cmd + "\n").encode())
            ack = self.ser.readline().decode().strip()
            return ack == erwartete_antwort
        except Exception as e:
            print(f"[HIDMaus] Fehler beim Senden '{cmd}': {e}")
            return False

    def ping(self):
        """Prüft die Verbindung zur Firmware."""
        return self._senden("PING", "PONG")

    def klick_links(self):
        """Führt einen Linksklick aus."""
        return self._senden("CLICK", "CLICKED")

    def klick_rechts(self):
        """Führt einen Rechtsklick aus."""
        return self._senden("RCLICK", "RCLICKED")

    def taste_gedrueckt(self):
        """Drückt die linke Maustaste."""
        return self._senden("DOWN", "DOWN")

    def taste_losgelassen(self):
        """Lässt die linke Maustaste los."""
        return self._senden("UP", "UP")

    def maus_bewegen(self, dx, dy):
        """Bewegt die Maus zur ABSOLUTEN Bildschirmposition (dx, dy) ueber die
        HID-Firmware (Aufloesung 1920x1080) - trotz der Parameternamen dx/dy
        (Signatur unveraendert) KEINE relative Bewegung mehr, sondern ein
        MOVE_ABS mit absoluten Koordinaten.
        """
        try:
            # KLICK_OFFSET_X_PX/Y_PX VOR dem Clamp/Rescale auf das gewuenschte
            # Bildschirmziel addieren (siehe Konstanten-Doku oben) - dadurch
            # komponiert die Korrektur korrekt mit der Y-Reskalierung darunter.
            x = max(0, min(1919, int(dx) + KLICK_OFFSET_X_PX))
            y = max(0, min(1079, int(dy) + KLICK_OFFSET_Y_PX))
            # Firmware klemmt auf 1920x1080, aber die Session ist nur screen_h
            # hoch (z.B. 955). Windows skaliert das gesendete Y dann herunter:
            # 191 -> 191*955/1080 = 169 (die konstanten ~22px Abweichung).
            # Deshalb Y vorab in den 1080er-Raum hochskalieren, damit es im
            # screen_h-Raum korrekt ankommt.
            if self.screen_h and self.screen_h != 1080:
                y = int(round(y * (1080.0 / self.screen_h)))
        except (TypeError, ValueError) as e:
            print(f"[HIDMaus] Ungueltige Position ({dx}, {dy}): {e}")
            return False
        return self._senden(f"MOVE_ABS {x} {y}", "MOVED")

    def _aktuelle_position(self):
        """Liest die tatsaechliche Cursor-Position per GetCursorPos() aus -
        im Gegensatz zu SetCursorPos() funktioniert das Auslesen zuverlaessig
        und dient maus_bewegen_abs() als Ist-Wert fuer die Korrekturschleife."""
        punkt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(punkt))
        return punkt.x, punkt.y

    def maus_bewegen_abs(self, x, y):
        """Absolute Bewegung - delegiert an maus_bewegen (praezise, ohne Korrekturschleife)."""
        return self.maus_bewegen(x, y)

    def maus_ziehen(self, x, y):
        """Bewegt den Cursor per Windows-API absolut zu Bildschirmkoordinate (x, y).

        Im Gegensatz zu maus_bewegen() laeuft dies nicht ueber die serielle
        HID-Firmware, sondern direkt ueber SetCursorPos.
        """
        try:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            return True
        except Exception as e:
            print(f"[HIDMaus] Fehler bei maus_ziehen({x}, {y}): {e}")
            return False

    def _taste_gueltig(self, name):
        if name not in _TASTEN_ERLAUBT:
            print(f"[HIDMaus] Ungueltiger Tastenname: {name!r}")
            return False
        return True

    def taste_druecken(self, name):
        """Drueckt und lässt eine Taste sofort wieder los (Tastendruck)."""
        if not self._taste_gueltig(name):
            return False
        return self._senden(f"KEY {name}", "KEYED")

    def taste_halten(self, name):
        """Haelt eine Taste gedrueckt, bis taste_loslassen() aufgerufen wird."""
        if not self._taste_gueltig(name):
            return False
        return self._senden(f"KEY_DOWN {name}", "KEYDOWN")

    def taste_loslassen(self, name):
        """Laesst eine zuvor mit taste_halten() gedrueckte Taste wieder los."""
        if not self._taste_gueltig(name):
            return False
        return self._senden(f"KEY_UP {name}", "KEYUP")

    def test_echter_klick(self):
        """Prüft per Windows-API, ob DOWN/UP tatsächlich als HID-Tastenzustand ankommen.

        Ein CLICK bewegt den Cursor absichtlich nicht (nur Press+Release an der
        aktuellen Position), daher ist eine Cursor-Positionsprüfung hier kein
        aussagekräftiger Test. Stattdessen wird der reale Tastenzustand der
        linken Maustaste über GetAsyncKeyState abgefragt.
        """
        if not self.taste_gedrueckt():
            return False
        time.sleep(0.05)
        gedrueckt = (ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0
        if not self.taste_losgelassen():
            return False
        time.sleep(0.05)
        losgelassen = (ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) == 0
        return gedrueckt and losgelassen

    def maus_sperren(self) -> bool:
        """Deaktiviert die virtuelle PS/2-Maus, damit der Arduino das
        einzige Zeigegeraet im Gast ist (siehe VirtualBox-Diagnose: die
        emulierte "Microsoft PS/2-Maus" konkurriert sonst mit den absoluten
        MOVE_ABS-Reports des Arduino und verursacht die beobachtete Drift).

        Erfordert einen ELEVATED (als Administrator gestarteten) Prozess -
        ohne Adminrechte gibt PowerShell/pnputil "Access denied" zurueck und
        diese Methode liefert False (das PS/2-Geraet bleibt dann aktiv).

        Returns:
            bool: True bei Erfolg, False bei Fehler (Geraet nicht gefunden
                oder keine Berechtigung).
        """
        instance_id = _ps2_maus_instance_id_ermitteln()
        if not instance_id:
            return False
        erfolg = _pnp_geraet_umschalten(instance_id, aktivieren=False)
        if erfolg:
            print(f"[HIDMaus] PS/2-Maus gesperrt ({instance_id})")
        else:
            print(f"[HIDMaus] maus_sperren fehlgeschlagen ({instance_id}) - "
                  "laeuft der Prozess als Administrator?")
        return erfolg

    def maus_freigeben(self) -> bool:
        """Aktiviert die virtuelle PS/2-Maus wieder (Gegenstueck zu
        maus_sperren() - beim Stoppen eines Ablaufs oder ueber den
        Not-Aus-Hotkey aufzurufen, damit der Gast nicht ohne Zeigegeraet
        zurueckbleibt).

        Returns:
            bool: True bei Erfolg, False bei Fehler (Geraet nicht gefunden
                oder keine Berechtigung).
        """
        instance_id = _ps2_maus_instance_id_ermitteln()
        if not instance_id:
            return False
        erfolg = _pnp_geraet_umschalten(instance_id, aktivieren=True)
        if erfolg:
            print(f"[HIDMaus] PS/2-Maus wieder freigegeben ({instance_id})")
        else:
            print(f"[HIDMaus] maus_freigeben fehlgeschlagen ({instance_id}) - "
                  "laeuft der Prozess als Administrator?")
        return erfolg

    def schliessen(self):
        """Schließt die serielle Verbindung."""
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.verbunden = False
        print("[HIDMaus] Verbindung geschlossen")
