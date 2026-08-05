import pyautogui
import pygetwindow as gw

# Fenster finden
fenster = gw.getWindowsWithTitle('METIN2')
if fenster:
    w = fenster[0]
    
    print("Fenster-Koordinaten:")
    print(f"  Position: left={w.left}, top={w.top}")
    print(f"  Groesse: width={w.width}, height={w.height}")
    
    # Fenster in den Vordergrund bringen
    try:
        w.activate()
        print("Fenster aktiviert!")
    except:
        print("Konnte nicht aktivieren (koennte normal sein)")
    
    # Mausposition vorher
    x, y = pyautogui.position()
    print(f"Mausposition: x={x}, y={y}")
    
    # Relativ zum Fenster
    rel_x = x - w.left
    rel_y = y - w.top
    print(f"Relativ zu METIN2: rel_x={rel_x}, rel_y={rel_y}")
    
    # Wuerde das im Fenster sein?
    if 0 <= rel_x < w.width and 0 <= rel_y < w.height:
        print("=> Maus IST im METIN2-Fenster!")
    else:
        print("=> Maus ist NICHT im METIN2-Fenster")
else:
    print("METIN2 Fenster nicht gefunden!")
