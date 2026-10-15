"""
Tier 4 safety net, piece 3 of 3 (see gibberish_detector.py for the CBAW
rules, layout_remap.py for "what would another layout have produced"): the
actual keystroke watcher. Phase 1: every suspected-gibberish detection is
recorded through skip_logger. Phase 2 (2026-10-14), only when its own
separate opt-in file (_AUTOCORRECT_FLAG_FILENAME) exists: once a detected
word reaches CORRECTION_TRIGGER_LENGTH keys and then ends (space, Enter,
punctuation — see ends_word), this module asks rule_engine
(through the on_autocorrect callback handed to start()) to switch the
layout. It never posts a layout switch itself — rule_engine owns all
switching bookkeeping, see rule_engine.apply_tier4_correction for why.

PRIVACY, stated as a hard rule, not a hope: the only things this module ever
keeps are (a) the CURRENT in-progress word's characters, in memory only,
cleared on every word boundary and capped at gibberish_detector.IncrementalWordBuffer.MAX_LENGTH
characters (5, as of 2026-10-14), and (b) counts
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
import collections
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
# Shift (generic, left, right) and Caps Lock: type nothing themselves.
# WH_KEYBOARD_LL reports the left/right-specific codes, not just VK_SHIFT.
_MODIFIER_ONLY_VKS = {win32con.VK_SHIFT, win32con.VK_LSHIFT, win32con.VK_RSHIFT, win32con.VK_CAPITAL}

# A key is part of a word if it types a letter in EITHER layout — decided
# in one place, layout_remap.is_letter_key. Anything else either ends the
# word or is an edit key (Backspace, arrows) that cancels it.
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
                # Modifiers read HERE, at press time — found by /code-review
                # 2026-10-14: reading Shift later, when the consumer thread
                # gets to the event, raced with the user's fingers ("hello!"
                # typed fast lost its "!" once Shift was already released).
                # GetAsyncKeyState is a cheap read; nothing slow runs here.
                shift = bool(win32api.GetAsyncKeyState(win32con.VK_SHIFT) & 0x8000)
                ctrl = bool(win32api.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                alt = bool(win32api.GetAsyncKeyState(VK_MENU) & 0x8000)
                try:
                    _event_queue.put_nowait((event.vk_code, event.scan_code, shift, ctrl, alt))
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
    decoded characters alone can't answer. Reset together, always — this
    was violated for a while (see the real bug noted in process_key_event's
    boundary-handling branch, 2026-09-27): a word-boundary reset triggered
    from INSIDE IncrementalWordBuffer.push() only cleared .chars, not the
    sibling .raw_keys here, letting raw_keys silently accumulate across many
    words. Fixed there; kept in lockstep everywhere else already (see
    reset() below, and every _reset_visit_state-style call site).
    """
    def __init__(self):
        """Starts with no word in progress and no raw keys recorded."""
        self.chars = gibberish_detector.IncrementalWordBuffer()
        self.raw_keys = []
        self.pending_correction = None  # (target_hkl, word_length) once a word qualifies; fired at its end
        # The word-end rule needs the word's LAST letter and full length, which
        # the 5-letter buffer stops tracking. Kept as one (vk, scan) pair and a
        # count — still only the current word, still memory only.
        self.last_letter_key = None
        self.letter_count = 0
        # Second-word rule (2026-10-15, user's call): which direction this word
        # was flagged in (the HKL it should have been typed in), and the same
        # for the previous two words. A second flagged word within three
        # switches the layout, whatever the word lengths.
        self.word_flag = None
        self.recent_word_flags = collections.deque(maxlen=2)
        # Whole-word English rules (judged at the word's end): how many English
        # letters, whether any was a vowel, the last two, and whether any was a
        # capital (tickers and acronyms are typed in capitals; Hebrew has none).
        self.en_letter_count = 0
        self.en_has_vowel = False
        self.en_ending = ""
        self.en_capital_seen = False

    def reset_word(self):
        """The word ended normally: clears everything about THIS word (the
        buffer and the raw (vk, scan) pairs together, so they can never drift
        out of sync), but keeps what spans words — a pending correction still
        waiting for its word end, and the recent-words history."""
        self.chars.reset()
        self.raw_keys = []
        self.last_letter_key = None
        self.letter_count = 0
        self.word_flag = None
        self.en_letter_count = 0
        self.en_has_vowel = False
        self.en_ending = ""
        self.en_capital_seen = False

    def reset(self):
        """Full reset: the word AND everything spanning words. Every path that
        calls this (focus change, Ctrl/Alt, password field, Backspace/arrows)
        is one where switching the layout at the next word end would be wrong.
        """
        self.reset_word()
        self.pending_correction = None
        self.recent_word_flags.clear()


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

    if vk_code in _MODIFIER_ONLY_VKS:
        # Found 2026-10-14 while building Phase 2's word-end trigger: Shift
        # and Caps Lock type no character — they change the NEXT key. Treating
        # them as a word boundary (the branch below) split every mixed-case
        # word in two, and would cancel a pending correction one keystroke
        # before the "?" or "!" that actually ends the word.
        return None

    other_hkl = ENGLISH_HKL_VALUE if current_hkl == HEBREW_HKL_VALUE else HEBREW_HKL_VALUE
    if not (layout_remap.is_letter_key(vk_code, current_hkl, shift_pressed)
            or layout_remap.is_letter_key(vk_code, other_hkl, shift_pressed)):
        # 2026-10-15: "is this key part of a word" is now ONE question — does
        # it type a letter in either layout (layout_remap.is_letter_key). The
        # old test, "is it A-Z", made the ; , . keys word boundaries even
        # when the user meant Hebrew and they type ף ת ץ — cancelling the
        # pending correction for any Hebrew word with ת after its 5th letter
        # (found by /code-review). Ends only this word: a pending correction
        # and the recent-words history are handled by the consumer loop.
        #
        # Real bug found live, 2026-10-08: this used to ask layout_remap what
        # character this key would produce, and only reset on a boundary if
        # THAT lookup returned one. But layout_remap only ever maps VK_A..VK_Z
        # (see its own module docstring) — Space, Enter, Tab and every real
        # punctuation/digit key always returned None here, so NONE of them
        # ever ended a word. A word that reached MAX_LENGTH without lucking
        # into a letter-key-produces-punctuation case (the one real path that
        # DID work — Hebrew's physical Q/W keys, see the raw_keys fix above)
        # stayed capped forever: silently blind for the rest of the session,
        # across every later window, until Ctrl/Alt or a password field reset
        # it. Confirmed live: typing a 4+ letter word in one window, then
        # switching entirely to another app and typing real wrong-layout
        # gibberish there, produced nothing — the buffer was still capped
        # from the first window. Lowering MAX_LENGTH from 12 to 4 earlier the
        # same day made this fire on almost any real word, not just long ones.
        # Fixed by treating ANY non-letter key as an unconditional boundary —
        # it can never be part of a word either way, so there's no reason to
        # ask what character it would decode to first.
        state.reset_word()
        return None

    english = layout_remap.remap_key_to_other_layout(vk_code, scan_code, ENGLISH_HKL_VALUE)
    if english and english.isalpha():
        state.en_letter_count += 1
        state.en_has_vowel = state.en_has_vowel or english in gibberish_detector.ENGLISH_VOWELS
        state.en_ending = (state.en_ending + english)[-2:]
        state.en_capital_seen = state.en_capital_seen or (shift_pressed != caps_lock_on)

    char = layout_remap.remap_key_to_other_layout(vk_code, scan_code, current_hkl, shift_pressed, caps_lock_on)
    if not char or not char.isalpha():
        # A letter only in the OTHER layout (on English, the , key that is ת
        # in Hebrew; on Hebrew, the W key that is ' here but w in English).
        # Mid-word for whoever meant the other language: keep the raw key so
        # the other-layout reading stays whole, but there's no letter to add
        # to this layout's buffer.
        if len(state.raw_keys) < gibberish_detector.IncrementalWordBuffer.MAX_LENGTH:
            state.raw_keys.append((vk_code, scan_code))
        state.last_letter_key = (vk_code, scan_code)
        state.letter_count += 1
        return None

    still_going = state.chars.push(char)
    if not still_going:
        # Real bug found live, 2026-09-27: IncrementalWordBuffer.push() resets
        # ITSELF on a word boundary (see gibberish_detector.py) — but that only
        # clears state.chars, a sibling of state.raw_keys, not state itself.
        # Confirmed from real production data: some gibberish_suspected rows
        # showed length up to 36, impossible under the documented 12-character
        # cap. Root cause: on Hebrew, the physical Q and W keys produce '/' and
        # "'" — both real, common Hebrew punctuation (the apostrophe especially,
        # used for real abbreviations) — which this module's own boundary check
        # correctly treats as ending a word, silently triggering the INTERNAL
        # reset above without ever reaching _PerThreadState.reset(). raw_keys
        # then kept accumulating across every subsequent word typed in that
        # window, for as long as no Ctrl/Alt, password field or window change
        # happened — directly contradicting the "only ever holds the current
        # word" design promise (an in-memory guarantee; nothing typed ever
        # reached the disk either way — log_skip only ever received a language
        # direction and a count, confirmed unaffected). An empty chars buffer
        # right after a failed push is the reliable signal this was a boundary
        # reset (a cap-triggered failure leaves 12 real characters in place),
        # so that's used here to keep raw_keys in lockstep without needing to
        # change IncrementalWordBuffer's own interface.
        if not state.chars.text():
            state.raw_keys = []
            state.last_letter_key = None
            state.letter_count = 0
        else:
            # Capped, not ended: the word goes on past MAX_LENGTH. Keep its
            # last letter and length current for the word-end rule.
            state.last_letter_key = (vk_code, scan_code)
            state.letter_count += 1
        return None
    state.raw_keys.append((vk_code, scan_code))
    state.last_letter_key = (vk_code, scan_code)
    state.letter_count += 1

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


