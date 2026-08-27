import ctypes, ctypes.wintypes
import win32api, win32con, win32gui, win32process, psutil

English_HKL = 0x04090409
Hebrew_HKL  = -0xfc2fbf3

RULES = {'Notepad.exe' : English_HKL,
          'Calculator.exe' : Hebrew_HKL}

user32 = ctypes.windll.user32
WinEventProcType = ctypes.WINFUNCTYPE(
    None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.HWND,
    ctypes.wintypes.LONG, ctypes.wintypes.LONG, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD)

def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    exe_name = psutil.Process(pid).name()

    # get(...) returns None if exe_name isn't in RULES, instead of crashing
    target_hkl = RULES.get(exe_name)
    if target_hkl is not None:
        win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
        print(f"{exe_name}: switched to {hex(target_hkl)}")
    else:
        print(f"{exe_name}: no rule, left alone")

callback = WinEventProcType(on_focus_change)
hook = user32.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
    0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT
)

print("CKILS is watching. Alt-Tab between your two configured apps. Ctrl+C to stop.")
win32gui.PumpMessages()
