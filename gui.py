# gui.py - Vision & Input Automation Tool (GUI)
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import config

from ablauf_rekorder import AblaufRekorder, liste_ablauefe
from arduino_steuerung import ArduinoSteuerung
from trigger import TriggerSystem

class VisionToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Vision & Input Automation Tool')
        self.root.geometry('720x560')
        self.root.resizable(False, False)
        self.arduino = ArduinoSteuerung()
        self.arduino_verbunden = False
        self.aufnahme_laeuft = False
        self.trigger = TriggerSystem()
        self.stil = ttk.Style()
        self.stil.theme_use('clam')
        self._baue_oberflaeche()

    def _baue_oberflaeche(self):
        header = tk.Frame(self.root, bg='#2c3e50', height=60)
        header.pack(fill='x')
        tk.Label(header, text='Vision & Input Automation Tool', bg='#2c3e50', fg='white',
                 font=('Segoe UI', 16, 'bold')).pack(pady=12)
        main = tk.Frame(self.root, padx=20, pady=15)
        main.pack(fill='both', expand=True)
        self.status_var = tk.StringVar(value='Arduino: Nicht verbunden')
        tk.Label(main, textvariable=self.status_var, font=('Segoe UI', 10), fg='#555').pack(anchor='w')
        btn_frame = tk.Frame(main)
        btn_frame.pack(pady=10, anchor='w')
        self.btn_aufnahme = ttk.Button(btn_frame, text='Aufnahme starten (F9 = Stopp)',
                                       command=self.toggle_aufnahme, width=30)
        self.btn_aufnahme.pack(side='left', padx=5)
        self.btn_abspielen = ttk.Button(btn_frame, text='Ablauf abspielen',
                                        command=self.abspielen, width=20)
        self.btn_abspielen.pack(side='left', padx=5)
        # Trigger-Bereich
        tk.Label(main, text='Trigger (Multi-Pixel):', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(10,2))
        trigger_frame = tk.Frame(main)
        trigger_frame.pack(anchor='w')
        self.btn_fenster = ttk.Button(trigger_frame, text='Fenster waehlen',
                                       command=self.fenster_waehlen, width=16)
        self.btn_fenster.pack(side='left', padx=5)
        self.btn_pixel = ttk.Button(trigger_frame, text='Pixel sammeln',
                                     command=self.pixel_sammeln, width=16)
        self.btn_pixel.pack(side='left', padx=5)
        self.btn_trigger_aufnahme = ttk.Button(trigger_frame, text='Aufnahme mit Trigger',
                                                 command=self.trigger_aufnahme, width=20)
        self.btn_trigger_aufnahme.pack(side='left', padx=5)
        self.trigger_status = tk.StringVar(value='Trigger: inaktiv')
        tk.Label(main, textvariable=self.trigger_status, font=('Segoe UI', 9), fg='#888').pack(anchor='w')
        tk.Label(main, text='Ablauf auswaehlen:', font=('Segoe UI', 11)).pack(anchor='w', pady=(10,2))
        self.ablauf_combo = ttk.Combobox(main, state='readonly', width=50)
        self.ablauf_combo.pack(anchor='w')
        self._aktualisiere_ablaeufe()
        tk.Label(main, text='Arduino:', font=('Segoe UI', 11)).pack(anchor='w', pady=(10,2))
        arduino_frame = tk.Frame(main)
        arduino_frame.pack(anchor='w')
        self.com_port_var = tk.StringVar(value=getattr(config, 'com_port', 'COM3'))
        tk.Entry(arduino_frame, textvariable=self.com_port_var, width=8).pack(side='left', padx=5)
        self.btn_arduino = ttk.Button(arduino_frame, text='Verbinden', command=self.arduino_verbinden, width=12)
        self.btn_arduino.pack(side='left', padx=5)
        tk.Label(main, text='Log:', font=('Segoe UI', 11)).pack(anchor='w', pady=(10,2))
        self.log_text = scrolledtext.ScrolledText(main, height=10, state='disabled', font=('Consolas', 9))
        self.log_text.pack(fill='both', expand=True)
        footer = tk.Frame(self.root, bg='#ecf0f1')
        footer.pack(fill='x', side='bottom')
        ttk.Button(footer, text='Beenden', command=self.root.quit).pack(side='right', padx=10, pady=5)

    def _aktualisiere_ablaeufe(self):
        self.ablaeufe = liste_ablauefe()
        self.ablauf_combo['values'] = self.ablaeufe if self.ablaeufe else ['(keine Ablaeufe)']

    def log(self, msg):
        self.log_text.config(state='normal')
        self.log_text.insert('end', '[%s] %s\n' % (time.strftime('%H:%M:%S'), msg))
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def arduino_verbinden(self):
        port = self.com_port_var.get().strip()
        self.arduino = ArduinoSteuerung(port=port)
        try:
            self.arduino.verbinde()
            self.arduino_verbunden = True
            self.status_var.set('Arduino: %s (aktiv)' % port)
            self.log('Arduino auf %s verbunden' % port)
        except Exception as e:
            self.arduino_verbunden = False
            self.status_var.set('Arduino: %s (Fehler)' % port)
            self.log('Arduino Fehler: %s' % e)

    def toggle_aufnahme(self):
        if not self.aufnahme_laeuft:
            self.aufnahme_laeuft = True
            self.btn_aufnahme.config(text='Aufnahme laeuft... (F9 = Stopp)')
            self.log('Aufnahme gestartet - F9 zum Stoppen')
            threading.Thread(target=self._aufnahme_worker, daemon=True).start()
        else:
            self.aufnahme_laeuft = False
            self.btn_aufnahme.config(text='Aufnahme starten (F9 = Stopp)')

    def _aufnahme_worker(self):
        self.aufzeichnung = AblaufRekorder()
        self.aufzeichnung.starte_aufnahme()
        while self.aufnahme_laeuft:
            time.sleep(0.1)
        name = time.strftime('ablauf_%Y%m%d_%H%M%S')
        self.aufzeichnung.speichere_ablauf(name)
        self.log('Aufnahme gespeichert: %s' % name)
        self._aktualisiere_ablaeufe()

    def abspielen(self):
        name = self.ablauf_combo.get()
        if not name or name == '(keine Ablaeufe)':
            messagebox.showwarning('Kein Ablauf', 'Bitte zuerst einen Ablauf auswaehlen.')
            return
        self.log('Spiele Ablauf ab: %s' % name)
        threading.Thread(target=self._abspielen_worker, args=(name,), daemon=True).start()

    def _abspielen_worker(self, name):
        try:
            aufzeichnung = AblaufRekorder()
            aufzeichnung.spiele_ab(name, config)
            self.log('Ablauf beendet')
        except Exception as e:
            self.log('Fehler beim Abspielen: %s' % e)

    def fenster_waehlen(self):
        self.log('Fenster waehlen: Klicke in das Fenster...')
        threading.Thread(target=self._fenster_worker, daemon=True).start()

    def _fenster_worker(self):
        try:
            region = self.trigger.waehle_fenster()
            if region:
                self.trigger_status.set('Trigger: Fenster gewaehlt (%d, %d)' % (region[0], region[1]))
                self.log('Fenster gewaehlt bei (%d, %d)' % (region[0], region[1]))
        except Exception as e:
            self.log('Fehler Fensterwahl: %s' % e)

    def pixel_sammeln(self):
        if not self.trigger.fenster_region:
            messagebox.showwarning('Kein Fenster', 'Bitte zuerst Fenster waehlen.')
            return
        self.log('Pixel sammeln: Klicke auf Trigger-Pixel, ESC = fertig')
        threading.Thread(target=self._pixel_worker, daemon=True).start()

    def _pixel_worker(self):
        try:
            pixel = self.trigger.sammle_pixel()
            self.trigger_status.set('Trigger: %d Pixel gespeichert' % len(pixel))
            self.log('%d Trigger-Pixel gespeichert' % len(pixel))
        except Exception as e:
            self.log('Fehler Pixel sammeln: %s' % e)

    def trigger_aufnahme(self):
        if not self.trigger.fenster_region or not self.trigger.pixel:
            messagebox.showwarning('Kein Trigger', 'Bitte zuerst Fenster und Pixel definieren.')
            return
        self.log('Warte auf Trigger... (Aufnahme startet wenn alle Pixel treffen)')
        threading.Thread(target=self._trigger_aufnahme_worker, daemon=True).start()

    def _trigger_aufnahme_worker(self):
        try:
            self.aufzeichnung = AblaufRekorder()
            self.aufzeichnung.starte_aufnahme(auf_trigger_warten=True, trigger=self.trigger)
            name = time.strftime('ablauf_%Y%m%d_%H%M%S')
            self.aufzeichnung.speichere_ablauf(name)
            self.log('Aufnahme gespeichert: %s' % name)
            self._aktualisiere_ablaeufe()
        except Exception as e:
            self.log('Fehler Trigger-Aufnahme: %s' % e)

def main():
    root = tk.Tk()
    VisionToolApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()

