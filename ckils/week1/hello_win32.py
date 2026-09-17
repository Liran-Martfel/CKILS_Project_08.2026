"""
Week 1, lesson 1 — the very first CKILS script. Prints the title of whichever
window is currently focused. Exists to prove the basic building block the
whole project is built on: that Python can ask Windows "what window is the
user looking at right now?" via win32gui. No loop, no keyboard switching yet
— just one read, once, to confirm the API works.
"""
import win32gui  ## importing win32gui, which gives access to the Windows user interface
## win32 is the API of built-in functions on Windows

hwnd = win32gui.GetForegroundWindow()  ## the unique identifier of the window
## I'm currently using
title = win32gui.GetWindowText(hwnd)  ## using hwnd, takes out the title of the window as a str

print(f"Focused window: {title}")
