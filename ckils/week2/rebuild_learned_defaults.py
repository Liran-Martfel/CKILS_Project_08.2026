"""Rebuilds the learned-defaults histories of every key touched by a recorded override.

A recorded override wrote its language into the trust history as if the user had chosen it; ~72% of them were
false detections (carry-over). Keys never touched by any recorded override are left exactly as they are. Touched
keys are rebuilt by replaying, in time order, the reliable events available: confident Tier 3 corrections (from
decisions.jsonl) plus the overrides NOT classified as carry-over. Usage: python rebuild_learned_defaults.py [--apply]
"""
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
APPLY = "--apply" in sys.argv
HISTORY = 8  # TRUST_HISTORY_LENGTH


def trust(hist):
    """Same rule as rule_engine._trust: >=3 samples and >=80% agreement."""
    if len(hist) < 3:
        return None
    h, e = hist.count("hebrew"), hist.count("english")
    return ("hebrew" if h > e else "english") if max(h, e) / len(hist) >= 0.8 else None


def hist_of(v):
    if v is None:
        return []
    return list(v.get("history", [])) if isinstance(v, dict) else [v]


autos = []
tier3 = []
for line in open(os.path.join(DIST, "logs", "decisions.jsonl"), encoding="utf-8"):
    d = json.loads(line)
    if d["event_type"] == "auto":
        t = datetime.fromisoformat(d["timestamp"])
        autos.append((t, d["thread_id"], d["new_language"]))
        if (d.get("reason") or {}).get("mechanism") == "tier3_content":
            tier3.append((t, d["exe_name"], d["title"], d["new_language"]))
autos.sort()

conn = sqlite3.connect(os.path.join(DIST, "ckils_decisions.db"))
overrides = conn.execute(
    "select timestamp, exe_name, title, thread_id, overridden_to_hkl from overrides order by timestamp").fetchall()
first_log = min(a[0] for a in autos)
touched_pages, touched_apps = set(), set()
real = []  # (time, exe, title, lang) overrides that are NOT carry-over-like, inside the log's coverage
for ts, exe, title, tid, hkl in overrides:
    touched_pages.add(f"{exe}||{title}")
    touched_apps.add(exe)
    t = datetime.fromisoformat(ts)
    lang = "english" if hkl == 67699721 else "hebrew"
    if t >= first_log:
        prev = [a for a in autos if a[0] < t and a[1] != tid]
        if not (prev and prev[-1][2] == lang):
            real.append((t, exe, title, lang))

events = [(t, exe, title, lang) for t, exe, title, lang in tier3] + real
events.sort()
rebuilt_pages, rebuilt_apps = {}, {}
for t, exe, title, lang in events:
    for store, key in ((rebuilt_pages, f"{exe}||{title}"), (rebuilt_apps, exe)):
        store.setdefault(key, []).append(lang)
for store in (rebuilt_pages, rebuilt_apps):
    for k in store:
        store[k] = store[k][-HISTORY:]

for fname, touched, rebuilt in (("page_learned_defaults.json", touched_pages, rebuilt_pages),
                                ("learned_defaults.json", touched_apps, rebuilt_apps)):
    path = os.path.join(DIST, fname)
    data = json.load(open(path, encoding="utf-8"))
    changed = trusted_before = trusted_after = removed = 0
    examples = []
    for key in list(data):
        if key not in touched:
            continue
        before = hist_of(data[key])
        after = rebuilt.get(key, [])
        trusted_before += trust(before) is not None
        trusted_after += trust(after) is not None
        if before != after:
            changed += 1
            if len(examples) < 4 and "Visual Studio" in key or key in ("Code.exe", "chrome.exe"):
                examples.append((key[:60].encode("ascii", "replace").decode(), before, after))
        if after:
            data[key] = {"history": after}
        else:
            del data[key]
            removed += 1
    print(f"{fname}: {len(data)} keys kept, {len([k for k in touched])} touched by overrides, "
          f"{changed} histories changed, {removed} emptied+removed, "
          f"trusted among touched: {trusted_before} -> {trusted_after}")
    for ex in examples[:4]:
        print("   e.g.", ex)
    if APPLY:
        shutil.copy2(path, path + ".bak-before-carryover-cleanup")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("   APPLIED (backup: " + fname + ".bak-before-carryover-cleanup)")
print("mode:", "APPLY" if APPLY else "DRY RUN (nothing written)")