def _reset_on_focus_change(state, thread_id, last_thread_id):
    """Returns thread_id, for the caller to carry into the next event as
    its own last_thread_id. Resets state (the word in progress) first if
    thread_id differs from last_thread_id — a genuine window/tab switch.

    Defense in depth alongside the 2026-10-08 non-letter-key fix in
    process_key_event: a word in progress in one window/tab must never
    bleed into a different one reached by a mouse-only switch (no
    keystroke at all in between to trigger that other fix). thread_id, not
    title, is what's compared — Chrome gives each tab its own thread, and
    WhatsApp/Zoom's own known-unstable title (an unread-count badge, see
    UNSTABLE_TITLE_MARKERS in rule_engine.py) never changes it, so this
    can't spuriously reset mid-word just because a badge ticked over.
    """
    if thread_id != last_thread_id:
        state.reset()
    return thread_id


# Tier 4 Phase 2 (2026-10-14). The user's own call: only a word still
# detected at 5 keys qualifies — a 2-4 key detection is the least certain
# kind, and acting on one would be the most likely false positive. A
# qualifying word is then corrected at its END (see ends_word), not at the
# 5th key.
CORRECTION_TRIGGER_LENGTH = 5
_AUTOCORRECT_FLAG_FILENAME = "enable_gibberish_autocorrect.on"
_autocorrect_callback = None  # set by start(); see rule_engine.apply_tier4_correction


