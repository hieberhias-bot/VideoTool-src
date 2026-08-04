import win32gui
import dxcam
import numpy as np
from screen.capture_interface import WindowCapture

class WindowsCapture(WindowCapture):
    """
    Class that allows to capture a window from the screen using dxcam module in windows.
    """

    def __init__(self):
        self.camera = dxcam.create(output_color="BGR")
        self.hwnd = None

    def set_window_name(self, window_name: str):
        self.hwnd = win32gui.FindWindow(None, window_name)
        if not self.hwnd:
            raise RuntimeError(f'Window not found: {window_name}')

    def get_screenshot(self) -> tuple[np.ndarray, int, int]:
        window_rect = win32gui.GetWindowRect(self.hwnd)
        screen_width = win32gui.GetSystemMetrics(0)
        screen_height = win32gui.GetSystemMetrics(1)

        start_x = min(screen_width, max(0, window_rect[0]))
        start_y = min(screen_height, max(0, window_rect[1]))
        end_x = min(screen_width, max(0, window_rect[2]))
        end_y = min(screen_height, max(0, window_rect[3]))

        if end_x == 0 or end_y == 0:
            return None

        return self.camera.grab(region=[start_x, start_y, end_x, end_y]), start_x, start_y

    def list_window_names(self):
        def winEnumHandler(hwnd, ctx):
            if win32gui.IsWindowVisible(hwnd):
                print(hex(hwnd), win32gui.GetWindowText(hwnd))
        win32gui.EnumWindows(winEnumHandler, None)
