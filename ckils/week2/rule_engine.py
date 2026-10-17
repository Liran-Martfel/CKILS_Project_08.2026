"""
CKILS's main engine and live entry point (`python rule_engine.py`, and what
the packaged exe actually runs). Watches Windows focus/title-change events
and a background poll, and switches the active window's keyboard input
language (Hebrew <-> English) automatically, in three layered tiers:

1. Fast path (learned defaults) — an instant guess for a window, built from
   CKILS's own past confident decisions, applied the moment focus changes
   (see on_focus_change). No AI involved; just counted history that has to
   earn trust before it's used (see _trust).
2. Content-aware correction (Tier 3) — runs afterward in a background
   thread (see apply_content_correction/decide_with_content): reads the
   focused control's real on-screen text (accessible text, OCR, or a
   Google Docs title as a last resort) and asks the trained classifier what
   language it is, correcting the fast path's guess if it disagrees and is
   confident.
3. Manual override, always respected — if the user switches the language
   themselves, CKILS leaves that window alone until they move on (see
   _detect_and_record_manual_override), and feeds the correction back into
   what the trust system learns.

Every real decision (automatic or manual) is written to a persistent log
via decision_logger, for later diagnosis and the monthly review-assisted
retrain (review_decisions.py). This module is safely importable by
test_regressions.py — everything that hooks real Windows events or blocks
on PumpMessages() is guarded behind `if __name__ == "__main__":` at the
bottom, so importing it just to reach its pure functions never starts a
live listener.
"""
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
import skip_logger
import keyboard_hook

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
    """Returns the folder anything meant to persist across runs should live
    in: the real exe's own folder when frozen (packaged), or this script's
    own folder when running from source.
    """
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
    """Loads the app-level learned-defaults dict from disk, or {} if the
    file doesn't exist yet (a brand-new install with no history at all).
    """
    if not os.path.exists(LEARNED_DEFAULTS_FILE):
        return {}
    with open(LEARNED_DEFAULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_learned_default(exe_name, language_name):
    """Appends one more confident observation (language_name) to exe_name's
    trust history and persists it to disk immediately.
    """
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
    """Builds the dict key page_learned_defaults uses for one exact
    (app, window title) combination.
    """
    return f"{exe_name}||{title}"


def load_page_learned_defaults():
    """Loads the page-level learned-defaults dict from disk, or {} if the
    file doesn't exist yet.
    """
    if not os.path.exists(PAGE_LEARNED_DEFAULTS_FILE):
        return {}
    with open(PAGE_LEARNED_DEFAULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_page_learned_default(exe_name, title, language_name):
    """Appends one more confident observation (language_name) to this exact
    (app, title) page's trust history and persists it to disk immediately.
    """
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
    """Creates the decisions/overrides tables in DECISIONS_DB_FILE if they
    don't already exist. Safe to call repeatedly — also used to self-heal a
    corrupted/missing schema (see _run_logged_write).
    """
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
    """Runs one write (sql, params) against DECISIONS_DB_FILE. If it fails
    (e.g. a missing/corrupted table), re-initializes the schema and retries
    once before giving up quietly — a logging failure must never be allowed
    to crash the actual language-switching logic that calls this.
    """
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
    """Records one Tier 3 classification attempt to the decisions table,
    regardless of whether it was confident enough to actually apply — this
    is the raw material review_decisions.py later mines for cases worth a
    human's attention.
    """
    _run_logged_write(
        "INSERT INTO decisions (timestamp, exe_name, title, thread_id, source, text, predicted_label, confidence, applied) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.datetime.now().isoformat(), exe_name, title, thread_id, source, text,
         predicted_label, confidence, int(applied))
    )


def log_override(exe_name, title, thread_id, overridden_to_hkl):
    """Records one confirmed manual override to the overrides table — real,
    free evidence that a preceding automatic decision was wrong.
    """
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

# Tier 4 Phase 2 (2026-10-14): thread_ids whose layout Tier 4 auto-corrected
# from the user's own keystrokes this visit. Tier 3 stays away from these for
# the rest of the visit (same lifecycle as `overridden`, cleared in
# _reset_visit_state) — otherwise its next poll could read English UI chrome,
# disagree, and flip it straight back: a ping-pong between Tier 3's OCR and
# Tier 4's typing evidence. Deliberately a SEPARATE set from `overridden`:
# Tier 4 respects `overridden` (the user's own manual choice always wins), so
# putting its own corrections in that same set would make a second Tier 4
# correction in the same visit (bilingual typing) block itself.
tier4_corrected = set()

# Tier 3 never changes a window's language within this many seconds of the
# user typing in it (keyboard_hook.typed_recently). Long enough to cover a
# pause to think mid-sentence; a read after a real break still applies.
TYPING_HOLD_SECONDS = 10

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

# Real bug found live, 2026-09-16: the untrusted poll below (see
# UNTRUSTED_POLL_SECONDS) re-ran a full Tesseract OCR read on whatever window was
# focused every single tick, forever — even once it had already confirmed the exact
# same answer many times in a row. Confirmed directly from a live 4+ hour run: one
# static Chrome tab got re-OCR'd every ~1.5s nonstop, ~600ms per read, "no change"
# every time, for over 1,300 CPU-seconds total. That sustained background OCR load
# is a real, measurable resource cost, and very plausibly what made switching feel
# slow everywhere (including typing into an unrelated app) — not a decision-logic
# bug, a performance one. Fixed by backing off, per (thread_id, title), once a read
# has come back unchanged several times in a row; any real event for that key
# (title change, different tab, different window) starts it fresh at full speed —
# so the WhatsApp-style "content changes with no Windows event" case this poll
# exists for is still caught, just not hammered nonstop on windows that already
# settled.
POLL_BACKOFF_STREAK_THRESHOLD = 3   # this many identical "no change" polls in a row before backing off
POLL_BACKOFF_SECONDS = 20.0         # how slowly to re-check a settled window, instead of every UNTRUSTED_POLL_SECONDS
poll_unchanged_streak = {}  # (thread_id, title) -> consecutive "no change" poll results
poll_next_allowed = {}      # (thread_id, title) -> earliest time.time() this key may be poll-checked again

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
    """True if rect overlaps the real virtual screen bounds (across every
    monitor) at all — used to reject control rectangles reported in some
    other coordinate space entirely (e.g. Google Docs' document-scroll
    coordinates), which would otherwise waste an OCR call on a guaranteed-
    blank capture.
    """
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
    """Normalizes a learned_defaults/page_learned_defaults entry into a
    plain list of past language observations, oldest first — handles both
    the current {"history": [...]} shape and a bare legacy string value
    (see the back-compat note below) uniformly for _trust() to consume.
    """
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
    """Returns the majority language ("hebrew"/"english") if history has at
    least TRUST_MIN_SAMPLES observations AND at least
    TRUST_AGREEMENT_THRESHOLD of them agree — otherwise None, meaning "not
    enough evidence either way, don't use this as a default yet." This is
    the sole mechanism that decides whether a learned key is trustworthy;
    nothing here names any specific app.
    """
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
# Real finding, 2026-09-16: WhatsApp has a THIRD, different empty-box
# placeholder — the contact-search box's "Search name, number or @username"
# — distinct from the message-compose box's "Type a message". Confirmed live:
# switched to Hebrew correctly from a real message, then a poll cycle 20
# seconds later happened to read this placeholder instead and forced English
# right back, before a later real message corrected it again.
# Real finding, 2026-10-09: the Claude Code extension in VS Code has its OWN
# empty-compose-box placeholder — "Queue another message..." — same category,
# same effect: a genuinely Hebrew conversation got forced to English every
# single time focus returned to an idle input box. Confirmed live with
# diagnose_focus.py: clicking anywhere in the chat panel (not just the input
# box itself) refocuses this same box, so GetFocusedControl() lands here
# almost every time the user "comes back to the app" — reported directly by
# the user ("every time i come to the app, it changes to english") and
# confirmed from the decisions log, dozens of reads of this exact text,
# always English, always applied.
# Real finding, 2026-10-14: typing English into Chrome's address bar or
# Google's search box flipped the layout to Hebrew mid-word, four times in
# 12 minutes (Tier 4 then flipped it back at the word end, twice). The
# focused control's accessible Name is its LABEL, not what's typed in it —
# Chrome's address bar is "שורת חיפוש וכתובות אתרים" ("Address and search
# bar") and Google's search box is "כאן אפשר לשאול מה שרוצים" ("Ask anything
# here"), both in Hebrew only because that's the Windows display language.
# Listed here, not in UI_CHROME_MARKERS: _looks_like_real_content checks
# this list, so the label is skipped and the read falls through to OCR of
# the box itself — which shows what the user is actually typing.
PLACEHOLDER_TEXT_PREFIXES = ["Type a message", "Write your prompt to Claude", "Write a message",
                              "Search name, number or @username", "Queue another message",
                              "שורת חיפוש וכתובות אתרים", "כאן אפשר לשאול מה שרוצים"]
# Real finding, from auditing every manual override on record: TradingView's
# own site tagline ("גרפי מניות, מדדים, חוזים עתידיים, מט"ח וביטקוין בזמן-אמת
# ב-TradingView" — "Real-time stock charts, indices, futures, forex, and
# Bitcoin on TradingView") is exposed as accessible text regardless of what
# ticker is actually on screen, always in Hebrew, and kept forcing Hebrew over
# real English ticker symbols (NVDA, QQQ, XAUUSD, ...) 10 times in the log.
# Same category as Zoom's "Workplace" branding text above — fixed marketing
# copy, not something a person is reading or typing.
# Real finding, 2026-10-09, same VS Code / Claude Code investigation as the
# "Queue another message" placeholder above: the SAME idle input box also
# always shows its keybinding hint — "ctrl esc to focus or unfocus Claude" —
# right next to the placeholder, read via OCR often enough to sometimes
# clip the leading letters ("[irl esc to focus or unfocus Claude" was one
# real OCR misread, confirmed live). Matched on the stable middle portion
# so OCR noise at the very start doesn't defeat it. Separately, VS Code's
# own menu bar ("File Edit Selection View Go Run Terminal Help") and the
# extension's own accessible-text region label ("Claude Code conversation")
# were ALSO read as if they were the conversation itself — neither is
# something a person ever typed, in either language, in any VS Code window.
# Real finding, 2026-10-12: on an entirely English page (Microsoft's own
# careers site), selecting text triggers Chrome's own right-click menu item
# "תרגום הטקסט שנבחר לעברית" ("Translate selected text to Hebrew") — shown in
# Hebrew because that's the OS/browser's own display language, nothing to do
# with the page's real content. Read as accessible text and classified
# Hebrew at 0.84 confidence, applied, forcing Hebrew over a real English job
# page. Matched on the stable prefix (before the target-language word) so
# it catches the menu item regardless of which language Chrome offers to
# translate into. See EXCLUDED_WINDOW_TITLES just below for the matching fix
# to the translation POPUP this menu item opens, a related but separate gap.
UI_CHROME_MARKERS = ["Workplace", "וביטקוין בזמן-אמת ב-TradingView",
                      "esc to focus or unfocus Claude", "File Edit Selection View Go",
                      "Claude Code conversation", "תרגום הטקסט שנבחר ל"]

# Real finding, 2026-10-12, same investigation as the UI_CHROME_MARKERS entry
# above: choosing "Translate selected text to..." doesn't just show a menu
# label, it also opens Chrome's own translation popup, always titled
# "מתורגם" ("Translated") regardless of what was actually selected or
# translated. Its content is a REAL, correctly-read translation — not OCR
# noise, not UI boilerplate text — so content-level rejection can't catch
# it the way UI_CHROME_MARKERS does. But it's not something the user is
# reading or typing as their own content either: it's a disposable utility
# popup layered over whatever real (often English) page they were actually
# on, and letting it set the page's language left the user's REAL page
# switched to Hebrew after they dismissed it. Windows with this exact title
# are skipped before OCR/accessible-text is even attempted.
EXCLUDED_WINDOW_TITLES = {"מתורגם"}

# Real finding: on a Hebrew-titled YouTube video, OCR repeatedly read nothing
# but YouTube's own logo/wordmark — always English, regardless of the video's
# real language — with stray OCR artifacts around it ('> YouTube', 'YouTube"'
# with a smart quote). This kept winning and forcing English back over real
# Hebrew content nearby. Matched precisely (not a bare "YouTube" substring
# check) so a real comment or title that happens to mention YouTube by name
# isn't wrongly rejected too — only the logo-only read is.
YOUTUBE_LOGO_ONLY_PATTERN = re.compile(r"^[>\s]*YouTube[\"“”']*$")

# Real finding, 2026-09-24: a 2-3 character OCR read (a misread icon, a
# scrollbar arrow) can score confidence just over
# CONTENT_CONFIDENCE_THRESHOLD purely by chance — a short string gives the
# classifier almost nothing to actually be confident ABOUT. Confirmed live:
# 'הם' (2 real Hebrew letters, confidence 0.665) flipped an English exam
# page ("Exam B - Machine Learning (Calculations)") mid-sentence. The
# confidence threshold alone doesn't protect against this — length is a
# separate, independent signal that a read is real evidence rather than
# noise. Direction marks (LRM/RLM/LRE/RLE/PDF, U+200E/U+200F/U+202A-U+202C)
# are stripped before counting, since Windows adds these around a lot of
# on-screen text and they carry no linguistic content of their own.
#
# Honest limit, found while writing the regression test: a SECOND real
# capture that day ("TEST -ML - Liran_Martfel_part_2", confidence 0.70,
# text 'ר וא ה-- ‏ ‎ll‏') is NOT caught by this — once
# direction marks are stripped it's still 12 characters (spaces and dashes
# included), well past this threshold, even though only a few of those are
# meaningful letters. This fix is deliberately scoped to what was approved:
# a plain length floor. It does not detect "mostly punctuation/whitespace
# padding a few real letters" — that would need counting letters specifically
# rather than raw length, a separate decision not made here.
MIN_CLASSIFIED_TEXT_LENGTH = 5
DIRECTION_MARKS_PATTERN = re.compile(r"[‎‏‪-‬]")


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
    real_chars = DIRECTION_MARKS_PATTERN.sub("", text).strip()
    if len(real_chars) < MIN_CLASSIFIED_TEXT_LENGTH:
        return "too short to be real evidence, not just noise"
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
#
# Real finding, 2026-09-16: a message from someone else (not "You") shows
# their own name as the prefix instead — confirmed live: 'Noa Levy:
# התכוונתי להגיע בבוקר ואז החלטתי לבוא בערב 09:44 Context menu for message from Noa
# Levy React' — a completely different, unstripped wrapper shape (a real
# contact name, not literally "You", and a "Context menu for message from
# <name> React" footer instead of "Delivered/Read/Sent") that scored only
# ~59% English and was correctly never applied, but for the wrong reason
# (luck, not a real fix) — the real content never even got a chance to be
# read as Hebrew. Generalized the sender prefix to any short, letters-only
# name (not just "You") and added the new footer shape. The prefix pattern
# is deliberately restricted to letters/spaces only, and short (≤30 chars)
# — real names look like that; a URL like 'https://...' or a time like
# '6:30pm' never matches, so this can't accidentally eat real content that
# happens to contain an early colon (confirmed directly against the exact
# link-preview and calendar-event strings already covered by other tests).
MESSAGE_SENDER_PREFIX_PATTERN = re.compile(r"^[A-Za-z֐-׿][A-Za-z֐-׿ ]{0,29}:\s*")
MESSAGE_METADATA_SUFFIX_PATTERN = re.compile(
    r"\s*\d{1,2}:\d{2}\s+(Delivered|Read|Sent|Context menu for message from)\b.*$", re.IGNORECASE)


def _strip_message_metadata(text):
    """Strips a chat app's own English sender-name prefix and
    delivery-status/action-menu suffix from text, keeping only the real
    message content in between (see the real findings above for the exact
    wrapper shapes this handles).
    """
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
    """Strips Google Calendar's English tile wrapper (time range, date,
    RSVP/task status, "No location", the calendar's own possessive name)
    from text, keeping only the real, user-typed event/task title (see the
    real findings above for the exact wrapper shapes this handles).
    """
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
    """True if a control's accessible Name is plausibly real, user-relevant
    content rather than UI boilerplate — long enough, not just an echo of
    the window title, not a generic status marker, not carrying a keyboard-
    shortcut hint, and not an empty-field placeholder. Only guards the
    accessible-text path; _rejected_as_ui_noise applies similar checks to
    whatever text was finally selected regardless of source.
    """
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
    """If control looks like a thin header pane, looks among its siblings
    for a meaningfully taller one sitting directly below it (the real
    content body, in the Zoom-header shape this was built for) and returns
    its bounding rectangle. Returns None if control has no parent, or no
    qualifying sibling exists.
    """
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


# Real gap, confirmed live and diagnosed with diagnose_zoom_tree.py: in Zoom's
# main "Zoom Meeting" call window, the focused control can instead be a
# toolbar button (e.g. "Start my video") whose siblings are just other
# toolbar buttons — no larger sibling exists, so _find_larger_sibling_rect
# above correctly finds nothing, but the real chat pane still isn't read,
# because it lives in a completely different branch of the tree entirely
# (a cousin, not a sibling — several levels away under a different parent).
# Reaching it means searching the WHOLE window, not just next to the focused
# control.
#
# Real risk found and designed around before shipping, not after: Zoom's main
# window has SEVERAL large panes at once — a video gallery and a screen-share
# container, both comparable in size to the actual chat pane, both plausible
# false positives for "largest pane in the window." What distinguishes the
# real chat pane in the live tree dump is that Zoom draws it as pixels with NO
# accessible children at all (a true leaf), while the video gallery and share
# container both contain further named child elements (participant tiles, a
# "Share Content" child). Requiring "no children" specifically, not just
# "large," is what excludes those two candidates. Structural, not app-named —
# nothing here checks exe_name or title, and this only ever runs after the
# sibling search already found nothing, which real evidence so far shows is
# rare.
WHOLE_WINDOW_SEARCH_MIN_HEIGHT = 300
WHOLE_WINDOW_SEARCH_NODE_CAP = 500
WHOLE_WINDOW_SEARCH_MAX_DEPTH = 12
# Real bug found live, 2026-09-17, confirmed with diagnose_window_search.py
# against the actual live window (not guessed): on a Chrome/Claude.ai tab,
# this search picked a "leaf" spanning the ENTIRE window — (0,0) to the full
# window width/height, tab strip and bookmarks bar included — because it had
# no UI-Automation children of its own, while the real chat content (which
# does have children) was excluded by the leaf-only rule. The subsequent OCR
# crop (always the top-left corner) then read the browser's own tab
# strip/bookmarks bar instead of the page — confirmed directly: the read
# text was garbage, and the bookmarks bar happened to have Hebrew-named
# folders, flipping the whole tab to Hebrew with nothing Hebrew actually on
# the page. A candidate that covers essentially the whole window is
# structurally never "the real content" — Zoom's real chat pane (the case
# this search was built for) was always a meaningfully smaller, bounded
# region, never edge-to-edge with the window itself.
WHOLE_WINDOW_SEARCH_MAX_WINDOW_COVERAGE = 0.98  # a candidate this close to full window size/position is rejected


def _find_largest_leaf_pane_in_window(hwnd):
    """Searches the ENTIRE window tree (not just siblings of whatever's
    focused) for the largest true-leaf pane — a control with no
    UI-Automation children at all, the shape real pixel-drawn content (like
    Zoom's chat pane) has. Rejects candidates shorter than
    WHOLE_WINDOW_SEARCH_MIN_HEIGHT, off-screen, or spanning essentially the
    entire window (see WHOLE_WINDOW_SEARCH_MAX_WINDOW_COVERAGE — real
    content is never the whole window, e.g. a browser's own tab strip).
    Bounded by WHOLE_WINDOW_SEARCH_NODE_CAP/MAX_DEPTH so this can't run away
    on a huge, deeply-nested tree like a web page. Returns the winning
    rectangle, or None if nothing qualifies.
    """
    try:
        root = auto.ControlFromHandle(hwnd)
        window_rect = root.BoundingRectangle
    except Exception:
        return None

    best = None
    visited = 0

    def walk(control, depth):
        """Depth-first visits control and every descendant, recording the
        largest qualifying true-leaf pane seen so far in the enclosing
        best/visited variables.
        """
        nonlocal best, visited
        if control is None or depth > WHOLE_WINDOW_SEARCH_MAX_DEPTH or visited >= WHOLE_WINDOW_SEARCH_NODE_CAP:
            return
        visited += 1
        try:
            child = control.GetFirstChildControl()
        except Exception:
            return
        if child is None:
            # A true leaf — no children at all — is exactly the shape Zoom's
            # own pixel-drawn chat pane has, unlike the video gallery or the
            # share container (both have named child elements of their own).
            try:
                rect = control.BoundingRectangle
                spans_whole_window = (
                    window_rect.width() > 0 and window_rect.height() > 0
                    and rect.width() >= window_rect.width() * WHOLE_WINDOW_SEARCH_MAX_WINDOW_COVERAGE
                    and rect.height() >= window_rect.height() * WHOLE_WINDOW_SEARCH_MAX_WINDOW_COVERAGE
                )
                if (rect.height() >= WHOLE_WINDOW_SEARCH_MIN_HEIGHT
                        and _is_onscreen(rect)
                        and not spans_whole_window
                        and (best is None or rect.height() * rect.width() > best.height() * best.width())):
                    best = rect
            except Exception:
                pass
            return
        while child is not None:
            walk(child, depth + 1)
            try:
                child = child.GetNextSiblingControl()
            except Exception:
                break

    walk(root, 0)
    return best


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
    """Extracts the real, user-authored document title from a Google Docs
    window title (the part before " - Google Docs"), or None if this isn't
    a Google Docs window or the title is generic/empty ("Untitled
    document"). Used only as a last-resort signal once the document body
    has been confirmed unreadable — see the real finding above.
    """
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
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_FOCUS_MOVED)
        return fallback_hkl, None

    # Real finding, 2026-10-12: a disposable utility window (Chrome's own
    # "מתורגם"/"Translated" popup, see EXCLUDED_WINDOW_TITLES) is never worth
    # reading at all — skip before any control lookup or OCR work, not just
    # reject its content afterward.
    if DIRECTION_MARKS_PATTERN.sub("", title or "").strip() in EXCLUDED_WINDOW_TITLES:
        if DEBUG:
            print(f"  [content] skipped, excluded window title: {title!r}")
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_REJECTED_NOISE,
                             "excluded window title")
        return fallback_hkl, None

    try:
        control = auto.GetFocusedControl()
        rect = control.BoundingRectangle
    except Exception as e:
        if DEBUG:
            print(f"  [content] skipped ({e})")
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_READ_FAILED,
                             f"focused_control:{type(e).__name__}")
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
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_DOCS_TITLE_USED)
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
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_OFF_SCREEN)
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
            else:
                window_rect = _find_largest_leaf_pane_in_window(hwnd)
                if window_rect is not None:
                    ocr_rect = window_rect
                    source = "ocr_window_search"
                    if DEBUG:
                        print(f"  [content] no larger sibling either — found a large leaf pane elsewhere in the window instead")
        try:
            right = min(ocr_rect.right, ocr_rect.left + MAX_OCR_WIDTH)
            bottom = min(ocr_rect.bottom, ocr_rect.top + MAX_OCR_HEIGHT)
            text = read_region(ocr_rect.left, ocr_rect.top, right, bottom)
            screenshot_rect = (ocr_rect.left, ocr_rect.top, right, bottom)
        except Exception as e:
            if DEBUG:
                print(f"  [content] skipped ({e})")
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_READ_FAILED,
                                 f"ocr:{type(e).__name__}")
            return fallback_hkl, None

    if not text.strip():
        if DEBUG:
            print("  [content] empty field, nothing to read")
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_EMPTY_FIELD, source)
        return fallback_hkl, None

    stripped_text = _strip_message_metadata(text)
    stripped_text = _strip_calendar_metadata(stripped_text)
    if stripped_text != text and DEBUG:
        print(f"  [content] stripped known UI wrapper: {text[:60]!r} -> {stripped_text[:60]!r}")
    text = stripped_text
    if not text:
        if DEBUG:
            print("  [content] nothing left after stripping known UI wrapper")
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_EMPTY_FIELD,
                             f"{source}: only a UI wrapper")
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
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_REJECTED_NOISE,
                             f"{rejection_reason}: {text}")
        return fallback_hkl, None

    try:
        label, proba = predict_language(text)
    except Exception as e:
        # Any future error in the model/prediction pipeline (not just the ones
        # already found and fixed) falls back gracefully here now, same as OCR.
        if DEBUG:
            print(f"  [content] skipped ({e})")
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_READ_FAILED,
                             f"classifier:{type(e).__name__}")
        return fallback_hkl, None
    confidence = proba[label]
    if DEBUG:
        print(f"  [content] read {text[:60]!r} -> {label} ({confidence:.2f} confidence)")

    # 2026-10-15: the retrained model can answer "noise" — not real text (a
    # menu, a label, garbled OCR). That is never a language decision.
    if label not in LANGUAGE_TO_HKL:
        log_decision(exe_name, title, thread_id, source, text, label, confidence, False)
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_REJECTED_NOISE,
                             f"model: not real text ({confidence:.2f}): {text}")
        return fallback_hkl, None

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