def autocorrect_target(result, current_hkl):
    """Pure decision: given a process_key_event result (or None) and the
    layout the user is actually typing in, returns the HKL Phase 2 should
    switch to, or None if this detection shouldn't trigger a correction
    (no detection, or the word hasn't reached CORRECTION_TRIGGER_LENGTH yet).
    """
    if result is None or result["length"] < CORRECTION_TRIGGER_LENGTH:
        return None
    return ENGLISH_HKL_VALUE if current_hkl == HEBREW_HKL_VALUE else HEBREW_HKL_VALUE


# The user's call, 2026-10-14: never flip the layout mid-word — a qualifying
# word is only marked pending, and the switch fires when that word ENDS:
# space, Enter, Tab or punctuation. Explicit allowlist, not "any non-letter
# key": Backspace, arrows and Delete are non-letters too, but they mean the
# user is editing — they cancel instead (see _handle_non_letter_key).
VK_SPACE, VK_RETURN, VK_TAB = win32con.VK_SPACE, win32con.VK_RETURN, win32con.VK_TAB
_OEM_PUNCTUATION_VKS = {
    layout_remap.VK_OEM_1, layout_remap.VK_OEM_PLUS, layout_remap.VK_OEM_COMMA, layout_remap.VK_OEM_MINUS,
    layout_remap.VK_OEM_PERIOD, layout_remap.VK_OEM_2, layout_remap.VK_OEM_3, layout_remap.VK_OEM_4,
    layout_remap.VK_OEM_5, layout_remap.VK_OEM_6, layout_remap.VK_OEM_7,
}
# The word-end rule (Hebrew never ends in a regular מ/נ/צ/כ) only fires on
# these: an apostrophe or quote mark can end a Hebrew abbreviation (מס',
# מנכ"ל) right after a regular letter.
_WORD_END_RULE_VKS = {VK_SPACE, VK_RETURN, VK_TAB}


