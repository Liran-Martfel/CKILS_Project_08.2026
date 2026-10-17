"""
CKILS's "why did it do nothing?" log.

WHAT IT IS
    decision_logger.py and rule_engine.py's decisions table only record checks
    that ended in a decision. When a check ends WITHOUT one (nothing readable,
    text rejected as UI noise, you left before the read finished...), nothing
    was recorded at all — so a failure to switch the language left no trace,
    and finding the cause needed a live reproduction. This module records one
    small row for each such check, with a reason code, so the cause can be read
    straight from the log later. It changes NO decision and NO return value: it
    only observes.

REASON CODES (what each one means, and what it usually tells you)
    empty_field       The region read was blank. Typical: a brand-new empty chat
                      or an empty compose box — nothing exists yet to decide from.
    rejected_noise    Text WAS read but recognised as UI chrome (a placeholder, a
                      logo, a tagline) and deliberately ignored. `detail` holds
                      the first 60 characters, to show what was rejected.
    off_screen        The focused control's rectangle lies outside every monitor
                      (e.g. Google Docs' document-scroll coordinates), so OCR
                      would only capture blackness.
    read_failed       Something raised while reading or classifying; `detail` is
                      the exception CLASS NAME only (never the message, which
                      could contain screen text).
    focus_moved       You left the window before the read finished.
    stale_discarded   A result was ready but the tab/title had changed meanwhile,
                      so it was thrown away.
    override_respected  A result was ready but you had manually overridden the
                      window, so CKILS correctly left it alone.
    docs_title_used   Google Docs' one-time title default was already spent for
                      this visit, so nothing new was applied.
    carryover_reasserted  The layout differed from CKILS's decision since arriving (Windows
                      shares the language across windows), so CKILS re-posted its own
                      decision instead of calling it a manual override; `detail` = attempt no.
    carryover_accepted  CKILS gave up re-asserting (or had decided nothing this visit) and
                      accepted the layout Windows insists on, still without recording an override.
    gibberish_suspected  Tier 4 Phase 1 (keyboard_hook.py): the current word looked
                      structurally impossible in the active layout's language, AND the
                      same physical keys looked plausible under the other layout —
                      exactly what a wrong-layout typo looks like. Phase 1 never
                      corrects anything; `detail` is language names and a key COUNT
                      only, never the characters actually typed (see keyboard_hook.py's
                      own privacy guarantees).
    tier4_respected   A Tier 3 result was ready, but Tier 4 Phase 2 had already
                      auto-corrected this window's layout from the user's own
                      keystrokes this visit, so Tier 3 left it alone (same idea as
                      override_respected — typing evidence outranks an OCR read).
    typed_respected   A Tier 3 result was ready, but it disagreed with the
                      language the user has actually typed most in this window
                      (keyboard_hook.typed_language), so Tier 3 left it alone.
    typing_respected  A Tier 3 result was ready, but the user had typed in this
                      window within the last few seconds, so Tier 3 left the
                      language alone — mid-sentence is never the moment for a
                      screen read to change it (Tier 4 watches the typing itself).
  Not logged, by design: routine "no change" results, the poll's backoff skips
  and its in-flight de-duplication — they are normal operation, not failures,
  and logging them would flood the file.

DESIGN GUARANTEES (each one exists to prevent a specific bug — see the plan)
    1. Never raises. Every public function swallows all exceptions, so a fault
       here can never stop a language correction.
    2. Never blocks the correction thread. log_skip() only does dictionary
       lookups and a non-blocking queue put; ALL disk I/O happens on one
       separate writer thread, so no lock or sqlite call is ever awaited by the
       switching logic.
    3. Its own database file (ckils_skips.db). It shares no lock, table or file
       with ckils_decisions.db, and review_decisions.py never reads it, so it
       cannot slow the decision log or reach the classifier's training data.
    4. Bounded everywhere: the queue (QUEUE_MAX; extra rows are dropped, never
       waited on), the de-duplication memory (MAX_TRACKED_KEYS), rows per hour
       (MAX_ROWS_PER_HOUR) and row age (RETENTION_DAYS).
    5. Inert until start() is called. Importing this module (as the test suite
       does) opens no file and starts no thread.
    6. Privacy: only the first MAX_DETAIL_CHARS characters of rejected UI text
       are stored. Local only, same 60-day retention as the decision log.

IF SOMETHING GOES WRONG — the failure plan (read this before changing anything
else in CKILS, so a bug here never becomes a reason to undo other work)
    Symptom -> action, cheapest first:
      a) ANY suspected problem, no rebuild needed: create an empty file named
         skip_logging.off next to CKILS.exe and restart CKILS. The logger then
         never starts. The rest of CKILS is unaffected.
      b) The writer keeps failing: it turns itself off after
         WRITER_FAILURE_LIMIT consecutive failures and prints one line to the
         console. Nothing else changes; you can ignore it until convenient.
      c) The log file grows too large: delete ckils_skips.db (safe — CKILS
         recreates it). If it recurs, lower MAX_ROWS_PER_HOUR.
      d) Corrections feel slower or CPU rises: apply (a) FIRST, then check
         whether it goes away. If it does, the logger was the cause; if not,
         it was never the logger — do not roll anything else back.
      e) Full rollback: `git revert` the single commit that added this module.
         It touches only this file, summarize_skips.py, its tests, and one-line
         log_skip() calls in rule_engine.py, so reverting it restores the
         previous behaviour exactly.
    Never "fix" a problem here by editing decision logic in rule_engine.py.
"""
import collections
import datetime
import os
import queue
import sqlite3
import sys
import threading
import time

