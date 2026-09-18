"""
Diagnostic tool: reproduces, step by step, what CKILS decides the moment you
land on a window — for confirming WHY it did or didn't switch the language
(rather than inferring it from logs, which never record empty or rejected
reads). Waits 15 seconds, then for the foreground window prints: the real
current keyboard layout, what the learned-default history says (read from
dist/, where the packaged exe keeps its own copies), whether the fast path
would have had anything trusted to apply, and the full step-by-step result
of the real Tier 3 read (decide_with_content, with its DEBUG output on).
"""
import json
import os
import time

import psutil
import win32api
import win32gui
import win32process
import uiautomation as auto

import rule_engine

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")


def load(name):
    """Loads one of the exe's own learned-defaults JSON files from dist/."""
    path = os.path.join(DIST, name)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


auto.InitializeUIAutomationInCurrentThread()
print("15 seconds - bring the window to the state you want checked "
      "(keyboard set the way it was when CKILS failed), then wait...")
time.sleep(15)

hwnd = win32gui.GetForegroundWindow()
title = win32gui.GetWindowText(hwnd)
thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
exe_name = psutil.Process(pid).name()
actual = win32api.GetKeyboardLayout(thread_id)
print(f"\nWindow: {exe_name}  title={title!r}  thread={thread_id}")
print(f"Actual keyboard layout right now: "
      f"{rule_engine.HKL_TO_LANGUAGE_NAME.get(actual, hex(actual))}")

page_hist = rule_engine._history_of(load("page_learned_defaults.json").get(
    rule_engine._page_key(exe_name, title)))
app_hist = rule_engine._history_of(load("learned_defaults.json").get(exe_name))
print(f"\nFast path inputs:")
print(f"  page history {page_hist} -> trusted: {rule_engine._trust(page_hist)}")
print(f"  app  history {app_hist} -> trusted: {rule_engine._trust(app_hist)}")
if rule_engine._trust(page_hist) is None and rule_engine._trust(app_hist) is None:
    print("  => NOTHING trusted: the fast path would apply NO language on arrival.")

try:
    control = auto.GetFocusedControl()
    rect = control.BoundingRectangle
    print(f"\nFocused control: type={control.ControlTypeName} "
          f"name={(control.Name or '')[:60]!r} size={rect.width()}x{rect.height()}")
except Exception as e:
    print(f"\nCould not read focused control: {e}")

print("\n--- Tier 3 read (the real decide_with_content, DEBUG output below) ---")
hkl, reason = rule_engine.decide_with_content(hwnd, actual, title, exe_name, thread_id)
if reason is None:
    print("\nRESULT: Tier 3 produced NO correction "
          "(see the [content] line above for why).")
else:
    print(f"\nRESULT: Tier 3 would switch to "
          f"{rule_engine.HKL_TO_LANGUAGE_NAME.get(hkl)} "
          f"(source={reason['source']}, confidence={reason['confidence']:.2f}, "
          f"text={reason['text'][:60]!r})")
