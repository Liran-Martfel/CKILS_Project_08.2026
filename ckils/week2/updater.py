"""
Tells the user when a newer CKILS has been published, and updates it in
place when they ask (the user's calls, 2026-10-21). At most once a day, in
the background, the packaged CKILS asks GitHub which release is the latest;
if it's newer than this one, a small window in the corner says so. "Update"
downloads it, checks it, keeps the current version, installs the new one and
restarts CKILS; "Close" dismisses it; a small arrow shows what's new.

Security and privacy, by design:
  - The only connections CKILS ever makes are to GitHub, over HTTPS: the
    daily "what's the latest release?" question, and the download the user
    asked for. Nothing about the user is sent.
  - A download is accepted only from this repository's own release files,
    and only if its SHA-256 fingerprint matches the one published with the
    release (CKILS-vX.Y.Z.zip.sha256) AND its signature (CKILS-vX.Y.Z.zip.sig)
    checks out against PUBLIC_KEY below. The fingerprint alone only proves
    the download arrived whole: anyone who could change the release could
    change both files. The signature needs the private key, which never
    leaves the developer's computer (added after /code-review 2026-10-21).
    A mismatch in either installs nothing.
  - Nothing is ever downloaded or installed without the user pressing Update.
  - The version being replaced is kept in previous_versions/ next to
    CKILS.exe; the user's data files are never touched.
  - Turned off by an empty file `disable_update_check.on` next to CKILS.exe.
  - Never runs from source (only the packaged exe), never raises, never
    delays CKILS starting.
"""
import base64
import datetime
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile

import skip_logger

VERSION = "2.1.0"  # bump with every release
REPO = "Liran-Martfel/CKILS_Project_08.2026"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/tag/"
DOWNLOAD_PREFIX = f"/{REPO}/releases/download/"
CHECK_EVERY_SECONDS = 24 * 60 * 60
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
DISABLE_FILENAME = "disable_update_check.on"
STATE_FILENAME = "update_check.json"  # only the time of the last check
PREVIOUS_DIR = "previous_versions"
# Ed25519 public key of the release signer (make_release.py signs with the
# private half, kept in %USERPROFILE%\.ckils_release_key\ — never in the repo).
PUBLIC_KEY = "budGn/LKg0QAUmHeY7TB2zYFgeRu3oYTLhmwL2r2OFA="
_TAG = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_HEX64 = re.compile(r"\b([0-9a-fA-F]{64})\b")


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


def asset_names(tag):
    """The two files every release carries: the zip, and its fingerprint."""
    zip_name = f"CKILS-{tag if tag.startswith('v') else 'v' + tag}.zip"
    return zip_name, zip_name + ".sha256"


def signature_name(tag):
    """The third file: the zip's Ed25519 signature, base64."""
    return asset_names(tag)[0] + ".sig"


def signature_ok(blob, signature_text, public_key=None):
    """True only if signature_text is a valid signature of blob by the
    holder of public_key's private half."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        signature = base64.b64decode((signature_text or "").strip(), validate=True)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key or PUBLIC_KEY)).verify(signature, blob)
        return True
    except (InvalidSignature, ValueError):
        return False


def trusted_download_url(url):
    """True only for a file of THIS repository's releases, over HTTPS."""
    try:
        u = urllib.parse.urlparse(url)
    except Exception:
        return False
    return u.scheme == "https" and u.hostname == "github.com" and u.path.startswith(DOWNLOAD_PREFIX) \
        and ".." not in u.path


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


def _get(url, timeout, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "CKILS-update-check",
                                                   "Accept": "application/vnd.github+json, */*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("file is larger than expected")
    return data


def fetch_latest(timeout=8):
    """(tag, notes, {asset name: download url}) of the latest release, or None."""
    data = json.loads(_get(LATEST_URL, timeout, 500_000).decode("utf-8"))
    tag = data.get("tag_name")
    if parse_version(tag) is None:
        return None
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    return tag, data.get("body") or "", assets


def check_once(now=None, show=None):
    """One check; returns the newer tag it announced, or None."""
    now = time.time() if now is None else now
    if not _due(now):
        return None
    try:
        latest = fetch_latest()
    except Exception:
        return None  # offline or GitHub didn't answer: try again next hour, not tomorrow
    # Remembered only after GitHub answered (found by /code-review 2026-10-21:
    # saved before asking, one failed check hid a new release for a whole day).
    _remember_check(now)
    if not latest or not is_newer(latest[0]):
        return None
    tag, notes, assets = latest
    (show or _show_window)(tag, summary_of(notes), assets)
    return tag


def download_verified(tag, assets, timeout=60):
    """The new CKILS.exe as bytes, after checking the zip's fingerprint and
    signature. Raises with a short, user-readable reason on any problem."""
    zip_name, sum_name = asset_names(tag)
    sig_name = signature_name(tag)
    zip_url, sum_url, sig_url = assets.get(zip_name), assets.get(sum_name), assets.get(sig_name)
    if not zip_url or not sum_url or not sig_url:
        raise ValueError("this release has no signed update file")
    if not all(trusted_download_url(u) for u in (zip_url, sum_url, sig_url)):
        raise ValueError("the update file is not from CKILS's own releases")
    expected = _HEX64.search(_get(sum_url, timeout, 10_000).decode("utf-8", "replace"))
    if not expected:
        raise ValueError("the published fingerprint is unreadable")
    signature = _get(sig_url, timeout, 10_000).decode("ascii", "replace")
    blob = _get(zip_url, timeout, MAX_DOWNLOAD_BYTES)
    if hashlib.sha256(blob).hexdigest().lower() != expected.group(1).lower():
        raise ValueError("the download doesn't match its published fingerprint")
    if not signature_ok(blob, signature):
        raise ValueError("the download isn't signed by CKILS's developer")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.replace("\\", "/").split("/")[-1] == "CKILS.exe"]
        if len(names) != 1:
            raise ValueError("the update file has no single CKILS.exe")
        return z.read(names[0])


