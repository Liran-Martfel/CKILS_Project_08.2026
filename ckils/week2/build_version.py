"""
Builds CKILS.exe and keeps every version (the user's rule, 2026-10-21):
each build is saved in versions/ with its version number, code commit and
time, and the exe being replaced is always kept first. Nothing here touches
GitHub — publishing is a separate, explicit step.

Usage (from ckils/week2):  python build_version.py "what changed"
       python build_version.py --list
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_EXE = os.path.join(HERE, "dist", "CKILS.exe")
VERSIONS = os.path.join(HERE, "versions")
LOG = os.path.join(VERSIONS, "versions.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _log():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_log(entries):
    with open(LOG, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def archive(exe, version, note, kind):
    """Copies exe into versions/ (once per distinct file) and logs it."""
    os.makedirs(VERSIONS, exist_ok=True)
    entries = _log()
    digest = sha256(exe)
    for e in entries:
        if e["sha256"] == digest:
            return e["file"]  # already kept
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    commit = _git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = "+uncommitted" if _git("status", "--porcelain", "--untracked-files=no") else ""
    name = f"CKILS-{version}-{commit}{dirty}-{stamp}.exe"
    shutil.copy2(exe, os.path.join(VERSIONS, name))
    entries.append({"file": name, "version": version, "commit": commit + dirty, "built": stamp,
                    "kind": kind, "note": note, "sha256": digest})
    _save_log(entries)
    return name


def build(note):
    sys.path.insert(0, HERE)
    import updater
    if os.path.exists(DIST_EXE):
        kept = archive(DIST_EXE, "previous", "the exe this build replaced", "replaced")
        print("kept the version being replaced:", kept)
    subprocess.run(["taskkill", "/IM", "CKILS.exe", "/F"], capture_output=True)
    result = subprocess.run([sys.executable, "-m", "PyInstaller", "CKILS.spec", "--noconfirm"], cwd=HERE,
                            capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(DIST_EXE):
        print(result.stdout[-2000:], result.stderr[-2000:])
        raise SystemExit("build failed")
    name = archive(DIST_EXE, updater.VERSION, note, "build")
    print("built and kept:", name)
    subprocess.Popen([DIST_EXE], cwd=os.path.dirname(DIST_EXE), creationflags=0x00000010)  # CREATE_NEW_CONSOLE


if __name__ == "__main__":
    if sys.argv[1:] == ["--list"]:
        for e in _log():
            print(f'{e["built"]}  {e["version"]:9s} {e["commit"]:22s} {e["kind"]:9s} {e["note"]}')
    else:
        build(" ".join(sys.argv[1:]) or "(no note)")
