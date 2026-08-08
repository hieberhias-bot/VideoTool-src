with open('fish_bot.py', 'r', encoding='utf-8') as f:
    text = f.read()

alt = "if not maus.klick_links():"
neu = ("_logger.info('Klick gesendet auf (%d, %d)', bildschirm_x, bildschirm_y)\n"
       "    if not maus.klick_links():")

if alt in text:
    text = text.replace(alt, neu)
    with open('fish_bot.py', 'w', encoding='utf-8') as f:
        f.write(text)
    print('Log-Zeile hinzugefuegt')
else:
    print('Muster nicht gefunden - nichts geaendert')