pending_override = {}  # thread_id -> (hkl_seen, first_seen_time) — an unconfirmed mismatch, not yet trusted

# Real bug found live, 2026-09-19 (root cause of the Sep 17 "false override" too): Windows shares the
# input language across windows (the "different input method for each app window" setting is off), so
# arriving in window B keeps whatever language window A had — including one CKILS itself just set in A.
# CKILS compares that with what it remembers for B, sees a mismatch, and used to call it a manual
# override. Measured on the real log: 38 of 51 recorded "overrides" over three days equalled the
# language CKILS had last set in ANOTHER window. The user never switched by hand. A false override
# froze correction AND taught the wrong language into the learned defaults.
# A real manual switch is a change that appears while a window already holds a layout CKILS has SEEN
# match on this visit. A mismatch that has been there since arrival, never matching, is carry-over.
matched_this_visit = set()   # thread_ids whose real layout has matched last_set at least once this visit
reassert_attempts = {}       # thread_id -> times CKILS re-posted its own decision against a carry-over mismatch
MAX_REASSERT_ATTEMPTS = 2    # after this many tries CKILS accepts the layout Windows insists on (never fights forever)


def _reset_visit_state(thread_id):
    """Forgets everything that only made sense within one visit to a window:
    whether its layout has matched this visit, re-assert attempts, any
    unconfirmed mismatch, and CKILS's own last-post time (so "did CKILS
    decide anything since arriving?" starts false). Called when focus leaves
    a thread and when a shared thread's title changes (a new tab = a new visit).
    """
    matched_this_visit.discard(thread_id)
    reassert_attempts.pop(thread_id, None)
    pending_override.pop(thread_id, None)
    last_switch_time.pop(thread_id, None)
    tier4_corrected.discard(thread_id)