REASON_EMPTY_FIELD = "empty_field"
REASON_REJECTED_NOISE = "rejected_noise"
REASON_OFF_SCREEN = "off_screen"
REASON_READ_FAILED = "read_failed"
REASON_FOCUS_MOVED = "focus_moved"
REASON_STALE_DISCARDED = "stale_discarded"
REASON_OVERRIDE_RESPECTED = "override_respected"
REASON_DOCS_TITLE_USED = "docs_title_used"
REASON_CARRYOVER_REASSERTED = "carryover_reasserted"
REASON_CARRYOVER_ACCEPTED = "carryover_accepted"
REASON_GIBBERISH_SUSPECTED = "gibberish_suspected"  # Tier 4 Phase 1 (keyboard_hook.py) — logged for every detection
REASON_TIER4_RESPECTED = "tier4_respected"          # Tier 3 held off: Tier 4 already corrected this window from real typing this visit
REASON_TYPING_RESPECTED = "typing_respected"        # Tier 3 held off: the user was typing in this window just now
REASON_TYPED_RESPECTED = "typed_respected"          # Tier 3 held off: it disagreed with what the user typed most in this window

ENABLED = True
KILL_SWITCH_FILENAME = "skip_logging.off"
DEDUPE_WINDOW_SECONDS = 600     # same window + title + reason is logged at most once per this long
MAX_ROWS_PER_HOUR = 120         # hard global cap, protects against volatile titles (e.g. unread counters)
QUEUE_MAX = 500                 # rows waiting for the writer; more are dropped, never waited on
MAX_TRACKED_KEYS = 2000         # bound on the de-duplication memory
RETENTION_DAYS = 60             # matches the decision log's retention
MAX_DETAIL_CHARS = 60           # privacy: how much rejected text is ever stored
WRITER_FAILURE_LIMIT = 5        # consecutive write failures before the logger disables itself


