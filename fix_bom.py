with open('config.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("encoding='utf-8'", "encoding='utf-8-sig'")
content = content.replace('encoding="utf-8"', 'encoding="utf-8-sig"')

with open('config.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('config.py: utf-8 -> utf-8-sig ERSETZT')
