import ctypes, ctypes.wintypes

import win32.lib.win32con
import win32api, win32con, win32gui, win32process, psutil
import time
import threading
# ================================================================================
# CKILS rule_engine.py — Legend (short)
# ================================================================================
#
# hwnd        "Handle to a WiNDow" — an ID number, not the window itself.
# hkl         "Handle to a Keyboard Layout" — an ID for one installed layout.
# pid         "Process ID" — a number identifying one running program.
# thread_id   Layout is tracked PER THREAD, not per window — why some calls
#             need this instead of a hwnd, identifies one thread of execution inside a process.
#
# user32.dll — the core Windows file handling windows/input/
#             keyboard layouts. Used via ctypes here specifically because
#             SetWinEventHook has no pywin32 wrapper — ctypes calls straight
#             into the DLL for just that one function.
#
# ctypes            Python's bridge to raw Windows DLL functions.
# WinEventProcType  Describes your callback's exact shape (# of args, types)
#                   so Windows (written in C) knows how to call it.
# callback          on_focus_change, wrapped in that shape. Kept in a
#                   variable so it isn't garbage-collected while active.
# hook              Your active SetWinEventHook registration.
#
# RULES             exe_name -> either a plain hkl (simple app) or a list of
#                   (keyword, hkl) tuples (multi-window app, matched by title).
# resolve_target()  Decides the hkl for the focused window, or None.
# exe_name          Focused app's file name — the RULES dict key.
# title             Focused window's title-bar text — tells apart windows
#                   sharing the same exe_name.
# target_hkl        What resolve_target() says this window SHOULD be.
# actual_hkl        What the layout ACTUALLY is right now — compared against
#                   last_set to catch a manual override.
#
# last_set          {hwnd: hkl} — what we last set (or the user last chose).
# last_switch_time  {hwnd: time} — when we last switched, for the grace check.
# SWITCH_GRACE      Brief window after our own switch where a mismatch is
#                   ignored (our own change may not have propagated yet).
# overridden        Set of hwnds currently in "leave it alone" mode.
# previous_hwnd     Window focused just before this event — used to detect
#                   "focus just left a window," which resets its override.
# elapsed_ms        How long PostMessage took, via time.perf_counter().
#
# EVENT_SYSTEM_FOREGROUND    "A different window just got focus."
# WM_INPUTLANGCHANGEREQUEST  Same message Windows sends on Alt+Shift.
# WINEVENT_OUTOFCONTEXT      Run the callback safely in our own process.
# ================================================================================

def check_layout_later(exe_name, thread_id, delay):
    # runs on its own, separate from the main program, so it can sleep
    # without freezing the hook/message loop
    time.sleep(delay)
    later_hkl = win32api.GetKeyboardLayout(thread_id)
    print(f"    [debug +{delay}s] {exe_name}: layout is now {hex(later_hkl)}")


English_HKL = 0x04090409
Hebrew_HKL  = -0xfc2fbf3

RULES = {'Code.exe' : English_HKL,
         'chrome.exe' : [
                        ('Gmail', Hebrew_HKL),
                        ('Gemini', Hebrew_HKL),
                        ('Google Docs', English_HKL),
                        ('WhatsApp Business', Hebrew_HKL),
                        ('Jupyter', English_HKL),
                        ('Linear Regression', Hebrew_HKL),
                        ('Polynomial Regression', English_HKL),
                        ('K-Nearest Neighbors', Hebrew_HKL),
                        ('Support Vector Machines', English_HKL),
                        ('Decision Trees', Hebrew_HKL),
                        ('Random Forest', English_HKL),
                        ('Cross-Validation', Hebrew_HKL),
                        ('Grid Search', English_HKL),
                        ('K-Means', Hebrew_HKL),
                        ('PCA', English_HKL),],
         'msedge.exe' : Hebrew_HKL,
         'WindowsTerminal.exe' : English_HKL,
         'firefox.exe' : [('Gmail',Hebrew_HKL),('Google Docs',English_HKL)],
         'ms-teams.exe' : English_HKL,
         'pycharm64.exe' : English_HKL,}

