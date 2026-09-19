"""Regression tests, one per real bug found and fixed live. Standard library
unittest only (no pytest dependency) — run with: python test_regressions.py

Per the team's own practice going forward: every future bug fix should add a
test here reproducing the exact failure that was found, not a synthetic
approximation of it. importing rule_engine is safe for testing because its
hook-setup / message-loop code is guarded by `if __name__ == "__main__":` —
see that guard's own comment for why.
"""
import os
import queue
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import rule_engine
import decision_logger
import skip_logger


class PlaceholderRejectionTests(unittest.TestCase):
    """Real bug: an app's own empty-compose-box placeholder read as if it were
    real typed content, confidently forcing the wrong language. Confirmed for
    WhatsApp ("Type a message") on 2026-09-0x and Claude.ai ("Write your
    prompt to Claude") on 2026-09-13 — same fix, different apps."""

    def test_whatsapp_placeholder_rejected(self):
        """Whatsapp placeholder rejected."""
        self.assertFalse(
            rule_engine._looks_like_real_content("Type a message", title="WhatsApp"))

    def test_whatsapp_placeholder_with_contact_name_rejected(self):
        """Whatsapp placeholder with contact name rejected."""
        self.assertFalse(
            rule_engine._looks_like_real_content(
                "Type a message to Ron Katz", title="WhatsApp"))

    def test_whatsapp_contact_search_placeholder_rejected(self):
        """Whatsapp contact search placeholder rejected."""
        # Real bug (2026-09-16): a THIRD, distinct WhatsApp placeholder (the
        # contact-search box, not the message-compose box) forced English
        # back over a real Hebrew message that had just been read correctly.
        self.assertIsNotNone(
            rule_engine._rejected_as_ui_noise("Search name, number or @username"))

    def test_claude_placeholder_rejected(self):
        """Claude placeholder rejected."""
        self.assertFalse(
            rule_engine._looks_like_real_content(
                "Write your prompt to Claude", title="Claude"))

    def test_claude_existing_conversation_placeholder_rejected(self):
        """Claude existing conversation placeholder rejected."""
        # Real bug (2026-09-14): Claude.ai's placeholder wording is DIFFERENT
        # once you're continuing an existing conversation ("Write a
        # message...") vs. starting a brand-new one ("Write your prompt to
        # Claude") — confirmed live, reached via OCR and kept flipping a real
        # Hebrew CV conversation back to English every time the box emptied.
        # The exact real capture (confidence 0.71 — above threshold — is what
        # actually flipped the real conversation back to English each time).
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("Write a message..."))

    def test_real_message_not_rejected_as_placeholder(self):
        """Real message not rejected as placeholder."""
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
        """Zoom workplace branding rejected."""
        self.assertIsNotNone(
            rule_engine._rejected_as_ui_noise("zoom. Workplace communication, redefined."))

    def test_whatsapp_placeholder_rejected_via_ocr_path_too(self):
        """Whatsapp placeholder rejected via ocr path too."""
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("Type a message"))

    def test_tradingview_tagline_rejected(self):
        """Tradingview tagline rejected."""
        # Real bug found by auditing every manual override on record: this
        # exact tagline kept forcing Hebrew over real English ticker symbols.
        self.assertIsNotNone(
            rule_engine._rejected_as_ui_noise(
                "גרפי מניות, מדדים, חוזים עתידיים, מט\"ח וביטקוין בזמן-אמת ב-TradingView"))

    def test_youtube_logo_only_rejected(self):
        """Youtube logo only rejected."""
        # Real bug: OCR repeatedly read nothing but YouTube's own logo/
        # wordmark on a Hebrew-titled video, forcing English over real
        # Hebrew content. Exact real captures, including OCR artifacts.
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("YouTube“"))
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("> YouTube"))
        self.assertIsNotNone(rule_engine._rejected_as_ui_noise("YouTube"))

    def test_real_comment_mentioning_youtube_not_rejected(self):
        """Real comment mentioning youtube not rejected."""
        # Must NOT catch real content that happens to mention YouTube by name.
        self.assertIsNone(
            rule_engine._rejected_as_ui_noise("I loved this YouTube video, thanks for sharing!"))

    def test_real_content_not_rejected(self):
        """Real content not rejected."""
        self.assertIsNone(rule_engine._rejected_as_ui_noise("היי, מה קורה מחר?"))


