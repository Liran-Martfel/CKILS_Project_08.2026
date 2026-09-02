import csv
import os
import time
import uiautomation as auto
from ocr_reader import read_region

DATA_FILE = "training_data.csv"
HEBREW_RANGE = range(0x0590, 0x05FF + 1)


def guess_label(text):
    hebrew_chars = sum(1 for ch in text if ord(ch) in HEBREW_RANGE)
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        return None
    return "hebrew" if hebrew_chars / letters > 0.3 else "english"


def append_row(text, label):
    is_new = not os.path.exists(DATA_FILE)
    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["text", "label"])
        writer.writerow([text, label])


def main():
    auto.InitializeUIAutomationInCurrentThread()
    print("Click into a text field with real content, then come back here.")
    print("You have 3 seconds...")
    time.sleep(3)

    control = auto.GetFocusedControl()
    rect = control.BoundingRectangle
    text = read_region(rect.left, rect.top, rect.right, rect.bottom)

    if not text.strip():
        print("Nothing readable in that region — skipped.")
        return

    guess = guess_label(text)
    print(f"OCR read: {text!r}")
    print(f"Guessed label (from character script): {guess}")

    answer = input("Press Enter to accept, or type 'english'/'hebrew' to correct: ").strip().lower()
    label = answer if answer in ("english", "hebrew") else guess

    if label is None:
        print("Could not determine a label (no letters found) — skipped.")
        return

    append_row(text, label)
    print(f"Saved as {label!r}. Run this again on a different field to add more rows.")


if __name__ == "__main__":
    main()
