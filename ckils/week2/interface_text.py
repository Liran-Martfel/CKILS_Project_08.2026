"""
Learns which text on screen is an app's own interface, not the user's content
(future idea "learn where the real text is", built 2026-10-18).

Measured on the decision log first: the screen reads that switched the
language wrongly were mostly the same interface strings read again and again
— Chrome's address-bar placeholder, YouTube's player label, the Gemini and
Claude input placeholders, Chrome's translate notice, WhatsApp's chat-list
header, "Claude Code conversation". Each had been found by hand and added to
a hand-written list, one at a time. Real content changes from page to page;
interface text repeats. So this learns it by itself: once the exact same text
has been read on PAGES_TO_LEARN other pages of the same app (for Chrome, the
same site), it is the app's interface, and Tier 3 never decides on it.
Replayed on the log: all 26 texts it would have blocked were interface text,
none was the user's writing.

Privacy: only fingerprints are stored — a short SHA-256 hash of the app/site,
of the text and of each page title. No readable text, title or site name is
ever written to disk. The file (interface_text.json, next to CKILS) is
personal data like the learned defaults: never committed, never packaged.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time

PAGES_TO_LEARN = 3         # read on this many OTHER pages of the app: interface text
MAX_TEXTS_PER_APP = 3000   # oldest dropped first; keeps the file small
SAVE_EVERY_SECONDS = 60    # writes are batched; at most this much learning is lost on exit

_MARKS = re.compile("[‎‏‪-‮]")
_COUNTER = re.compile(r"^\(\d+\)\s*")


def _persistent_dir():
    """The exe's own folder when packaged, or this script's folder from
    source — same rule as skip_logger and the learned defaults."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


FILE = os.path.join(_persistent_dir(), "interface_text.json")


def _fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _clean_title(title):
    return _COUNTER.sub("", _MARKS.sub("", title or "").strip())


def _app(exe_name, title):
    """The app, or for a browser tab title shaped "page - site - browser"
    the site: interface text belongs to a site, not to all of Chrome."""
    parts = [p.strip() for p in _clean_title(title).split(" - ")]
    return _fingerprint(f"{exe_name}|{parts[-2]}" if len(parts) >= 3 else exe_name)


def _text(text):
    return _fingerprint(re.sub(r"\s+", " ", _MARKS.sub("", text or "")).strip().lower())


def _page(title):
    return _fingerprint(_clean_title(title))


_lock = threading.Lock()
_last_save = 0.0
_dirty = False


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_data = _load()  # {app: {text: [page, ...]}} — fingerprints only


def pages_seen(exe_name, title, text):
    """On how many OTHER pages of this app the same text was read before."""
    with _lock:
        pages = _data.get(_app(exe_name, title), {}).get(_text(text), [])
        return len([p for p in pages if p != _page(title)])


def is_interface_text(exe_name, title, text):
    return pages_seen(exe_name, title, text) >= PAGES_TO_LEARN


def record(exe_name, title, text):
    """Remembers that this text was read on this page. Saves at most once a
    minute; a save failure only loses learning, never breaks a read."""
    global _dirty
    if not (text or "").strip():
        return
    with _lock:
        texts = _data.setdefault(_app(exe_name, title), {})
        key, page = _text(text), _page(title)
        pages = texts.pop(key, [])  # re-inserted below: most recently read last
        if page not in pages and len(pages) <= PAGES_TO_LEARN:
            pages.append(page)
            _dirty = True
        texts[key] = pages
        while len(texts) > MAX_TEXTS_PER_APP:
            texts.pop(next(iter(texts)))
    save_if_due()


def save_if_due(force=False):
    global _last_save, _dirty
    if not _dirty or (not force and time.time() - _last_save < SAVE_EVERY_SECONDS):
        return
    with _lock:
        snapshot = json.dumps(_data, separators=(",", ":"))
        _dirty = False
    _last_save = time.time()
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            f.write(snapshot)
    except Exception:
        pass


def seed_from_log(dist):
    """One-time start from the reads already in the local decision database
    (ckils_decisions.db, read-only), so the learning works from day one on
    this computer. Returns how many reads were replayed."""
    import sqlite3
    db = sqlite3.connect(f"file:{os.path.join(dist, 'ckils_decisions.db')}?mode=ro", uri=True)
    rows = db.execute("SELECT exe_name, title, source, text FROM decisions ORDER BY timestamp").fetchall()
    db.close()
    n = 0
    for exe_name, title, source, text in rows:
        if source != "google_docs_title" and text:
            record(exe_name, title, text)
            n += 1
    save_if_due(force=True)
    return n


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--seed":
        FILE = os.path.join(sys.argv[2], "interface_text.json")
        _data.clear()
        print(f"replayed {seed_from_log(sys.argv[2])} reads into {FILE}")
    else:
        print("usage: python interface_text.py --seed <dist folder>")
