import os
from screen.capture_interface import WindowCapture
if os.name == 'nt':
    from screen.windows_capture import WindowsCapture as GeneralCapture
elif os.name == 'posix':
    from screen.linux_capture import LinuxCapture as GeneralCapture
else:
    raise Exception("Unsupported OS")
