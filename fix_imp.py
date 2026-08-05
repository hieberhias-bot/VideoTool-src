with open('screen/windows_capture.py', 'r', encoding='utf-8') as f:
    content = f.read()

# win32api Import hinzufuegen falls nicht vorhanden
if 'import win32api' not in content and 'from win32api' not in content:
    content = content.replace('import win32gui', 'import win32gui\nimport win32api')

with open('screen/windows_capture.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('win32api import ADDED')
