import serial
import time
import ctypes

VK_LBUTTON = 0x01

class HIDMaus:
    """Schnittstelle zum Arduino HID-Maus-Emulator (Text-Protokoll)."""

    def __init__(self, port="COM5", baud=115200, timeout=1.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser = None
        self.verbunden = False

    def verbinden(self):
        """Öffnet die serielle Verbindung zum Arduino."""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            time.sleep(2)  # Arduino-Reset abwarten
            self.verbunden = True
            print(f"[HIDMaus] Verbunden mit {self.port}")
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

    def schliessen(self):
        """Schließt die serielle Verbindung."""
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.verbunden = False
        print("[HIDMaus] Verbindung geschlossen")