def is_word_end_key(vk_code, shift_pressed=False):
    """Space, Enter, Tab, punctuation, or Shift+digit (! @ # ...)."""
    if vk_code in (VK_SPACE, VK_RETURN, VK_TAB):
        return True
    if shift_pressed and 0x30 <= vk_code <= 0x39:
        return True
    return vk_code in _OEM_PUNCTUATION_VKS


def ends_word(vk_code, target_hkl, shift_pressed=False):
    """True if vk_code ends the word for someone typing in target_hkl's
    language (the language they actually meant — the one Phase 2 is about
    to switch to)."""
    if target_hkl == HEBREW_HKL_VALUE and layout_remap.is_letter_key(vk_code, HEBREW_HKL_VALUE, shift_pressed):
        return False  # ; , . type ף ת ץ in Hebrew — part of the word, not punctuation after it
    if continues_word(vk_code, target_hkl, shift_pressed):
        return False
    return is_word_end_key(vk_code, shift_pressed)


def continues_word(vk_code, target_hkl, shift_pressed=False):
    """The apostrophe, for someone who meant English: inside the word
    ("couldn't"), not after it. Found by /code-review 2026-10-14 — it used
    to fire the switch between "could" and "n't"."""
    return target_hkl == ENGLISH_HKL_VALUE and vk_code == layout_remap.VK_OEM_7 and not shift_pressed


