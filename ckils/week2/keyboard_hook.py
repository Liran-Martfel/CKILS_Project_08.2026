"""
Tier 4 safety net, piece 3 of 3 (see gibberish_detector.py for the CBAW
rules, layout_remap.py for "what would another layout have produced"): the
actual keystroke watcher. Phase 1 ONLY — this module never changes your
keyboard layout. It only decides "would this have been flagged as
gibberish", and records that decision through skip_logger — nothing about
how CKILS actually switches languages is touched by this file.

PRIVACY, stated as a hard rule, not a hope: the only things this module ever
keeps are (a) the CURRENT in-progress word's characters, in memory only,
cleared on every word boundary and capped at 12 characters, and (b) counts
and reason codes it hands to skip_logger — never the characters themselves.
Nothing here writes a raw keystroke to disk, ever. REPLACE_TIER4_PRIVACY_TEST
in test_regressions.py exists specifically to keep that true — it fails
loudly if any code path here ever reaches a logging/persistence call with
actual typed character content attached.

WHAT IS DELIBERATELY NEVER BUFFERED AT ALL (not "checked and ignored" —
never even added to the buffer, closing off entire categories of risk):
  - Any keystroke typed while Ctrl or Alt is held (a shortcut, not text).
  - Any keystroke while the focused control's IsPassword property is true.
  - Any keystroke flagged LLKHF_INJECTED (synthetic — including CKILS's own
    corrections elsewhere, and any other tool's simulated input).

WHY THE HOOK CALLBACK ITSELF DOES ALMOST NOTHING: a low-level keyboard hook
(WH_KEYBOARD_LL) runs synchronously, system-wide, on every keystroke,
everywhere, before the keystroke reaches the app you're typing into. Real
analysis (UI Automation calls, the CBAW check, the other-layout remap) is
real work with real latency — doing any of that inside the hook callback
would risk making typing itself feel laggy, which is a worse failure mode
than a wrong keyboard language ever was. The callback only records the bare
minimum (which key, up or down, a timestamp) onto a small queue and returns
immediately; a separate consumer thread does everything else.
"""
import ctypes
import ctypes.wintypes
import queue
import threading

import win32api
import win32con
import uiautomation as auto

import gibberish_detector
import layout_remap
import skip_logger

user32 = ctypes.windll.user32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
LLKHF_INJECTED = 0x00000010
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt

# Only plain letter keys are ever considered "typed text" here — anything
# else (digits, punctuation, function keys) either ends the current word
# (see gibberish_detector.is_word_boundary_char, applied to the DECODED
# character, not the vk code) or is simply not a letter to judge.
VK_A, VK_Z = 0x41, 0x5A

_event_queue = queue.Queue(maxsize=200)  # bounded — a burst of keys never blocks the hook callback
_started = False