def _handle_carry_over(thread_id, hwnd, exe_name, title, actual_hkl):
    """A mismatch that has existed since arrival (never matched this visit) is
    carry-over from another window, NOT a manual switch: records no override
    and teaches the learned defaults nothing. If CKILS itself decided
    something this visit (it has posted a switch since arriving) it re-posts
    that decision up to MAX_REASSERT_ATTEMPTS times, since Windows may have
    re-synced the layout right after the first post. Otherwise, or once the
    attempts are used up, it accepts the layout Windows insists on as the new
    baseline, so any LATER change is correctly seen as a real one. With
    hwnd=None (the focus-event path, where the fast path is about to post the
    right target anyway) it only declines to call it an override.

    IF THIS MISBEHAVES — failure plan, cheapest first (so a bug here never
    becomes a reason to undo other work):
      a) Language keeps flipping back / feels like CKILS fights you: set
         MAX_REASSERT_ATTEMPTS = 0 and rebuild. CKILS then never re-posts; it
         only adopts the layout Windows shows. It still never records a false
         override, so the original bug stays fixed either way.
      b) Real manual switches are not being respected: check the skip log
         (summarize_skips.py) for carryover_accepted rows on that window; a
         genuine switch made BEFORE the layout ever matched this visit is
         indistinguishable from carry-over by design and is simply adopted.
      c) Anything else, or if unsure: `git revert` the single commit that added
         matched_this_visit / _handle_carry_over. That restores the previous
         behaviour exactly (including its false overrides).
      Never fix a problem here by touching the fast path or Tier 3 logic.
    """
    if hwnd is None:
        return
    attempts = reassert_attempts.get(thread_id, 0)
    decided_this_visit = thread_id in last_switch_time
    if decided_this_visit and attempts < MAX_REASSERT_ATTEMPTS:
        reassert_attempts[thread_id] = attempts + 1
        try:
            win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, last_set[thread_id])
        except Exception:
            pass
        last_switch_time[thread_id] = time.time()  # give Windows the usual grace before judging again
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_CARRYOVER_REASSERTED,
                             f"attempt {attempts + 1}")
        return
    last_set[thread_id] = actual_hkl
    matched_this_visit.add(thread_id)
    reassert_attempts.pop(thread_id, None)
    skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_CARRYOVER_ACCEPTED)