def word_end_check(state, current_hkl):
    """The user's word-end rule (2026-10-14): called when a word typed on
    the Hebrew layout ends with a space or Enter. If its last letter is a
    regular מ/נ/צ/כ — impossible at the end of a Hebrew word — and the same
    keys read as plausible English, returns a process_key_event-shaped
    result; else None. Catches short English words typed on the Hebrew
    layout ("can" -> בשמ, "man", "pin") that the 5-letter trigger can't.

    Only space/Enter/Tab (_WORD_END_RULE_VKS), on purpose: in Hebrew, an
    apostrophe or a quote mark ends abbreviations and acronyms (מס', עמ',
    מנכ"ל) right after a regular letter, so treating those as word ends
    would flag real Hebrew.
    """
    if current_hkl != HEBREW_HKL_VALUE or state.letter_count < 2 or state.last_letter_key is None:
        return None
    last_vk, last_scan = state.last_letter_key
    last_letter = layout_remap.remap_key_to_other_layout(last_vk, last_scan, HEBREW_HKL_VALUE)
    if not last_letter or not gibberish_detector.hebrew_word_cannot_end_with(last_letter):
        return None
    keys = list(state.raw_keys)
    if state.letter_count > len(keys):
        keys.append(state.last_letter_key)  # the buffer capped before the last letter
    english = "".join(layout_remap.remap_key_to_other_layout(vk, scan, ENGLISH_HKL_VALUE) or ""
                      for vk, scan in keys)
    if gibberish_detector.looks_impossible(english, "english") is not None:
        return None  # not plausible English either — no evidence of a wrong layout
    return {"current_language": "hebrew", "other_language": "english", "length": state.letter_count}


# The user's choice, 2026-10-15: a single English whole-word hit switches the
# keyboard on its own. Measured both ways first: switching alone doubles the
# Hebrew-typed-on-English sentences caught by word 3 (31% -> 61%), at the cost
# of about 1 in 100 correctly typed English sentences switching wrongly
# (short code/chat words the exception list misses). Set False to make hits
# only mark the word for the second-word rule instead.
ENGLISH_WORD_END_SWITCHES_ALONE = True


def english_word_end_check(state, current_hkl):
    """Whole-word English rules (gibberish_detector.english_word_end_suspect)
    for a word typed on the English layout that just ended with space, Enter
    or Tab. Returns a process_key_event-shaped result if the word can't be
    English AND the same keys read as plausible Hebrew; else None. Skipped
    for any word typed with a capital: stock tickers and acronyms (SPDR,
    HTML) are typed that way, and Hebrew has no capitals at all."""
    if current_hkl != ENGLISH_HKL_VALUE or state.en_letter_count < 2 or state.en_capital_seen:
        return None
    keys = list(state.raw_keys)
    if state.letter_count > len(keys) and state.last_letter_key is not None:
        keys.append(state.last_letter_key)
    known_word = None
    if state.letter_count <= gibberish_detector.IncrementalWordBuffer.MAX_LENGTH:
        known_word = "".join(c for c in (layout_remap.remap_key_to_other_layout(vk, s, ENGLISH_HKL_VALUE) or ""
                                         for vk, s in keys) if c.isalpha())
    if gibberish_detector.english_word_end_suspect(
            known_word, state.en_letter_count, state.en_has_vowel, state.en_ending) is None:
        return None
    hebrew = "".join(layout_remap.remap_key_to_other_layout(vk, s, HEBREW_HKL_VALUE) or "" for vk, s in keys)
    hebrew_letters = "".join(c for c in hebrew if c.isalpha())
    if (gibberish_detector.looks_impossible(hebrew_letters, "hebrew") is not None
            or (hebrew_letters and gibberish_detector.hebrew_word_cannot_end_with(hebrew_letters[-1]))):
        return None  # not plausible Hebrew either — no evidence of a wrong layout
    return {"current_language": "english", "other_language": "hebrew", "length": state.en_letter_count}


def _autocorrect_enabled():
    """The user's on/off switch for Phase 2: true only while
    _AUTOCORRECT_FLAG_FILENAME exists next to CKILS. Checked live, at the
    moment a correction would fire (rare — once per wrong-layout word at
    most), so creating or deleting the file takes effect immediately, no
    restart. Independent of Phase 1's own opt-in: deleting this file drops
    back to log-only without turning Tier 4 off.
    """
    try:
        return skip_logger.os.path.exists(
            skip_logger.os.path.join(skip_logger._persistent_dir(), _AUTOCORRECT_FLAG_FILENAME))
    except Exception:
        return False


