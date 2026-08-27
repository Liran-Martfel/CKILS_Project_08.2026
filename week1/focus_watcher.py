import ctypes
import ctypes.wintypes
import win32api
import win32con, win32gui, win32process, psutil

user32 = ctypes.windll.user32  ## direct access to Windows' user32.dll — this is where
## SetWinEventHook actually lives, since pywin32 doesn't wrap it

## Describes the exact shape of our callback (7 arguments, no return value) so ctypes
## can safely hand it to a C function expecting a real C function pointer.
WinEventProcType = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LONG,
    ctypes.wintypes.LONG,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD
)