def _detect_and_record_manual_override(thread_id, exe_name, title, actual_hkl, hwnd=None):
    """Real bug found live, 2026-09-17 ("ping-pong" complaint): manual-override
    detection used to live ONLY inside on_focus_change, which only runs on a
    genuine Windows focus/title event. Switching the language yourself with
    Alt+Shift while staying in the exact same window (no title change) fires
    no such event — so the untrusted poll's very next Tier 3 check had no way
    to know you'd just corrected it, and could silently switch it right back.
    The only way to make CKILS notice was to alt-tab away and back, forcing a
    real event so on_focus_change would finally see the mismatch. Extracted
    so both the event path (on_focus_change) and the poll path
    (_poll_focused_window) can detect this the moment it happens, not only
    when the user happens to trigger a focus event afterward.

    Real regression found live, same day, right after shipping the above: a
    single mismatched read isn't reliable proof of a manual override.
    win32api.PostMessage(WM_INPUTLANGCHANGEREQUEST) is fire-and-forget — it
    doesn't guarantee Windows has actually applied the switch by the time the
    very next check runs, especially right after a slow Tier 3 correction
    (confirmed live taking 700ms-3+ seconds under load, far past the 0.3s
    SWITCH_GRACE window). Confirmed directly from the overrides table: the
    exact same Code.exe thread falsely "overrode" to Hebrew four separate
    times in one session while the user was just typing, each time freezing
    further correction and even feeding the bad reading into the trust
    history as if it were real. Fixed by requiring the SAME mismatch to be
    seen on two independent checks before it's trusted (pending_override) —
    a real manual switch is still caught within about one extra tick; a
    one-off propagation-lag reading resolves itself on the next check
    instead of ever being committed as fact.

    Returns True if a manual override was detected (and fully recorded,
    same as before) — the caller should treat this tick as "leave it alone"
    rather than run any further automatic correction.
    """
    if thread_id not in last_set:
        return False
    if actual_hkl == last_set[thread_id]:
        matched_this_visit.add(thread_id)  # from now on, a change in THIS window is a real change
        reassert_attempts.pop(thread_id, None)
        pending_override.pop(thread_id, None)
        return False
    just_switched = time.time() - last_switch_time.get(thread_id, 0) < SWITCH_GRACE
    if just_switched:
        pending_override.pop(thread_id, None)  # Windows hasn't caught up to our own post yet — not an override
        return False
    if thread_id not in matched_this_visit:
        # Never matched since arrival: carry-over from another window, not a manual switch.
        _handle_carry_over(thread_id, hwnd, exe_name, title, actual_hkl)
        return False

    pending_hkl, _ = pending_override.get(thread_id, (None, None))
    if pending_hkl != actual_hkl:
        # First time seeing this exact mismatch — note it, but a single
        # snapshot isn't enough to commit to. Let the caller's normal
        # correction path run this tick instead of freezing on one bad read.
        pending_override[thread_id] = (actual_hkl, time.time())
        return False

    # Same mismatch confirmed independently on a second check — trust it now.
    pending_override.pop(thread_id, None)
    overridden.add(thread_id)
    last_set[thread_id] = actual_hkl  # treat the user's manual choice as the new "last known" state
    log_override(exe_name, title, thread_id, actual_hkl)  # real, free evidence a recent decision was wrong
    # A manual override is the user telling CKILS, with certainty, what this
    # app/page should be — feed it into the same trust history a confident
    # Tier 3 decision uses, so this stops being a one-time log entry only a
    # monthly human review ever sees. One override is still just one data
    # point under the same TRUST_MIN_SAMPLES/TRUST_AGREEMENT_THRESHOLD rule as
    # everything else, so it can't single-handedly overwrite an otherwise
    # well-established default.
    override_language = HKL_TO_LANGUAGE_NAME.get(actual_hkl)
    if override_language is not None:
        save_learned_default(exe_name, override_language)
        save_page_learned_default(exe_name, title, override_language)
    decision_logger.log_manual_override(exe_name, title, thread_id, override_language)
    print(f"{exe_name}: manual override detected, leaving it alone")
    return True