def _consumer_loop():
    """Pulls queued key events and runs the real analysis — everything the
    hook callback itself deliberately avoids doing. One _PerThreadState per
    call, since this runs in its own dedicated thread.
    """
    state = _PerThreadState()
    last_thread_id = None
    while True:
        vk_code, scan_code, shift_pressed, ctrl_held, alt_held = _event_queue.get()
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

            last_thread_id = _reset_on_focus_change(state, thread_id, last_thread_id)

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

            # Phase 2 decisions happen BEFORE process_key_event, which ends the
            # word (and with it this word's letters and flag) on a non-letter.
            # Ctrl/Alt combos are shortcuts, never a word end;
            # process_key_event cancels everything for those.
            if not (ctrl_held or alt_held) and vk_code not in _MODIFIER_ONLY_VKS:
                _handle_word_end(state, vk_code, shift_pressed, current_hkl, thread_id, exe_name, title)

            result = process_key_event(vk_code, scan_code, state, current_hkl, ctrl_held, alt_held,
                                       shift_pressed, caps_lock_on)
            if result is not None:
                # PRIVACY: only counts and language names ever reach the log —
                # never the characters that were actually typed.
                skip_logger.log_skip(
                    exe_name, title, thread_id, skip_logger.REASON_GIBBERISH_SUSPECTED,
                    f"{result['current_language']}->{result['other_language']} len={result['length']}")
                state.word_flag = ENGLISH_HKL_VALUE if current_hkl == HEBREW_HKL_VALUE else HEBREW_HKL_VALUE

            target_hkl = autocorrect_target(result, current_hkl)
            if target_hkl is not None:
                state.pending_correction = (target_hkl, result["length"])  # fires when this word ends
        except Exception:
            continue  # one bad event must never take down the whole consumer thread


def _handle_word_end(state, vk_code, shift_pressed, current_hkl, thread_id, exe_name, title):
    """Runs for every non-modifier key outside a shortcut, before the key is
    added to (or ends) the word. Three ways a word can trigger a switch when
    it ends, checked in order, at most one switch per word end:
      1. a word that qualified at 5 keys (pending_correction);
      2. the word-end rule — Hebrew never ends in a regular מ/נ/צ/כ;
      3. the second-word rule — this word was flagged and so was one of the
         two words before it, in the same direction (user's call, 2026-10-15:
         catches runs of short wrong-layout words like "and good with").
    A non-letter that isn't a word end (Backspace, arrows, Delete, a plain
    digit) means the user is editing: everything pending is cancelled."""
    fired = False
    pending = state.pending_correction
    if pending is not None and ends_word(vk_code, pending[0], shift_pressed):
        state.pending_correction = None
        _fire_autocorrect(thread_id, exe_name, title, current_hkl, pending[0], pending[1])
        fired = True

    other_hkl = ENGLISH_HKL_VALUE if current_hkl == HEBREW_HKL_VALUE else HEBREW_HKL_VALUE
    if (layout_remap.is_letter_key(vk_code, current_hkl, shift_pressed)
            or layout_remap.is_letter_key(vk_code, other_hkl, shift_pressed)):
        return  # still inside a word

    if not fired and vk_code in _WORD_END_RULE_VKS:
        end_result = word_end_check(state, current_hkl)
        if end_result is not None:
            skip_logger.log_skip(
                exe_name, title, thread_id, skip_logger.REASON_GIBBERISH_SUSPECTED,
                f"hebrew->english len={end_result['length']} word-end")
            state.word_flag = ENGLISH_HKL_VALUE
            _fire_autocorrect(thread_id, exe_name, title, current_hkl, ENGLISH_HKL_VALUE, end_result["length"])
            fired = True
        en_result = english_word_end_check(state, current_hkl)
        if not fired and en_result is not None:
            skip_logger.log_skip(
                exe_name, title, thread_id, skip_logger.REASON_GIBBERISH_SUSPECTED,
                f"english->hebrew len={en_result['length']} word-end")
            state.word_flag = HEBREW_HKL_VALUE
            if ENGLISH_WORD_END_SWITCHES_ALONE:
                _fire_autocorrect(thread_id, exe_name, title, current_hkl, HEBREW_HKL_VALUE, en_result["length"])
                fired = True

    flag = state.word_flag
    if flag is not None and ends_word(vk_code, flag, shift_pressed):
        if not fired and flag in state.recent_word_flags:
            _fire_autocorrect(thread_id, exe_name, title, current_hkl, flag, state.letter_count)
            fired = True
        state.recent_word_flags.append(flag)
    elif is_word_end_key(vk_code, shift_pressed):
        state.recent_word_flags.append(None)
    elif not (state.pending_correction and continues_word(vk_code, state.pending_correction[0], shift_pressed)):
        state.reset()  # an edit key: the user is changing the text, not ending a word
        return
    if fired:
        state.recent_word_flags.clear()  # the layout just changed: count from scratch