class MessageMetadataStrippingTests(unittest.TestCase):
    """Real bug (2026-09-11): a real, unambiguously Hebrew WhatsApp message
    was glued to English UI metadata (sender prefix + timestamp/status/action
    footer), diluting classifier confidence from ~84% Hebrew down to 56%
    English — below threshold, so nothing corrected. String shape preserved
    from the real live capture; wording changed (see PROJECT_JOURNEY.md for
    why — this is example content, not a transcript of a real conversation)."""

    def test_strips_sender_prefix_and_status_footer(self):
        """Strips sender prefix and status footer."""
        raw = "You: בטח אחי נדבר מחר על התוכנית 16:36 Delivered Open message o"
        self.assertEqual(
            rule_engine._strip_message_metadata(raw),
            "בטח אחי נדבר מחר על התוכנית")

    def test_reclassifies_correctly_after_stripping(self):
        """Reclassifies correctly after stripping."""
        raw = "You: בטח אחי נדבר מחר על התוכנית 16:36 Delivered Open message o"
        stripped = rule_engine._strip_message_metadata(raw)
        label, proba = rule_engine.predict_language(stripped)
        self.assertEqual(label, "hebrew")
        self.assertGreaterEqual(proba[label], rule_engine.CONTENT_CONFIDENCE_THRESHOLD)

    def test_strips_other_contacts_sender_prefix_and_context_menu_footer(self):
        """Strips other contacts sender prefix and context menu footer."""
        # Real bug (2026-09-16): a message from someone else (not "You")
        # wasn't stripped at all - different sender-name prefix, different
        # footer shape ("Context menu for message from <name> React").
        raw = ("Noa Levy: התכוונתי להגיע בבוקר ואז החלטתי לבוא בערב "
               "09:44 Context menu for message from Noa Levy React")
        self.assertEqual(
            rule_engine._strip_message_metadata(raw),
            "התכוונתי להגיע בבוקר ואז החלטתי לבוא בערב")

    def test_reclassifies_other_contacts_message_correctly_after_stripping(self):
        """Reclassifies other contacts message correctly after stripping."""
        raw = ("Noa Levy: התכוונתי להגיע בבוקר ואז החלטתי לבוא בערב "
               "09:44 Context menu for message from Noa Levy React")
        stripped = rule_engine._strip_message_metadata(raw)
        label, proba = rule_engine.predict_language(stripped)
        self.assertEqual(label, "hebrew")
        self.assertGreaterEqual(proba[label], rule_engine.CONTENT_CONFIDENCE_THRESHOLD)

    def test_does_not_strip_a_leading_time_as_a_sender_prefix(self):
        """Does not strip a leading time as a sender prefix."""
        # The generalized sender-prefix pattern must NOT catch a calendar
        # time range ("6:30pm...") or a URL scheme ("https://...") just
        # because they contain an early colon - both stay letters-only-free.
        raw = "6:30pm to 7pm, לאסוף חבילה מהדואר, Liran's calender, No location, September 15, 2026"
        self.assertEqual(rule_engine._strip_message_metadata(raw), raw)

    def test_does_not_strip_a_url_scheme_as_a_sender_prefix(self):
        """Does not strip a url scheme as a sender prefix."""
        raw = ("example-link-preview.example.com https://example-link-preview.example.com/ "
               "17:49 Read Open message options React Forward media")
        stripped = rule_engine._strip_message_metadata(raw)
        self.assertTrue(stripped.startswith("example-link-preview.example.com"))

    def test_leaves_unrelated_text_untouched(self):
        """Leaves unrelated text untouched."""
        # No "You:" prefix, no HH:MM+status footer — must pass through as-is.
        text = "Search or start a new chat chat-list-filters Archived Chat list"
        self.assertEqual(rule_engine._strip_message_metadata(text), text)

    def test_does_not_over_strip_a_real_link_preview_message(self):
        """Does not over strip a real link preview message."""
        # Real shape (a link-preview message, status footer, no "You:" prefix)
        # — only the trailing footer should go, the URL content must stay.
        # example.com is the reserved documentation domain (RFC 2606) —
        # deliberately not a real site, unlike the URL this was first written
        # against, which turned out to belong to an unrelated project of the
        # user's and had no business being an example in this public repo.
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
        """Strips event tile wrapper."""
        raw = "6:30pm to 7pm, לאסוף חבילה מהדואר, Liran's calender, No location, September 15, 2026"
        self.assertEqual(rule_engine._strip_calendar_metadata(raw), "לאסוף חבילה מהדואר")

    def test_strips_event_tile_with_rsvp_status_and_trailing_note(self):
        """Strips event tile with rsvp status and trailing note."""
        raw = ("8am to 9am, לקנות מצרכים לשבת, Liran's calender, Accepted, No location, "
               "September 11, 2026 Event is being created.")
        self.assertEqual(rule_engine._strip_calendar_metadata(raw), "לקנות מצרכים לשבת")

    def test_strips_task_tile_wrapper(self):
        """Strips task tile wrapper."""
        raw = ("task: לסיים לקרוא את הפרק הבא בספר ולהכין סיכום קצר לפני הפגישה, "
               "Not completed, September 11, 2026, 10:30am")
        self.assertEqual(
            rule_engine._strip_calendar_metadata(raw),
            "לסיים לקרוא את הפרק הבא בספר ולהכין סיכום קצר לפני הפגישה")

    def test_reclassifies_event_tile_correctly_after_stripping(self):
        """Reclassifies event tile correctly after stripping."""
        raw = "6:30pm to 7pm, לאסוף חבילה מהדואר, Liran's calender, No location, September 15, 2026"
        stripped = rule_engine._strip_calendar_metadata(raw)
        label, proba = rule_engine.predict_language(stripped)
        self.assertEqual(label, "hebrew")
        self.assertGreaterEqual(proba[label], rule_engine.CONTENT_CONFIDENCE_THRESHOLD)

    def test_leaves_unrelated_text_untouched(self):
        """Leaves unrelated text untouched."""
        text = "Search or start a new chat chat-list-filters Archived Chat list"
        self.assertEqual(rule_engine._strip_calendar_metadata(text), text)


# Fake uiautomation-style Control objects — just enough surface area
# (BoundingRectangle, GetParentControl, GetFirstChildControl,
# GetNextSiblingControl) for _find_larger_sibling_rect to walk, without
# needing a real window or the uiautomation library's live tree.
class _FakeRect:
    """A minimal stand-in for uiautomation's real rect type — just left/top/
    right/bottom plus width()/height(), enough for the code under test.
    """
    def __init__(self, left, top, right, bottom):
        """Stores the four raw edge coordinates."""
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        """Returns right - left."""
        return self.right - self.left

    def height(self):
        """Returns bottom - top."""
        return self.bottom - self.top


class _FakeControl:
    """A minimal stand-in for a real uiautomation Control — just enough
    surface area (BoundingRectangle, GetParentControl, GetFirstChildControl,
    GetNextSiblingControl via _link_siblings) for the tree-walking functions
    under test to operate on, without a real window or live UI tree.
    """
    def __init__(self, rect, parent=None, name=""):
        """Builds a fake control with the given rect/parent/name and no
        children yet (append to self._children directly to add some).
        """
        self.BoundingRectangle = rect
        self.Name = name
        self._parent = parent
        self._children = []

    def GetParentControl(self):
        """Returns the parent passed at construction time, or None."""
        return self._parent

    def GetFirstChildControl(self):
        """Returns the first child added to self._children, or None."""
        return self._children[0] if self._children else None


