"""Regression tests, one per real bug found and fixed live. Standard library
unittest only (no pytest dependency) — run with: python test_regressions.py

Per the team's own practice going forward: every future bug fix should add a
test here reproducing the exact failure that was found, not a synthetic
approximation of it. importing rule_engine is safe for testing because its
hook-setup / message-loop code is guarded by `if __name__ == "__main__":` —
see that guard's own comment for why.
"""
import shutil
import tempfile
import unittest
from unittest.mock import patch

import rule_engine
import decision_logger


class PlaceholderRejectionTests(unittest.TestCase):
    """Real bug: an app's own empty-compose-box placeholder read as if it were
    real typed content, confidently forcing the wrong language. Confirmed for
    WhatsApp ("Type a message") on 2026-09-0x and Claude.ai ("Write your
    prompt to Claude") on 2026-09-13 — same fix, different apps."""

    def test_whatsapp_placeholder_rejected(self):
        self.assertFalse(
            rule_engine._looks_like_real_content("Type a message", title="WhatsApp"))

    def test_whatsapp_placeholder_with_contact_name_rejected(self):
        self.assertFalse(
            rule_engine._looks_like_real_content(
                "Type a message to Idan Avitan", title="WhatsApp"))

    def test_claude_placeholder_rejected(self):
        self.assertFalse(
            rule_engine._looks_like_real_content(
                "Write your prompt to Claude", title="Claude"))

    def test_claude_existing_conversation_placeholder_rejected(self):
        # Real bug (2026-09-14): Claude.ai's placeholder wording is DIFFERENT
        # once you're continuing an existing conversation ("Write a
        # message...") vs. starting a brand-new one ("Write your prompt to
        # Claude") — confirmed live, reached via OCR and kept flipping a real
        # Hebrew CV conversation back to English every time the box emptied.
        # The exact real capture (confidence 0.71 — above threshold — is what
        # actually flipped the real conversation back to English each time).
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("Write a message..."))

    def test_real_message_not_rejected_as_placeholder(self):
        # A real, unrelated long message must NOT get caught by the same check.
        self.assertTrue(
            rule_engine._looks_like_real_content(
                "בטח אחי נדבר מחר על התוכנית ונסגור הכל", title="WhatsApp"))


class UiNoiseRejectionTests(unittest.TestCase):
    """Real bug: Zoom's own product-branding text ("zoom. Workplace ...") and
    WhatsApp's placeholder both reached the classifier via OCR, bypassing the
    accessible-text-only checks above, because the old code only checked
    UI_CHROME_MARKERS/PLACEHOLDER_TEXT_PREFIXES inline at one call site.
    _rejected_as_ui_noise() is that same check, extracted so it's testable
    directly instead of only reachable through a live OCR read."""

    def test_zoom_workplace_branding_rejected(self):
        self.assertIsNotNone(
            rule_engine._rejected_as_ui_noise("zoom. Workplace communication, redefined."))

    def test_whatsapp_placeholder_rejected_via_ocr_path_too(self):
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("Type a message"))

    def test_real_content_not_rejected(self):
        self.assertIsNone(rule_engine._rejected_as_ui_noise("היי, מה קורה מחר?"))


class MessageMetadataStrippingTests(unittest.TestCase):
    """Real bug (2026-09-11): a real, unambiguously Hebrew WhatsApp message
    was glued to English UI metadata (sender prefix + timestamp/status/action
    footer), diluting classifier confidence from ~84% Hebrew down to 56%
    English — below threshold, so nothing corrected. String shape preserved
    from the real live capture; wording changed (see PROJECT_JOURNEY.md for
    why — this is example content, not a transcript of a real conversation)."""

    def test_strips_sender_prefix_and_status_footer(self):
        raw = "You: בטח אחי נדבר מחר על התוכנית 16:36 Delivered Open message o"
        self.assertEqual(
            rule_engine._strip_message_metadata(raw),
            "בטח אחי נדבר מחר על התוכנית")

    def test_reclassifies_correctly_after_stripping(self):
        raw = "You: בטח אחי נדבר מחר על התוכנית 16:36 Delivered Open message o"
        stripped = rule_engine._strip_message_metadata(raw)
        label, proba = rule_engine.predict_language(stripped)
        self.assertEqual(label, "hebrew")
        self.assertGreaterEqual(proba[label], rule_engine.CONTENT_CONFIDENCE_THRESHOLD)

    def test_leaves_unrelated_text_untouched(self):
        # No "You:" prefix, no HH:MM+status footer — must pass through as-is.
        text = "Search or start a new chat chat-list-filters Archived Chat list"
        self.assertEqual(rule_engine._strip_message_metadata(text), text)

    def test_does_not_over_strip_a_real_link_preview_message(self):
        # A different real message, ending in a status footer but with no "You:"
        # prefix — only the trailing footer should go, the URL content must stay.
        raw = ("example-link-preview.example.com "
               "https://example-link-preview.example.com/ "
               "17:49 Read Open message options React Forward media")
        stripped = rule_engine._strip_message_metadata(raw)
        self.assertIn("example-link-preview.example.com", stripped)
        self.assertNotIn("Delivered", stripped)
        self.assertNotIn("Read", stripped)