_TITLE_COUNTER_PREFIX = re.compile(r"^\(\d+\)\s*")


def _site_of(title):
    """(site, app) from a window title shaped "page - site - app", e.g.
    ("Google Gemini", "Google Chrome") for both "Google Gemini - Google
    Chrome" and "My chat - Google Gemini - Google Chrome". None when the
    title doesn't have that shape — the caller then changes nothing.
    Direction marks and a leading unread counter ("(3) ") are ignored."""
    clean = _TITLE_COUNTER_PREFIX.sub("", DIRECTION_MARKS_PATTERN.sub("", title or "").strip())
    parts = [p.strip() for p in clean.split(" - ")]
    if len(parts) < 2 or not parts[-2] or not parts[-1]:
        return None
    return parts[-2], parts[-1]


def _same_site_hkl(thread_id, old_title, new_title):
    """Real finding, 2026-10-15: Gemini renamed a Hebrew chat ("Google
    Gemini" -> "חוקי סיום מילה בעברית - Google Gemini") and the layout
    flipped to English — no focus change, nothing typed. The new title had
    no page history, so the fast path fell back to Chrome's app-wide
    default, which for a browser hosting every kind of site is the weakest
    guess there is. When the SAME tab's title changes but the site stays the
    same, the language you're on right now is better evidence: returns it,
    or None to leave today's behavior. Deliberately conservative — titles
    whose site can't be read the same way on both sides change nothing.
    """
    old_site = _site_of(old_title)
    if old_site is None or old_site != _site_of(new_title):
        return None
    try:
        actual = win32api.GetKeyboardLayout(thread_id)
    except Exception:
        return None
    return actual if actual in (English_HKL, Hebrew_HKL) else None