def _link_siblings(children):
    """Wires up GetNextSiblingControl on each fake control in children so a
    caller can walk the list as a real sibling chain, ending in None.
    """
    for i, child in enumerate(children):
        child._next_sibling = children[i + 1] if i + 1 < len(children) else None

        def _get_next_sibling(self=child):
            """Returns this fake control's next sibling, or None if last."""
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
        """Redirects from header to large sibling body."""
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
        """No redirect when only small siblings exist."""
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
        """Does not redirect to a sibling above it."""
        # A large sibling ABOVE the focused control is not "the body under the
        # header" — must not redirect to it.
        parent = _FakeControl(rect=_FakeRect(0, 0, 500, 1000))
        big_sibling_above = _FakeControl(rect=_FakeRect(0, 0, 500, 900), parent=parent)
        header = _FakeControl(rect=_FakeRect(0, 900, 500, 966), parent=parent)
        parent._children = [big_sibling_above, header]
        _link_siblings(parent._children)

        result = rule_engine._find_larger_sibling_rect(header)
        self.assertIsNone(result)


class WholeWindowSearchTests(unittest.TestCase):
    """Real bug (2026-09-16), diagnosed with diagnose_zoom_tree.py: Zoom's main
    call window can leave the focused control on a toolbar button whose
    siblings are just other toolbar buttons — no larger sibling exists, but
    the real chat pane still isn't read, because it lives in a completely
    different branch of the tree (a cousin, not a sibling, several levels
    away). Also locks in a real risk found while designing the fix: a video
    gallery and a screen-share container are BOTH large enough in the real
    tree to be false positives, and the share container is even LARGER in raw
    area than the real chat pane — only requiring the candidate to be a true
    leaf (no children at all), matching exactly how Zoom draws real pixel-
    based chat content (unlike the gallery/share panes, which both have their
    own child elements), correctly excludes both."""

    def setUp(self):
        """Remembers the real auto.ControlFromHandle so tests can patch it
        with a fake tree and this can restore it afterward.
        """
        self._orig_control_from_handle = rule_engine.auto.ControlFromHandle

    def tearDown(self):
        """Restores the real auto.ControlFromHandle patched in setUp."""
        rule_engine.auto.ControlFromHandle = self._orig_control_from_handle

    def test_finds_the_leaf_pane_even_when_larger_non_leaf_panes_exist(self):
        """Finds the leaf pane even when larger non leaf panes exist."""
        root = _FakeControl(rect=_FakeRect(0, 0, 2000, 1000))

        video_gallery = _FakeControl(rect=_FakeRect(0, 0, 200, 900), parent=root)
        video_gallery._children = [_FakeControl(rect=_FakeRect(0, 0, 200, 150), parent=video_gallery)]

        # Largest raw area of any candidate here — but has a child (a nested,
        # unrelated small element), so it must be excluded despite the size.
        share_container = _FakeControl(rect=_FakeRect(200, 0, 1200, 900), parent=root)
        share_container._children = [_FakeControl(rect=_FakeRect(200, 0, 400, 50), parent=share_container)]

        # Smaller raw area than share_container, but a true leaf — this is
        # the one that must win.
        chat_body_leaf = _FakeControl(rect=_FakeRect(1200, 0, 1700, 900), parent=root)

        root._children = [video_gallery, share_container, chat_body_leaf]
        _link_siblings(root._children)
        _link_siblings(video_gallery._children)
        _link_siblings(share_container._children)

        rule_engine.auto.ControlFromHandle = lambda hwnd: root

        result = rule_engine._find_largest_leaf_pane_in_window(hwnd=12345)
        self.assertIs(result, chat_body_leaf.BoundingRectangle)

    def test_returns_none_when_nothing_qualifies(self):
        """Returns none when nothing qualifies."""
        root = _FakeControl(rect=_FakeRect(0, 0, 500, 500))
        small = _FakeControl(rect=_FakeRect(0, 0, 100, 100), parent=root)
        root._children = [small]
        _link_siblings(root._children)

        rule_engine.auto.ControlFromHandle = lambda hwnd: root

        result = rule_engine._find_largest_leaf_pane_in_window(hwnd=12345)
        self.assertIsNone(result)

    def test_rejects_a_leaf_that_spans_the_entire_window(self):
        """Rejects a leaf that spans the entire window."""
        # Real bug found live, 2026-09-17, confirmed with
        # diagnose_window_search.py against the actual live window: on a
        # Chrome/Claude.ai tab, this search picked a leaf spanning (0,0) to
        # the full window size — tab strip and bookmarks bar included —
        # because it had no UI-Automation children, while the real chat
        # content (which does have children) was excluded by the leaf-only
        # rule. The subsequent OCR crop then read the browser's own tab
        # strip/bookmarks bar (which happened to have Hebrew-named folders)
        # instead of the page, flipping the tab to Hebrew with nothing
        # Hebrew actually on screen. A candidate covering essentially the
        # whole window must never win — real content is always meaningfully
        # smaller than the window itself.
        root = _FakeControl(rect=_FakeRect(0, 0, 1920, 1079))

        # The exact real shape: a leaf with no children spanning (almost)
        # the entire window — must be rejected even though it's a true leaf
        # and easily the largest candidate by raw area.
        whole_window_leaf = _FakeControl(rect=_FakeRect(0, 0, 1920, 1079), parent=root)

        # Smaller than the whole-window leaf, but a real, meaningfully
        # bounded true leaf — this is the one that must win.
        real_content_leaf = _FakeControl(rect=_FakeRect(400, 180, 1900, 1000), parent=root)

        root._children = [whole_window_leaf, real_content_leaf]
        _link_siblings(root._children)

        rule_engine.auto.ControlFromHandle = lambda hwnd: root

        result = rule_engine._find_largest_leaf_pane_in_window(hwnd=12345)
        self.assertIs(result, real_content_leaf.BoundingRectangle)

    def test_still_returns_none_when_only_the_whole_window_leaf_qualifies(self):
        """Still returns none when only the whole window leaf qualifies."""
        root = _FakeControl(rect=_FakeRect(0, 0, 1920, 1079))
        whole_window_leaf = _FakeControl(rect=_FakeRect(0, 0, 1920, 1079), parent=root)
        root._children = [whole_window_leaf]
        _link_siblings(root._children)

        rule_engine.auto.ControlFromHandle = lambda hwnd: root

        result = rule_engine._find_largest_leaf_pane_in_window(hwnd=12345)
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
        """Clears google_docs_title_already_applied so no state leaks in
        from a previous test.
        """
        rule_engine.google_docs_title_already_applied.clear()

    def tearDown(self):
        """Clears google_docs_title_already_applied so no state leaks into
        the next test.
        """
        rule_engine.google_docs_title_already_applied.clear()

    @staticmethod
    def _fake_offscreen_doc_control():
        """Builds a fake control with the real off-screen, document-scroll-
        coordinate rect shape Google Docs is confirmed to report.
        """
        # Real captured shape: Google Docs reports its focused control's rect
        # in document-scroll coordinates, often far outside any real monitor.
        return _FakeControl(rect=_FakeRect(1076, -13318, 1921, -13292), name="")

    def test_first_read_uses_the_title_and_marks_it_applied(self):
        """First read uses the title and marks it applied."""
        hwnd = 12345
        title = "קורות חיים - לירן - Google Docs"
        with patch.object(rule_engine.win32gui, "GetForegroundWindow", return_value=hwnd), \
             patch.object(rule_engine.auto, "GetFocusedControl", return_value=self._fake_offscreen_doc_control()):
            hkl, reason = rule_engine.decide_with_content(hwnd, None, title, "chrome.exe", thread_id=999)

        self.assertEqual(hkl, rule_engine.Hebrew_HKL)
        self.assertEqual(reason["source"], "google_docs_title")
        self.assertIn(999, rule_engine.google_docs_title_already_applied)

    def test_second_read_same_visit_does_not_reassert(self):
        """Second read same visit does not reassert."""
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
        """New visit after title change gets a fresh read."""
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
        """Below minimum samples is not trusted."""
        self.assertIsNone(rule_engine._trust(["hebrew", "hebrew"]))

    def test_consistent_history_is_trusted(self):
        """Consistent history is trusted."""
        # 4/5 = 80% — exactly at TRUST_AGREEMENT_THRESHOLD.
        self.assertEqual(
            rule_engine._trust(["hebrew", "hebrew", "hebrew", "hebrew", "english"]), "hebrew")

    def test_inconsistent_history_is_not_trusted(self):
        """Inconsistent history is not trusted."""
        self.assertIsNone(
            rule_engine._trust(["hebrew", "english", "hebrew", "english"]))

    def test_history_of_normalizes_legacy_bare_string(self):
        """History of normalizes legacy bare string."""
        self.assertEqual(rule_engine._history_of("hebrew"), ["hebrew"])

    def test_history_of_normalizes_new_dict_shape(self):
        """History of normalizes new dict shape."""
        self.assertEqual(
            rule_engine._history_of({"history": ["hebrew", "english"]}),
            ["hebrew", "english"])

    def test_history_of_handles_missing_key(self):
        """History of handles missing key."""
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
        """Redirects decision_logger's log/screenshot paths to a fresh
        temp directory, so this test never touches the real log file.
        """
        self._tmp_dir = tempfile.mkdtemp()
        self._orig_logs_dir = decision_logger.LOGS_DIR
        self._orig_screenshots_dir = decision_logger.SCREENSHOTS_DIR
        self._orig_log_file = decision_logger.LOG_FILE
        decision_logger.LOGS_DIR = self._tmp_dir
        decision_logger.SCREENSHOTS_DIR = self._tmp_dir
        decision_logger.LOG_FILE = f"{self._tmp_dir}/decisions.jsonl"
        decision_logger._last_auto_decision.clear()

    def tearDown(self):
        """Restores decision_logger's real paths and deletes the temp
        directory created in setUp.
        """
        decision_logger.LOGS_DIR = self._orig_logs_dir
        decision_logger.SCREENSHOTS_DIR = self._orig_screenshots_dir
        decision_logger.LOG_FILE = self._orig_log_file
        decision_logger._last_auto_decision.clear()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def test_override_links_to_preceding_auto_decision(self):
        """Override links to preceding auto decision."""
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


