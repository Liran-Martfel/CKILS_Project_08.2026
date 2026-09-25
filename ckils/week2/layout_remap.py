"""
Tier 4 safety net, piece 2 of 3: given a physical key that was just pressed,
answers "what character would THIS layout have produced for that same key?"
— for English or Hebrew, the only two layouts CKILS ever needs to tell apart
(see README.md — no other language is supported).

REAL BUG FOUND LIVE, 2026-09-25, AND WHY THIS IS A STATIC TABLE, NOT A LIVE
WINDOWS API CALL: the original design asked Windows itself (ToUnicodeEx)
what a given physical key produces under an arbitrary layout. Confirmed
directly with a live test that this does NOT reliably work for a layout
that isn't the CALLING THREAD's own currently active one — Windows requires
the calling thread to have a real, focused input queue for ToUnicodeEx's
target-layout parameter to be honored, which a background thread inside
CKILS never has. Even passing the exact, correct, installed Hebrew layout
ID (confirmed against the real system's own win32api.GetKeyboardLayoutList())
returned failure (0) every time from that thread.

Since CKILS only ever needs to distinguish exactly two FIXED layouts, a
live, generic "ask Windows about any layout" mechanism was solving a harder
problem than the one that actually exists. This table answers the one real
question Tier 4 needs — "which Hebrew letter sits on this English letter's
physical key, and vice versa" — with no OS dependency, no thread-association
requirement, and no live API call at all.

CONFIRMED AGAINST REAL TYPED EVIDENCE, NOT GUESSED: h->י, e->ק, l->ך, o->ם,
k->ל, a->ש, u->ו were independently verified the same day from real
captures — typing "hello" produced "יקךךם" on the Hebrew layout, "hkl"
produced "ילך", and typing שלום's physical keys on the English layout
produced "akuo" (cross-checking ש->a, ל->k, ו->u, ם->o against the same
letters from the other two captures). The remaining letters are the same
published SI-1452 standard Israeli keyboard layout (unchanged for decades),
not independently verified today but not guessed either.
"""

ENGLISH_HKL = 0x04090409
HEBREW_HKL = -0xfc2fbf3

# Standard SI-1452 Hebrew keyboard layout: which character sits on each
# US-QWERTY letter key. See the module docstring for which of these were
# directly confirmed against real typed evidence today versus taken from the
# published standard. q/w map to punctuation on the real Hebrew layout
# (they're kept here for completeness — gibberish_detector only ever judges
# alphabetic characters, so these two are never treated as evidence anyway).
ENGLISH_TO_HEBREW_KEY_MAP = {
    "q": "/", "w": "'", "e": "ק", "r": "ר", "t": "א", "y": "ט", "u": "ו",
    "i": "ן", "o": "ם", "p": "פ",
    "a": "ש", "s": "ד", "d": "ג", "f": "כ", "g": "ע", "h": "י", "j": "ח", "k": "ל", "l": "ך",
    "z": "ז", "x": "ס", "c": "ב", "v": "ה", "b": "נ", "n": "מ", "m": "צ",
}

VK_A = 0x41
_VK_TO_ENGLISH_LETTER = {VK_A + i: chr(ord("a") + i) for i in range(26)}  # VK_A..VK_Z -> 'a'..'z'


def remap_key_to_other_layout(vk_code, scan_code, target_hkl, shift_pressed=False, caps_lock_on=False):
    """Returns the character that target_hkl (ENGLISH_HKL or HEBREW_HKL —
    also accepts rule_engine.English_HKL/Hebrew_HKL, the same real values)
    would have produced for this exact physical key, or None if vk_code
    isn't a plain letter key or target_hkl is neither layout this module
    knows. scan_code is accepted for interface compatibility with the
    OS-call-based design this replaced but isn't needed by a static table
    lookup. shift_pressed/caps_lock_on are accepted but not applied to
    case — case never changes which letter it is, and Hebrew has no case at
    all, so it carries no information gibberish_detector.py's rules need.
    """
    base_letter = _VK_TO_ENGLISH_LETTER.get(vk_code)
    if base_letter is None:
        return None
    if target_hkl == ENGLISH_HKL:
        return base_letter
    if target_hkl == HEBREW_HKL:
        return ENGLISH_TO_HEBREW_KEY_MAP.get(base_letter)
    return None
