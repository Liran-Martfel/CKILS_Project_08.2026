import ctypes, ctypes.wintypes
import win32.lib.win32con
import win32api, win32con, win32gui, win32process, psutil
import time
import threading
import json
import os
import sys
import sqlite3
import datetime
import re
import uiautomation as auto
from ocr_reader import read_region
from predict_language import predict_language
import decision_logger

# Set to False for a quiet, end-user-facing run — True prints a line for every
# focus change and every content-layer check, useful while developing/debugging.
DEBUG = True

# Real bug found live: in the packaged .exe, __file__ resolves inside a TEMPORARY
# extraction folder that PyInstaller deletes when the process exits — fine for
# reading bundled read-only files (tessdata, the model), but anything written
# there using that path silently vanishes on close. Files meant to persist
# across runs (learned_defaults.json, page_learned_defaults.json, the decisions
# database) need the exe's own real, permanent folder instead.
def _persistent_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))
# ================================================================================
# CKILS rule_engine.py — Legend (short)
# ================================================================================
#
# hwnd        "Handle to a WiNDow" — an ID number, not the window itself.
# hkl         "Handle to a Keyboard Layout" — an ID for one installed layout.
# pid         "Process ID" — a number identifying one running program.
# thread_id   Layout is tracked PER THREAD, not per window — why some calls
#             need this instead of a hwnd, identifies one thread of execution inside a process.
#
# user32.dll — the core Windows file handling windows/input/
#             keyboard layouts. Used via ctypes here specifically because
#             SetWinEventHook has no pywin32 wrapper — ctypes calls straight
#             into the DLL for just that one function.
#
# ctypes            Python's bridge to raw Windows DLL functions.
# WinEventProcType  Describes your callback's exact shape (# of args, types)
#                   so Windows (written in C) knows how to call it.
# callback          on_focus_change, wrapped in that shape. Kept in a
#                   variable so it isn't garbage-collected while active.
# hook              Your active SetWinEventHook registration.
#
# learned_defaults  exe_name -> "english"/"hebrew", written by the program itself
#                   whenever Tier 3 confidently decides a window's language —
#                   never hand-written. This is the instant first guess for a
#                   brand-new, still-empty window of that app; genuinely AI-driven,
#                   not a human-authored assumption about what an app "should" be.
# exe_name          Focused app's file name — the learned_defaults dict key.
# title             Focused window's title-bar text — used only for debug output
#                   now; Tier 3's per-window content decision replaced the old
#                   per-title keyword matching entirely.
# target_hkl        The instant first guess for this event — the current
#                   content_decision for this window if one exists yet, else
#                   whatever's in learned_defaults for this app, else None.
# actual_hkl        What the layout ACTUALLY is right now — compared against
#                   last_set to catch a manual override.
#
# last_set          {hwnd: hkl} — what we last set (or the user last chose).
# last_switch_time  {hwnd: time} — when we last switched, for the grace check.
# SWITCH_GRACE      Brief window after our own switch where a mismatch is
#                   ignored (our own change may not have propagated yet).
# overridden        Set of hwnds currently in "leave it alone" mode.
# previous_hwnd     Window focused just before this event — used to detect
#                   "focus just left a window," which resets its override.
# elapsed_ms        How long PostMessage took, via time.perf_counter().
#
# EVENT_SYSTEM_FOREGROUND    "A different window just got focus."
# WM_INPUTLANGCHANGEREQUEST  Same message Windows sends on Alt+Shift.
# WINEVENT_OUTOFCONTEXT      Run the callback safely in our own process.
# ================================================================================

English_HKL = 0x04090409
Hebrew_HKL  = -0xfc2fbf3
LANGUAGE_NAME_TO_HKL = {"english": English_HKL, "hebrew": Hebrew_HKL}
HKL_TO_LANGUAGE_NAME = {v: k for k, v in LANGUAGE_NAME_TO_HKL.items()}

# No hand-written per-app assumptions anymore — this file is a small memory the
# program builds up itself, only ever written by a confident Tier 3 decision
# (see apply_content_correction below). It's the instant first guess for a
# brand-new, still-empty window of an app CKILS has seen decide confidently
# before; a genuinely new app just gets no instant guess until Tier 3 has
# actually read real content from it at least once.
LEARNED_DEFAULTS_FILE = os.path.join(_persistent_dir(), "learned_defaults.json")
learned_defaults_lock = threading.Lock()  # multiple correction threads could write this file at once


