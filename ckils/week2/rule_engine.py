import ctypes, ctypes.wintypes
import win32.lib.win32con
import win32api, win32con, win32gui, win32process, psutil
import time
import threading
import json
import os
import shutil
import uiautomation as auto
from ocr_reader import read_region
from predict_language import predict_language

# Set to False for a quiet, end-user-facing run — True prints a line for every
# focus change and every content-layer check, useful while developing/debugging.
DEBUG = True
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

English_HKL = 0x04090409
Hebrew_HKL  = -0xfc2fbf3
LANGUAGE_NAME_TO_HKL = {"english": English_HKL, "hebrew": Hebrew_HKL}

# Your own app -> language rules live in rules_config.json, not hardcoded here —
# that file is personal/local (gitignored), so this code stays clean and generic
# for anyone else who downloads it. See rules_config.example.json for the format.
RULES_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_CONFIG_FILE = os.path.join(RULES_DIR, "rules_config.json")
RULES_EXAMPLE_FILE = os.path.join(RULES_DIR, "rules_config.example.json")


def load_rules():
    if not os.path.exists(RULES_CONFIG_FILE):
        if os.path.exists(RULES_EXAMPLE_FILE):
            shutil.copy(RULES_EXAMPLE_FILE, RULES_CONFIG_FILE)
        else:
            return {}

    with open(RULES_CONFIG_FILE, encoding="utf-8") as f:
        raw = json.load(f)

    rules = {}
    for exe_name, value in raw.items():
        if exe_name.startswith("_"):  # e.g. "_comment" — documentation, not a rule
            continue
        if isinstance(value, str):
            rules[exe_name] = LANGUAGE_NAME_TO_HKL[value]
        else:
            rules[exe_name] = [(keyword, LANGUAGE_NAME_TO_HKL[lang]) for keyword, lang in value.items()]
    return rules


RULES = load_rules()

last_set = {}          # hwnd -> HKL we last set (or the user's manual choice) for that window
last_switch_time = {}  # hwnd -> time.time() of our last switch attempt
overridden = set()     # hwnd the user manually overrode, not yet reset
SWITCH_GRACE = 0.3     # seconds to ignore mismatches right after we switch

# Real bug found live: some apps fire EVENT_OBJECT_NAMECHANGE repeatedly for the
# same window in quick succession (e.g. while a page is still loading). Each one
# used to spawn its own background correction thread, and multiple could race on
# the same thread_id's last_set — one thread's stale result landing after
# another's made it look like a manual override that never actually happened.
# This tracks which thread_ids already have a correction in flight, so a new
# NAMECHANGE event skips spawning a redundant, racing one.
content_check_in_progress = set()

# Tier 3 (Week 5): refines — or, for an unruled app, supplies — the switch decision
# using the actual on-screen text, via UI Automation + OCR + the model trained in 5.4.
CONTENT_CONFIDENCE_THRESHOLD = 0.65
LANGUAGE_TO_HKL = {"english": English_HKL, "hebrew": Hebrew_HKL}


# Latency scales with how much text there is to recognize, not raw pixel area —
# measured 6805ms on a full 1920x1080 dense pane vs 523ms capped to 300x100.
# Capping keeps this closer to Tesseract's own ~500-650ms floor instead of scaling
# unboundedly with a large code editor or webpage.
MAX_OCR_WIDTH = 400
MAX_OCR_HEIGHT = 150


