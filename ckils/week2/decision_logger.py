"""
CKILS's diagnostic memory: a persistent, timestamped log of every real
language decision (automatic or manual), each with the reasoning behind it
and a screenshot cropped to exactly the region read — so a wrong guess can
be diagnosed from real evidence later instead of guessed at. rule_engine.py
calls log_auto_change/log_manual_override on every real decision;
review_decisions.py later reads this data back to find cases worth a human's
attention. Old entries and their screenshots are pruned automatically after
RETENTION_DAYS so this doesn't grow forever.
"""
import os
import sys
import json
import glob
import time
import threading
import datetime
from PIL import ImageGrab

# Mirrors rule_engine.py's own _persistent_dir(): a packaged .exe's __file__
# resolves inside a temporary extraction folder that vanishes on close, so
# anything meant to persist across runs needs the exe's real, permanent
# folder instead. Duplicated here (not imported from rule_engine) to avoid a
# circular import, same pattern ocr_reader.py already uses for its own paths.
def _persistent_dir():
    """Returns the folder decision logs/screenshots should actually live in:
    the real exe's own folder when frozen (packaged), or this script's own
    folder when running from source — never a temporary extraction path.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DEBUG = True

LOGS_DIR = os.path.join(_persistent_dir(), "logs")
SCREENSHOTS_DIR = os.path.join(LOGS_DIR, "screenshots")
LOG_FILE = os.path.join(LOGS_DIR, "decisions.jsonl")
RETENTION_DAYS = 60

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

_log_lock = threading.Lock()

# thread_id -> the most recently logged automatic decision for that window.
# When a manual override follows shortly after, it references this instead of
# duplicating a full reasoning/screenshot entry for the manual act itself —
# per design, a manual change only ever gets "here's what CKILS decided, and
# why, right before you corrected it," never its own detailed entry.
_last_auto_decision = {}
_last_auto_lock = threading.Lock()


def _safe_filename_part(text, max_len=40):
    """Sanitizes text (typically an exe name) into something safe to embed
    in a filename — non-alphanumeric characters become underscores, and the
    result is capped at max_len characters ("unknown" if nothing is left).
    """
    kept = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in text)
    return kept[:max_len] or "unknown"


def _capture_screenshot(rect, exe_name, event_type):
    """Screenshots exactly rect (left, top, right, bottom) and saves it under
    SCREENSHOTS_DIR with a timestamped, sanitized filename. Returns the
    saved file's path relative to LOGS_DIR (for embedding in a log entry),
    or None if rect is missing/invalid or the capture fails.
    """
    # Cropped to the actual read region (or window rect for a fast-path
    # switch), not the full screen — smaller files and avoids capturing
    # unrelated on-screen content (e.g. another app, or other people's video
    # during a call) that has nothing to do with the decision being logged.
    if rect is None:
        return None
    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return None
    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{_safe_filename_part(exe_name)}_{event_type}.png"
        path = os.path.join(SCREENSHOTS_DIR, filename)
        img.save(path)
        return os.path.join("screenshots", filename)
    except Exception as e:
        if DEBUG:
            print(f"  [log] screenshot capture failed ({e})")
        return None


def _append(entry):
    """Appends one JSON entry as a new line to LOG_FILE, under a lock so
    concurrent decision threads never interleave partial writes.
    """
    with _log_lock:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            if DEBUG:
                print(f"  [log] failed to write decision log ({e})")


def log_auto_change(exe_name, title, thread_id, previous_language, new_language, reason):
    """Call whenever CKILS itself changes the active language for a window —
    the fast-path switch (Tier 1/2) or a Tier 3 content correction. Never for
    a manual switch — see log_manual_override for that."""
    screenshot = _capture_screenshot(reason.get("screenshot_rect"), exe_name, "auto")
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "event_type": "auto",
        "exe_name": exe_name,
        "title": title,
        "thread_id": thread_id,
        "previous_language": previous_language,
        "new_language": new_language,
        "reason": {k: v for k, v in reason.items() if k != "screenshot_rect"},
        "screenshot": screenshot,
    }
    _append(entry)
    with _last_auto_lock:
        _last_auto_decision[thread_id] = entry


def log_manual_override(exe_name, title, thread_id, new_language):
    """Call whenever a manual override is detected. Per design: no separate
    screenshot or detailed reasoning for the manual act itself — just the
    automatic decision (if any) that was in effect immediately before it."""
    with _last_auto_lock:
        preceding_auto = _last_auto_decision.get(thread_id)
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "event_type": "manual_override",
        "exe_name": exe_name,
        "title": title,
        "thread_id": thread_id,
        "new_language": new_language,
        "preceding_auto": preceding_auto,
    }
    _append(entry)


def prune_old_logs():
    """Drops every log entry older than RETENTION_DAYS and deletes any
    screenshot no longer referenced by a surviving entry (including
    screenshots referenced only via another entry's preceding_auto). Keeps
    the log and screenshots folder from growing forever.
    """
    cutoff = datetime.datetime.now() - datetime.timedelta(days=RETENTION_DAYS)
    if not os.path.exists(LOG_FILE):
        return

    with _log_lock:
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return

        kept_lines = []
        kept_screenshots = set()
        for line in lines:
            try:
                entry = json.loads(line)
                ts = datetime.datetime.fromisoformat(entry["timestamp"])
            except Exception:
                continue  # drop unparseable lines rather than let them accumulate forever
            if ts < cutoff:
                continue
            kept_lines.append(line)
            shot = entry.get("screenshot")
            if shot:
                kept_screenshots.add(os.path.basename(shot))
            preceding = entry.get("preceding_auto")
            if preceding and preceding.get("screenshot"):
                kept_screenshots.add(os.path.basename(preceding["screenshot"]))

        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(kept_lines)
        except Exception as e:
            if DEBUG:
                print(f"  [log] failed to rewrite pruned log ({e})")

    # Anything not referenced by a still-kept entry (its own entry aged out,
    # or it belongs to an aged-out entry another one was pointing at) gets
    # deleted here rather than left to accumulate forever.
    for path in glob.glob(os.path.join(SCREENSHOTS_DIR, "*.png")):
        if os.path.basename(path) not in kept_screenshots:
            try:
                os.remove(path)
            except Exception:
                pass


_PRUNE_INTERVAL_SECONDS = 6 * 60 * 60


def _prune_loop():
    """Calls prune_old_logs() forever, once every _PRUNE_INTERVAL_SECONDS."""
    while True:
        time.sleep(_PRUNE_INTERVAL_SECONDS)
        prune_old_logs()


def start_background_pruning():
    """Prunes once immediately (so a long-overdue backlog doesn't wait for
    the first interval to elapse), then starts the periodic background
    pruning thread. Called once at CKILS startup.
    """
    prune_old_logs()  # once immediately at startup, then every 6 hours
    threading.Thread(target=_prune_loop, daemon=True).start()