def on_focus_change(hook, event, hwnd, id_object, id_child, thread_id, timestamp):
    """The Windows event callback (registered below via SetWinEventHook)
    that fires on every real foreground-window change and window-title
    change. Resets per-visit state when focus genuinely moves to a
    different thread/title, computes this window's target language from
    the layered fallback (sticky Tier 3 decision -> trusted page default ->
    trusted app default), applies it instantly via the fast path unless a
    manual override is detected, and kicks off a background Tier 3 check to
    confirm/correct it from real content.
    """
    global previous_thread
    # The instant focus leaves a window we were overriding, forget it ever happened —
    # its next visit starts completely fresh, learned default applied automatically.

    if event == win32con.EVENT_OBJECT_NAMECHANGE:
        if id_object != win32.lib.win32con.OBJID_WINDOW or id_child != win32.lib.win32con.CHILDID_SELF:
            return
        if hwnd != win32gui.GetForegroundWindow():
            return
    same_thread_as_before = previous_thread == thread_id
    if previous_thread is not None and previous_thread != thread_id:
        if previous_thread in overridden:
            overridden.discard(previous_thread)
            last_set.pop(previous_thread, None)
        content_decision.pop(previous_thread, None)  # fresh window = learned default first, again
        google_docs_title_already_applied.discard(previous_thread)
        _reset_visit_state(previous_thread)  # matched-state, re-asserts, unconfirmed mismatches: all end with the visit
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
    same_site_hkl = None
    if last_title_by_thread.get(thread_id) != title:
        if same_thread_as_before and last_title_by_thread.get(thread_id) is not None:
            same_site_hkl = _same_site_hkl(thread_id, last_title_by_thread[thread_id], title)
        content_decision.pop(thread_id, None)
        google_docs_title_already_applied.discard(thread_id)
        _reset_visit_state(thread_id)
        old_key = (thread_id, last_title_by_thread.get(thread_id))
        poll_unchanged_streak.pop(old_key, None)
        poll_next_allowed.pop(old_key, None)
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
    # A trusted history for this exact page still wins; only when there's
    # none does "same site, same tab" beat the app-wide guess.
    if page_hkl is not None:
        default_hkl = page_hkl
    elif same_site_hkl is not None:
        default_hkl = same_site_hkl
    else:
        default_hkl = app_hkl
    target_hkl = content_decision.get(thread_id, default_hkl)

    if target_hkl is not None:
        actual_hkl = win32api.GetKeyboardLayout(thread_id)
        if DEBUG:
            print(f"  [debug] {exe_name} hwnd={hwnd} thread={thread_id} title={title!r} actual={hex(actual_hkl)} last={hex(last_set.get(thread_id, -1))}")
        if _detect_and_record_manual_override(thread_id, exe_name, title, actual_hkl):
            pass
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
                elif same_site_hkl is not None:
                    fast_source = "same_site_title_change"
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
    """Runs Tier 3 (decide_with_content) in the calling thread and, if it
    confidently disagrees with fallback_hkl, applies the correction — but
    only if the same window/tab is still focused and not manually
    overridden by the time the (potentially slow) read finishes. Called
    from a fresh background thread by both on_focus_change and the poll.
    Returns True if a correction was actually applied, False otherwise
    (used by the poll path to track when a window has settled — see
    _poll_apply_content_correction).
    """
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
            return False
        if win32gui.GetForegroundWindow() != hwnd:
            if DEBUG:
                print(f"  [content] {exe_name}: decision arrived too late, focus moved on ({elapsed_ms:.0f} ms)")
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_FOCUS_MOVED, "result ready too late")
            return False
        # Real bug found live: Chrome's hwnd doesn't change between tabs, so the
        # check above alone can't tell "still the same window" apart from "same
        # window, but you've since switched to a different tab." Re-check the
        # window's CURRENT title still matches what this correction was actually
        # computed for — otherwise this is a stale result for a tab you've left.
        if win32gui.GetWindowText(hwnd) != title:
            if DEBUG:
                print(f"  [content] {exe_name}: decision is for a different tab now, discarding ({elapsed_ms:.0f} ms)")
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_STALE_DISCARDED)
            return False
        if thread_id in overridden:
            if DEBUG:
                print(f"  [content] {exe_name}: user has manually overridden this window, leaving it alone ({elapsed_ms:.0f} ms)")
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_OVERRIDE_RESPECTED)
            return False
        if thread_id in tier4_corrected:
            if DEBUG:
                print(f"  [content] {exe_name}: Tier 4 corrected this window from your typing, leaving it alone ({elapsed_ms:.0f} ms)")
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_TIER4_RESPECTED)
            return False
        if keyboard_hook.typed_recently(thread_id, title, TYPING_HOLD_SECONDS):
            # Found live 2026-10-17: a poll read claude.ai's "Let's noodle"
            # greeting (0.67) and switched Hebrew typing to English mid-
            # sentence. While the user is typing, the keystrokes are the
            # evidence (Tier 4 watches them) — a screen read waits.
            if DEBUG:
                print(f"  [content] {exe_name}: you're typing here, leaving the language alone ({elapsed_ms:.0f} ms)")
            skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_TYPING_RESPECTED)
            return False

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
        return True
    finally:
        content_check_in_progress.discard(check_key)


