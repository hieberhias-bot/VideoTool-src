import re, io

path = r'command_center.py'
with open(path, 'r', encoding='utf-8-sig') as f:
    src = f.read()

elevation_code = '''

def _ensure_admin():
    import ctypes, sys, os
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True
    except:
        return True
    script = os.path.abspath(sys.argv[0]) if sys.argv and os.path.exists(sys.argv[0]) else os.path.abspath(__file__)
    ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, '"%s"' % script, None, 1)
    return False

if __name__ == '__main__':
    if not _ensure_admin():
        sys.exit()
'''

if '_ensure_admin' not in src:
    if "if __name__ == '__main__':" in src:
        src = src.replace("if __name__ == '__main__':", elevation_code + "\nif __name__ == '__main__':", 1)
    else:
        src += elevation_code
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src)
    print('ELEVATION_CODE_EINGEFUEGT')
else:
    print('BEREITS_VORHANDEN')