def _fire_autocorrect(thread_id, exe_name, title, from_hkl, target_hkl, word_length):
    """Hands a ready correction to rule_engine — only if Phase 2's on/off
    file is present right now and focus is still on the window the word was
    typed in. Never raises."""
    try:
        if from_hkl == target_hkl:
            # Found by /code-review 2026-10-14: the layout already changed
            # since the word qualified (Tier 3, or the user's own click on the
            # language bar). "Correcting" it would log a fake correction and
            # make Tier 3 stand down for the rest of the visit.
            return
        if _autocorrect_callback is None or not _autocorrect_enabled():
            return
        hwnd = _foreground_hwnd_for(thread_id)
        if hwnd is not None:
            _autocorrect_callback(hwnd, thread_id, exe_name, title, from_hkl, target_hkl, word_length)
    except Exception:
        pass


def _foreground_hwnd_for(thread_id):
    """The current foreground window's hwnd, but only if it still belongs to
    thread_id — the window this keystroke was actually judged against.
    Events are processed slightly after they happen; if focus moved on in
    between, correcting whatever is focused NOW would switch the wrong
    window. Returns None in that case.
    """
    import win32gui
    import win32process
    try:
        hwnd = win32gui.GetForegroundWindow()
        fg_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        return hwnd if fg_thread == thread_id else None
    except Exception:
        return None


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


def start(english_hkl, hebrew_hkl, on_autocorrect=None):
    """Starts Tier 4 — OFF BY DEFAULT. Requires an explicit opt-in file
    (_ENABLE_FLAG_FILENAME) next to CKILS, the inverse of skip_logger's
    kill-switch: this feature watches keystrokes, so it must be deliberately
    turned ON, never silently active. Registers the real OS hook and starts
    the consumer thread; never raises. on_autocorrect (Phase 2) is
    rule_engine.apply_tier4_correction — only ever called while
    _AUTOCORRECT_FLAG_FILENAME also exists (checked live).
    """
    global _started, ENGLISH_HKL_VALUE, HEBREW_HKL_VALUE, _autocorrect_callback
    try:
        if _started:
            return
        if not skip_logger.os.path.exists(
                skip_logger.os.path.join(skip_logger._persistent_dir(), _ENABLE_FLAG_FILENAME)):
            print(f"  [keyboard_hook] not started: opt-in file {_ENABLE_FLAG_FILENAME} not present")
            return
        ENGLISH_HKL_VALUE, HEBREW_HKL_VALUE = english_hkl, hebrew_hkl
        _autocorrect_callback = on_autocorrect
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
        print(f"  [keyboard_hook] Tier 4 active — auto-correction "
              f"{'ON' if _autocorrect_enabled() else 'OFF (log-only)'} via {_AUTOCORRECT_FLAG_FILENAME}; "
              f"create {PANIC_TRIGGER_FILENAME} next to CKILS.exe to disable Tier 4 live, no restart needed")
    except Exception as e:
        print(f"  [keyboard_hook] failed to start: {e}")