class PollBackoffTests(unittest.TestCase):
    """Real bug found live, 2026-09-16: the untrusted poll re-ran a full
    Tesseract OCR read on whatever window was focused every ~1.5s, forever,
    even once it had already confirmed the identical answer many times in a
    row. Confirmed directly from a live 4+ hour run: one static Chrome tab
    got re-OCR'd nonstop, ~600ms per read, over 1,300 CPU-seconds total, with
    "no change" every single time. Fixed with per-(thread_id, title) backoff:
    _poll_apply_content_correction (the poll path's wrapper around
    apply_content_correction) tracks consecutive unchanged results and, past
    a threshold, makes that exact key ineligible for re-polling for a while."""

    def setUp(self):
        """Clears the backoff state dicts so no state leaks in from a
        previous test.
        """
        rule_engine.poll_unchanged_streak.clear()
        rule_engine.poll_next_allowed.clear()

    def tearDown(self):
        """Clears the backoff state dicts so no state leaks into the next
        test.
        """
        rule_engine.poll_unchanged_streak.clear()
        rule_engine.poll_next_allowed.clear()

    def test_repeated_unchanged_results_trigger_backoff(self):
        """Repeated unchanged results trigger backoff."""
        check_key = (999, "Static Page - Google Chrome")
        with patch.object(rule_engine, "apply_content_correction", return_value=False):
            for _ in range(rule_engine.POLL_BACKOFF_STREAK_THRESHOLD):
                rule_engine._poll_apply_content_correction(
                    12345, 999, "chrome.exe", rule_engine.English_HKL,
                    "Static Page - Google Chrome", check_key)

        self.assertEqual(
            rule_engine.poll_unchanged_streak[check_key],
            rule_engine.POLL_BACKOFF_STREAK_THRESHOLD)
        self.assertIn(check_key, rule_engine.poll_next_allowed)
        self.assertGreater(rule_engine.poll_next_allowed[check_key], time.time())

    def test_below_threshold_does_not_back_off_yet(self):
        """Below threshold does not back off yet."""
        check_key = (999, "Static Page - Google Chrome")
        with patch.object(rule_engine, "apply_content_correction", return_value=False):
            for _ in range(rule_engine.POLL_BACKOFF_STREAK_THRESHOLD - 1):
                rule_engine._poll_apply_content_correction(
                    12345, 999, "chrome.exe", rule_engine.English_HKL,
                    "Static Page - Google Chrome", check_key)

        self.assertNotIn(check_key, rule_engine.poll_next_allowed)

    def test_a_real_change_resets_any_existing_backoff(self):
        """A real change resets any existing backoff."""
        # Reproduces the WhatsApp-shape case this poll exists for: a window
        # backs off after settling, then its content genuinely changes with
        # no Windows event (the poll is the only thing that ever notices) —
        # that real change must immediately clear the backoff, not extend it.
        check_key = (999, "WhatsApp Business - Google Chrome")
        rule_engine.poll_unchanged_streak[check_key] = rule_engine.POLL_BACKOFF_STREAK_THRESHOLD
        rule_engine.poll_next_allowed[check_key] = time.time() + rule_engine.POLL_BACKOFF_SECONDS

        with patch.object(rule_engine, "apply_content_correction", return_value=True):
            rule_engine._poll_apply_content_correction(
                12345, 999, "chrome.exe", rule_engine.English_HKL,
                "WhatsApp Business - Google Chrome", check_key)

        self.assertNotIn(check_key, rule_engine.poll_unchanged_streak)
        self.assertNotIn(check_key, rule_engine.poll_next_allowed)


