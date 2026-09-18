"""
Reads ckils_skips.db (written by skip_logger.py) and prints why CKILS ended
checks without a decision: how many of each reason code, and which
app/title/reason combinations are most common. This is the tool that turns
the log into an answer to "what stops CKILS from switching the language?".

Usage:
    python summarize_skips.py [path-to-ckils_skips.db] [hours]

Defaults: the copy next to the packaged exe (dist/ckils_skips.db, falling back
to the one next to this script), and the last 72 hours — the observation
window used to judge a change. Read-only: it never modifies the database.
"""
import datetime
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def default_db_path():
    """Returns dist/ckils_skips.db if it exists (where the packaged exe
    writes), otherwise the copy next to this script.
    """
    packaged = os.path.join(HERE, "dist", "ckils_skips.db")
    return packaged if os.path.exists(packaged) else os.path.join(HERE, "ckils_skips.db")


def summarize(db_path, hours):
    """Prints reason totals and the top app/title/reason groups for rows newer
    than `hours` hours ago.
    """
    if not os.path.exists(db_path):
        print(f"No database at {db_path} yet — run CKILS for a while first.")
        return
    since = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    total = conn.execute("SELECT COUNT(*) FROM skipped_reads WHERE timestamp >= ?", (since,)).fetchone()[0]
    print(f"{total} no-decision checks in the last {hours} hours ({db_path})\n")
    print("By reason:")
    for reason, n in conn.execute(
            "SELECT reason, COUNT(*) c FROM skipped_reads WHERE timestamp >= ? "
            "GROUP BY reason ORDER BY c DESC", (since,)):
        print(f"  {n:6d}  {reason}")
    print("\nTop 15 app / window / reason:")
    for exe, title, reason, n in conn.execute(
            "SELECT exe_name, substr(title, 1, 50), reason, COUNT(*) c FROM skipped_reads "
            "WHERE timestamp >= ? GROUP BY exe_name, title, reason ORDER BY c DESC LIMIT 15", (since,)):
        shown = (title or "").encode("ascii", "replace").decode()
        print(f"  {n:5d}  {exe}  {shown!r}  {reason}")
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else default_db_path()
    span = float(sys.argv[2]) if len(sys.argv) > 2 else 72
    summarize(path, span)