def _ps_literal(text):
    """A PowerShell single-quoted string: nothing inside is expanded."""
    return "'" + str(text).replace("'", "''") + "'"


def _processes_holding(exe_path):
    """This process, and PyInstaller's launcher above it (which keeps the
    exe open too) — the swap waits for both to exit."""
    pids = [os.getpid()]
    try:
        import psutil
        parent = psutil.Process(os.getpid()).parent()
        if parent and os.path.normcase(parent.exe()) == os.path.normcase(exe_path):
            pids.append(parent.pid)
    except Exception:
        pass
    return pids


def install_and_restart(new_exe_bytes, exe_path=None, launch=True):
    """Writes the new exe next to the current one and hands over to a small
    script that, once this CKILS has exited, moves the current exe into
    previous_versions/, moves the new one into its place and starts it.
    If either move fails it puts the old exe back and starts that instead,
    so CKILS is never left missing. Returns the script path (for tests);
    with launch=True this process then exits.

    Found by /code-review 2026-10-21: the swap was a .cmd file, which cmd
    reads in the system code page — a folder with a Hebrew name became
    gibberish and the swap silently did nothing. PowerShell reads a UTF-8
    file with a BOM correctly, and -LiteralPath takes [ ] and ' as written."""
    exe_path = os.path.abspath(exe_path or sys.executable)
    folder = os.path.dirname(exe_path)
    new_path = os.path.join(folder, "CKILS.update.exe")
    previous = os.path.join(folder, PREVIOUS_DIR)
    os.makedirs(previous, exist_ok=True)
    keep = os.path.join(previous, f"CKILS-v{VERSION}.exe")
    if os.path.exists(keep):  # never overwrite a kept version
        keep = os.path.join(previous, f"CKILS-v{VERSION}-{datetime.datetime.now():%Y%m%d-%H%M%S}.exe")
    with open(new_path, "wb") as f:
        f.write(new_exe_bytes)
    script = os.path.join(tempfile.gettempdir(), f"ckils_update_{os.getpid()}.ps1")
    waits = "\n".join(f"try {{ Wait-Process -Id {pid} -Timeout 30 -ErrorAction Stop }} catch {{}}"
                      for pid in _processes_holding(exe_path))
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(f'''# Swaps in the new CKILS once the running one has exited (written by updater.py).
$exe = {_ps_literal(exe_path)}
$new = {_ps_literal(new_path)}
$keep = {_ps_literal(keep)}
$folder = {_ps_literal(folder)}
try {{
{waits}
$kept = $false
for ($i = 0; $i -lt 60 -and -not $kept; $i++) {{
    try {{ Move-Item -LiteralPath $exe -Destination $keep -Force -ErrorAction Stop; $kept = $true }}
    catch {{ Start-Sleep -Seconds 1 }}
}}
if ($kept) {{
    try {{ Move-Item -LiteralPath $new -Destination $exe -Force -ErrorAction Stop }}
    catch {{ Move-Item -LiteralPath $keep -Destination $exe -Force }}  # new one failed: old one back
}}
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $exe
$start.WorkingDirectory = $folder
$start.UseShellExecute = $true
[void][System.Diagnostics.Process]::Start($start)
}} finally {{
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}}
''')
    if launch:
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-WindowStyle", "Hidden", "-File", script], cwd=folder,
                         creationflags=0x08000000 | 0x00000200)  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
        os._exit(0)
    return script


def _show_window(tag, summary, assets=None):
    """A small window in the corner, in the house colours (navy on beige):
    Update, Close, and an arrow that opens the summary."""
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
    status = tk.StringVar(value=f"You have {VERSION}.")
    tk.Label(frame, textvariable=status, bg=bg, fg=muted, font=("Segoe UI", 9),
             wraplength=380, justify="left").pack(anchor="w")
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
    result = {}

    def worker():
        try:
            result["exe"] = download_verified(tag, assets or {})
        except Exception as e:
            result["error"] = str(e) or type(e).__name__

    def install():
        try:
            install_and_restart(result.pop("exe"))
        except Exception as e:
            # Found by /code-review 2026-10-21: a failure here (folder not
            # writable, disk full) left the window stuck on "Installing".
            result["error"] = f"couldn't install ({e.__class__.__name__})"
            poll()

    def poll():
        if "exe" in result:
            status.set("Installing — CKILS will restart in a moment.")
            root.update_idletasks()
            root.after(400, install)
        elif "error" in result:
            status.set(f"Couldn't update automatically: {result['error']}.")
            update_button.configure(text="Open download page", state="normal",
                                    command=lambda: (webbrowser.open(RELEASE_PAGE + tag), root.destroy()))
            close_button.configure(state="normal")
        else:
            root.after(200, poll)

    def update():
        update_button.configure(state="disabled")
        close_button.configure(state="disabled")
        status.set("Downloading and checking the new version...")
        threading.Thread(target=worker, daemon=True).start()
        root.after(200, poll)

    close_button = tk.Button(buttons, text="Close", command=root.destroy, bg=bg, fg=navy, relief="groove",
                             padx=12, font=("Segoe UI", 9))
    close_button.pack(side="right")
    update_button = tk.Button(buttons, text="Update", command=update, bg=accent, fg="#fbf8f2", relief="flat",
                              padx=12, font=("Segoe UI", 9, "bold"))
    update_button.pack(side="right", padx=(0, 8))

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
