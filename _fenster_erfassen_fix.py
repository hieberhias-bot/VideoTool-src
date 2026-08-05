# --- Fenster erfassen (fuer fenster-relative Aufnahme) ---
def _fenster_erfassen(self):
    if not FENSTER_OK:
        messagebox.showinfo("Hinweis",
            "Fenster-Modul nicht verfuegbar. Nutze absolute Koordinaten.")
        return
    if self.recording:
        return
    # Automatische Suche nach Metin2-Fenster (kein Klick noetig)
    such = self.trig_fenster.get().strip() or "Metin2"
    info = fenster_util.fenster_finden(such)
    if not info:
        self.lbl_rec_status.config(
            text="Fenster '%s' nicht gefunden - ist es offen?" % such,
            foreground="#f38ba8")
        self._log_fish("Fenster '%s' nicht gefunden." % such)
        return
    self._fenster_erfasst({"titel": such, **info})
