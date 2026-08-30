import win32gui  ## importing win32gui, which gives access to the Windows user interface
## win32 is the API of built-in functions on Windows

hwnd = win32gui.GetForegroundWindow()  ## the unique identifier of the window
## I'm currently using
title = win32gui.GetWindowText(hwnd)  ## using hwnd, takes out the title of the window as a str

print(f"Focused window: {title}")
