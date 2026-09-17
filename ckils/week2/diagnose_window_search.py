import time
import win32gui
import uiautomation as auto

import rule_engine

# Reuses the ACTUAL function CKILS runs (_find_largest_leaf_pane_in_window),
# not a reimplementation — so whatever it reports is exactly what the real
# app would have picked, for real diagnosis instead of guessing.

auto.InitializeUIAutomationInCurrentThread()
print("You have 8 seconds - bring the Chrome/Claude.ai tab to the front "
      "(the one that keeps flipping to Hebrew), then wait...")
time.sleep(8)

hwnd = win32gui.GetForegroundWindow()
title = win32gui.GetWindowText(hwnd)
print(f"\nInspecting foreground window: hwnd={hwnd} title={title!r}\n")

picked = rule_engine._find_largest_leaf_pane_in_window(hwnd)
if picked is None:
    print("_find_largest_leaf_pane_in_window found NOTHING (no qualifying leaf).")
else:
    print(f"_find_largest_leaf_pane_in_window PICKED: "
          f"rect=({picked.left},{picked.top},{picked.right},{picked.bottom}) "
          f"size={picked.width()}x{picked.height()}")

    # Show exactly what CKILS's own OCR crop (top-left corner, capped) would read
    right = min(picked.right, picked.left + rule_engine.MAX_OCR_WIDTH)
    bottom = min(picked.bottom, picked.top + rule_engine.MAX_OCR_HEIGHT)
    print(f"Actual OCR crop region (top-left corner, capped): "
          f"({picked.left},{picked.top},{right},{bottom})")
    try:
        text = rule_engine.read_region(picked.left, picked.top, right, bottom)
        print(f"OCR read from that region: {text!r}")
    except Exception as e:
        print(f"OCR failed: {e}")

print("\nNow listing EVERY leaf candidate >= 300px tall found anywhere in the "
      "window, so we can see what else was in the running:")

WHOLE_WINDOW_SEARCH_MIN_HEIGHT = rule_engine.WHOLE_WINDOW_SEARCH_MIN_HEIGHT
visited = 0


def walk(control, depth=0):
    global visited
    if control is None or depth > rule_engine.WHOLE_WINDOW_SEARCH_MAX_DEPTH or visited >= rule_engine.WHOLE_WINDOW_SEARCH_NODE_CAP:
        return
    visited += 1
    try:
        child = control.GetFirstChildControl()
    except Exception:
        return
    if child is None:
        try:
            rect = control.BoundingRectangle
            name = (control.Name or "").strip()
            ctype = control.ControlTypeName
            if rect.height() >= WHOLE_WINDOW_SEARCH_MIN_HEIGHT and rule_engine._is_onscreen(rect):
                print(f"  [{ctype}] Name={name[:50]!r} rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) "
                      f"size={rect.width()}x{rect.height()}")
        except Exception:
            pass
        return
    while child is not None:
        walk(child, depth + 1)
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            break


try:
    root = auto.ControlFromHandle(hwnd)
    walk(root)
except Exception as e:
    print(f"tree walk failed: {e}")

print(f"\nDone ({visited} nodes visited).")
