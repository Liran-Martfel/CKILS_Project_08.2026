"""
Tells the user when a newer CKILS has been published (the user's call,
2026-10-21). At most once a day, in the background, the packaged CKILS asks
GitHub which release is the latest; if it's newer than this one, a small
window in the corner says so — "Download" opens the release page, "Close"
dismisses it, and a small arrow shows a summary of what's new.

Security and privacy, by design:
  - The only connection CKILS ever makes, and only to api.github.com, over
    HTTPS. It sends nothing about the user: a plain request for the latest
    release of this one public repository.
  - Nothing is downloaded or run automatically. The user downloads by hand.
  - The link the window opens is built here from a strictly checked version
    tag, always pointing at this repository — never a URL taken from the
    response.
  - Turned off by an empty file `disable_update_check.on` next to CKILS.exe.
  - Never runs from source (only the packaged exe), never raises, never
    delays CKILS starting.
"""
import json
import re
import sys
import threading
import time
import urllib.request
import webbrowser

import skip_logger

VERSION = "2.1.0"  # bump with every release
REPO = "Liran-Martfel/CKILS_Project_08.2026"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/tag/"
CHECK_EVERY_SECONDS = 24 * 60 * 60
DISABLE_FILENAME = "disable_update_check.on"
STATE_FILENAME = "update_check.json"  # only the time of the last check
_TAG = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")


def parse_version(tag):
    """(major, minor, patch) from "v2.1.0" or "2.1.0"; None for anything else."""
    m = _TAG.match((tag or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(tag, current=VERSION):
    latest, mine = parse_version(tag), parse_version(current)
    return bool(latest and mine and latest > mine)


def summary_of(notes, limit=1500):
    """The release notes as short plain text for the window."""
    text = re.sub(r"\*\*|`|__|^#+\s*", "", notes or "", flags=re.M).strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n..."


def _path(name):
    return skip_logger.os.path.join(skip_logger._persistent_dir(), name)


def _due(now):
    """True if the user hasn't turned it off and a day has passed since the last check."""
    if skip_logger.os.path.exists(_path(DISABLE_FILENAME)):
        return False
    try:
        with open(_path(STATE_FILENAME), encoding="utf-8") as f:
            return now - float(json.load(f).get("last_check", 0)) >= CHECK_EVERY_SECONDS
    except Exception:
        return True


def _remember_check(now):
    try:
        with open(_path(STATE_FILENAME), "w", encoding="utf-8") as f:
            json.dump({"last_check": now}, f)
    except Exception:
        pass


def fetch_latest(timeout=8):
    """(tag, notes) of the latest release, or None on any problem."""
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "CKILS-update-check"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read(200_000).decode("utf-8"))
    tag = data.get("tag_name")
    if parse_version(tag) is None:
        return None
    return tag, data.get("body") or ""


def check_once(now=None, show=None):
    """One check; returns the newer tag it announced, or None."""
    now = time.time() if now is None else now
    if not _due(now):
        return None
    _remember_check(now)
    try:
        latest = fetch_latest()
    except Exception:
        return None
    if not latest or not is_newer(latest[0]):
        return None
    tag, notes = latest
    (show or _show_window)(tag, summary_of(notes))
    return tag


def _show_window(tag, summary):
    """A small window in the corner, in the house colours (navy on beige):
    Download, Close, and an arrow that opens the summary."""
    import tkinter as tk
    bg, navy, muted, accent = "#f4efe6", "#1b2a4a", "#5f6678", "#24407a"
    root = tk.Tk()
    root.title("CKILS")
    root.configure(bg=bg)
    root.attributes("-topmost", True)
    root.resizable(False, False)
    frame = tk.Frame(root, bg=bg, padx=16, pady=12)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text=f"A new version of CKILS is available ({tag})", bg=bg, fg=navy,
             font=("Segoe UI", 10, "bold")).pack(anchor="w")
    tk.Label(frame, text=f"You have {VERSION}.", bg=bg, fg=muted, font=("Segoe UI", 9)).pack(anchor="w")
    notes = tk.Text(frame, width=52, height=10, wrap="word", bg="#fbf8f2", fg=navy, relief="flat",
                    font=("Segoe UI", 9), padx=8, pady=6)
    notes.insert("1.0", summary or "No summary was published.")
    notes.configure(state="disabled")
    toggle = tk.StringVar(value="▸ What's new")

    def flip():
        if notes.winfo_ismapped():
            notes.pack_forget()
            toggle.set("▸ What's new")
        else:
            notes.pack(fill="both", pady=(8, 0), before=buttons)
            toggle.set("▾ What's new")
        place()

    tk.Button(frame, textvariable=toggle, command=flip, bg=bg, fg=accent, relief="flat", bd=0,
              activebackground=bg, cursor="hand2", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
    buttons = tk.Frame(frame, bg=bg)
    buttons.pack(fill="x", pady=(10, 0))

    def download():
        webbrowser.open(RELEASE_PAGE + tag)  # built here from a checked tag, always this repository
        root.destroy()

    tk.Button(buttons, text="Close", command=root.destroy, bg=bg, fg=navy, relief="groove",
              padx=12, font=("Segoe UI", 9)).pack(side="right")
    tk.Button(buttons, text="Download", command=download, bg=accent, fg="#fbf8f2", relief="flat",
              padx=12, font=("Segoe UI", 9, "bold")).pack(side="right", padx=(0, 8))

    def place():
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry(f"+{root.winfo_screenwidth() - w - 24}+{root.winfo_screenheight() - h - 72}")

    place()
    root.mainloop()


def start():
    """Starts the daily check in the background — packaged CKILS only."""
    if not getattr(sys, "frozen", False):
        return

    def loop():
        while True:
            try:
                check_once()
            except Exception:
                pass
            time.sleep(60 * 60)  # look again hourly; check_once itself waits a day between checks

    threading.Thread(target=loop, daemon=True).start()
