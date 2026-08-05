with open('screen/windows_capture.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('win32gui.GetSystemMetrics', 'win32api.GetSystemMetrics')

with open('screen/windows_capture.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('windows_capture.py: GetSystemMetrics -> win32api FIXED')