def apply_tier4_correction(hwnd, thread_id, exe_name, title, from_hkl, target_hkl, word_length):
    """Tier 4 Phase 2 (2026-10-14): switches the layout because the user's
    own keystrokes came out as wrong-layout gibberish (keyboard_hook.py calls
    this through the callback handed to keyboard_hook.start()). Returns True
    if the switch was posted.

    Goes through the same bookkeeping as every other CKILS switch, on
    purpose: posting WM_INPUTLANGCHANGEREQUEST behind this module's back
    would leave last_set stale, and _detect_and_record_manual_override would
    then see "layout != what CKILS last set" and record Tier 4's own switch
    as the USER's manual override — the exact false-override bug class from
    2026-09-17/19, freezing correction and teaching learned defaults the
    wrong thing.

    Design decisions made with the user, 2026-10-14:
      - A real manual override always wins: skipped if thread_id is in
        `overridden` (same lifecycle — clears when focus leaves and returns).
      - Does NOT feed learned defaults (no save_learned_default /
        save_page_learned_default): Tier 4 is a narrow structural signal,
        not a full content read, and must not contaminate trust history.
        content_decision IS set, so this visit's own fast path re-applies
        it instead of undoing it — per-visit only, never persisted.
      - Logged via decision_logger with mechanism "tier4_gibberish" and NO
        screenshot_rect: a screenshot here would capture the very garbled
        characters the user just typed, breaking Tier 4's guarantee that
        typed content is never written to disk.
    """
    if thread_id in overridden:
        skip_logger.log_skip(exe_name, title, thread_id, skip_logger.REASON_OVERRIDE_RESPECTED, "tier4")
        return False
    if win32gui.GetForegroundWindow() != hwnd:
        return False  # focus moved on between the keystroke and this call
    win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
    last_set[thread_id] = target_hkl
    last_switch_time[thread_id] = time.time()
    content_decision[thread_id] = target_hkl
    tier4_corrected.add(thread_id)
    decision_logger.log_auto_change(
        exe_name, title, thread_id,
        HKL_TO_LANGUAGE_NAME.get(from_hkl), HKL_TO_LANGUAGE_NAME.get(target_hkl),
        {"mechanism": "tier4_gibberish", "word_length": word_length},
    )
    print(f"{exe_name}: Tier 4 auto-correction to {hex(target_hkl)} (wrong-layout word, {word_length} keys)")
    return True

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
    """Background timer loop, started once at startup: every
    UNTRUSTED_POLL_SECONDS, checks whatever window currently has focus for
    (a) a silent manual override with no accompanying focus/title event,
    and (b) content that may have changed with no accompanying event either
    (the WhatsApp-shape gap this poll exists for) — deduping against
    in-flight checks and honoring each key's backoff state (see
    poll_next_allowed) so an already-settled window isn't hammered forever.
    """
    while True:
        time.sleep(UNTRUSTED_POLL_SECONDS)
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe_name = psutil.Process(pid).name()
        except Exception:
            continue  # window vanished or info unavailable between calls — just skip this tick

        # Real bug found live, 2026-09-17: a manual Alt+Shift switch that doesn't
        # also change focus or title fires no Windows event at all, so this poll
        # used to have no idea it had just happened — it would go ahead and read
        # content, and could silently switch the language right back, undoing
        # the user's own correction. Checking for it here, on every tick, means
        # the very next poll after a silent manual switch (well within
        # UNTRUSTED_POLL_SECONDS) notices and records it — not "whenever the
        # user happens to alt-tab away and back."
        if thread_id in last_set:
            try:
                actual_hkl = win32api.GetKeyboardLayout(thread_id)
            except Exception:
                actual_hkl = None
            if actual_hkl is not None and _detect_and_record_manual_override(thread_id, exe_name, title, actual_hkl, hwnd):
                continue  # just recorded a fresh override — don't immediately fight it with a Tier 3 read

        check_key = (thread_id, title)
        if check_key in content_check_in_progress:
            continue  # a check for this same title (from an event or a previous tick) is already in flight
        if time.time() < poll_next_allowed.get(check_key, 0.0):
            continue  # this exact window+title has already settled — see poll_unchanged_streak below
        content_check_in_progress.add(check_key)
        threading.Thread(
            target=_poll_apply_content_correction,
            args=(hwnd, thread_id, exe_name, last_set.get(thread_id), title, check_key),
            daemon=True
        ).start()


