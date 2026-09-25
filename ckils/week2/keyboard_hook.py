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
import time

import win32api
import win32con
import uiautomation as auto

import gibberish_detector
import layout_remap
import skip_logger

user32 = ctypes.windll.user32

# Real bug found live, caused a total keyboard freeze until CKILS was killed:
# neither of these two calls had its real return type declared, so ctypes
# defaulted to a plain 32-bit `int` for both. The real Windows type is
# LRESULT — pointer-sized, 64-bit on a 64-bit machine. WH_KEYBOARD_LL's
# contract is that returning ANY NONZERO value from the hook tells Windows
# to swallow that keystroke everywhere, for every app, permanently until the
# hook is removed. With the upper 32 bits of a 64-bit return register left
# as garbage instead of correctly zero-extended, the value Windows actually
# read back could easily be nonzero even when CallNextHookEx's real,
# intended answer was 0 (pass the key through) — silently blocking every
# keystroke system-wide. This is exactly why the keyboard came back the
# instant the process (and its malformed hook) was torn down. Declaring the
# real return types below is the fix — c_ssize_t is pointer-sized on every
# Windows build, unlike c_long, which is always 32-bit even on 64-bit
# Windows (the LLP64 model).
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD]
user32.UnhookWindowsHookEx.restype = ctypes.c_int
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

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
_hook_callback_ref = None  # keeps the ctypes callback alive for the hook's lifetime — see _run_hook
_hook_handle = None  # the real HHOOK, once installed — needed by the panic watcher to remove it live

# Real request from the user, after the keyboard-freeze incident: a way to
# recover WITHOUT closing CKILS, since only the process dying (or the
# process unhooking itself) can remove a live low-level keyboard hook, and a
# frozen keyboard can't type anything to trigger the second option. This
# watcher runs on its own thread, checking for one file's existence every
# PANIC_CHECK_INTERVAL_SECONDS — nothing about window focus, nothing about
# what app is active, just that one file. It has NOTHING to do with focus
# changes; it runs continuously regardless of what you're doing. The moment
# the file appears, it removes Tier 4's hook (not the rest of CKILS — Tiers
# 1-3 are untouched and keep running) and deletes the trigger file so it
# doesn't fire again. One-shot per run: once triggered, Tier 4 stays off for
# the rest of this CKILS session (restart to re-arm it), the same lifetime a
# real process-kill would have given it, just without losing the other tiers.
PANIC_TRIGGER_FILENAME = "disable_tier4_now.trigger"
PANIC_CHECK_INTERVAL_SECONDS = 1.5


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


# The real HOOKPROC return type is LRESULT — pointer-sized (c_ssize_t), not
# c_long (always 32-bit). See the module-level comment above CallNextHookEx's
# restype declaration for why getting this wrong froze the keyboard.
_HOOK_CALLBACK_TYPE = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)


