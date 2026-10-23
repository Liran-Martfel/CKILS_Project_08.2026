"""
Which thread really receives the user's typing in a window.

Found live 2026-10-22/23 in Sticky Notes: Store apps (Sticky Notes, Settings,
Calculator...) are shown inside a frame window owned by ApplicationFrameHost.exe,
while the typing goes to the app's own window, in another process, on another
thread. CKILS read and switched the frame's thread: it believed Hebrew while
the user was really typing on English (so a whole Hebrew line typed on English
looked like correct Hebrew), and its switches never reached the app — on
2026-10-22 three corrections in a row bounced straight back.

thread_and_pid() is GetWindowThreadProcessId, except that for such a frame it
returns the hosted app's own thread. The pid stays the frame's, so the app
name CKILS has learned under (ApplicationFrameHost.exe) doesn't change.
"""
import win32gui
import win32process

FRAME_CLASS = "ApplicationFrameWindow"


def is_store_frame(hwnd):
    """True for the frame window a Store app is shown in."""
    try:
        return bool(hwnd) and win32gui.GetClassName(hwnd) == FRAME_CLASS
    except Exception:
        return False


def _hosted_thread(hwnd, frame_pid):
    """The thread of the first child window that belongs to another process —
    the hosted app — or None (an app that is suspended shows no such child)."""
    found = []

    def visit(child, _):
        if not found:
            thread_id, pid = win32process.GetWindowThreadProcessId(child)
            if pid != frame_pid:
                found.append(thread_id)
        return True

    try:
        win32gui.EnumChildWindows(hwnd, visit, None)
    except Exception:
        pass
    return found[0] if found else None


def thread_and_pid(hwnd):
    """(thread_id, pid) of hwnd, with a Store app frame's thread replaced by
    the hosted app's own typing thread."""
    thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
    if is_store_frame(hwnd):
        hosted = _hosted_thread(hwnd, pid)
        if hosted:
            thread_id = hosted
    return thread_id, pid
