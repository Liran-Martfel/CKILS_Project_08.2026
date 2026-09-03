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
import uiautomation as auto
from ocr_reader import read_region
from predict_language import predict_language

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
        learned_defaults[exe_name] = language_name
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
        page_learned_defaults[_page_key(exe_name, title)] = language_name
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


# Real finding: Chrome's own PDF viewer exposes a generic status message
# through the control's Name - "מסמך ה-PDF מכיל N דפים" ("This PDF document
# contains N pages") - completely unrelated to the actual PDF's content, but
# long enough and Hebrew enough to fool the accessible-text shortcut into
# classifying EVERY PDF as Hebrew regardless of what's actually in it.
GENERIC_ACCESSIBLE_TEXT_MARKERS = ["מכיל", "דפים"]


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
    return True


def decide_with_content(fallback_hkl, title, exe_name, thread_id):
    """
    Falls back to fallback_hkl (Tier 1/2's answer, possibly None) on an empty
    field, low model confidence, or any failure in this layer — Tier 1/2 stays
    the proven base (Week 4: "Go with Conditions"), this only adds to it.
    """
    try:
        control = auto.GetFocusedControl()
        rect = control.BoundingRectangle
    except Exception as e:
        if DEBUG:
            print(f"  [content] skipped ({e})")
        return fallback_hkl

    accessible_text = (control.Name or "").strip()
    if _looks_like_real_content(accessible_text, title):
        text = accessible_text
        source = "accessible_text"
        if DEBUG:
            print(f"  [content] read from accessible text, no OCR needed: {text[:60]!r}")
    elif not _is_onscreen(rect):
        if DEBUG:
            print(f"  [content] control rect is off-screen ({rect.left},{rect.top}) — skipping OCR")
        return fallback_hkl
    else:
        try:
            right = min(rect.right, rect.left + MAX_OCR_WIDTH)
            bottom = min(rect.bottom, rect.top + MAX_OCR_HEIGHT)
            text = read_region(rect.left, rect.top, right, bottom)
            source = "ocr"
        except Exception as e:
            if DEBUG:
                print(f"  [content] skipped ({e})")
            return fallback_hkl

    if not text.strip():
        if DEBUG:
            print("  [content] empty field, nothing to read")
        return fallback_hkl

    try:
        label, proba = predict_language(text)
    except Exception as e:
        # Any future error in the model/prediction pipeline (not just the ones
        # already found and fixed) falls back gracefully here now, same as OCR.
        if DEBUG:
            print(f"  [content] skipped ({e})")
        return fallback_hkl
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
        return fallback_hkl

    return LANGUAGE_TO_HKL[label]

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
        last_title_by_thread[thread_id] = title

    # Layered fallback, most specific first: this visit's own decision (if Tier 3
    # already confidently decided this exact window) -> this exact page's learned
    # history (seen this app+title combination decide confidently before) ->
    # this app's general learned history -> nothing.
    page_hkl = LANGUAGE_NAME_TO_HKL.get(page_learned_defaults.get(_page_key(exe_name, title)))
    app_hkl = LANGUAGE_NAME_TO_HKL.get(learned_defaults.get(exe_name))
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
            print(f"{exe_name}: manual override detected, leaving it alone")
        else:
            # This is the fast path — unchanged from Weeks 2-4, still sub-millisecond.
            # Tier 3 (below) never blocks this; it only corrects it afterward if needed.
            start = time.perf_counter()
            win32api.PostMessage(hwnd, win32con.WM_INPUTLANGCHANGEREQUEST, 0, target_hkl)
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f'{exe_name}: switched to {hex(target_hkl)} in {elapsed_ms:.1f} ms')
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
    if thread_id not in content_check_in_progress:
        content_check_in_progress.add(thread_id)
        threading.Thread(
            target=apply_content_correction,
            args=(hwnd, thread_id, exe_name, target_hkl, title),
            daemon=True
        ).start()


def apply_content_correction(hwnd, thread_id, exe_name, fallback_hkl, title):
    # Held for the whole function, not just the OCR part — this is what actually
    # stops two corrections for the same window from racing on last_set/overridden.
    try:
        # COM (which UI Automation needs) is initialized per THREAD, not once for the
        # whole process — this function runs in a new background thread every time,
        # so it needs its own init call here, separate from the one before PumpMessages().
        auto.InitializeUIAutomationInCurrentThread()

        start = time.perf_counter()
        corrected_hkl = decide_with_content(fallback_hkl, title, exe_name, thread_id)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if corrected_hkl == fallback_hkl or corrected_hkl is None:
            if DEBUG:
                print(f"  [content] {exe_name}: no change ({elapsed_ms:.0f} ms)")
            return
        if win32gui.GetForegroundWindow() != hwnd:
            if DEBUG:
                print(f"  [content] {exe_name}: decision arrived too late, focus moved on ({elapsed_ms:.0f} ms)")
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
        save_learned_default(exe_name, language_name)  # this app in general
        save_page_learned_default(exe_name, title, language_name)  # this exact page — both genuinely AI-learned
        print(f"{exe_name}: content-aware correction to {hex(corrected_hkl)} ({elapsed_ms:.0f} ms)")
    finally:
        content_check_in_progress.discard(thread_id)

callback = WinEventProcType(on_focus_change)
hook = user32.SetWinEventHook(
    win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_SYSTEM_FOREGROUND,
    0, callback, 0, 0, win32con.WINEVENT_OUTOFCONTEXT)

name_hook = user32.SetWinEventHook(win32con.EVENT_OBJECT_NAMECHANGE,
    win32con.EVENT_OBJECT_NAMECHANGE,0,callback,0,0,win32con.WINEVENT_OUTOFCONTEXT)
auto.InitializeUIAutomationInCurrentThread()  # once, before the message loop — needed by decide_with_content()
print("CKILS is watching in the background. Press Ctrl+C in this window to stop.")
win32gui.PumpMessages()