class LowLevelKeyboardInputEvent(ctypes.Structure):
    """The KBDLLHOOKSTRUCT Windows passes to a WH_KEYBOARD_LL hook."""
    _fields_ = [
        ("vk_code", ctypes.wintypes.DWORD),
        ("scan_code", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


def _hook_proc(n_code, w_param, l_param):
    """The actual OS callback — kept intentionally trivial (see module
    docstring). Never calls UI Automation, never runs the CBAW check, never
    does anything that could take a meaningful amount of time.
    """
    try:
        if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            event = ctypes.cast(l_param, ctypes.POINTER(LowLevelKeyboardInputEvent)).contents
            if not (event.flags & LLKHF_INJECTED):
                try:
                    _event_queue.put_nowait((event.vk_code, event.scan_code))
                except queue.Full:
                    pass  # a burst of keys is dropped rather than ever blocking real typing
    except Exception:
        pass
    return user32.CallNextHookEx(None, n_code, w_param, l_param)


class _PerThreadState:
    """Per-consumer-thread state: the current word's decoded characters
    (gibberish_detector.IncrementalWordBuffer) alongside the SAME word's raw
    (vk, scan) pairs, kept in lockstep — the raw pairs are what let this
    re-derive "what would the OTHER layout have produced", something the
    decoded characters alone can't answer. Reset together, always.
    """
    def __init__(self):
        self.chars = gibberish_detector.IncrementalWordBuffer()
        self.raw_keys = []

    def reset(self):
        self.chars.reset()
        self.raw_keys = []


def _is_password_field_focused():
    """True if the currently focused control is a password field — checked
    lazily, only when actually about to record a suspected-gibberish event
    (not on every keystroke), since a UI Automation call is real work this
    module's own design guarantees say must never run on the hot path.
    """
    try:
        return bool(auto.GetFocusedControl().IsPassword)
    except Exception:
        return False


def process_key_event(vk_code, scan_code, state, current_hkl, ctrl_held, alt_held,
                       shift_pressed=False, caps_lock_on=False):
    """The pure decision function — everything about handling one keystroke
    that ISN'T a raw OS call, fully unit-testable with fakes. Mutates state
    (the caller's _PerThreadState) and returns a dict describing what
    happened (for logging/testing), or None if nothing worth recording
    happened this keystroke. Never touches the disk itself — see
    _run_phase1_check for the one place that calls skip_logger.
    """
    if ctrl_held or alt_held:
        state.reset()  # a shortcut, not text — whatever word was in progress is over
        return None

    if not (VK_A <= vk_code <= VK_Z):
        # A digit, punctuation, or other non-letter key: if it's a real word
        # boundary character it ends the current word (see below); either
        # way it's never itself judged as a letter.
        char = layout_remap.remap_key_to_other_layout(vk_code, scan_code, current_hkl, shift_pressed, caps_lock_on)
        if char and gibberish_detector.is_word_boundary_char(char):
            state.reset()
        return None

    char = layout_remap.remap_key_to_other_layout(vk_code, scan_code, current_hkl, shift_pressed, caps_lock_on)
    if not char:
        return None

    still_going = state.chars.push(char)
    if not still_going:
        return None  # boundary just reset it, or it just hit the cap — nothing new to judge yet
    state.raw_keys.append((vk_code, scan_code))

    current_language = "hebrew" if current_hkl == HEBREW_HKL_VALUE else "english"
    other_language = "english" if current_language == "hebrew" else "hebrew"
    if gibberish_detector.looks_impossible(state.chars.text(), current_language) is None:
        return None  # plausible so far under the current layout — nothing to suspect yet

    other_hkl = ENGLISH_HKL_VALUE if current_language == "hebrew" else HEBREW_HKL_VALUE
    other_text = "".join(
        layout_remap.remap_key_to_other_layout(k_vk, k_scan, other_hkl, shift_pressed, caps_lock_on) or ""
        for k_vk, k_scan in state.raw_keys
    )
    if gibberish_detector.looks_impossible(other_text, other_language) is not None:
        return None  # the alternate reading isn't plausible either — not real evidence either way

    return {
        "current_language": current_language,
        "other_language": other_language,
        "length": len(state.raw_keys),
    }


# Set by start(), read by process_key_event — module-level so tests can patch
# them directly without threading a dozen parameters through every call.
ENGLISH_HKL_VALUE = None
HEBREW_HKL_VALUE = None


def _consumer_loop():
    """Pulls queued key events and runs the real analysis — everything the
    hook callback itself deliberately avoids doing. One _PerThreadState per
    call, since this runs in its own dedicated thread.
    """
    state = _PerThreadState()
    while True:
        vk_code, scan_code = _event_queue.get()
        try:
            ctrl_held = bool(win32api.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            alt_held = bool(win32api.GetAsyncKeyState(VK_MENU) & 0x8000)
            shift_pressed = bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
            caps_lock_on = bool(win32api.GetKeyState(win32con.VK_CAPITAL) & 0x0001)
            current_hkl = win32api.GetKeyboardLayout(0) & 0xFFFFFFFF
            # Normalize to this module's signed HKL constants for comparison —
            # see layout_remap.py's own note on the same sign-representation gap.
            if current_hkl == (ENGLISH_HKL_VALUE & 0xFFFFFFFF):
                current_hkl = ENGLISH_HKL_VALUE
            elif current_hkl == (HEBREW_HKL_VALUE & 0xFFFFFFFF):
                current_hkl = HEBREW_HKL_VALUE
            else:
                continue  # neither layout we know about (e.g. a third installed layout) — nothing to judge

            if _is_password_field_focused():
                state.reset()
                continue

            result = process_key_event(vk_code, scan_code, state, current_hkl, ctrl_held, alt_held,
                                       shift_pressed, caps_lock_on)
            if result is not None:
                try:
                    exe_name, title, thread_id = _current_window_identity()
                except Exception:
                    exe_name, title, thread_id = "unknown", "", 0
                # PRIVACY: only counts and language names ever reach the log —
                # never the characters that were actually typed.
                skip_logger.log_skip(
                    exe_name, title, thread_id, skip_logger.REASON_GIBBERISH_SUSPECTED,
                    f"{result['current_language']}->{result['other_language']} len={result['length']}")
        except Exception:
            continue  # one bad event must never take down the whole consumer thread


def _current_window_identity():
    """Returns (exe_name, title, thread_id) for the currently focused
    window — same shape as rule_engine.py's own lookups, kept separate here
    to avoid a circular import.
    """
    import psutil
    import win32gui
    import win32process
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd)
    thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
    return psutil.Process(pid).name(), title, thread_id


_ENABLE_FLAG_FILENAME = "enable_gibberish_detection.on"


def start(english_hkl, hebrew_hkl):
    """Starts Tier 4 Phase 1 (log-only) — OFF BY DEFAULT. Requires an
    explicit opt-in file (_ENABLE_FLAG_FILENAME) next to CKILS, the inverse
    of skip_logger's kill-switch: this feature watches keystrokes, so it
    must be deliberately turned ON, never silently active. Registers the
    real OS hook and starts the consumer thread; never raises.
    """
    global _started, ENGLISH_HKL_VALUE, HEBREW_HKL_VALUE
    try:
        if _started:
            return
        if not skip_logger.os.path.exists(
                skip_logger.os.path.join(skip_logger._persistent_dir(), _ENABLE_FLAG_FILENAME)):
            print(f"  [keyboard_hook] not started: opt-in file {_ENABLE_FLAG_FILENAME} not present")
            return
        ENGLISH_HKL_VALUE, HEBREW_HKL_VALUE = english_hkl, hebrew_hkl
        _started = True
        threading.Thread(target=_consumer_loop, daemon=True).start()

        def _run_hook():
            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
            callback = callback_type(_hook_proc)
            hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, callback, None, 0)
            if not hook:
                print("  [keyboard_hook] failed to install the low-level keyboard hook")
                return
            import win32gui
            win32gui.PumpMessages()
        threading.Thread(target=_run_hook, daemon=True).start()
        print("  [keyboard_hook] Tier 4 Phase 1 active (log-only, corrects nothing)")
    except Exception as e:
        print(f"  [keyboard_hook] failed to start: {e}")