class CalendarMetadataStrippingTests(unittest.TestCase):
    """Real bug (2026-09-15): Google Calendar event/task tiles glue the real,
    user-typed title to a comma-separated wrapper of English fields (time
    range, calendar's own possessive name, location, RSVP/task status, date)
    — often longer than a short Hebrew title, flipping the classification to
    English. String shapes preserved from the real live capture; wording
    changed (this is example content, not a transcript of a real calendar)."""

    def test_strips_event_tile_wrapper(self):
        raw = "6:30pm to 7pm, לאסוף חבילה מהדואר, Liran's calender, No location, September 15, 2026"
        self.assertEqual(rule_engine._strip_calendar_metadata(raw), "לאסוף חבילה מהדואר")

    def test_strips_event_tile_with_rsvp_status_and_trailing_note(self):
        raw = ("8am to 9am, לקנות מצרכים לשבת, Liran's calender, Accepted, No location, "
               "September 11, 2026 Event is being created.")
        self.assertEqual(rule_engine._strip_calendar_metadata(raw), "לקנות מצרכים לשבת")

    def test_strips_task_tile_wrapper(self):
        raw = ("task: לסיים לקרוא את הפרק הבא בספר ולהכין סיכום קצר לפני הפגישה, "
               "Not completed, September 11, 2026, 10:30am")
        self.assertEqual(
            rule_engine._strip_calendar_metadata(raw),
            "לסיים לקרוא את הפרק הבא בספר ולהכין סיכום קצר לפני הפגישה")

    def test_reclassifies_event_tile_correctly_after_stripping(self):
        raw = "6:30pm to 7pm, לאסוף חבילה מהדואר, Liran's calender, No location, September 15, 2026"
        stripped = rule_engine._strip_calendar_metadata(raw)
        label, proba = rule_engine.predict_language(stripped)
        self.assertEqual(label, "hebrew")
        self.assertGreaterEqual(proba[label], rule_engine.CONTENT_CONFIDENCE_THRESHOLD)

    def test_leaves_unrelated_text_untouched(self):
        text = "Search or start a new chat chat-list-filters Archived Chat list"
        self.assertEqual(rule_engine._strip_calendar_metadata(text), text)


# Fake uiautomation-style Control objects — just enough surface area
# (BoundingRectangle, GetParentControl, GetFirstChildControl,
# GetNextSiblingControl) for _find_larger_sibling_rect to walk, without
# needing a real window or the uiautomation library's live tree.
class _FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _FakeControl:
    def __init__(self, rect, parent=None, name=""):
        self.BoundingRectangle = rect
        self.Name = name
        self._parent = parent
        self._children = []

    def GetParentControl(self):
        return self._parent

    def GetFirstChildControl(self):
        return self._children[0] if self._children else None


def _link_siblings(children):
    for i, child in enumerate(children):
        child._next_sibling = children[i + 1] if i + 1 < len(children) else None

        def _get_next_sibling(self=child):
            return self._next_sibling

        child.GetNextSiblingControl = _get_next_sibling