def _persistent_dir():
    """Returns the folder that survives between runs: the real exe's own
    folder when packaged, or this script's folder when run from source (never
    the temporary extraction folder — same rule decision_logger.py follows).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DB_FILE = os.path.join(_persistent_dir(), "ckils_skips.db")
KILL_SWITCH_PATH = os.path.join(_persistent_dir(), KILL_SWITCH_FILENAME)

_lock = threading.Lock()
_last_logged = {}                      # (thread_id, title, reason) -> time.time() it was last queued
_recent_stamps = collections.deque()   # queue-times within the last hour, for the rate cap
_queue = queue.Queue(maxsize=QUEUE_MAX)
_started = False
_disabled_reason = None                # set once the logger has turned itself off (or was never allowed on)


def log_skip(exe_name, title, thread_id, reason, detail=None):
    """Records that a check ended without a decision, and why. Safe to call
    from anywhere, any number of times: it never raises, never touches the
    disk, and returns immediately. A repeat of the same (thread, title,
    reason) within DEDUPE_WINDOW_SECONDS, or anything beyond
    MAX_ROWS_PER_HOUR, or anything while the queue is full, is silently
    dropped. `detail` (optional short text) is truncated to MAX_DETAIL_CHARS.

    REASON_GIBBERISH_SUSPECTED is exempt from the dedupe window (the
    MAX_ROWS_PER_HOUR cap still applies as a safety net): unlike a noisy,
    repeat-every-poll reason like empty_field, a real Tier 4 detection is
    rare by construction and the user explicitly asked, 2026-10-11, that
    every one be logged — Phase 1's whole purpose is counting real
    detections accurately, and the dedupe window could otherwise silently
    drop a second real wrong-layout word typed in the same window/tab
    within DEDUPE_WINDOW_SECONDS (10 minutes) of the first.
    """
    try:
        if not ENABLED or _disabled_reason is not None:
            return
        now = time.time()
        key = (thread_id, title, reason)
        with _lock:
            if reason != REASON_GIBBERISH_SUSPECTED:
                last = _last_logged.get(key)
                if last is not None and now - last < DEDUPE_WINDOW_SECONDS:
                    return
            cutoff = now - 3600
            while _recent_stamps and _recent_stamps[0] < cutoff:
                _recent_stamps.popleft()
            if len(_recent_stamps) >= MAX_ROWS_PER_HOUR:
                return
            if len(_last_logged) >= MAX_TRACKED_KEYS:
                _last_logged.clear()
            _last_logged[key] = now
            _recent_stamps.append(now)
        short_detail = str(detail)[:MAX_DETAIL_CHARS] if detail else None
        _queue.put_nowait((datetime.datetime.now().isoformat(), exe_name, title, thread_id, reason, short_detail))
    except Exception:
        return


def _init_db(conn):
    """Creates the skipped_reads table if missing and deletes rows older than
    RETENTION_DAYS. Runs once, on the writer thread, at startup.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skipped_reads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            exe_name TEXT,
            title TEXT,
            thread_id INTEGER,
            reason TEXT NOT NULL,
            detail TEXT
        )
    """)
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM skipped_reads WHERE timestamp < ?", (cutoff,))
    conn.commit()


def _writer_loop():
    """The only place that touches the disk: pulls queued rows and inserts
    them into DB_FILE, one short connection per row. After
    WRITER_FAILURE_LIMIT failures in a row it disables the logger and stops
    (see the failure plan above) rather than retrying forever.
    """
    global _disabled_reason
    try:
        conn = sqlite3.connect(DB_FILE, timeout=5)
        try:
            _init_db(conn)
        finally:
            conn.close()
    except Exception as e:
        _disabled_reason = f"could not initialise {DB_FILE} ({type(e).__name__})"
        print(f"  [skip_logger] disabled: {_disabled_reason}")
        return

    failures = 0
    while True:
        try:
            row = _queue.get()
            if row is None:  # stop sentinel (used by the tests to shut the writer down cleanly)
                return
            conn = sqlite3.connect(DB_FILE, timeout=5)
            try:
                conn.execute(
                    "INSERT INTO skipped_reads (timestamp, exe_name, title, thread_id, reason, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?)", row)
                conn.commit()
            finally:
                conn.close()
            failures = 0
        except Exception as e:
            failures += 1
            if failures >= WRITER_FAILURE_LIMIT:
                _disabled_reason = f"{failures} consecutive write failures ({type(e).__name__})"
                print(f"  [skip_logger] disabled itself: {_disabled_reason}")
                return


def start():
    """Starts the background writer, once. Does nothing (and stays disabled)
    if the kill-switch file skip_logging.off exists next to CKILS. Never
    raises. Called once from rule_engine.py's startup block.
    """
    global _started, _disabled_reason
    try:
        if _started:
            return
        if os.path.exists(KILL_SWITCH_PATH):
            _disabled_reason = f"kill-switch file present ({KILL_SWITCH_FILENAME})"
            print(f"  [skip_logger] not started: {_disabled_reason}")
            return
        _started = True
        threading.Thread(target=_writer_loop, daemon=True).start()
    except Exception:
        return