def _poll_apply_content_correction(hwnd, thread_id, exe_name, fallback_hkl, title, check_key):
    """Poll-only wrapper around apply_content_correction: runs the same
    correction, then updates check_key's backoff bookkeeping based on
    whether anything actually changed — a real change resets the streak to
    full speed, while repeated no-ops push this key toward a slower
    re-check interval (see poll_unchanged_streak/poll_next_allowed).
    """
    # Thin wrapper around apply_content_correction just for the poll path — tracks
    # whether this specific (thread_id, title) keeps coming back unchanged so this
    # timer can stop hammering it with full OCR reads once it has (see
    # poll_unchanged_streak/poll_next_allowed above). Event-driven checks (a real
    # focus or title change) go straight to apply_content_correction and never
    # touch this bookkeeping — a real event always deserves a fresh, full-speed look.
    try:
        changed = apply_content_correction(hwnd, thread_id, exe_name, fallback_hkl, title)
    except Exception:
        changed = False
    if changed:
        poll_unchanged_streak.pop(check_key, None)
        poll_next_allowed.pop(check_key, None)
    else:
        streak = poll_unchanged_streak.get(check_key, 0) + 1
        poll_unchanged_streak[check_key] = streak
        if streak >= POLL_BACKOFF_STREAK_THRESHOLD:
            poll_next_allowed[check_key] = time.time() + POLL_BACKOFF_SECONDS


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
    # Tier 4: off unless the user has explicitly created
    # enable_gibberish_detection.on next to CKILS — see keyboard_hook.py's own
    # module docstring for why this one, alone among everything else here,
    # defaults to off rather than on. Phase 2's actual correction is a second,
    # separate opt-in (enable_gibberish_autocorrect.on), checked live. The
    # callback is passed in rather than imported by keyboard_hook: in the
    # packaged exe this module runs as __main__, so `import rule_engine` from
    # inside keyboard_hook would load a SECOND copy with its own empty
    # `overridden`/`last_set` — silently breaking override respect.
    keyboard_hook.start(English_HKL, Hebrew_HKL, on_autocorrect=apply_tier4_correction)
    skip_logger.start()

    callback = WinEventProcType(on_focus_change)
    hook = user32.SetWinEventHook(
        win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
        0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT)

    name_hook = user32.SetWinEventHook(win32con.EVENT_OBJECT_NAMECHANGE,
        win32con.EVENT_OBJECT_NAMECHANGE,0,callback,0,0,win32con.WINEVENT_OUTOFCONTEXT)
    auto.InitializeUIAutomationInCurrentThread()  # once, before the message loop — needed by decide_with_content()
    print("CKILS is watching in the background. Press Ctrl+C in this window to stop.")
    win32gui.PumpMessages()
