"""
A clean measure of the user's manual corrections — the number that says
whether CKILS actually saves corrections.

Per day of use depends on how much the computer was used that day, so the
report also gives corrections per 100 automatic switches, which doesn't.

CKILS records every layout change it didn't make itself as a "manual
override" (the overrides table in ckils_decisions.db). Many of those aren't
real corrections: CKILS's own lag right after it switched, a language carried
over from another window, deliberate test sessions. A hand audit on
2026-10-15 found only 324 of 446 real. This sorts every recorded override
the same way, automatically, and reports real corrections per day of use.

Real corrections are split once more, because they mean different things:
  - "undid CKILS": CKILS had switched this window shortly before and the user
    switched it back — a wrong CKILS decision.
  - "on your own": CKILS hadn't acted in this window just before — the user
    changed language and CKILS didn't anticipate it.

Read-only: opens the database read-only and the decision log for reading;
writes nothing unless --json is given.

Usage:
    python measure_corrections.py [dist folder] [--days N] [--json out.json]
        [--exclude START END ...]   (extra test sessions, ISO times)
"""
import argparse
import collections
import datetime
import json
import os
import sqlite3

LANGUAGE_BY_HKL = {67699721: "english", -264436723: "hebrew"}
LAG_SECONDS = 5        # an override this soon after CKILS's own switch here is CKILS's lag
CARRY_SECONDS = 10     # an override equal to what CKILS just set in ANOTHER window: carried over
UNDO_SECONDS = 120     # CKILS switched this window this recently, the user switched it back

# Deliberate test sessions recorded in PROJECT_JOURNEY.md. Add new ones with
# --exclude rather than editing this list mid-measurement.
TEST_SESSIONS = [
    ("2026-10-08T19:15", "2026-10-08T19:50"),
    ("2026-10-11T17:35", "2026-10-11T18:20"),
    ("2026-10-12T16:00", "2026-10-12T17:10"),
    ("2026-10-14T18:15", "2026-10-14T18:35"),
]

# Periods between the main fixes, for the before/after comparison.
PERIODS = [
    ("Sep 15-19  (before the Sep 19 carry-over fix)", "2026-09-15", "2026-09-19"),
    ("Sep 20-30", "2026-09-20", "2026-09-30"),
    ("Oct 1-14   (before Tier 4 switching / letter model)", "2026-10-01", "2026-10-14"),
    ("Oct 15-    (Tier 4, letter model, typing guards)", "2026-10-15", "2099-12-31"),
]

CATEGORIES = ["real: undid CKILS", "real: on your own", "CKILS lag", "carried over", "test session"]


def _time(text):
    return datetime.datetime.fromisoformat(text)


