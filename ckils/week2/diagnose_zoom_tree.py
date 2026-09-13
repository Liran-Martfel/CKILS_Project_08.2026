import time
import win32gui
import uiautomation as auto

# Unlike diagnose_focus.py (which only looks at whatever GetFocusedControl()
# reports, and walks UP toward parents), this walks the WHOLE descendant tree
# of the current foreground window, top-down — needed for cases (confirmed:
# Zoom's main call window, WhatsApp Web's chat list sidebar) where whatever
# GetFocusedControl() reports is an unrelated branch nowhere near the actual
# content pane in the tree. Walking up from the wrong branch can never find
# it; only walking down from the window root can. Not app-specific — works
# against any foreground window, including a Chrome tab's rendered page.

auto.InitializeUIAutomationInCurrentThread()
print("You have 8 seconds — bring the window you want inspected to the "
      "front (with the real content visible), then wait...")
time.sleep(8)

hwnd = win32gui.GetForegroundWindow()
title = win32gui.GetWindowText(hwnd)
print(f"\nInspecting foreground window: hwnd={hwnd} title={title!r}\n")

root = auto.ControlFromHandle(hwnd)

# A rendered web page's accessibility tree can run to many thousands of nodes
# (every span, icon, spacer) — unlike a native app's much smaller tree. Both a
# hard node cap and skipping tiny/unnamed decorative nodes keep this readable
# and keep it from running for minutes on a Chrome tab.
MAX_NODES = 800
MIN_INTERESTING_AREA = 400  # skip tiny decorative nodes unless they have a real Name
_node_count = 0


def walk(control, depth=0, max_depth=10):
    global _node_count
    if control is None or depth > max_depth or _node_count >= MAX_NODES:
        return
    try:
        rect = control.BoundingRectangle
        name = (control.Name or "").strip()
        ctype = control.ControlTypeName
        area = rect.width() * rect.height() if rect else 0
        size = f"{rect.width()}x{rect.height()}" if rect else "?"
    except Exception as e:
        print("  " * depth + f"<error reading control: {e}>")
        return
    if name or area >= MIN_INTERESTING_AREA:
        _node_count += 1
        print("  " * depth + f"[{ctype}] Name={name[:70]!r} rect=({rect.left},{rect.top},{rect.right},{rect.bottom}) size={size}")
        if _node_count >= MAX_NODES:
            print(f"... stopped after {MAX_NODES} nodes (tree is larger than this) ...")
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
print(f"\nDone ({_node_count} nodes shown). Look for a Pane/List/Document-type "
      "control whose Name or position matches where the real content is on screen.")
