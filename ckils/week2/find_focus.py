import asyncio
import time
import uiautomation as auto
from PIL import ImageGrab
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.globalization import Language
from winrt.windows.storage.streams import DataWriter
from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
auto.InitializeUIAutomationInCurrentThread()

print("You have 3 seconds — click into whatever you want to test...")
time.sleep(3)

control = auto.GetFocusedControl()
rect = control.BoundingRectangle

print(f"Focused control: {control.Name!r} ({control.ControlTypeName})")
print(f"Region: left={rect.left} top={rect.top} right={rect.right} bottom={rect.bottom}")
print(f"Size: {rect.width()} x {rect.height()}")