def load_learned_defaults():
    if not os.path.exists(LEARNED_DEFAULTS_FILE):
        return {}
    with open(LEARNED_DEFAULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_learned_default(exe_name, language_name):
    with learned_defaults_lock:
        history = _history_of(learned_defaults.get(exe_name))
        history.append(language_name)
        learned_defaults[exe_name] = {"history": history[-TRUST_HISTORY_LENGTH:]}
        with open(LEARNED_DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(learned_defaults, f, ensure_ascii=False, indent=2)


learned_defaults = load_learned_defaults()

# Per-app memory alone is nearly useless for a browser (chrome.exe hosts wildly
# different sites in wildly different languages). This is the more precise
# layer: remembers a learned language per (app, exact window title) — "this
# Gmail inbox is Hebrew," "this Google Doc is Hebrew" — individually, still
# entirely self-taught from real confident Tier 3 decisions, never hand-written.
# Real, honest limitation: apps with volatile titles (an unread-count badge that
# changes every message, e.g. Telegram) build up many near-duplicate entries
# instead of one reusable one — harmless, just less effective for those apps.
PAGE_LEARNED_DEFAULTS_FILE = os.path.join(_persistent_dir(), "page_learned_defaults.json")
page_learned_defaults_lock = threading.Lock()


def _page_key(exe_name, title):
    return f"{exe_name}||{title}"


def load_page_learned_defaults():
    if not os.path.exists(PAGE_LEARNED_DEFAULTS_FILE):
        return {}
    with open(PAGE_LEARNED_DEFAULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_page_learned_default(exe_name, title, language_name):
    with page_learned_defaults_lock:
        key = _page_key(exe_name, title)
        history = _history_of(page_learned_defaults.get(key))
        history.append(language_name)
        page_learned_defaults[key] = {"history": history[-TRUST_HISTORY_LENGTH:]}
        with open(PAGE_LEARNED_DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(page_learned_defaults, f, ensure_ascii=False, indent=2)


# A real database logging every content decision CKILS makes, for the monthly
# review-assisted retrain discussed with the user: NOT auto-retrained blindly
# (that would just teach the model to repeat its own mistakes — confirmed by
# real testing, e.g. the PDF-viewer message was confidently "correct" before
# it was found to be wrong). Instead this just captures everything; a separate
# script (review_decisions.py) picks out the entries actually worth a human's
# 30 seconds — low/borderline confidence, or followed shortly by a manual
# override — for a quick confirm/correct pass, same style as collect_data.py.
DECISIONS_DB_FILE = os.path.join(_persistent_dir(), "ckils_decisions.db")
decisions_db_lock = threading.Lock()


def init_decisions_db():
    with decisions_db_lock:
        conn = sqlite3.connect(DECISIONS_DB_FILE)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                exe_name TEXT NOT NULL,
                title TEXT,
                thread_id INTEGER,
                source TEXT,
                text TEXT,
                predicted_label TEXT,
                confidence REAL,
                applied INTEGER,
                reviewed INTEGER DEFAULT 0,
                confirmed_label TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                exe_name TEXT NOT NULL,
                title TEXT,
                thread_id INTEGER,
                overridden_to_hkl INTEGER
            )
        """)
        conn.commit()
        conn.close()


def _run_logged_write(sql, params):
    # Real bug found live: a 0-byte/corrupted db file (from the exe being force-
    # killed mid-write during earlier testing) raised "no such table", and since
    # nothing caught it, it crashed the entire background correction thread —
    # meaning NO corrections applied at all, not just logging failing quietly.
    # This must never be able to break the actual switching logic, so: try once,
    # self-heal the schema and retry once on failure, then give up quietly.
    try:
        with decisions_db_lock:
            conn = sqlite3.connect(DECISIONS_DB_FILE)
            conn.execute(sql, params)
            conn.commit()
            conn.close()
    except Exception as e:
        if DEBUG:
            print(f"  [content] decisions db write failed, healing schema and retrying ({e})")
        try:
            init_decisions_db()
            with decisions_db_lock:
                conn = sqlite3.connect(DECISIONS_DB_FILE)
                conn.execute(sql, params)
                conn.commit()
                conn.close()
        except Exception as e2:
            if DEBUG:
                print(f"  [content] decisions db write still failing, giving up for this entry ({e2})")


def log_decision(exe_name, title, thread_id, source, text, predicted_label, confidence, applied):
    _run_logged_write(
        "INSERT INTO decisions (timestamp, exe_name, title, thread_id, source, text, predicted_label, confidence, applied) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.datetime.now().isoformat(), exe_name, title, thread_id, source, text,
         predicted_label, confidence, int(applied))
    )


def log_override(exe_name, title, thread_id, overridden_to_hkl):
    _run_logged_write(
        "INSERT INTO overrides (timestamp, exe_name, title, thread_id, overridden_to_hkl) VALUES (?, ?, ?, ?, ?)",
        (datetime.datetime.now().isoformat(), exe_name, title, thread_id, overridden_to_hkl)
    )


init_decisions_db()


page_learned_defaults = load_page_learned_defaults()

last_set = {}          # hwnd -> HKL we last set (or the user's manual choice) for that window
last_switch_time = {}  # hwnd -> time.time() of our last switch attempt
overridden = set()     # hwnd the user manually overrode, not yet reset
SWITCH_GRACE = 0.3     # seconds to ignore mismatches right after we switch

# Real bug found live: once Tier 3 corrected a window's language, the very next
# focus/title event for that SAME window re-applied the raw learned default and
# undid the correction — the fast path had no memory that content already
# decided this window. This makes a confident content decision "stick" for as
# long as you stay in that window; it resets to the learned default the moment
# you leave and return.
content_decision = {}  # thread_id -> the last confident Tier 3 decision, if any

# Real bug found live: Google Docs' body text is a confirmed dead end to read
# (see _google_docs_title_text below) — the ONLY signal decide_with_content can
# use there is the document's own title, which never changes for the whole
# visit. But it was being re-derived and re-applied EVERY time Tier 3 ran
# (every focus/title event, plus the poll thread every 3 seconds) as if it
# were live, time-varying content — repeatedly force-reasserting the same
# static guess with zero new information each time, capable of overriding
# real mid-typing work (e.g. an English term inside an otherwise-Hebrew
# document) the moment ANY brief, unrelated focus event reset the manual-
# override protection. Fixed by treating a title-derived read as a genuine
# one-time default for this visit, same spirit as the learned-defaults
# layers — not something Tier 3 keeps re-asserting once already answered.
google_docs_title_already_applied = set()  # thread_ids already given their one title-derived read this visit

# Real bug found live: Chrome shares ONE thread_id across every tab in the same
# window — confirmed directly (hwnd=197900 thread=18984 identical across Google
# Docs, Gemini, and multiple PDF tabs in the same log). Without this, a content
# decision made on one tab was leaking straight into every other tab sharing
# that thread — the actual cause of Google Docs looking like "a coin flip."
last_title_by_thread = {}  # thread_id -> last-seen window title

# Real bug found live: some apps fire EVENT_OBJECT_NAMECHANGE repeatedly for the
# same window in quick succession (e.g. while a page is still loading). Each one
# used to spawn its own background correction thread, and multiple could race on
# the same thread_id's last_set — one thread's stale result landing after
# another's made it look like a manual override that never actually happened.
# This tracks which thread_ids already have a correction in flight, so a new
# NAMECHANGE event skips spawning a redundant, racing one.
content_check_in_progress = set()

# Tier 3 (Week 5): refines — or, for an app with no learned default yet, supplies — the switch decision
# using the actual on-screen text, via UI Automation + OCR + the model trained in 5.4.
CONTENT_CONFIDENCE_THRESHOLD = 0.65
LANGUAGE_TO_HKL = {"english": English_HKL, "hebrew": Hebrew_HKL}


# Latency scales with how much text there is to recognize, not raw pixel area —
# measured 6805ms on a full 1920x1080 dense pane vs 523ms capped to 300x100.
# Capping keeps this closer to Tesseract's own ~500-650ms floor instead of scaling
# unboundedly with a large code editor or webpage.
MAX_OCR_WIDTH = 400
MAX_OCR_HEIGHT = 150

# Real finding from diagnose_focus.py: some apps (confirmed: Google Chat) expose
# the actual visible text directly through the control's accessible Name — e.g.
# a whole real message, not a generic label. Using that is faster than OCR and
# immune to the off-screen problem below. Reject short Names (e.g. Google Docs'
# own "תוכן מסמך" is just its generic role label, not real content) so this
# doesn't get used for apps where Name isn't actually the content.
MIN_ACCESSIBLE_TEXT_LENGTH = 20

# Real finding from diagnose_focus.py: some apps (confirmed: Google Docs) report
# the focused control's rectangle in the *document's own scroll coordinates*,
# not real screen pixels — after scrolling, this can land far outside any
# monitor (e.g. top=-13318) and OCR there is a guaranteed-blank capture every
# time. This is the actual virtual desktop's real bounds, across all monitors.
SCREEN_LEFT = win32api.GetSystemMetrics(76)    # SM_XVIRTUALSCREEN
SCREEN_TOP = win32api.GetSystemMetrics(77)     # SM_YVIRTUALSCREEN
SCREEN_RIGHT = SCREEN_LEFT + win32api.GetSystemMetrics(78)   # + SM_CXVIRTUALSCREEN
SCREEN_BOTTOM = SCREEN_TOP + win32api.GetSystemMetrics(79)   # + SM_CYVIRTUALSCREEN


def _is_onscreen(rect):
    return (rect.right > SCREEN_LEFT and rect.left < SCREEN_RIGHT
            and rect.bottom > SCREEN_TOP and rect.top < SCREEN_BOTTOM)


# Real finding: hand-naming specific apps as "too coarse to trust" (a browser
# hosting wildly different pages, e.g.) or "title can't identify the real
# page" (WhatsApp, Zoom, ...) is itself a hand-authored assumption — it won't
# generalize to an app nobody's named yet, or to this code running on a
# different computer with different apps installed. Replaced with a mechanism
# that measures trustworthiness from CKILS's own observed history for that
# exact key (app-level or page-level) — no app name anywhere in this file.
#
# TRUST_HISTORY_LENGTH: how many of the most recent confident decisions (Tier
# 3 reads AND manual overrides — see on_focus_change) are kept per key.
# TRUST_MIN_SAMPLES: fewer than this many observations isn't enough evidence
# either way — same as "no default yet" today.
# TRUST_AGREEMENT_THRESHOLD: the smallest round fraction that means "near-
# unanimous" (7/8, 4/5) rather than a bare majority, so one stray wrong
# reading can't flip a key that's otherwise been consistent.
#
# Checked against the user's real accumulated page_learned_defaults.json:
# most keys have only ever been decided once, so requiring 3 before trusting
# doesn't regress a typical single-visit app once it's had a couple more
# confident reads — and a key that's genuinely inconsistent (a browser's
# whole-app guess, WhatsApp/Zoom's one shared title) naturally never clears
# 80% agreement, so it's excluded automatically, with nothing hand-named.
TRUST_HISTORY_LENGTH = 8
TRUST_MIN_SAMPLES = 3
TRUST_AGREEMENT_THRESHOLD = 0.8


def _history_of(value):
    # Back-compat: every key in the user's real, already-accumulated JSON
    # files today is a bare string ("chrome.exe": "hebrew") — the single most
    # recent decision, no history. Treating that as a 1-length history means
    # it starts below TRUST_MIN_SAMPLES (not yet trusted) rather than being
    # instantly re-trusted from a possibly-already-wrong single old value —
    # deliberate: the point of this change is to stop trusting exactly the
    # kind of contaminated single guesses this session found (WhatsApp,
    # Zoom, chrome.exe's coarse default), not to preserve them.
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.get("history", []))
    return [value]


def _trust(history):
    if len(history) < TRUST_MIN_SAMPLES:
        return None
    hebrew_count = history.count("hebrew")
    english_count = history.count("english")
    majority_count = max(hebrew_count, english_count)
    if majority_count / len(history) >= TRUST_AGREEMENT_THRESHOLD:
        return "hebrew" if hebrew_count > english_count else "english"
    return None


# Real finding: Chrome's own PDF viewer exposes a generic status message
# through the control's Name - "מסמך ה-PDF מכיל N דפים" ("This PDF document
# contains N pages") - completely unrelated to the actual PDF's content, but
# long enough and Hebrew enough to fool the accessible-text shortcut into
# classifying EVERY PDF as Hebrew regardless of what's actually in it.
GENERIC_ACCESSIBLE_TEXT_MARKERS = ["מכיל", "דפים"]

# Real finding: WhatsApp's own empty-compose-box placeholder — "Type a message"
# with or without a trailing "to <contact name>" — is always in English
# regardless of what language the actual conversation is in, but reached the
# classifier as if it were real content, confidently and wrongly forcing
# English on Hebrew conversations every time the box was empty. Same category
# as the PDF-viewer boilerplate above: UI chrome, not something a person
# actually typed. Zoom's own product-branding text ("zoom. Workplace ...")
# read the same way, every single call, real content or not — same fix.
# Real finding, confirmed from the decisions log: Claude.ai's own empty
# compose-box placeholder ("Write your prompt to Claude") hit this exact gap
# too — read as confident, real English content dozens of times over one
# genuinely Hebrew conversation, each one silently feeding that page's
# learned-default history another false "english" data point. That poisoned
# history is what kept overriding the real (Hebrew) content via the fast path
# faster than Tier 3 could correct it — not a flaw in the trust mechanism
# itself, just contaminated input reaching it in the first place.
# Real finding, same day: Claude.ai has a SECOND, differently-worded empty-box
# placeholder — "Write a message..." — shown once you're continuing an
# existing conversation, as opposed to "Write your prompt to Claude" on a
# brand-new chat. Neither prefix matches the other, so this one slipped
# through via OCR (accessible_text wasn't even involved this time) and kept
# flipping a real Hebrew CV conversation back to English every time the box
# went empty, confirmed live in logs/decisions.jsonl.
PLACEHOLDER_TEXT_PREFIXES = ["Type a message", "Write your prompt to Claude", "Write a message"]
# Real finding, from auditing every manual override on record: TradingView's
# own site tagline ("גרפי מניות, מדדים, חוזים עתידיים, מט"ח וביטקוין בזמן-אמת
# ב-TradingView" — "Real-time stock charts, indices, futures, forex, and
# Bitcoin on TradingView") is exposed as accessible text regardless of what
# ticker is actually on screen, always in Hebrew, and kept forcing Hebrew over
# real English ticker symbols (NVDA, QQQ, XAUUSD, ...) 10 times in the log.
# Same category as Zoom's "Workplace" branding text above — fixed marketing
# copy, not something a person is reading or typing.
UI_CHROME_MARKERS = ["Workplace", "וביטקוין בזמן-אמת ב-TradingView"]

# Real finding: on a Hebrew-titled YouTube video, OCR repeatedly read nothing
# but YouTube's own logo/wordmark — always English, regardless of the video's
# real language — with stray OCR artifacts around it ('> YouTube', 'YouTube"'
# with a smart quote). This kept winning and forcing English back over real
# Hebrew content nearby. Matched precisely (not a bare "YouTube" substring
# check) so a real comment or title that happens to mention YouTube by name
# isn't wrongly rejected too — only the logo-only read is.
YOUTUBE_LOGO_ONLY_PATTERN = re.compile(r"^[>\s]*YouTube[\"“”']*$")


def _rejected_as_ui_noise(text):
    """Applied to whatever text was FINALLY selected, regardless of source
    (unlike _looks_like_real_content, which only guards the accessible-text
    path) — see the real findings above for why OCR needs the same checks.
    Returns a short reason string if text should be rejected, else None."""
    if any(marker in text for marker in UI_CHROME_MARKERS):
        return "app UI chrome"
    if any(text.startswith(prefix) for prefix in PLACEHOLDER_TEXT_PREFIXES):
        return "an empty-field placeholder"
    if YOUTUBE_LOGO_ONLY_PATTERN.match(text.strip()):
        return "YouTube's own logo/wordmark, not real content"
    return None

# Real finding: clicking Gemini's "New chat" button (שיחה חדשה) briefly put
# focus on the BUTTON itself, whose Name was "New chat" plus its keyboard-
# shortcut hint ("Ctrl+Shift+O") — never something a person would actually
# type, but long/mixed enough to reach the classifier and score a shaky,
# meaningless confidence. Reject any accessible text carrying a shortcut hint.
SHORTCUT_HINT_PATTERN = re.compile(r"(Ctrl|Alt|Shift|Cmd)\s*\+\s*(Ctrl|Alt|Shift|Cmd)?", re.IGNORECASE)

# Real finding: clicking directly into a WhatsApp Web message bubble DOES
# correctly focus that message (confirmed live: fixed the "wrong pane read
# entirely" problem) — but its accessible Name glues the real message text
# together with English UI metadata on both ends: a "You: " sender prefix,
# and a trailing "HH:MM Delivered/Read/Sent Open message options ..." status/
# action footer, e.g. (shape preserved, wording changed from the real live
# capture) 'You: בטח אחי נדבר מחר על התוכנית 16:36 Delivered Open message o'.
# That English wrapper dilutes a real, unambiguously-Hebrew message down to
# ~56% confidence — below CONTENT_CONFIDENCE_THRESHOLD — so nothing gets
# corrected even though the actual message content is obvious. Unlike the
# reject-the-whole-string checks above, this only strips the known wrapper
# and keeps the real content in between.
MESSAGE_SENDER_PREFIX_PATTERN = re.compile(r"^You:\s*")
MESSAGE_METADATA_SUFFIX_PATTERN = re.compile(r"\s*\d{1,2}:\d{2}\s+(Delivered|Read|Sent)\b.*$", re.IGNORECASE)


def _strip_message_metadata(text):
    text = MESSAGE_SENDER_PREFIX_PATTERN.sub("", text)
    text = MESSAGE_METADATA_SUFFIX_PATTERN.sub("", text)
    return text.strip()


# Real finding: Google Calendar's event/task tiles glue the real, user-typed
# title together with a comma-separated wrapper of English UI fields — a time
# range, the calendar's own possessive name ("Liran's calender" — Google's own
# wording, not a typo introduced here), location status, RSVP/task status, and
# the date, e.g. (shape preserved, wording changed from the real live capture)
# 'task: לסיים לקרוא את הפרק הבא בספר ... , Not completed, September 11,
# 2026, 10:30am' and '6:30pm to 7pm, לאסוף חבילה מהדואר, Liran's calender,
# No location, September 15, 2026'. That wrapper is often
# LONGER than a short Hebrew title, so it can outweigh the real content and
# flip the classification to English even though the actual event/task text is
# unambiguously Hebrew. Same category as _strip_message_metadata — strip the
# known wrapper, keep the real content in between.
CALENDAR_TASK_PREFIX_PATTERN = re.compile(r"^task:\s*", re.IGNORECASE)
CALENDAR_TIME_RANGE_PATTERN = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)(\s+to\s+\d{1,2}(:\d{2})?\s*(am|pm))?\b", re.IGNORECASE)
CALENDAR_DATE_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b")
CALENDAR_STATUS_PATTERN = re.compile(r"\b(Not completed|Completed|Accepted|Declined|Maybe)\b", re.IGNORECASE)
CALENDAR_NO_LOCATION_PATTERN = re.compile(r"\bNo location\b", re.IGNORECASE)
CALENDAR_OWNER_CALENDAR_PATTERN = re.compile(r"\b\w+'s\s+calend?er\b", re.IGNORECASE)
CALENDAR_TRAILING_NOTE_PATTERN = re.compile(r"\bEvent is being created\.?", re.IGNORECASE)


def _strip_calendar_metadata(text):
    text = CALENDAR_TASK_PREFIX_PATTERN.sub("", text)
    text = CALENDAR_TIME_RANGE_PATTERN.sub("", text)
    text = CALENDAR_DATE_PATTERN.sub("", text)
    text = CALENDAR_STATUS_PATTERN.sub("", text)
    text = CALENDAR_NO_LOCATION_PATTERN.sub("", text)
    text = CALENDAR_OWNER_CALENDAR_PATTERN.sub("", text)
    text = CALENDAR_TRAILING_NOTE_PATTERN.sub("", text)
    text = re.sub(r"[\s,]*,[\s,]*", ", ", text)  # collapse comma debris left by removed fields
    return text.strip(" ,")


def _looks_like_real_content(accessible_text, title):
    if len(accessible_text) < MIN_ACCESSIBLE_TEXT_LENGTH:
        return False
    # Real finding: some apps (confirmed: "Segment Studio Checklist", Gemini's
    # own top-level element) report the page/tab TITLE through Name, not the
    # actual visible content — reject anything that's just an echo of the title.
    if accessible_text in title:
        return False
    if all(marker in accessible_text for marker in GENERIC_ACCESSIBLE_TEXT_MARKERS):
        return False
    if SHORTCUT_HINT_PATTERN.search(accessible_text):
        return False
    if any(accessible_text.startswith(prefix) for prefix in PLACEHOLDER_TEXT_PREFIXES):
        return False
    return True


# Real finding, confirmed live with diagnose_zoom_tree.py: for Zoom's chat panel
# (both the popped-out "Meeting chat" window and the docked panel inside the main
# "Zoom Meeting" call window), GetFocusedControl() lands on a short header pane
# (~66px tall, holding only the session/recording title text) that sits as a
# SIBLING right above the real chat body — a much taller pane (~925px) that Zoom
# draws as pixels with no accessible Name of its own, meaning it can only ever be
# read via OCR. The old top-anchored crop was reading the correct control just
# fine — it was simply the wrong control. Structural, not app-named: this pattern
# (a short header sibling next to a much taller content sibling) can occur in any
# app; nothing here checks exe_name or title.
HEADER_LIKE_MAX_HEIGHT = 90
LARGE_SIBLING_MIN_HEIGHT = 300


def _find_larger_sibling_rect(control):
    try:
        parent = control.GetParentControl()
        if parent is None:
            return None
        my_rect = control.BoundingRectangle
        best = None
        sibling = parent.GetFirstChildControl()
        while sibling is not None:
            try:
                srect = sibling.BoundingRectangle
                # Only a sibling clearly BELOW this one (not overlapping/above it)
                # counts as "the body under this header" — a small vertical
                # tolerance for adjacent panes that touch exactly at the border.
                if (srect.height() >= LARGE_SIBLING_MIN_HEIGHT
                        and srect.top >= my_rect.bottom - 5
                        and _is_onscreen(srect)
                        and (best is None or srect.height() > best.height())):
                    best = srect
            except Exception:
                pass
            sibling = sibling.GetNextSiblingControl()
        return best
    except Exception:
        return None


# Real finding, confirmed directly with diagnose_textpattern.py on real documents
# with real content: Google Docs does not expose its actual body text through
# ANY UI Automation mechanism — not the bounding rectangle (document-scroll
# coordinates, often off-screen), not accessible Name, not even TextPattern's
# DocumentRange (all three return only the generic "תוכן מסמך" role label).
# This is a genuine wall in Google Docs' own accessibility support, not
# something fixable in this codebase. The one real, honest signal left: the
# document's own title — not the body, but genuine user-authored text, used
# only when the body is confirmed unreadable, not pretended to be the content.
GOOGLE_DOCS_GENERIC_TITLES = ["מסמך ללא שם", "Untitled document"]


def _google_docs_title_text(title):
    if " - Google Docs" not in title:
        return None
    doc_title = title.split(" - Google Docs")[0].strip()
    if not doc_title or doc_title in GOOGLE_DOCS_GENERIC_TITLES:
        return None
    return doc_title


def decide_with_content(hwnd, fallback_hkl, title, exe_name, thread_id):
    """
    Falls back to fallback_hkl (Tier 1/2's answer, possibly None) on an empty
    field, low model confidence, or any failure in this layer — Tier 1/2 stays
    the proven base (Week 4: "Go with Conditions"), this only adds to it.
    """
    # Real bug found live: this runs in a background thread that can be delayed
    # (Tesseract alone takes 500ms+, on top of thread-scheduling lag) — by the
    # time GetFocusedControl() below actually runs, the user may have alt-tabbed
    # away from hwnd and back to a DIFFERENT window. GetFocusedControl() reads
    # whatever is focused RIGHT NOW, with no idea it's supposed to be reading for
    # hwnd specifically, so it can silently read a completely unrelated window's
    # content. The existing checks in apply_content_correction() only catch this
    # if hwnd is no longer foreground by the time the decision is APPLIED — if
    # the user flickers back to hwnd before then, those checks pass even though
    # the content read was for a different window entirely. Checking here, right
    # before the read, closes that gap at the source.
    if win32gui.GetForegroundWindow() != hwnd:
        if DEBUG:
            print("  [content] skipped, focus moved before content could be read")
        return fallback_hkl, None

    try:
        control = auto.GetFocusedControl()
        rect = control.BoundingRectangle
    except Exception as e:
        if DEBUG:
            print(f"  [content] skipped ({e})")
        return fallback_hkl, None

    # Diagnostic, not behavior: the raw, UNCAPPED control rect of whatever was
    # actually focused (unlike screenshot_rect below, which reflects the final
    # region actually read, possibly redirected to a sibling — see
    # _find_larger_sibling_rect) — kept so a logged decision shows the real
    # height/width CKILS started from, useful for spotting this exact
    # short-header-control shape in some future app.
    full_control_rect = (rect.left, rect.top, rect.right, rect.bottom)
    screenshot_rect = None
    accessible_text = (control.Name or "").strip()
    if _looks_like_real_content(accessible_text, title):
        text = accessible_text
        source = "accessible_text"
        if _is_onscreen(rect):
            screenshot_rect = (rect.left, rect.top, rect.right, rect.bottom)
        if DEBUG:
            print(f"  [content] read from accessible text, no OCR needed: {text[:60]!r}")
    elif not _is_onscreen(rect):
        title_text = _google_docs_title_text(title)
        if title_text is not None and thread_id in google_docs_title_already_applied:
            if DEBUG:
                print("  [content] Google Docs title already used as this visit's one-time default — not re-asserting")
            return fallback_hkl, None
        if title_text is not None:
            text = title_text
            source = "google_docs_title"
            google_docs_title_already_applied.add(thread_id)
            if DEBUG:
                print(f"  [content] Google Docs body unreadable, using document title instead: {text!r}")
        else:
            if DEBUG:
                print(f"  [content] control rect is off-screen ({rect.left},{rect.top}) — skipping OCR")
            return fallback_hkl, None
    else:
        ocr_rect = rect
        source = "ocr"
        if rect.height() < HEADER_LIKE_MAX_HEIGHT:
            sibling_rect = _find_larger_sibling_rect(control)
            if sibling_rect is not None:
                ocr_rect = sibling_rect
                source = "ocr_sibling"
                if DEBUG:
                    print(f"  [content] focused control looks like a thin header ({rect.height()}px) — reading its larger sibling pane instead")
        try:
            right = min(ocr_rect.right, ocr_rect.left + MAX_OCR_WIDTH)
            bottom = min(ocr_rect.bottom, ocr_rect.top + MAX_OCR_HEIGHT)
            text = read_region(ocr_rect.left, ocr_rect.top, right, bottom)
            screenshot_rect = (ocr_rect.left, ocr_rect.top, right, bottom)
        except Exception as e:
            if DEBUG:
                print(f"  [content] skipped ({e})")
            return fallback_hkl, None

    if not text.strip():
        if DEBUG:
            print("  [content] empty field, nothing to read")
        return fallback_hkl, None

    stripped_text = _strip_message_metadata(text)
    stripped_text = _strip_calendar_metadata(stripped_text)
    if stripped_text != text and DEBUG:
        print(f"  [content] stripped known UI wrapper: {text[:60]!r} -> {stripped_text[:60]!r}")
    text = stripped_text
    if not text:
        if DEBUG:
            print("  [content] nothing left after stripping known UI wrapper")
        return fallback_hkl, None

    # Real finding: Zoom's own product-branding text ("zoom. Workplace ...")
    # came through OCR, not accessible text, so _looks_like_real_content()
    # above (which only guards the accessible-text path) never saw it — it
    # reached the classifier as if it were real meeting content every single
    # call. Same gap, confirmed again for WhatsApp's "Type a message"
    # placeholder: when accessible text is (correctly) rejected as that
    # placeholder, this falls through to OCR of the exact same on-screen
    # region — which just reads that same visible placeholder text again,
    # completely bypassing the accessible-text-only check. Both checks must
    # apply to whatever text was FINALLY selected, regardless of source.
    rejection_reason = _rejected_as_ui_noise(text)
    if rejection_reason is not None:
        if DEBUG:
            print(f"  [content] rejected as {rejection_reason}, not real content: {text[:60]!r}")
        return fallback_hkl, None

    try:
        label, proba = predict_language(text)
    except Exception as e:
        # Any future error in the model/prediction pipeline (not just the ones
        # already found and fixed) falls back gracefully here now, same as OCR.
        if DEBUG:
            print(f"  [content] skipped ({e})")
        return fallback_hkl, None
    confidence = proba[label]
    if DEBUG:
        print(f"  [content] read {text[:60]!r} -> {label} ({confidence:.2f} confidence)")

    applied = confidence >= CONTENT_CONFIDENCE_THRESHOLD
    # Logged regardless of outcome — this is the raw material for the monthly
    # review pass (review_decisions.py), not something retrained on directly.
    log_decision(exe_name, title, thread_id, source, text, label, confidence, applied)

    if not applied:
        if DEBUG:
            print(f"  [content] confidence below {CONTENT_CONFIDENCE_THRESHOLD} threshold, keeping the current default")
        return fallback_hkl, None

    # Full "why" for decision_logger — everything that went into this call,
    # not just the resulting hkl, so a bad decision can be inspected later
    # from the log instead of needing to be caught live in DEBUG output.
    reason = {
        "mechanism": "tier3_content",
        "source": source,
        "text": text,
        "predicted_label": label,
        "confidence": confidence,
        "control_rect": full_control_rect,
        "control_size": (full_control_rect[2] - full_control_rect[0], full_control_rect[3] - full_control_rect[1]),
        "screenshot_rect": screenshot_rect,
    }
    return LANGUAGE_TO_HKL[label], reason

previous_thread = None   # whichever thread window was focused just before the current event


user32 = ctypes.windll.user32
WinEventProcType = ctypes.WINFUNCTYPE(
    None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.HWND,
    ctypes.wintypes.LONG, ctypes.wintypes.LONG, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD)

def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
    global previous_thread
    # The instant focus leaves a window we were overriding, forget it ever happened —
    # its next visit starts completely fresh, learned default applied automatically.

    if event == win32con.EVENT_OBJECT_NAMECHANGE:
        if id_object != win32.lib.win32con.OBJID_WINDOW or id_child != win32.lib.win32con.CHILDID_SELF:
            return
        if hwnd != win32gui.GetForegroundWindow():
            return
    if previous_thread is not None and previous_thread != thread_id:
        if previous_thread in overridden:
            overridden.discard(previous_thread)
            last_set.pop(previous_thread, None)
        content_decision.pop(previous_thread, None)  # fresh window = learned default first, again
        google_docs_title_already_applied.discard(previous_thread)
        # Real bug found live: unlike content_decision (a per-visit "sticky"
        # value that SHOULD reset the moment you leave), decision_logger's
        # last-auto-decision record is meant to answer "what did CKILS decide
        # right before this override" even when the override comes after
        # briefly tabbing away and back — the single most common real pattern
        # (glance elsewhere, come back, notice it's wrong, correct it). Forgetting
        # it here made every such override log "preceding_auto": null instead of
        # the decision that was actually being corrected. Intentionally NOT
        # cleared on focus-away — same lifetime as last_set, not content_decision.
    previous_thread = thread_id

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        title = win32gui.GetWindowText(hwnd)
        exe_name = psutil.Process(pid).name()
    except Exception as e:
        # A window/process can vanish between the event firing and this lookup
        # (short-lived popups, permission-restricted elevated windows) — skip
        # this one event rather than crash the whole hook callback over it.
        if DEBUG:
            print(f"  [debug] could not resolve window info, skipping ({e})")
        return

    if DEBUG:
        print(f"  [debug] exe_name = {exe_name!r}")

    # A real title change on a shared thread (e.g. switching Chrome tabs) means
    # this is genuinely different content, even though thread_id didn't change —
    # see last_title_by_thread above for why this matters.
    if last_title_by_thread.get(thread_id) != title:
        content_decision.pop(thread_id, None)
        google_docs_title_already_applied.discard(thread_id)
        last_title_by_thread[thread_id] = title

    # Layered fallback, most specific first: this visit's own decision (if Tier 3
    # already confidently decided this exact window) -> this exact page's learned
    # history, IF it's actually trustworthy (see _trust above) -> this app's
    # general learned history, IF that's trustworthy -> nothing. No app name is
    # checked anywhere here — a coarse or contradictory history (a browser's
    # whole-app guess, WhatsApp/Zoom's one shared title) simply never earns
    # trust, automatically, for any app with that shape.
    page_hkl = LANGUAGE_NAME_TO_HKL.get(_trust(_history_of(page_learned_defaults.get(_page_key(exe_name, title)))))
    app_hkl = LANGUAGE_NAME_TO_HKL.get(_trust(_history_of(learned_defaults.get(exe_name))))
    default_hkl = page_hkl if page_hkl is not None else app_hkl
    target_hkl = content_decision.get(thread_id, default_hkl)

    if target_hkl is not None:
        actual_hkl = win32api.GetKeyboardLayout(thread_id)
        if DEBUG:
            print(f"  [debug] {exe_name} hwnd={hwnd} thread={thread_id} title={title!r} actual={hex(actual_hkl)} last={hex(last_set.get(thread_id, -1))}")
        # ignore mismatches caused by our own switch not having propagated yet
        just_switched = time.time() - last_switch_time.get(thread_id, 0) < SWITCH_GRACE
        if thread_id in last_set and actual_hkl != last_set[thread_id] and not just_switched:
            overridden.add(thread_id)
            last_set[thread_id] = actual_hkl  # treat the user's manual choice as the new "last known" state
            log_override(exe_name, title, thread_id, actual_hkl)  # real, free evidence a recent decision was wrong
            # A manual override is the user telling CKILS, with certainty, what
            # this app/page should be — feed it into the same trust history a
            # confident Tier 3 decision uses, so this stops being a one-time
            # log entry only a monthly human review ever sees. One override is
            # still just one data point under the same TRUST_MIN_SAMPLES/
            # TRUST_AGREEMENT_THRESHOLD rule as everything else, so it can't
            # single-handedly overwrite an otherwise well-established default.
            override_language = HKL_TO_LANGUAGE_NAME.get(actual_hkl)
            if override_language is not None:
                save_learned_default(exe_name, override_language)
                save_page_learned_default(exe_name, title, override_language)
            decision_logger.log_manual_override(exe_name, title, thread_id, override_language)
            print(f"{exe_name}: manual override detected, leaving it alone")
        else:
            # This is the fast path — unchanged from Weeks 2-4, still sub-millisecond.
            # Tier 3 (below) never blocks this; it only corrects it afterward if needed.
            previous_hkl_for_thread = last_set.get(thread_id)
            start = time.perf_counter()
            win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f'{exe_name}: switched to {hex(target_hkl)} in {elapsed_ms:.1f} ms')
            if previous_hkl_for_thread != target_hkl:
                if thread_id in content_decision:
                    fast_source = "sticky_content_decision"
                elif page_hkl is not None:
                    fast_source = "page_learned_default"
                elif app_hkl is not None:
                    fast_source = "app_learned_default"
                else:
                    fast_source = "unknown"
                try:
                    screenshot_rect = win32gui.GetWindowRect(hwnd)
                except Exception:
                    screenshot_rect = None
                decision_logger.log_auto_change(
                    exe_name, title, thread_id,
                    HKL_TO_LANGUAGE_NAME.get(previous_hkl_for_thread),
                    HKL_TO_LANGUAGE_NAME.get(target_hkl),
                    {
                        "mechanism": "fast_path",
                        "source": fast_source,
                        "page_history": _history_of(page_learned_defaults.get(_page_key(exe_name, title))),
                        "app_history": _history_of(learned_defaults.get(exe_name)),
                        "screenshot_rect": screenshot_rect,
                    },
                )
            last_set[thread_id] = target_hkl
            last_switch_time[thread_id] = time.time()

    # Tier 3 (Week 5) runs in a background thread: real testing showed OCR alone
    # costs 500ms+ even on a tiny, near-empty region (Tesseract reloads its language
    # models from scratch every call) plus a few more ms per character recognized —
    # both far past SC-02's 150ms target. Rather than block the proven fast path
    # above on that, it runs after the fact and only corrects the switch if it
    # disagrees, is confident, and the user hasn't already moved on or overridden it.
    # Skip spawning one if this same window already has a correction in flight —
    # see content_check_in_progress above for why that matters.
    # Real bug found live: keyed by thread_id alone, this blocked a genuinely new
    # tab from ever getting its own check queued whenever an older tab's check
    # (same shared Chrome thread_id) was still running — the user had to keep
    # switching back and forth until one finally landed. Keying by (thread_id,
    # title) instead means different tabs can check concurrently without either
    # blocking the other, while repeated NAMECHANGE spam for the SAME tab still
    # only gets one check in flight, exactly as before.
    check_key = (thread_id, title)
    if check_key not in content_check_in_progress:
        content_check_in_progress.add(check_key)
        threading.Thread(
            target=apply_content_correction,
            args=(hwnd, thread_id, exe_name, target_hkl, title),
            daemon=True
        ).start()


def apply_content_correction(hwnd, thread_id, exe_name, fallback_hkl, title):
    # Held for the whole function, not just the OCR part — this is what actually
    # stops two corrections for the same window from racing on last_set/overridden.
    check_key = (thread_id, title)
    try:
        # COM (which UI Automation needs) is initialized per THREAD, not once for the
        # whole process — this function runs in a new background thread every time,
        # so it needs its own init call here, separate from the one before PumpMessages().
        auto.InitializeUIAutomationInCurrentThread()

        start = time.perf_counter()
        corrected_hkl, reason = decide_with_content(hwnd, fallback_hkl, title, exe_name, thread_id)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if corrected_hkl == fallback_hkl or corrected_hkl is None:
            if DEBUG:
                print(f"  [content] {exe_name}: no change ({elapsed_ms:.0f} ms)")
            return
        if win32gui.GetForegroundWindow() != hwnd:
            if DEBUG:
                print(f"  [content] {exe_name}: decision arrived too late, focus moved on ({elapsed_ms:.0f} ms)")
            return
        # Real bug found live: Chrome's hwnd doesn't change between tabs, so the
        # check above alone can't tell "still the same window" apart from "same
        # window, but you've since switched to a different tab." Re-check the
        # window's CURRENT title still matches what this correction was actually
        # computed for — otherwise this is a stale result for a tab you've left.
        if win32gui.GetWindowText(hwnd) != title:
            if DEBUG:
                print(f"  [content] {exe_name}: decision is for a different tab now, discarding ({elapsed_ms:.0f} ms)")
            return
        if thread_id in overridden:
            if DEBUG:
                print(f"  [content] {exe_name}: user has manually overridden this window, leaving it alone ({elapsed_ms:.0f} ms)")
            return

        win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, corrected_hkl)
        last_set[thread_id] = corrected_hkl
        last_switch_time[thread_id] = time.time()
        content_decision[thread_id] = corrected_hkl  # sticks for the rest of this visit
        language_name = HKL_TO_LANGUAGE_NAME[corrected_hkl]
        decision_logger.log_auto_change(
            exe_name, title, thread_id,
            HKL_TO_LANGUAGE_NAME.get(fallback_hkl), language_name,
            reason or {},
        )
        # Always record this confident decision into both histories — even for
        # a key whose history is currently inconsistent (a browser's whole-app
        # guess, WhatsApp/Zoom's one shared title). Recording every observation
        # is exactly how _trust() can tell a consistent key from an inconsistent
        # one; skipping the write for "unreliable" keys would mean nothing ever
        # measures whether they've become reliable (or stayed unreliable). What
        # changes is only whether a later READ trusts this key (see _trust
        # above and its use in on_focus_change) — never whether it gets written.
        save_learned_default(exe_name, language_name)  # this app in general
        save_page_learned_default(exe_name, title, language_name)  # this exact page — both genuinely AI-learned
        print(f"{exe_name}: content-aware correction to {hex(corrected_hkl)} ({elapsed_ms:.0f} ms)")
    finally:
        content_check_in_progress.discard(check_key)

# Real gap: switching conversations inside some chat apps (confirmed:
# WhatsApp Web/Business) fires no Windows focus/title event at all — the
# window never loses focus and its title never changes — so on_focus_change
# would never even get a chance to re-check. There's no reliable way to name
# in advance which apps have this gap (that was the hand-written-list problem
# this session removed), so this polls the CURRENTLY FOCUSED window
# unconditionally, on a plain timer — no app name, no trust check. A normal
# single-purpose app (Notepad, an editor) just gets one redundant, cheap,
# deduped-against-in-flight-checks Tier 3 read every interval; an app with
# this exact gap gets the re-check it would otherwise never receive.
#
# Real complaint, 2026-09-16: on a brand-new page with no learned history yet
# (see the YouTube/general-web finding the same day), the wait between polls
# is exactly how long a wrong/stale keyboard state visibly persists once a
# read didn't land well. Halved from 3.0s to give it roughly twice as many
# chances per minute to land on a good read. This does NOT fix the root cause
# (OCR/UI-Automation landing on the wrong element in the first place) — it
# only shortens how long you're stuck in that state once it happens. Honest
# cost: this roughly doubles how often the background poll's OCR read runs
# for whatever window is currently focused, even when nothing has changed.
UNTRUSTED_POLL_SECONDS = 1.5


def _poll_focused_window():
    while True:
        time.sleep(UNTRUSTED_POLL_SECONDS)
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = psutil.Process(pid).name()
        except Exception:
            continue  # window vanished or info unavailable between calls — just skip this tick

        check_key = (thread_id, title)
        if check_key in content_check_in_progress:
            continue  # a check for this same title (from an event or a previous tick) is already in flight
        content_check_in_progress.add(check_key)
        threading.Thread(
            target=apply_content_correction,
            args=(hwnd, thread_id, exe_name, last_set.get(thread_id), title),
            daemon=True
        ).start()


# Real gap found while adding regression tests: everything below this point used
# to run unconditionally at import time — hooking real Windows-wide events and
# blocking forever in PumpMessages(). That's correct for `python rule_engine.py`
# or the packaged exe (both run as "__main__"), but it means a test file can
# never simply `import rule_engine` to reach its pure functions (_trust,
# _strip_message_metadata, _find_larger_sibling_rect, ...) without also starting
# a real background listener and hanging on the message loop. Guarding it here
# changes nothing about running CKILS itself — only makes the module safely
# importable for testing.
if __name__ == "__main__":
    threading.Thread(target=_poll_focused_window, daemon=True).start()
    decision_logger.start_background_pruning()

    callback = WinEventProcType(on_focus_change)
    hook = user32.SetWinEventHook(
        win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
        0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT)

    name_hook = user32.SetWinEventHook(win32con.EVENT_OBJECT_NAMECHANGE,
        win32con.EVENT_OBJECT_NAMECHANGE,0,callback,0,0,win32con.WINEVENT_OUTOFCONTEXT)
    auto.InitializeUIAutomationInCurrentThread()  # once, before the message loop — needed by decide_with_content()
    print("CKILS is watching in the background. Press Ctrl+C in this window to stop.")
    win32gui.PumpMessages()
