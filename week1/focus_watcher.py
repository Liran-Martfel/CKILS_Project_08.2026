import ctypes
import ctypes.wintypes
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

def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
    title = win32gui.GetWindowText(hwnd)
    # GetWindowThreadProcessId returns TWO values: (thread_id, process_id).
    # We only need the second one — the underscore is a Python convention
    # meaning "I'm intentionally throwing this value away."

    pid = win32process.GetWindowThreadProcessId(hwnd)
    # Now that we have the process ID, psutil can look up its .exe name.
    exe_name = psutil.Process(pid).name()

    print(f'Switched to: {title!r} ({exe_name})')

## Wrap our plain Python function in that exact shape. Keep this variable alive —
## if it gets garbage collected while the hook is active, Windows will crash.
callback = WinEventProcType(on_focus_change)

hook = user32.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND,  # smallest event ID we care about
    win32con.EVENT_SYSTEM_FOREGROUND,  # largest event ID we care about (same = "just this one")
    0,                                  # 0 = we're not loading this from an external DLL
    callback,                           # our wrapped callback from above
    0, 0,                                # 0, 0 = don't filter by process/thread — catch every window
    win32con.WINEVENT_OUTOFCONTEXT       # run our callback safely inside our own program
)

print("Watching for focus changes. Alt-Tab between a few windows. Ctrl+C to stop.")
win32gui.PumpMessages()  ## the message loop — keeps the program alive and listening
