"""
Early exploration script: lists every keyboard layout installed on this
Windows machine (and the numeric language ID each one maps to), then
demonstrates the exact mechanism CKILS uses everywhere to actually switch
languages — PostMessage(WM_INPUTLANGCHANGEREQUEST) — by forcing the
current foreground window to English. This is where the English_HKL/
Hebrew_HKL constants used throughout rule_engine.py were first identified.
"""
import ctypes.wintypes
import win32api
import win32con, win32gui, win32process, psutil


##identify the numeric language ID in 16 bits - need to see: 40d for hebrew and 409 for english
layouts = win32api.GetKeyboardLayoutList()
for hkl in layouts:
    lcid = hkl & 0xFFFF  # the low 16 bits are the language ID
    print(f"HKL: {hex(hkl)}   LCID: {hex(lcid)}")

#HKL = handle to a keyboard layout
English_HKL = 0x4090409
Hebrew_HKL = -0xfc2fbf3

hwnd = win32gui.GetForegroundWindow()
# This is the same message Windows sends itself when switching
# layout by hand with Alt+Shift — we're just sending it programmatically.
win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, English_HKL)
##############################################################################################