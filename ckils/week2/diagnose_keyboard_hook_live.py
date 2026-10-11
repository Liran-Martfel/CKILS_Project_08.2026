"""
Live, verbose diagnostic for Tier 4's actual keystroke pipeline — built
after repeated real attempts showed zero gibberish_suspected rows despite
two real fixes already landing (the ctypes ABI mismatch, the wrong-thread
layout lookup) and the pure logic passing all its unit tests. Reuses the
REAL functions from keyboard_hook.py, layout_remap.py and
gibberish_detector.py directly — no reimplementation — and prints every
step for every letter/boundary key pressed, for LOOK_SECONDS, so a live
mismatch between what's expected and what's actually happening becomes
visible instead of only showing up (or not) as a row in ckils_skips.db
afterward.

Real bug found live, 2026-10-11: this tool itself gave a FALSE "stuck"
reading after the 2026-10-08 fixes landed — it only ever watched
VK_A..VK_Z (so Space/Enter/Tab, which process_key_event now resets on
unconditionally, were invisible to it) and never called
_reset_on_focus_change (so a real window switch didn't reset its local
`state` either, unlike the real _consumer_loop). The buffer looked
permanently capped on an old word while the REAL CKILS.exe, watching the
exact same keystrokes through the real pipeline, had already correctly
moved on and logged a real detection. Fixed by watching a small set of
real boundary keys too and calling the same _reset_on_focus_change the
real consumer loop calls, so this tool's `state` can no longer drift from
what the real app is doing.

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

# Space, Enter, Tab — real, common word-boundary keys, watched alongside the
# letters so the 2026-10-08 non-letter-key reset is actually exercised here
# too, not just the letter path.
BOUNDARY_VKS = {0x20: "space", 0x0D: "enter", 0x09: "tab"}
WATCHED_VKS = list(range(keyboard_hook.VK_A, keyboard_hook.VK_Z + 1)) + list(BOUNDARY_VKS)

LOOK_SECONDS = 20

auto.InitializeUIAutomationInCurrentThread()
print(f"Type for the next {LOOK_SECONDS}s in whatever window you want checked "
      f"(bring it to front now). Every letter/boundary key is printed as it's processed.\n")

state = keyboard_hook._PerThreadState()
last_thread_id = None
seen_down = set()
start = time.time()

while time.time() - start < LOOK_SECONDS:
    for vk in WATCHED_VKS:
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

            # Same call the real _consumer_loop makes, every event, before
            # anything else — a real window/tab switch must reset `state`
            # here too, or this tool's own buffer can silently drift from
            # what the real app is doing (see module docstring).
            if thread_id != last_thread_id:
                print(f"  [focus change] thread {last_thread_id} -> {thread_id}: state reset")
            last_thread_id = keyboard_hook._reset_on_focus_change(state, thread_id, last_thread_id)

            scan = win32api.MapVirtualKey(vk, 0)
            shift = bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
            caps = bool(win32api.GetKeyState(win32con.VK_CAPITAL) & 0x0001)

            try:
                is_pw = bool(auto.GetFocusedControl().IsPassword)
            except Exception:
                is_pw = False

            if vk in BOUNDARY_VKS:
                label = f"[{BOUNDARY_VKS[vk]}]"
                char = None
            else:
                label = None
                char = layout_remap.remap_key_to_other_layout(vk, scan, current_hkl, shift, caps)
            print(f"vk={hex(vk)}{' ' + label if label else ''} window={exe_name}/{title[:25]!r} "
                  f"layout={NAMES.get(current_hkl)} is_password={is_pw} decoded_char={char!r}")

            if is_pw:
                print("  -> skipped: password field")
                state.reset()
            elif vk in BOUNDARY_VKS:
                keyboard_hook.ENGLISH_HKL_VALUE, keyboard_hook.HEBREW_HKL_VALUE = ENGLISH_HKL, HEBREW_HKL
                result = keyboard_hook.process_key_event(vk, scan, state, current_hkl, False, False, shift, caps)
                print(f"  -> buffer so far: {state.chars.text()!r}  |  process_key_event result: {result}")
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