last_set = {}          # hwnd -> HKL we last set (or the user's manual choice) for that window
last_switch_time = {}  # hwnd -> time.time() of our last switch attempt
overridden = set()     # hwnd the user manually overrode, not yet reset
SWITCH_GRACE = 0.3     # seconds to ignore mismatches right after we switch

previous_thread = None   # whichever thread window was focused just before the current event


user32 = ctypes.windll.user32
WinEventProcType = ctypes.WINFUNCTYPE(
    None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.HWND,
    ctypes.wintypes.LONG, ctypes.wintypes.LONG, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD)

def resolve_target(exe_name,title):
    """
    if it's none, nothing happened.
    rule = RULES.get(exe_name) means look up what is stored in RULES
    and check, is that a value a number? if that so, return the rule.
    if it's not a number, check if the keyword or hkl is anywhere inside this title text, if so return the hkl
    """
    rule = RULES.get(exe_name)
    if rule is None:
        return None
    if isinstance(rule, int): #a simple app, the title doesn't matter, just the rule.
        return rule
    for keyword, hkl in rule: #relevent in multi-window app - first matching to the title wins.
        if keyword in title:
            return hkl
    return None # none of the known titles matched — leave it alone


def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
    global previous_thread
    # The instant focus leaves a window we were overriding, forget it ever happened —
    # its next visit starts completely fresh, rule applied automatically, nothing to see.

    if event == win32con.EVENT_OBJECT_NAMECHANGE:
        if id_object != win32.lib.win32con.OBJID_WINDOW or id_child != win32.lib.win32con.CHILDID_SELF:
            return
        if hwnd != win32gui.GetForegroundWindow():
            return
    if previous_thread is not None and previous_thread != thread_id and previous_thread in overridden:
        overridden.discard(previous_thread)
        last_set.pop(previous_thread, None)
    previous_thread = thread_id

    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    exe_name = psutil.Process(pid).name()
    print(f"  [debug] exe_name = {exe_name!r}")   # add this line temporarily
    target_hkl = resolve_target(exe_name, title)
    if target_hkl is None:
        return

    actual_hkl = win32api.GetKeyboardLayout(thread_id)
    print(f"  [debug] {exe_name} hwnd={hwnd} thread={thread_id} actual={hex(actual_hkl)} last={hex(last_set.get(thread_id, -1))}")
    #print(f"  [debug] {exe_name}: actual={hex(actual_hkl)}  target={hex(target_hkl)}")
    # ignore mismatches caused by our own switch not having propagated yet
    just_switched = time.time() - last_switch_time.get(thread_id, 0) < SWITCH_GRACE
    if thread_id in last_set and actual_hkl != last_set[thread_id] and not just_switched:
        overridden.add(thread_id)
        last_set[thread_id] = actual_hkl  # treat the user's manual choice as the new "last known" state
        print(f"{exe_name}: manual override detected, leaving it alone")
        return

    # This is the ONLY PostMessage call in the whole file — time exactly this one,
    # right where the actual switch happens, after the rule lookup and override guard.
    start = time.perf_counter()
    win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f'{exe_name}: switched to {hex(target_hkl)} in {elapsed_ms:.1f} ms')

    last_set[thread_id] = target_hkl
    last_switch_time[thread_id] = time.time()

callback = WinEventProcType(on_focus_change)
hook = user32.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
    0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT)

name_hook = user32.SetWinEventHook(win32con.EVENT_OBJECT_NAMECHANGE,
    win32con.EVENT_OBJECT_NAMECHANGE,0,callback,0,0,win32con.WINEVENT_OUTOFCONTEXT)
print("CKILS is watching. Alt-Tab between your two configured apps. Ctrl+C to stop.")
# Exception ignored while calling ctypes callback function <function on_focus_change at 0x00000202CF8EAAE0>:
# Traceback (most recent call last):
#   File "C:\Users\liran\Personal_Project\ckils\week2\rule_engine.py", line 100, in on_focus_change
#     def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
# KeyboardInterrupt: expected error when stopping the program the first time
win32gui.PumpMessages()
