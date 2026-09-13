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
                "Type a message to Ron Katz", title="WhatsApp"))

    def test_claude_placeholder_rejected(self):
        self.assertFalse(
            rule_engine._looks_like_real_content(
                "Write your prompt to Claude", title="Claude"))

    def test_real_message_not_rejected_as_placeholder(self):
        # A real, unrelated long message must NOT get caught by the same check.
        self.assertTrue(
            rule_engine._looks_like_real_content(
                "בטח אחי נדבר מחר על התוכנית, נדבר מחר", title="WhatsApp"))


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
    English — below threshold, so nothing corrected. Exact string captured
    live from logs/decisions.jsonl at the time."""

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
    def __init__(self, rect, parent=None):
        self.BoundingRectangle = rect
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
        parent = _FakeControl(rect=_FakeRect(-574, 78, -11, 1069))
        header = _FakeControl(rect=_FakeRect(-574, 78, -11, 144), parent=parent)  # 66px tall
        body = _FakeControl(rect=_FakeRect(-574, 144, -11, 1069), parent=parent)  # 925px tall
        parent._children = [header, body]
        _link_siblings(parent._children)

        result = rule_engine._find_larger_sibling_rect(header)
        self.assertIs(result, body.BoundingRectangle)

    def test_no_redirect_when_only_small_siblings_exist(self):
        # The "Start my video" toolbar-button case: short control, but its
        # siblings are other short toolbar buttons, not a real content pane.
        parent = _FakeControl(rect=_FakeRect(-1920, 1003, -600, 1076))
        buttons = [
            _FakeControl(rect=_FakeRect(-1908, 1003, -1776, 1076), parent=parent),
            _FakeControl(rect=_FakeRect(-1776, 1003, -1629, 1076), parent=parent),
            _FakeControl(rect=_FakeRect(-1538, 1003, -1343, 1076), parent=parent),
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
