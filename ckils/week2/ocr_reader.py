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
