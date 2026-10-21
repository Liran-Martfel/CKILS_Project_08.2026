"""
Read-only diagnostic (2026-10-21): can CKILS tell VS Code's code editor from
its chat panel? Both live in one window, so CKILS treats them as one place —
but code is almost always English and the chat is often Hebrew.

For the next N seconds (default 60) it records, every time keyboard focus
moves, what Windows' UI Automation reports about the focused element: its
control type, class name, AutomationId, framework, and the LENGTH of its
name — never the name or any text itself. Click between the code editor, the
chat box and the terminal while it runs; the output shows whether those
places look different to Windows.

Usage: python diagnose_vscode_focus.py [seconds] [out.txt]
"""
import sys
import time

import uiautomation as auto


def describe(control):
    try:
        parent = control.GetParentControl()
        return (f"type={control.ControlTypeName} class={control.ClassName!r} "
                f"automation_id={control.AutomationId!r} framework={control.FrameworkId!r} "
                f"name_length={len(control.Name or '')} parent_type={parent.ControlTypeName if parent else '-'} "
                f"parent_class={parent.ClassName if parent else '-'!r}")
    except Exception as e:
        return f"unreadable ({type(e).__name__})"


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    out = open(sys.argv[2], "w", encoding="utf-8") if len(sys.argv) > 2 else sys.stdout
    auto.InitializeUIAutomationInCurrentThread()
    last, end = None, time.time() + seconds
    while time.time() < end:
        try:
            line = describe(auto.GetFocusedControl())
        except Exception as e:
            line = f"no focus ({type(e).__name__})"
        if line != last:
            out.write(f"{time.strftime('%H:%M:%S')} {line}\n")
            out.flush()
            last = line
        time.sleep(0.25)
