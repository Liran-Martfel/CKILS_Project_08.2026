"""
Diagnostic tool built specifically to settle whether Google Docs' body text
is readable through UI Automation's TextPattern interface at all (visible
ranges, the full document range, and the current selection). The answer
this tool confirmed live — no, on every one of those — is why rule_engine.py
gives up on reading Google Docs' body and falls back to the document's own
title instead (see _google_docs_title_text). Not something you'd run
routinely; it exists to have settled that question once, with real evidence.
"""
import time
import uiautomation as auto

auto.InitializeUIAutomationInCurrentThread()
print("You have 5 seconds — click into the Google Docs document text, then wait...")
time.sleep(5)

control = auto.GetFocusedControl()
print(f"Focused control: {control.Name!r} ({control.ControlTypeName})")

text_pattern = control.GetPattern(auto.PatternId.TextPattern)
if text_pattern is None:
    print("This control does NOT support TextPattern at all.")
else:
    print("TextPattern is supported.")

    print("\n--- GetVisibleRanges() ---")
    ranges = text_pattern.GetVisibleRanges()
    print(f"Got {len(ranges)} visible range(s)")
    for i, r in enumerate(ranges):
        text = r.GetText(1000)
        print(f"Range {i} ({len(text)} chars): {text[:200]!r}")

    print("\n--- DocumentRange (the whole document, not just what's visible) ---")
    try:
        doc_range = text_pattern.DocumentRange
        text = doc_range.GetText(2000)
        print(f"DocumentRange text ({len(text)} chars): {text[:300]!r}")
    except Exception as e:
        print(f"DocumentRange failed: {e}")

    print("\n--- GetSelection() (the caret/cursor position) ---")
    try:
        selection = text_pattern.GetSelection()
        print(f"Got {len(selection)} selection range(s)")
        for i, r in enumerate(selection):
            text = r.GetText(1000)
            print(f"Selection {i} ({len(text)} chars): {text[:200]!r}")
    except Exception as e:
        print(f"GetSelection failed: {e}")
