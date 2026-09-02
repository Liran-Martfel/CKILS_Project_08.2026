import time
import uiautomation as auto
from PIL import ImageGrab

auto.InitializeUIAutomationInCurrentThread()
print("You have 5 seconds — click into whatever you want to test...")
time.sleep(5)

control = auto.GetFocusedControl()
rect = control.BoundingRectangle

print(f"Focused control: {control.Name!r} ({control.ControlTypeName})")
print(f"Rect: left={rect.left} top={rect.top} right={rect.right} bottom={rect.bottom}")
print(f"Size: {rect.width()} x {rect.height()}")

img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
img.save("debug_capture.png")
print(f"Saved debug_capture.png — image mode={img.mode}, size={img.size}")