class ManualOverrideDetectionTests(unittest.TestCase):
    """Real bug found live, 2026-09-17 (the "ping-pong" complaint): manual
    override detection lived only inside on_focus_change, which only runs on
    a genuine Windows focus/title event. Switching the language yourself with
    Alt+Shift while staying in the exact same window (no title change) fires
    no such event, so the untrusted poll's very next Tier 3 check had no idea
    an override had just happened and could silently switch it right back —
    the only way to make CKILS notice was to alt-tab away and back, forcing a
    real event. Fixed by extracting detection into
    _detect_and_record_manual_override and calling it from both the event
    path (on_focus_change) and the poll path (_poll_focused_window)."""

    def setUp(self):
        """Clears the override-tracking state dicts so no state leaks in
        from a previous test.
        """
        rule_engine.last_set.clear()
        rule_engine.last_switch_time.clear()
        rule_engine.overridden.clear()
        rule_engine.pending_override.clear()
        rule_engine.matched_this_visit.clear()
        rule_engine.reassert_attempts.clear()

    def tearDown(self):
        """Clears the override-tracking state dicts so no state leaks into
        the next test.
        """
        rule_engine.last_set.clear()
        rule_engine.last_switch_time.clear()
        rule_engine.overridden.clear()
        rule_engine.pending_override.clear()
        rule_engine.matched_this_visit.clear()
        rule_engine.reassert_attempts.clear()

    def test_nothing_to_compare_against_is_not_an_override(self):
        """Nothing to compare against is not an override."""
        result = rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.Hebrew_HKL)
        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)

    def test_matching_actual_layout_is_not_an_override(self):
        """Matching actual layout is not an override."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        rule_engine.last_switch_time[999] = time.time() - 10
        result = rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.English_HKL)
        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)

    def test_does_not_misfire_right_after_our_own_switch(self):
        """Does not misfire right after our own switch."""
        # Within SWITCH_GRACE of CKILS's own last switch, a mismatch is just
        # the OS not having propagated it yet — not a real manual override.
        rule_engine.last_set[999] = rule_engine.English_HKL
        rule_engine.last_switch_time[999] = time.time()
        result = rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.Hebrew_HKL)
        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)

    def test_a_single_mismatch_is_not_yet_trusted(self):
        """A single mismatch is not yet trusted."""
        # Real regression found live, 2026-09-17, right after shipping the
        # fix above: PostMessage(WM_INPUTLANGCHANGEREQUEST) is fire-and-
        # forget, so a single mismatched read shortly after a slow Tier 3
        # correction can just be Windows not having caught up yet — not a
        # real manual override. Confirmed from the real overrides table: the
        # same Code.exe thread falsely "overrode" to Hebrew four times in one
        # session while the user was only typing. A single reading must NOT
        # commit to an override.
        rule_engine.last_set[999] = rule_engine.English_HKL
        rule_engine.last_switch_time[999] = time.time() - 10  # well past the switch grace
        rule_engine.matched_this_visit.add(999)  # a real change is only judged once the layout has matched this visit
        result = rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.Hebrew_HKL)

        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)
        self.assertIn(999, rule_engine.pending_override)  # noted, not yet trusted

    def test_a_mismatch_that_resolves_itself_is_never_trusted(self):
        """A mismatch that resolves itself is never trusted."""
        # The propagation-lag case: the first read catches Windows mid-way
        # through applying CKILS's own correction; by the next check it's
        # caught up and matches again. Must never become a committed override.
        rule_engine.last_set[999] = rule_engine.English_HKL
        rule_engine.last_switch_time[999] = time.time() - 10
        rule_engine.matched_this_visit.add(999)
        rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.Hebrew_HKL)

        result = rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.English_HKL)

        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)
        self.assertNotIn(999, rule_engine.pending_override)

    def test_the_same_mismatch_confirmed_twice_is_a_real_override(self):
        """The same mismatch confirmed twice is a real override."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        rule_engine.last_switch_time[999] = time.time() - 10
        rule_engine.matched_this_visit.add(999)
        rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.Hebrew_HKL)

        with patch.object(rule_engine, "log_override"), \
             patch.object(rule_engine, "save_learned_default"), \
             patch.object(rule_engine, "save_page_learned_default"), \
             patch.object(rule_engine.decision_logger, "log_manual_override"):
            result = rule_engine._detect_and_record_manual_override(999, "chrome.exe", "t", rule_engine.Hebrew_HKL)

        self.assertTrue(result)
        self.assertIn(999, rule_engine.overridden)
        self.assertEqual(rule_engine.last_set[999], rule_engine.Hebrew_HKL)
        self.assertNotIn(999, rule_engine.pending_override)

    def test_poll_loop_detects_a_silent_override_confirmed_over_two_ticks(self):
        """Poll loop detects a silent override confirmed over two ticks."""
        # Reproduces the exact real scenario: the user manually switches with
        # no focus/title event at all, then the SAME reading confirmed on a
        # second poll tick must record it as an override — a single tick
        # must not, and must still allow a normal correction attempt.
        rule_engine.last_set[999] = rule_engine.English_HKL
        rule_engine.last_switch_time[999] = time.time() - 10
        hwnd = 12345
        with patch.object(rule_engine.win32gui, "GetForegroundWindow", return_value=hwnd), \
             patch.object(rule_engine.win32gui, "GetWindowText", return_value="Some Title"), \
             patch.object(rule_engine.win32process, "GetWindowThreadProcessId", return_value=(999, 4321)), \
             patch.object(rule_engine.psutil, "Process") as mock_process, \
             patch.object(rule_engine.win32api, "GetKeyboardLayout",
                          side_effect=[rule_engine.English_HKL, rule_engine.Hebrew_HKL, rule_engine.Hebrew_HKL]), \
             patch.object(rule_engine, "log_override"), \
             patch.object(rule_engine, "save_learned_default"), \
             patch.object(rule_engine, "save_page_learned_default"), \
             patch.object(rule_engine.decision_logger, "log_manual_override"), \
             patch.object(rule_engine.threading, "Thread") as mock_thread, \
             patch.object(rule_engine.time, "sleep", side_effect=[None, None, None, StopIteration]):
            mock_process.return_value.name.return_value = "chrome.exe"
            with self.assertRaises(StopIteration):
                rule_engine._poll_focused_window()

        self.assertIn(999, rule_engine.overridden)
        # First tick was a normal (unconfirmed) reading and still queued a Tier 3
        # check; only the second, confirming tick should have skipped one.
        self.assertEqual(mock_thread.call_count, 1)