def decide_with_content(fallback_hkl):
    """
    Falls back to fallback_hkl (Tier 1/2's answer, possibly None) on an empty
    field, low model confidence, or any failure in this layer — Tier 1/2 stays
    the proven base (Week 4: "Go with Conditions"), this only adds to it.
    """
    try:
        control = auto.GetFocusedControl()
        rect = control.BoundingRectangle
        right = min(rect.right, rect.left + MAX_OCR_WIDTH)
        bottom = min(rect.bottom, rect.top + MAX_OCR_HEIGHT)
        text = read_region(rect.left, rect.top, right, bottom)
    except Exception as e:
        if DEBUG:
            print(f"  [content] skipped ({e})")
        return fallback_hkl

    if not text.strip():
        if DEBUG:
            print("  [content] empty field, nothing to read")
        return fallback_hkl

    label, proba = predict_language(text)
    confidence = proba[label]
    if DEBUG:
        print(f"  [content] read {text[:60]!r} -> {label} ({confidence:.2f} confidence)")
    if confidence < CONTENT_CONFIDENCE_THRESHOLD:
        if DEBUG:
            print(f"  [content] confidence below {CONTENT_CONFIDENCE_THRESHOLD} threshold, trusting the rule")
        return fallback_hkl

    return LANGUAGE_TO_HKL[label]

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
    if DEBUG:
        print(f"  [debug] exe_name = {exe_name!r}")
    target_hkl = resolve_target(exe_name, title)

    if target_hkl is not None:
        actual_hkl = win32api.GetKeyboardLayout(thread_id)
        if DEBUG:
            print(f"  [debug] {exe_name} hwnd={hwnd} thread={thread_id} title={title!r} actual={hex(actual_hkl)} last={hex(last_set.get(thread_id, -1))}")
        # ignore mismatches caused by our own switch not having propagated yet
        just_switched = time.time() - last_switch_time.get(thread_id, 0) < SWITCH_GRACE
        if thread_id in last_set and actual_hkl != last_set[thread_id] and not just_switched:
            overridden.add(thread_id)
            last_set[thread_id] = actual_hkl  # treat the user's manual choice as the new "last known" state
            print(f"{exe_name}: manual override detected, leaving it alone")
        else:
            # This is the fast path — unchanged from Weeks 2-4, still sub-millisecond.
            # Tier 3 (below) never blocks this; it only corrects it afterward if needed.
            start = time.perf_counter()
            win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f'{exe_name}: switched to {hex(target_hkl)} in {elapsed_ms:.1f} ms')
            last_set[thread_id] = target_hkl
            last_switch_time[thread_id] = time.time()

    # Tier 3 (Week 5) runs in a background thread: real testing showed OCR alone
    # costs 500ms+ even on a tiny, near-empty region (Tesseract reloads its language
    # models from scratch every call) plus a few more ms per character recognized —
    # both far past SC-02's 150ms target. Rather than block the proven fast path
    # above on that, it runs after the fact and only corrects the switch if it
    # disagrees, is confident, and the user hasn't already moved on or overridden it.
    # Skip spawning one if this same window already has a correction in flight —
    # see content_check_in_progress above for why that matters.
    if thread_id not in content_check_in_progress:
        content_check_in_progress.add(thread_id)
        threading.Thread(
            target=apply_content_correction,
            args=(hwnd, thread_id, exe_name, target_hkl),
            daemon=True
        ).start()


def apply_content_correction(hwnd, thread_id, exe_name, rule_hkl):
    # Held for the whole function, not just the OCR part — this is what actually
    # stops two corrections for the same window from racing on last_set/overridden.
    try:
        # COM (which UI Automation needs) is initialized per THREAD, not once for the
        # whole process — this function runs in a new background thread every time,
        # so it needs its own init call here, separate from the one before PumpMessages().
        auto.InitializeUIAutomationInCurrentThread()

        start = time.perf_counter()
        corrected_hkl = decide_with_content(rule_hkl)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if corrected_hkl == rule_hkl or corrected_hkl is None:
            if DEBUG:
                print(f"  [content] {exe_name}: no change ({elapsed_ms:.0f} ms)")
            return
        if win32gui.GetForegroundWindow() != hwnd:
            if DEBUG:
                print(f"  [content] {exe_name}: decision arrived too late, focus moved on ({elapsed_ms:.0f} ms)")
            return
        if thread_id in overridden:
            if DEBUG:
                print(f"  [content] {exe_name}: user has manually overridden this window, leaving it alone ({elapsed_ms:.0f} ms)")
            return

        win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, corrected_hkl)
        last_set[thread_id] = corrected_hkl
        last_switch_time[thread_id] = time.time()
        print(f"{exe_name}: content-aware correction to {hex(corrected_hkl)} ({elapsed_ms:.0f} ms)")
    finally:
        content_check_in_progress.discard(thread_id)

callback = WinEventProcType(on_focus_change)
hook = user32.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
    0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT)

name_hook = user32.SetWinEventHook(win32con.EVENT_OBJECT_NAMECHANGE,
    win32con.EVENT_OBJECT_NAMECHANGE,0,callback,0,0,win32con.WINEVENT_OUTOFCONTEXT)
auto.InitializeUIAutomationInCurrentThread()  # once, before the message loop — needed by decide_with_content()
print("CKILS is watching in the background. Press Ctrl+C in this window to stop.")
win32gui.PumpMessages()