class SiblingRedirectTests(unittest.TestCase):
    """Real bug (2026-09-11), diagnosed with diagnose_zoom_tree.py: Zoom's chat
    panel puts GetFocusedControl() on a short header pane (~66px) that sits as
    a sibling right above the real ~925px chat body, which Zoom draws as
    pixels with no accessible Name — OCR was reading the header every time,
    not the conversation. Reproduces that exact tree shape, plus the second,
    still-unfixed shape (a toolbar button with only other short siblings) to
    lock in that this fix correctly does nothing there instead of misfiring."""

    def test_redirects_from_header_to_large_sibling_body(self):
        # Positive, monitor-agnostic coordinates deliberately (not the real
        # negative multi-monitor ones captured live) — _is_onscreen() depends
        # on the ACTUAL current virtual screen bounds (win32api.GetSystemMetrics
        # at import time), which varies by machine/monitor arrangement; a fixed
        # negative-coordinate rect would only be "on screen" on a matching
        # multi-monitor setup, making this test flaky across machines.
        parent = _FakeControl(rect=_FakeRect(100, 78, 700, 1069))
        header = _FakeControl(rect=_FakeRect(100, 78, 700, 144), parent=parent)  # 66px tall
        body = _FakeControl(rect=_FakeRect(100, 144, 700, 1069), parent=parent)  # 925px tall
        parent._children = [header, body]
        _link_siblings(parent._children)

        result = rule_engine._find_larger_sibling_rect(header)
        self.assertIs(result, body.BoundingRectangle)

    def test_no_redirect_when_only_small_siblings_exist(self):
        # The "Start my video" toolbar-button case: short control, but its
        # siblings are other short toolbar buttons, not a real content pane.
        # Positive coordinates deliberately — see the note in the test above.
        parent = _FakeControl(rect=_FakeRect(0, 1003, 1320, 1076))
        buttons = [
            _FakeControl(rect=_FakeRect(12, 1003, 144, 1076), parent=parent),
            _FakeControl(rect=_FakeRect(144, 1003, 291, 1076), parent=parent),
            _FakeControl(rect=_FakeRect(382, 1003, 577, 1076), parent=parent),
        ]
        parent._children = buttons
        _link_siblings(parent._children)

        result = rule_engine._find_larger_sibling_rect(buttons[0])
        self.assertIsNone(result)

    def test_does_not_redirect_to_a_sibling_above_it(self):
        # A large sibling ABOVE the focused control is not "the body under the
        # header" — must not redirect to it.
        parent = _FakeControl(rect=_FakeRect(0, 0, 500, 1000))
        big_sibling_above = _FakeControl(rect=_FakeRect(0, 0, 500, 900), parent=parent)
        header = _FakeControl(rect=_FakeRect(0, 900, 500, 966), parent=parent)
        parent._children = [big_sibling_above, header]
        _link_siblings(parent._children)

        result = rule_engine._find_larger_sibling_rect(header)
        self.assertIsNone(result)


class GoogleDocsTitleOneTimeDefaultTests(unittest.TestCase):
    """Real bug (2026-09-15): Google Docs' body text is a confirmed dead end to
    read, so the only signal decide_with_content has is the document's own
    TITLE — which never changes for the whole visit. It was being re-derived
    and re-applied every time Tier 3 ran (every focus/title event, plus the
    3-second poll thread) as if it were live content, capable of silently
    overriding real mid-typing work (e.g. an English term inside an otherwise-
    Hebrew document) the moment an unrelated focus blip reset the manual-
    override protection. Fixed to behave as a one-time default per visit,
    same spirit as the learned-defaults layers."""

    def setUp(self):
        rule_engine.google_docs_title_already_applied.clear()

    def tearDown(self):
        rule_engine.google_docs_title_already_applied.clear()

    @staticmethod
    def _fake_offscreen_doc_control():
        # Real captured shape: Google Docs reports its focused control's rect
        # in document-scroll coordinates, often far outside any real monitor.
        return _FakeControl(rect=_FakeRect(1076, -13318, 1921, -13292), name="")

    def test_first_read_uses_the_title_and_marks_it_applied(self):
        hwnd = 12345
        title = "קורות חיים - לירן - Google Docs"
        with patch.object(rule_engine.win32gui, "GetForegroundWindow", return_value=hwnd), \
             patch.object(rule_engine.auto, "GetFocusedControl", return_value=self._fake_offscreen_doc_control()):
            hkl, reason = rule_engine.decide_with_content(hwnd, None, title, "chrome.exe", thread_id=999)

        self.assertEqual(hkl, rule_engine.Hebrew_HKL)
        self.assertEqual(reason["source"], "google_docs_title")
        self.assertIn(999, rule_engine.google_docs_title_already_applied)

    def test_second_read_same_visit_does_not_reassert(self):
        # Reproduces the exact real scenario: the first read applies Hebrew
        # from the title, then the poll thread re-checks a few seconds later
        # while the user's own manual English override is the current
        # fallback — this must NOT get silently overwritten back to Hebrew.
        hwnd = 12345
        title = "קורות חיים - לירן - Google Docs"
        with patch.object(rule_engine.win32gui, "GetForegroundWindow", return_value=hwnd), \
             patch.object(rule_engine.auto, "GetFocusedControl", return_value=self._fake_offscreen_doc_control()):
            rule_engine.decide_with_content(hwnd, None, title, "chrome.exe", thread_id=999)
            hkl, reason = rule_engine.decide_with_content(
                hwnd, rule_engine.English_HKL, title, "chrome.exe", thread_id=999)

        self.assertEqual(hkl, rule_engine.English_HKL)  # fallback returned untouched
        self.assertIsNone(reason)

    def test_new_visit_after_title_change_gets_a_fresh_read(self):
        # Switching to a DIFFERENT Google Docs tab (same shared Chrome
        # thread_id, confirmed real quirk) must still get its own one-time
        # title-derived read — this fix must not disable the mechanism
        # entirely, only stop it repeating within the same still-open
        # document. on_focus_change resets google_docs_title_already_applied
        # on any title change for a thread (see rule_engine.py) BEFORE calling
        # decide_with_content — simulated directly here since this test
        # targets decide_with_content in isolation, not the full event path.
        hwnd = 12345
        rule_engine.google_docs_title_already_applied.add(999)  # "קורות חיים" already answered
        rule_engine.google_docs_title_already_applied.discard(999)  # on_focus_change's title-change reset
        new_title = "Resume - Liran Martfel - Google Docs"
        with patch.object(rule_engine.win32gui, "GetForegroundWindow", return_value=hwnd), \
             patch.object(rule_engine.auto, "GetFocusedControl", return_value=self._fake_offscreen_doc_control()):
            hkl, reason = rule_engine.decide_with_content(hwnd, None, new_title, "chrome.exe", thread_id=999)

        self.assertEqual(hkl, rule_engine.English_HKL)
        self.assertEqual(reason["source"], "google_docs_title")
        self.assertIn(999, rule_engine.google_docs_title_already_applied)  # now marked for THIS title