class CarryOverTests(unittest.TestCase):
    """Real bug found live, 2026-09-19 (and the true cause of the Sep 17 "false
    override"): Windows shares the input language across windows, so arriving
    in window B keeps the language CKILS just set in window A. CKILS compared
    that with its stale memory of B, called the mismatch a manual override,
    stopped correcting, and taught the wrong language into the learned
    defaults - while the user never switched anything by hand. Measured on the
    real log: 38 of 51 recorded "overrides" over three days equalled the
    language CKILS had last set in ANOTHER window. A real manual switch is a
    change that appears in a window whose layout CKILS has already SEEN match
    this visit; a mismatch present since arrival is carry-over.
    """

    def setUp(self):
        """Clears every piece of per-visit state and starts with no recorded posts."""
        for d in (rule_engine.last_set, rule_engine.last_switch_time, rule_engine.pending_override,
                  rule_engine.reassert_attempts):
            d.clear()
        rule_engine.overridden.clear()
        rule_engine.matched_this_visit.clear()
        self.posts = []
        self.learned = 0
        self.override_rows = 0

    tearDown = setUp

    def _seen(self, hkl, hwnd=12345):
        """Runs one detection with every side effect mocked, tallying posts/learning/override rows."""
        with patch.object(rule_engine.win32api, "PostMessage") as post, \
             patch.object(rule_engine, "log_override") as log_row, \
             patch.object(rule_engine, "save_learned_default") as learn_app, \
             patch.object(rule_engine, "save_page_learned_default") as learn_page, \
             patch.object(rule_engine.decision_logger, "log_manual_override"):
            result = rule_engine._detect_and_record_manual_override(999, "Code.exe", "t", hkl, hwnd)
        self.posts += post.call_args_list
        self.learned += learn_app.call_count + learn_page.call_count
        self.override_rows += log_row.call_count
        return result

    def _aged(self):
        """Marks CKILS's last post as long ago, so the switch-grace window doesn't hide the mismatch."""
        rule_engine.last_switch_time[999] = time.time() - 10

    def test_a_mismatch_present_since_arrival_is_not_an_override(self):
        """Never having matched this visit, a mismatch is carry-over: no override, no learning."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        self._aged()
        result = self._seen(rule_engine.Hebrew_HKL, hwnd=None)
        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)
        self.assertEqual((self.learned, self.override_rows), (0, 0))

    def test_repeating_the_same_carry_over_never_becomes_an_override(self):
        """The old two-checks rule was fooled by this; carry-over must stay carry-over however often seen."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        for _ in range(6):
            self._aged()
            self._seen(rule_engine.Hebrew_HKL, hwnd=None)
        self.assertNotIn(999, rule_engine.overridden)
        self.assertEqual((self.learned, self.override_rows), (0, 0))

    def test_reasserts_its_own_decision_when_it_decided_this_visit(self):
        """If CKILS posted a switch this visit, it re-posts that decision instead of backing off."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        self._aged()
        self._seen(rule_engine.Hebrew_HKL)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0].args[1:],
                         (rule_engine.win32con.WM_INPUTLANGCHANGEREQUEST, 0, rule_engine.English_HKL))
        self.assertEqual(rule_engine.reassert_attempts[999], 1)
        self.assertNotIn(999, rule_engine.overridden)

    def test_gives_up_after_the_limit_and_accepts_the_layout(self):
        """It never fights forever: after MAX_REASSERT_ATTEMPTS it adopts the layout Windows insists on, recording no override."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        for _ in range(rule_engine.MAX_REASSERT_ATTEMPTS + 1):
            self._aged()
            self._seen(rule_engine.Hebrew_HKL)
        self.assertEqual(len(self.posts), rule_engine.MAX_REASSERT_ATTEMPTS)
        self.assertEqual(rule_engine.last_set[999], rule_engine.Hebrew_HKL)
        self.assertIn(999, rule_engine.matched_this_visit)
        self.assertNotIn(999, rule_engine.overridden)
        self.assertEqual((self.learned, self.override_rows), (0, 0))

    def test_a_window_where_ckils_decided_nothing_is_never_pushed_to_a_stale_language(self):
        """With no decision this visit, last_set is stale memory: adopt the real layout, post nothing."""
        rule_engine.last_set[999] = rule_engine.English_HKL  # stale; no last_switch_time this visit
        self._seen(rule_engine.Hebrew_HKL)
        self.assertEqual(self.posts, [])
        self.assertEqual(rule_engine.last_set[999], rule_engine.Hebrew_HKL)
        self.assertNotIn(999, rule_engine.overridden)

    def test_a_change_after_a_match_is_still_a_real_override_and_teaches(self):
        """The genuine case still works: layout seen matching, then changed and confirmed twice."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        self._aged()
        self._seen(rule_engine.English_HKL)   # matches -> this visit is now settled
        self._seen(rule_engine.Hebrew_HKL)    # first sighting of the change
        result = self._seen(rule_engine.Hebrew_HKL)  # confirmed
        self.assertTrue(result)
        self.assertIn(999, rule_engine.overridden)
        self.assertEqual(self.override_rows, 1)
        self.assertGreaterEqual(self.learned, 1)

    def test_after_accepting_the_layout_a_later_change_is_treated_as_real(self):
        """Once the baseline is adopted, a subsequent change (the user's) is judged normally."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        self._seen(rule_engine.Hebrew_HKL)             # undecided window: accepted silently
        self._seen(rule_engine.English_HKL)            # first sighting of a change
        result = self._seen(rule_engine.English_HKL)   # confirmed
        self.assertTrue(result)

    def test_the_real_incident_sequence_produces_no_override(self):
        """Replays 12:52 exactly: VS Code entered with Hebrew carried over; CKILS re-asserts, then Windows follows."""
        rule_engine.last_set[999] = rule_engine.English_HKL
        self._aged()
        self._seen(rule_engine.Hebrew_HKL)  # tick 1: carry-over, re-assert #1
        self._aged()
        self._seen(rule_engine.Hebrew_HKL)  # tick 2: still carried over, re-assert #2
        self._aged()
        result = self._seen(rule_engine.English_HKL)  # tick 3: Windows finally follows
        self.assertFalse(result)
        self.assertNotIn(999, rule_engine.overridden)
        self.assertIn(999, rule_engine.matched_this_visit)
        self.assertEqual((self.learned, self.override_rows), (0, 0))

    def test_leaving_a_window_ends_the_visit(self):
        """_reset_visit_state clears the matched flag, re-assert count, pending mismatch and last post time."""
        rule_engine.matched_this_visit.add(999)
        rule_engine.reassert_attempts[999] = 2
        rule_engine.pending_override[999] = (rule_engine.Hebrew_HKL, time.time())
        rule_engine.last_switch_time[999] = time.time()
        rule_engine._reset_visit_state(999)
        self.assertNotIn(999, rule_engine.matched_this_visit)
        self.assertNotIn(999, rule_engine.reassert_attempts)
        self.assertNotIn(999, rule_engine.pending_override)
        self.assertNotIn(999, rule_engine.last_switch_time)


class SkipLoggerTests(unittest.TestCase):
    """Guards skip_logger.py's design guarantees, each of which exists to
    prevent a specific bug named in the plan: it must never raise, never
    block, never flood, and stay inert until started. Nothing here touches
    the real ckils_skips.db — the writer tests use a temp directory.
    """

    def setUp(self):
        """Resets the module's in-memory state so tests can't affect each other."""
        skip_logger._last_logged.clear()
        skip_logger._recent_stamps.clear()
        while not skip_logger._queue.empty():
            skip_logger._queue.get_nowait()
        skip_logger._disabled_reason = None
        skip_logger._started = False

    def tearDown(self):
        """Leaves the module clean for whatever runs next."""
        self.setUp()

    def test_queues_a_row_with_the_reason(self):
        """A skip becomes exactly one queued row carrying the reason code."""
        skip_logger.log_skip("chrome.exe", "New chat", 7, skip_logger.REASON_EMPTY_FIELD, "ocr")
        self.assertEqual(skip_logger._queue.qsize(), 1)
        row = skip_logger._queue.get_nowait()
        self.assertEqual(row[1:], ("chrome.exe", "New chat", 7, "empty_field", "ocr"))

    def test_same_window_and_reason_is_logged_once(self):
        """Repeats of the same (window, title, reason) inside the dedupe window are dropped."""
        for _ in range(10):
            skip_logger.log_skip("chrome.exe", "New chat", 7, skip_logger.REASON_EMPTY_FIELD)
        self.assertEqual(skip_logger._queue.qsize(), 1)

    def test_a_different_reason_is_still_logged(self):
        """De-duplication is per reason, so a new kind of failure is never hidden."""
        skip_logger.log_skip("chrome.exe", "New chat", 7, skip_logger.REASON_EMPTY_FIELD)
        skip_logger.log_skip("chrome.exe", "New chat", 7, skip_logger.REASON_REJECTED_NOISE)
        self.assertEqual(skip_logger._queue.qsize(), 2)

    def test_hourly_cap_stops_a_flood_of_volatile_titles(self):
        """Titles that change constantly (unread counters) can't produce unbounded rows."""
        with patch.object(skip_logger, "MAX_ROWS_PER_HOUR", 5):
            for i in range(50):
                skip_logger.log_skip("whatsapp.exe", f"({i}) WhatsApp", 7, skip_logger.REASON_EMPTY_FIELD)
        self.assertEqual(skip_logger._queue.qsize(), 5)

    def test_detail_is_truncated_for_privacy(self):
        """Only the first MAX_DETAIL_CHARS characters of rejected text are ever kept."""
        skip_logger.log_skip("a.exe", "t", 1, skip_logger.REASON_REJECTED_NOISE, "x" * 500)
        self.assertEqual(len(skip_logger._queue.get_nowait()[5]), skip_logger.MAX_DETAIL_CHARS)

    def test_a_full_queue_drops_instead_of_blocking_or_raising(self):
        """If the writer falls behind, the correction thread must never wait or fail."""
        with patch.object(skip_logger, "_queue", queue.Queue(maxsize=1)):
            skip_logger.log_skip("a.exe", "t1", 1, skip_logger.REASON_EMPTY_FIELD)
            skip_logger.log_skip("a.exe", "t2", 1, skip_logger.REASON_EMPTY_FIELD)

    def test_never_raises_on_hostile_input(self):
        """Even a detail whose str() explodes must not escape log_skip."""
        class Boom:
            """An object whose string conversion always raises."""
            def __str__(self):
                raise RuntimeError("boom")
        skip_logger.log_skip(None, None, None, skip_logger.REASON_READ_FAILED, Boom())

    def test_disabled_logger_records_nothing(self):
        """Once disabled (circuit breaker or kill switch) log_skip is a no-op."""
        skip_logger._disabled_reason = "test"
        skip_logger.log_skip("a.exe", "t", 1, skip_logger.REASON_EMPTY_FIELD)
        self.assertEqual(skip_logger._queue.qsize(), 0)

    def test_kill_switch_file_prevents_start(self):
        """Creating skip_logging.off next to the exe keeps the writer from ever starting."""
        tmp = tempfile.mkdtemp()
        try:
            switch = os.path.join(tmp, "skip_logging.off")
            open(switch, "w").close()
            with patch.object(skip_logger, "KILL_SWITCH_PATH", switch), \
                 patch.object(skip_logger.threading, "Thread") as mock_thread:
                skip_logger.start()
            mock_thread.assert_not_called()
            self.assertIsNotNone(skip_logger._disabled_reason)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_logging_alone_starts_no_writer(self):
        """Without start(), log_skip only queues in memory: no thread, no file."""
        skip_logger.log_skip("a.exe", "t", 1, skip_logger.REASON_EMPTY_FIELD)
        self.assertFalse(skip_logger._started)

    def test_writer_persists_rows_to_its_own_database(self):
        """End to end: start() -> log_skip() -> a real row in the temp database."""
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, "skips.db")
        try:
            with patch.object(skip_logger, "DB_FILE", db), \
                 patch.object(skip_logger, "KILL_SWITCH_PATH", os.path.join(tmp, "absent.off")):
                skip_logger.start()
                skip_logger.log_skip("chrome.exe", "New chat", 7, skip_logger.REASON_EMPTY_FIELD)
                rows = []
                for _ in range(50):
                    time.sleep(0.1)
                    if os.path.exists(db):
                        conn = sqlite3.connect(db)
                        rows = conn.execute("SELECT exe_name, reason FROM skipped_reads").fetchall()
                        conn.close()
                        if rows:
                            break
                skip_logger._queue.put(None)  # stop the writer before the temp dir vanishes
                time.sleep(0.3)
            self.assertEqual(rows, [("chrome.exe", "empty_field")])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_writer_disables_itself_after_repeated_failures(self):
        """The circuit breaker: after WRITER_FAILURE_LIMIT consecutive failures it stops, quietly."""
        tmp = tempfile.mkdtemp()
        real_connect = sqlite3.connect
        calls = {"n": 0}

        def flaky_connect(*args, **kwargs):
            """Succeeds once (for table creation), then always fails."""
            calls["n"] += 1
            if calls["n"] == 1:
                return real_connect(os.path.join(tmp, "skips.db"))
            raise sqlite3.OperationalError("disk full")

        try:
            for i in range(skip_logger.WRITER_FAILURE_LIMIT):
                skip_logger._queue.put(("t", "a.exe", "t", i, "empty_field", None))
            with patch.object(skip_logger.sqlite3, "connect", flaky_connect):
                skip_logger._writer_loop()
            self.assertIn("consecutive write failures", skip_logger._disabled_reason)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SkipWiringTests(unittest.TestCase):
    """Proves the log_skip() calls added to decide_with_content report the
    right reason WITHOUT changing what it returns — the property that keeps
    this whole feature from altering any language decision.
    """

    def _run(self, control, read_text="", foreground_matches=True):
        """Runs decide_with_content on fakes and returns (result, reasons logged)."""
        hwnd = 12345
        fg = hwnd if foreground_matches else 99999
        with patch.object(rule_engine.win32gui, "GetForegroundWindow", return_value=fg), \
             patch.object(rule_engine.auto, "GetFocusedControl", return_value=control), \
             patch.object(rule_engine, "read_region", return_value=read_text), \
             patch.object(rule_engine, "log_decision"), \
             patch.object(rule_engine.skip_logger, "log_skip") as mock_log:
            result = rule_engine.decide_with_content(
                hwnd, rule_engine.English_HKL, "Some Page - Google Chrome", "chrome.exe", 7)
        return result, [c.args[3] for c in mock_log.call_args_list]

    def test_empty_read_logs_empty_field_and_changes_nothing(self):
        """An empty compose box: reason empty_field, and the fallback is returned untouched."""
        control = _FakeControl(rect=_FakeRect(100, 100, 600, 160), name="")
        result, reasons = self._run(control, read_text="")
        self.assertEqual(result, (rule_engine.English_HKL, None))
        self.assertEqual(reasons, ["empty_field"])

    def test_placeholder_logs_rejected_noise_and_changes_nothing(self):
        """A recognised placeholder: reason rejected_noise, fallback returned untouched."""
        control = _FakeControl(rect=_FakeRect(100, 100, 600, 160), name="")
        result, reasons = self._run(control, read_text="Write a message...")
        self.assertEqual(result, (rule_engine.English_HKL, None))
        self.assertEqual(reasons, ["rejected_noise"])

    def test_off_screen_control_logs_off_screen(self):
        """A control rect outside every monitor: reason off_screen, fallback returned."""
        control = _FakeControl(rect=_FakeRect(1076, -13318, 1921, -13292), name="")
        result, reasons = self._run(control)
        self.assertEqual(result, (rule_engine.English_HKL, None))
        self.assertEqual(reasons, ["off_screen"])

    def test_focus_moved_logs_focus_moved(self):
        """Losing focus before the read: reason focus_moved, fallback returned."""
        control = _FakeControl(rect=_FakeRect(100, 100, 600, 160), name="")
        result, reasons = self._run(control, foreground_matches=False)
        self.assertEqual(result, (rule_engine.English_HKL, None))
        self.assertEqual(reasons, ["focus_moved"])

    def test_a_real_read_logs_no_skip(self):
        """A normal confident read is a decision, not a skip: nothing is logged here."""
        control = _FakeControl(rect=_FakeRect(100, 100, 600, 160), name="")
        result, reasons = self._run(control, read_text="This is a normal English sentence about the project")
        self.assertEqual(result[0], rule_engine.English_HKL)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
