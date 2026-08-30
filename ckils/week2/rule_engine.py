import ctypes, ctypes.wintypes
import win32api, win32con, win32gui, win32process, psutil
import time
import threading

def check_layout_later(exe_name, thread_id, delay):
    # runs on its own, separate from the main program, so it can sleep
    # without freezing the hook/message loop
    time.sleep(delay)
    later_hkl = win32api.GetKeyboardLayout(thread_id)
    print(f"    [debug +{delay}s] {exe_name}: layout is now {hex(later_hkl)}")


English_HKL = 0x04090409
Hebrew_HKL  = -0xfc2fbf3

RULES = {'Code.exe' : English_HKL,
          'Zoom.exe' : Hebrew_HKL}
last_set = {}          # hwnd -> HKL we last set (or the user's manual choice) for that window
last_switch_time = {}  # hwnd -> time.time() of our last switch attempt
overridden = set()     # hwnd the user manually overrode, not yet reset
SWITCH_GRACE = 0.3     # seconds to ignore mismatches right after we switch

previous_hwnd = None   # whichever window was focused just before the current event


user32 = ctypes.windll.user32
WinEventProcType = ctypes.WINFUNCTYPE(
    None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.HWND,
    ctypes.wintypes.LONG, ctypes.wintypes.LONG, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD)

def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
    global previous_hwnd

    # The instant focus leaves a window we were overriding, forget it ever happened —
    # its next visit starts completely fresh, rule applied automatically, nothing to see.
    if previous_hwnd is not None and previous_hwnd != hwnd and previous_hwnd in overridden:
        overridden.discard(previous_hwnd)
        last_set.pop(previous_hwnd, None)
    previous_hwnd = hwnd

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    exe_name = psutil.Process(pid).name()
    target_hkl = RULES.get(exe_name)
    if target_hkl is None:
        return

    actual_hkl = win32api.GetKeyboardLayout(thread_id)
#print(f"  [debug] {exe_name}: actual={hex(actual_hkl)}  target={hex(target_hkl)}")
    # ignore mismatches caused by our own switch not having propagated yet
    just_switched = time.time() - last_switch_time.get(hwnd, 0) < SWITCH_GRACE
    if hwnd in last_set and actual_hkl != last_set[hwnd] and not just_switched:
        overridden.add(hwnd)
        last_set[hwnd] = actual_hkl  # treat the user's manual choice as the new "last known" state
        print(f"{exe_name}: manual override detected, leaving it alone")
        return

    # This is the ONLY PostMessage call in the whole file — time exactly this one,
    # right where the actual switch happens, after the rule lookup and override guard.
    start = time.perf_counter()
    win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f'{exe_name}: switched to {hex(target_hkl)} in {elapsed_ms:.1f} ms')
#
# # spin up two background helpers to peek again shortly after, without blocking this callback
# threading.Thread(target=check_layout_later, args=(exe_name, thread_id, 0.5), daemon=True).start()
# threading.Thread(target=check_layout_later, args=(exe_name, thread_id, 1.5), daemon=True).start()
#
#
# win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)

    last_set[hwnd] = target_hkl
    last_switch_time[hwnd] = time.time()

callback = WinEventProcType(on_focus_change)
hook = user32.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
    0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT
)

print("CKILS is watching. Alt-Tab between your two configured apps. Ctrl+C to stop.")
win32gui.PumpMessages()
