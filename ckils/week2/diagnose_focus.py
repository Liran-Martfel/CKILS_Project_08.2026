import time
import uiautomation as auto
from PIL import ImageGrab

auto.InitializeUIAutomationInCurrentThread()
print("You have 5 seconds — click into the real text/content area (not a button), then wait...")
time.sleep(5)

control = auto.GetFocusedControl()
rect = control.BoundingRectangle

print(f"Focused control Name: {control.Name!r}")
print(f"Focused control Type: {control.ControlTypeName}")
print(f"Rect: left={rect.left} top={rect.top} right={rect.right} bottom={rect.bottom}")
print(f"Size: {rect.width()} x {rect.height()}")

# Walk up a couple of parents too, in case the focused element itself is tiny
# (e.g. a button) but its parent is the real content area
parent = control.GetParentControl()
for i in range(3):
    if parent is None:
        break
    prect = parent.BoundingRectangle
    print(f"Parent {i+1}: Name={parent.Name!r} Type={parent.ControlTypeName} "
          f"rect=({prect.left},{prect.top},{prect.right},{prect.bottom}) size={prect.width()}x{prect.height()}")
    parent = parent.GetParentControl()

img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
img.save("diagnose_focus.png")
print("Saved diagnose_focus.png - open it to see exactly what would get OCR'd")