class _PerThreadState:
    """Per-consumer-thread state: the current word's decoded characters
    (gibberish_detector.IncrementalWordBuffer) alongside the SAME word's raw
    (vk, scan) pairs, kept in lockstep — the raw pairs are what let this
    re-derive "what would the OTHER layout have produced", something the
    decoded characters alone can't answer. Reset together, always.
    """
    def __init__(self):
        """Starts with no word in progress and no raw keys recorded."""
        self.chars = gibberish_detector.IncrementalWordBuffer()
        self.raw_keys = []

    def reset(self):
        """Clears both the decoded-character buffer and the raw (vk, scan)
        pairs together, so they can never drift out of sync with each other.
        """
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
            # Real bug found live, 2026-09-25: keyboard layout is tracked PER
            # THREAD in Windows (the same fact rule_engine.py is built around
            # throughout) — GetKeyboardLayout(0) asks for THIS thread's own
            # layout (the consumer thread itself, which never has a real user
            # typing into it), not the layout of whatever window the user is
            # actually focused on. That silently judged every keystroke
            # against the wrong layout regardless of what was really active,
            # which is why even a guaranteed catch (a Hebrew final-form
            # letter not at the end of a word) never fired. Fixed by looking
            # up the REAL foreground window's thread first, same as
            # rule_engine.py already does everywhere else, and using THAT
            # thread's layout instead of this thread's own.
            try:
                exe_name, title, thread_id = _current_window_identity()
                current_hkl = win32api.GetKeyboardLayout(thread_id) & 0xFFFFFFFF
            except Exception:
                continue  # the focused window vanished mid-keystroke — skip this one event

            ctrl_held = bool(win32api.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            alt_held = bool(win32api.GetAsyncKeyState(VK_MENU) & 0x8000)
            shift_pressed = bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
            caps_lock_on = bool(win32api.GetKeyState(win32con.VK_CAPITAL) & 0x0001)
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
                # PRIVACY: only counts and language names ever reach the log —
                # never the characters that were actually typed.
                skip_logger.log_skip(
                    exe_name, title, thread_id, skip_logger.REASON_GIBBERISH_SUSPECTED,
                    f"{result['current_language']}->{result['other_language']} len={result['length']}")
        except Exception:
            continue  # one bad event must never take down the whole consumer thread


def check_panic_trigger_once():
    """Checks, once, whether PANIC_TRIGGER_FILENAME exists next to CKILS. If
    it does: removes the live keyboard hook (Tiers 1-3 are untouched — this
    only ever affects Tier 4), deletes the trigger file, and returns True.
    Returns False if the file wasn't there, or if there's no hook to remove
    yet (checked separately from _started so this is safe to call at any
    point). Never raises — a failure here must not be able to crash the
    watcher thread that calls this in a loop.
    """
    global _hook_handle
    try:
        trigger_path = skip_logger.os.path.join(skip_logger._persistent_dir(), PANIC_TRIGGER_FILENAME)
        if not skip_logger.os.path.exists(trigger_path):
            return False
        if _hook_handle is not None:
            user32.UnhookWindowsHookEx(_hook_handle)
            _hook_handle = None
        try:
            skip_logger.os.remove(trigger_path)
        except Exception:
            pass
        print("  [keyboard_hook] Tier 4 disabled live via panic trigger — CKILS itself keeps running")
        return True
    except Exception:
        return False


def _panic_watcher_loop():
    """Calls check_panic_trigger_once() every PANIC_CHECK_INTERVAL_SECONDS,
    forever — one-shot in effect, since once the hook is removed there's
    nothing left to disable, but this keeps running harmlessly for the rest
    of the session rather than needing its own shutdown signal.
    """
    while True:
        time.sleep(PANIC_CHECK_INTERVAL_SECONDS)
        check_panic_trigger_once()


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
            """Registers the real WH_KEYBOARD_LL hook and pumps messages
            forever — WH_KEYBOARD_LL requires a live message loop on the
            thread that installed it, so this runs on its own dedicated
            thread rather than sharing rule_engine.py's own PumpMessages().
            """
            global _hook_callback_ref, _hook_handle
            # Kept as a module-level global, not a local — a ctypes callback
            # object must stay alive for as long as Windows might call it;
            # storing it only as a local here would be relying on this one
            # stack frame never unwinding, which PumpMessages() blocking
            # forever happens to guarantee, but a module-level reference
            # removes any doubt rather than depending on that.
            _hook_callback_ref = _HOOK_CALLBACK_TYPE(_hook_proc)
            hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _hook_callback_ref, None, 0)
            if not hook:
                print("  [keyboard_hook] failed to install the low-level keyboard hook")
                return
            _hook_handle = hook  # exposed module-level so check_panic_trigger_once() can remove it live
            import win32gui
            win32gui.PumpMessages()
        threading.Thread(target=_run_hook, daemon=True).start()
        threading.Thread(target=_panic_watcher_loop, daemon=True).start()
        print("  [keyboard_hook] Tier 4 Phase 1 active (log-only, corrects nothing) — "
              f"create {PANIC_TRIGGER_FILENAME} next to CKILS.exe to disable it live, no restart needed")
    except Exception as e:
        print(f"  [keyboard_hook] failed to start: {e}")