class TrustHistoryTests(unittest.TestCase):
    """Real design (2026-09-08): trust must be earned from CKILS's own observed
    history for a key, never assumed from a hand-named app list. A brand-new,
    never-named fake app is used deliberately here to prove the mechanism
    itself withholds/grants trust — not a name check."""

    def test_below_minimum_samples_is_not_trusted(self):
        self.assertIsNone(rule_engine._trust(["hebrew", "hebrew"]))

    def test_consistent_history_is_trusted(self):
        # 4/5 = 80% — exactly at TRUST_AGREEMENT_THRESHOLD.
        self.assertEqual(
            rule_engine._trust(["hebrew", "hebrew", "hebrew", "hebrew", "english"]), "hebrew")

    def test_inconsistent_history_is_not_trusted(self):
        self.assertIsNone(
            rule_engine._trust(["hebrew", "english", "hebrew", "english"]))

    def test_history_of_normalizes_legacy_bare_string(self):
        self.assertEqual(rule_engine._history_of("hebrew"), ["hebrew"])

    def test_history_of_normalizes_new_dict_shape(self):
        self.assertEqual(
            rule_engine._history_of({"history": ["hebrew", "english"]}),
            ["hebrew", "english"])

    def test_history_of_handles_missing_key(self):
        self.assertEqual(rule_engine._history_of(None), [])


class DecisionLoggerOverrideLinkTests(unittest.TestCase):
    """Real bug (2026-09-11): log_manual_override always recorded
    "preceding_auto": null, even seconds after a real auto-decision fired for
    that same window, because forget_thread() cleared it on every focus
    change to a different thread — the correct lifetime for a per-visit
    sticky value (content_decision), not for this. Fixed by removing that
    clearing entirely; this locks in that the link survives across an
    intervening focus change to a different window, which is exactly the
    real pattern that broke it (tab away, come back, then correct it)."""

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_logs_dir = decision_logger.LOGS_DIR
        self._orig_screenshots_dir = decision_logger.SCREENSHOTS_DIR
        self._orig_log_file = decision_logger.LOG_FILE
        decision_logger.LOGS_DIR = self._tmp_dir
        decision_logger.SCREENSHOTS_DIR = self._tmp_dir
        decision_logger.LOG_FILE = f"{self._tmp_dir}/decisions.jsonl"
        decision_logger._last_auto_decision.clear()

    def tearDown(self):
        decision_logger.LOGS_DIR = self._orig_logs_dir
        decision_logger.SCREENSHOTS_DIR = self._orig_screenshots_dir
        decision_logger.LOG_FILE = self._orig_log_file
        decision_logger._last_auto_decision.clear()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_override_links_to_preceding_auto_decision(self):
        decision_logger.log_auto_change(
            "zoom.exe", "Zoom Meeting", 6384, "english", "hebrew",
            {"mechanism": "tier3_content", "source": "ocr", "text": "x",
             "predicted_label": "hebrew", "confidence": 0.9, "screenshot_rect": None})

        decision_logger.log_manual_override("zoom.exe", "Zoom Meeting", 6384, "english")

        with open(decision_logger.LOG_FILE, encoding="utf-8") as f:
            import json
            lines = [json.loads(line) for line in f]
        override_entry = lines[-1]
        self.assertEqual(override_entry["event_type"], "manual_override")
        self.assertIsNotNone(override_entry["preceding_auto"])
        self.assertEqual(override_entry["preceding_auto"]["new_language"], "hebrew")


if __name__ == "__main__":
    unittest.main()
