import time
import win32gui
import uiautomation as auto

# Unlike diagnose_focus.py (which only looks at whatever GetFocusedControl()
# reports, and walks UP toward parents), this walks the WHOLE descendant tree
# of the current foreground window, top-down — needed because for Zoom's main
# "Zoom Meeting" call window, GetFocusedControl() lands on the mute/audio-video
# toolbar button, an unrelated sibling branch nowhere near the actual chat pane
# in the tree. Walking up from the wrong branch can never find it; only walking
# down from the window root can.

auto.InitializeUIAutomationInCurrentThread()
print("You have 8 seconds — bring the Zoom window you want inspected to the "
      "front (with the real Hebrew chat content visible), then wait...")
time.sleep(8)

hwnd = win32gui.GetForegroundWindow()
title = win32gui.GetWindowText(hwnd)
print(f"\nInspecting foreground window: hwnd={hwnd} title={title!r}\n")

root = auto.ControlFromHandle(hwnd)


def walk(control, depth=0, max_depth=8):
    if control is None or depth > max_depth:
        return
    try:
        rect = control.BoundingRectangle
        name = (control.Name or "").strip()
        ctype = control.ControlTypeName
        size = f"{rect.width()}x{rect.height()}" if rect else "?"
        print("  " * depth + f"[{ctype}] Name={name[:70]!r} rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) size={size}")
    except Exception as e:
        print("  " * depth + f"<error reading control: {e}>")
        return
    try:
        child = control.GetFirstChildControl()
    except Exception:
        return
    while child is not None:
        walk(child, depth + 1, max_depth)
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            break


walk(root)
print("\nDone. Look for a Pane/List/Document-type control whose Name or "
      "position matches where the real chat messages are on screen.")
