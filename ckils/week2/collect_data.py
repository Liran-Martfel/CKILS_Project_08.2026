"""
The tool used to build training_data.csv — the labeled dataset train_model.py
trains on. OCR's whatever field is focused, guesses its language from the
raw character script (mostly-Hebrew-Unicode-range vs not), asks the user to
confirm or correct that guess, then appends the real (text, label) pair to
the CSV. This is how every one of the model's training examples became real
captured usage instead of hand-written or synthetic examples.
"""
import csv
import os
import time
import uiautomation as auto
from ocr_reader import read_region

DATA_FILE = "training_data.csv"
HEBREW_RANGE = range(0x0590, 0x05FF + 1)


def guess_label(text):
    """Guesses "hebrew" or "english" from the raw proportion of Hebrew-range
    Unicode characters among all letters in text — a rough, mechanical guess
    meant to be confirmed or corrected by a human in main(), not trusted on
    its own. Returns None if the text has no letters at all to judge from.
    """
    hebrew_chars = sum(1 for ch in text if ord(ch) in HEBREW_RANGE)
    letters = sum(1 for ch in text if ch.isalpha())
    if letters == 0:
        return None
    return "hebrew" if hebrew_chars / letters > 0.3 else "english"


def append_row(text, label):
    """Appends one (text, label) row to DATA_FILE, writing the header row
    first if the file doesn't exist yet.
    """
    is_new = not os.path.exists(DATA_FILE)
    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["text", "label"])
        writer.writerow([text, label])


def main():
    """Interactive one-shot data-collection flow: capture the focused
    field's text via OCR, guess its label, let the user confirm/correct it,
    then save the real (text, label) pair. Run this again for each new
    example — one call adds exactly one row.
    """
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
