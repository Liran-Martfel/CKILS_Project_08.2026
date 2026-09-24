"""
Live confirmation tool for layout_remap.py — real OS/keyboard-driver behavior
(dead keys, per-layout quirks) can't be meaningfully unit-tested, so this
exists to confirm it by hand: press real keys and see what each installed
layout would have produced for them, side by side.
"""
import time

import win32api

import layout_remap
import rule_engine

print("Press some letter keys (on your CURRENT layout). Ctrl+C to stop.")
print("Shows what English and Hebrew would each produce for that same physical key.\n")

seen = set()
try:
    while True:
        for vk in range(0x30, 0x5B):  # 0-9 and A-Z
            pressed = win32api.GetAsyncKeyState(vk) & 0x8000
            if pressed and vk not in seen:
                seen.add(vk)
                scan = win32api.MapVirtualKey(vk, 0)
                en = layout_remap.remap_key_to_other_layout(vk, scan, rule_engine.English_HKL)
                he = layout_remap.remap_key_to_other_layout(vk, scan, rule_engine.Hebrew_HKL)
                print(f"vk={hex(vk)} scan={scan}  english={en!r}  hebrew={he!r}")
            elif not pressed and vk in seen:
                seen.discard(vk)
        time.sleep(0.02)
except KeyboardInterrupt:
    print("\nDone.")
