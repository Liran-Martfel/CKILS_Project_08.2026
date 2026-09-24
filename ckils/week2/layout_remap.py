"""
Tier 4 safety net, piece 2 of 3: given a physical key that was just pressed,
answers "what character would THIS layout have produced for that same key?"
— for ANY installed layout, not just the one currently active. This is the
actual mechanism behind "wrong layout" detection: the physical key position
never changes, only which character it maps to changes with the active
layout, so asking Windows what the OTHER layout would have produced for the
same key is how a real remap (not a guess) is computed.

Built on ToUnicodeEx (user32.dll), the same real Windows API every keyboard-
layout-fixing tool uses — it's the only public API that can translate a
(virtual-key, scan-code) pair through a layout that ISN'T the one currently
active, which is exactly what's needed here.

WHY THIS IS SPLIT FROM keyboard_hook.py: ToUnicodeEx is real OS behavior
(dead keys, per-layout quirks) that cannot be meaningfully unit-tested
without a real Windows keyboard driver — the same reason ocr_reader.py's
actual Tesseract call isn't unit-tested either, only the logic around it.
_to_unicode_ex() is the one function that touches the real API and is
replaced with a fake in tests; everything else here is pure logic tested
directly. diagnose_layout_remap.py is the live tool for real confirmation.
"""
import ctypes
import ctypes.wintypes

user32 = ctypes.windll.user32

VK_SHIFT = 0x10
VK_CAPITAL = 0x14


def _to_unicode_ex(vk_code, scan_code, key_state, hkl):
    """The one function that calls the real Windows API. key_state is a
    256-byte bytearray (index = virtual-key code, 0x80 bit set = pressed,
    0x01 bit set = toggled for CAPS LOCK). Returns the produced string
    (usually one character, sometimes empty for a dead key or a key with
    no character), or None if the call itself fails.
    """
    buf = ctypes.create_unicode_buffer(8)
    # Real bug caught before it shipped: this codebase represents an HKL as a
    # signed Python int (Hebrew_HKL is negative — see rule_engine.py), which
    # is fine for pywin32 calls (it masks internally), but ctypes.wintypes.
    # HANDLE sign-extends a negative int to a 64-bit pointer instead of
    # zero-extending it — confirmed directly: HANDLE(Hebrew_HKL) produces a
    # value with the upper 32 bits all set, not the real HKL bit pattern
    # Windows expects. Masking to 32 bits first gives the correct value
    # either way (a positive HKL is unaffected by the mask).
    try:
        result = user32.ToUnicodeEx(
            ctypes.wintypes.UINT(vk_code),
            ctypes.wintypes.UINT(scan_code),
            (ctypes.c_ubyte * 256)(*key_state),
            buf, 8,
            ctypes.wintypes.UINT(0),
            ctypes.wintypes.HANDLE(hkl & 0xFFFFFFFF),
        )
    except Exception:
        return None
    if result <= 0:
        return None
    return buf.value


def build_key_state(shift_pressed=False, caps_lock_on=False):
    """Builds the 256-byte key-state array ToUnicodeEx expects, reflecting
    only what actually affects a plain letter's case/shift-state — this
    module only ever remaps plain letter keys, never Ctrl/Alt combinations
    (see keyboard_hook.py, which never buffers a keystroke typed with
    Ctrl or Alt held, since those are shortcuts, not typed text).
    """
    state = bytearray(256)
    if shift_pressed:
        state[VK_SHIFT] = 0x80
    if caps_lock_on:
        state[VK_CAPITAL] = 0x01
    return state


def remap_key_to_other_layout(vk_code, scan_code, target_hkl, shift_pressed=False, caps_lock_on=False):
    """Returns the single character that target_hkl (an HKL like
    rule_engine.English_HKL/Hebrew_HKL) would have produced for this exact
    physical key press, or None if that key produces no plain character
    under that layout (a dead key, a control key, or the API call failing).
    Only ever asked about plain letter keys — see keyboard_hook.py.
    """
    key_state = build_key_state(shift_pressed, caps_lock_on)
    text = _to_unicode_ex(vk_code, scan_code, key_state, target_hkl)
    if not text or len(text) != 1:
        return None
    return text
