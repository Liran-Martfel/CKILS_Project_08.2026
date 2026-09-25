"""
Live, verbose diagnostic for Tier 4's actual keystroke pipeline — built
after repeated real attempts showed zero gibberish_suspected rows despite
two real fixes already landing (the ctypes ABI mismatch, the wrong-thread
layout lookup) and the pure logic passing all its unit tests. Reuses the
REAL functions from keyboard_hook.py, layout_remap.py and
gibberish_detector.py directly — no reimplementation — and prints every
step for every letter key pressed, for LOOK_SECONDS, so a live mismatch
between what's expected and what's actually happening becomes visible
instead of only showing up (or not) as a row in ckils_skips.db afterward.

Does not touch ckils_skips.db and does not require the opt-in file — this
runs standalone, independent of whether CKILS.exe itself is running.
"""
import time

import win32api
import win32con
import win32gui
import win32process
import psutil
import uiautomation as auto

import gibberish_detector
import layout_remap
import keyboard_hook

ENGLISH_HKL = 0x04090409
HEBREW_HKL = -0xfc2fbf3
NAMES = {ENGLISH_HKL: "english", HEBREW_HKL: "hebrew"}

LOOK_SECONDS = 20

auto.InitializeUIAutomationInCurrentThread()
print(f"Type for the next {LOOK_SECONDS}s in whatever window you want checked "
      f"(bring it to front now). Every letter key is printed as it's processed.\n")

state = keyboard_hook._PerThreadState()
seen_down = set()
start = time.time()

while time.time() - start < LOOK_SECONDS:
    for vk in range(keyboard_hook.VK_A, keyboard_hook.VK_Z + 1):
        pressed = win32api.GetAsyncKeyState(vk) & 0x8000
        if pressed and vk not in seen_down:
            seen_down.add(vk)
            try:
                hwnd = win32gui.GetForegroundWindow()
                title = win32gui.GetWindowText(hwnd)
                thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
                exe_name = psutil.Process(pid).name()
                raw_hkl = win32api.GetKeyboardLayout(thread_id) & 0xFFFFFFFF
            except Exception as e:
                print(f"  [!] could not resolve focused window: {e}")
                continue

            if raw_hkl == (ENGLISH_HKL & 0xFFFFFFFF):
                current_hkl = ENGLISH_HKL
            elif raw_hkl == (HEBREW_HKL & 0xFFFFFFFF):
                current_hkl = HEBREW_HKL
            else:
                print(f"  [!] unrecognized layout raw_hkl={hex(raw_hkl)} — neither English nor Hebrew constant matched")
                continue

            scan = win32api.MapVirtualKey(vk, 0)
            shift = bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
            caps = bool(win32api.GetKeyState(win32con.VK_CAPITAL) & 0x0001)

            try:
                is_pw = bool(auto.GetFocusedControl().IsPassword)
            except Exception:
                is_pw = False

            char = layout_remap.remap_key_to_other_layout(vk, scan, current_hkl, shift, caps)
            print(f"vk={hex(vk)} window={exe_name}/{title[:25]!r} layout={NAMES.get(current_hkl)} "
                  f"is_password={is_pw} decoded_char={char!r}")

            if is_pw:
                print("  -> skipped: password field")
                state.reset()
            elif char is None:
                print("  -> skipped: no character produced for this key under the current layout")
            else:
                keyboard_hook.ENGLISH_HKL_VALUE, keyboard_hook.HEBREW_HKL_VALUE = ENGLISH_HKL, HEBREW_HKL
                result = keyboard_hook.process_key_event(vk, scan, state, current_hkl, False, False, shift, caps)
                print(f"  -> buffer so far: {state.chars.text()!r}  |  process_key_event result: {result}")
        elif not pressed and vk in seen_down:
            seen_down.discard(vk)
    time.sleep(0.01)

print("\nDone.")
