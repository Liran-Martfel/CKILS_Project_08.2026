"""
The OCR layer CKILS's Tier 3 depends on. Defines read_region(), which
screenshots a screen rectangle and runs Tesseract over it reading both
English and Hebrew at once — this is what rule_engine.py calls whenever
accessible text isn't available and it has to actually look at the pixels.
Also runnable directly for a quick manual check: click into anything, and
it reads back whatever's under the currently focused control.
"""
import os
import time
import uiautomation as auto
import pytesseract
from PIL import ImageGrab

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Tesseract's own installer only ships English data. Hebrew's language data lives
# in this project (tessdata/heb.traineddata) instead of Program Files, so no admin
# rights are needed to add it — Program Files itself is admin-only to write to.
TESSDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")


def read_region(left, top, right, bottom):
    """Screenshots the given screen rectangle and returns whatever text
    Tesseract reads from it, checking both English and Hebrew in one pass.
    Coordinates are absolute screen coordinates (not window-relative), and
    all_screens=True is required for correct results on any monitor other
    than the primary one.
    """
    # all_screens=True matters on multi-monitor setups — without it, a rectangle on any
    # monitor except the primary one (often at negative coordinates) grabs solid black.
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)

    # eng+heb = one call, reading both scripts at once — handles a field with mixed
    # Hebrew/English content directly, instead of guessing which single language to try.
    config = f"--tessdata-dir {TESSDATA_DIR}"
    text = pytesseract.image_to_string(img, lang="eng+heb", config=config)
    return text.strip()


if __name__ == "__main__":
    auto.InitializeUIAutomationInCurrentThread()
    print("You have 3 seconds — click into whatever you want to test...")
    time.sleep(3)

    control = auto.GetFocusedControl()
    rect = control.BoundingRectangle

    text = read_region(rect.left, rect.top, rect.right, rect.bottom)
    print(f"Read: {text!r}")
