import csv
import os
import sqlite3

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ckils_decisions.db")
TRAINING_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_data.csv")

# Cases actually worth a human's time: borderline confidence (not clearly right
# or wrong either way), or an entry followed shortly by a real manual override
# (free, genuine evidence the decision was wrong) — not everything logged.
BORDERLINE_LOW = 0.50
BORDERLINE_HIGH = 0.80
OVERRIDE_WINDOW_SECONDS = 8


def find_candidates(conn):
    borderline = conn.execute(
        "SELECT id, exe_name, title, source, text, predicted_label, confidence "
        "FROM decisions WHERE reviewed = 0 AND confidence BETWEEN ? AND ? "
        "ORDER BY timestamp",
        (BORDERLINE_LOW, BORDERLINE_HIGH),
    ).fetchall()

    # A decision is "possibly wrong" if a manual override for the same window
    # happened within a few seconds afterward — real, free evidence, not a guess.
    near_override = conn.execute(
        """
        SELECT d.id, d.exe_name, d.title, d.source, d.text, d.predicted_label, d.confidence
        FROM decisions d
        JOIN overrides o
          ON o.thread_id = d.thread_id
         AND (julianday(o.timestamp) - julianday(d.timestamp)) * 86400 BETWEEN 0 AND ?
        WHERE d.reviewed = 0
        ORDER BY d.timestamp
        """,
        (OVERRIDE_WINDOW_SECONDS,),
    ).fetchall()

    seen_ids = set()
    candidates = []
    for row in list(borderline) + list(near_override):
        if row[0] not in seen_ids:
            seen_ids.add(row[0])
            candidates.append(row)
    return candidates


def append_training_row(text, label):
    is_new = not os.path.exists(TRAINING_DATA_FILE)
    with open(TRAINING_DATA_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["text", "label"])
        writer.writerow([text, label])


def main():
    if not os.path.exists(DB_FILE):
        print("No ckils_decisions.db found yet — run CKILS for a while first.")
        return

    conn = sqlite3.connect(DB_FILE)
    candidates = find_candidates(conn)
    print(f"{len(candidates)} entries worth a quick look.\n")

    added = 0
    for decision_id, exe_name, title, source, text, predicted_label, confidence in candidates:
        print(f"[{exe_name}] {title!r}")
        print(f"  source: {source}")
        print(f"  read:   {text!r}")
        print(f"  predicted: {predicted_label} ({confidence:.2f} confidence)")
        answer = input("  correct label? (english/hebrew, blank to skip, q to stop): ").strip().lower()

        if answer == "q":
            break
        if answer in ("english", "hebrew"):
            append_training_row(text, answer)
            added += 1
            conn.execute(
                "UPDATE decisions SET reviewed = 1, confirmed_label = ? WHERE id = ?",
                (answer, decision_id),
            )
        else:
            # Skipped — mark reviewed so it doesn't keep coming back every month.
            conn.execute("UPDATE decisions SET reviewed = 1 WHERE id = ?", (decision_id,))
        conn.commit()
        print()

    conn.close()
    print(f"Added {added} new row(s) to training_data.csv.")
    if added:
        print("Run train_model.py to retrain on the updated dataset.")


if __name__ == "__main__":
    main()
