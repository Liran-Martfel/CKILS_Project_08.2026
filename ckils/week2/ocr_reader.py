import asyncio
import time
import uiautomation as auto
from PIL import ImageGrab
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.globalization import Language
from winrt.windows.storage.streams import DataWriter
from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat

# Both scripts are tried because OCR can't know in advance which one it's looking at —
# Hebrew and English aren't just different words, they're different character shapes.
CANDIDATE_LANGUAGES = ["en", "he"]


def _build_engines():
    engines = {}
    for tag in CANDIDATE_LANGUAGES:
        engine = OcrEngine.try_create_from_language(Language(tag))
        # None means that language pack isn't installed — skip it, don't crash
        if engine is not None:
            engines[tag] = engine
    return engines


async def read_region(left, top, right, bottom):
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # WinRT wants the pixels as a SoftwareBitmap, not a PIL Image directly
    writer = DataWriter()
    writer.write_bytes(img.tobytes())
    buffer = writer.detach_buffer()
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        buffer, BitmapPixelFormat.RGBA8, img.width, img.height
    )

    engines = _build_engines()
    if not engines:
        raise RuntimeError("No OCR language packs installed at all.")

    results = {}
    for tag, engine in engines.items():
        result = await engine.recognize_async(bitmap)
        results[tag] = result.text

    # whichever engine recognized the most characters is almost certainly the right script
    best_tag = max(results, key=lambda t: len(results[t]))
    return results[best_tag], best_tag


if __name__ == "__main__":
    auto.InitializeUIAutomationInCurrentThread()
    print("You have 3 seconds — click into whatever you want to test...")
    time.sleep(3)

    control = auto.GetFocusedControl()
    rect = control.BoundingRectangle

    text, used_lang = asyncio.run(read_region(rect.left, rect.top, rect.right, rect.bottom))
    print(f"Read with the '{used_lang}' engine: {text!r}")