def load(dist):
    """(automatic switches, overrides) from the decision log and database."""
    autos = []
    with open(os.path.join(dist, "logs", "decisions.jsonl"), encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            if event.get("event_type") == "auto" and event.get("new_language"):
                autos.append((_time(event["timestamp"]), event.get("thread_id"), event["new_language"]))
    autos.sort()
    db = sqlite3.connect(f"file:{os.path.join(dist, 'ckils_decisions.db')}?mode=ro", uri=True)
    overrides = [(_time(t), thread, LANGUAGE_BY_HKL.get(hkl)) for t, thread, hkl in
                 db.execute("SELECT timestamp, thread_id, overridden_to_hkl FROM overrides ORDER BY timestamp")]
    db.close()
    return autos, overrides


def classify(when, thread, language, autos, tests):
    """One override -> one of CATEGORIES."""
    if any(start <= when <= end for start, end in tests):
        return "test session"
    recent = [a for a in autos if when - datetime.timedelta(seconds=UNDO_SECONDS) <= a[0] <= when]
    here = [a for a in recent if a[1] == thread]
    if any((when - a[0]).total_seconds() <= LAG_SECONDS for a in here):
        return "CKILS lag"
    if any(a[1] != thread and a[2] == language and (when - a[0]).total_seconds() <= CARRY_SECONDS
           for a in recent):
        return "carried over"
    if here and here[-1][2] != language:
        return "real: undid CKILS"
    return "real: on your own"


def measure(dist, extra_tests=()):
    """{date: Counter(category)}, {date: automatic switches}, days of use."""
    autos, overrides = load(dist)
    tests = [(_time(a), _time(b)) for a, b in list(TEST_SESSIONS) + list(extra_tests)]
    first = autos[0][0] if autos else None
    per_day = collections.defaultdict(collections.Counter)
    for when, thread, language in overrides:
        if first is None or when < first:
            continue  # before the decision log existed: nothing to explain it with
        per_day[when.date()][classify(when, thread, language, autos, tests)] += 1
    autos_per_day = collections.Counter(a[0].date() for a in autos)
    return per_day, autos_per_day, sorted(autos_per_day)


def report(dist, days, extra_tests=()):
    per_day, autos_per_day, use_days = measure(dist, extra_tests)
    totals = collections.Counter()
    for counts in per_day.values():
        totals.update(counts)
    lines = [f"Recorded manual overrides since {use_days[0]}: {sum(totals.values())}, "
             f"over {len(use_days)} days of use", ""]
    for name in CATEGORIES:
        lines.append(f"  {totals[name]:5d}  {name}")
    lines += ["", "Real corrections per day of use, by period:",
              f"  {'period':52s} {'real':>6s} {'undid':>6s} {'own':>6s} {'auto':>7s} {'real/100 auto':>14s} "
              f"{'undid/100 auto':>15s}"]
    summary = []
    for label, start, end in PERIODS:
        span = [d for d in use_days if _time(start).date() <= d <= _time(end).date()]
        if not span:
            continue
        undid = sum(per_day[d]["real: undid CKILS"] for d in span)
        own = sum(per_day[d]["real: on your own"] for d in span)
        auto = sum(autos_per_day[d] for d in span)
        n = len(span)
        row = {"period": label.split("  ")[0].strip(), "days": n, "real_per_day": (undid + own) / n,
               "undid_per_day": undid / n, "own_per_day": own / n, "auto_per_day": auto / n,
               "real_per_100_auto": 100 * (undid + own) / auto if auto else 0.0,
               "undid_per_100_auto": 100 * undid / auto if auto else 0.0}
        summary.append(row)
        lines.append(f"  {label:52s} {row['real_per_day']:6.1f} {row['undid_per_day']:6.1f} "
                     f"{row['own_per_day']:6.1f} {row['auto_per_day']:7.0f} {row['real_per_100_auto']:14.1f} "
                     f"{row['undid_per_100_auto']:15.1f}"
                     f"   ({n} days)")
    lines += ["", f"Last {days} days of use:",
              f"  {'day':12s} {'real':>5s} {'undid':>6s} {'own':>5s} {'lag':>5s} {'carry':>6s} {'test':>5s} {'auto':>6s}"]
    for d in (use_days[-days:] if days > 0 else []):
        c = per_day[d]
        lines.append(f"  {d.isoformat():12s} {c['real: undid CKILS'] + c['real: on your own']:5d} "
                     f"{c['real: undid CKILS']:6d} {c['real: on your own']:5d} {c['CKILS lag']:5d} "
                     f"{c['carried over']:6d} {c['test session']:5d} {autos_per_day[d]:6d}")
    daily = [{"day": d.isoformat(), "auto": autos_per_day[d],
              **{name: per_day[d][name] for name in CATEGORIES}} for d in use_days]
    return "\n".join(lines), {"totals": dict(totals), "periods": summary, "daily": daily}


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", nargs="?", default=os.path.join(here, "dist"))
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--json")
    parser.add_argument("--exclude", nargs=2, action="append", default=[], metavar=("START", "END"))
    args = parser.parse_args()
    text, data = report(args.dist, args.days, args.exclude)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
