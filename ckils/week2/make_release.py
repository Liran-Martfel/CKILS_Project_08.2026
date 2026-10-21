"""
Prepares a release locally — the zip, its SHA-256 fingerprint and its
signature — from the current dist/CKILS.exe. It does NOT publish anything:
publishing to GitHub happens only when the user says so (it prints the
command to use then).

Every release carries three files, which the in-app updater requires:
    CKILS-vX.Y.Z.zip          CKILS/CKILS.exe + CKILS/SETUP.txt — no personal data
    CKILS-vX.Y.Z.zip.sha256   its fingerprint; the updater refuses a zip that doesn't match
    CKILS-vX.Y.Z.zip.sig      its Ed25519 signature, made with the private key in
                              %USERPROFILE%\\.ckils_release_key\\ (never in the repo);
                              the updater refuses a zip whose signature doesn't check out

Before packing, it checks that dist/CKILS.exe is a build that
build_version.py recorded for this exact version, from the current commit
with nothing uncommitted (found by /code-review 2026-10-21: it zipped
whatever exe happened to be in dist/, so a test build could be released
under the wrong version number).

Usage (from ckils/week2):  python make_release.py
"""
import base64
import hashlib
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_version  # noqa: E402
import updater  # noqa: E402

OUT = os.path.join(HERE, "release_out")
KEY_FILE = os.path.join(os.path.expanduser("~"), ".ckils_release_key", "ckils_release_ed25519.pem")


def check_build(exe, entries, version, head, dirty):
    """None if exe may be released as version; otherwise why not."""
    if dirty:
        return "there are uncommitted changes — commit first, then build again"
    digest = build_version.sha256(exe)
    for e in entries:
        if e.get("sha256") == digest:
            if e.get("version") != version:
                return f"dist/CKILS.exe was built as {e.get('version')}, not {version}"
            if e.get("commit") != head:
                return f"dist/CKILS.exe was built from {e.get('commit')}, not the current commit {head}"
            return None
    return "dist/CKILS.exe isn't in versions/versions.json — build it with build_version.py"


def sign(blob, key_file=KEY_FILE):
    """The blob's Ed25519 signature, base64, checked against the updater's
    own public key before it is returned."""
    from cryptography.hazmat.primitives import serialization
    with open(key_file, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    signature = base64.b64encode(key.sign(blob)).decode("ascii")
    if not updater.signature_ok(blob, signature):
        raise SystemExit("the signing key doesn't match updater.PUBLIC_KEY — nothing was made")
    return signature


def make():
    tag = f"v{updater.VERSION}"
    exe = os.path.join(HERE, "dist", "CKILS.exe")
    head = build_version._git("rev-parse", "--short", "HEAD")
    dirty = build_version._git("status", "--porcelain", "--untracked-files=no")
    problem = check_build(exe, build_version._log(), updater.VERSION, head, dirty)
    if problem:
        raise SystemExit(f"Not making a release: {problem}.")
    if not os.path.exists(KEY_FILE):
        raise SystemExit(f"Not making a release: the signing key isn't at {KEY_FILE}.")

    zip_name, sum_name = updater.asset_names(tag)
    sig_name = updater.signature_name(tag)
    os.makedirs(OUT, exist_ok=True)
    zip_path = os.path.join(OUT, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(exe, "CKILS/CKILS.exe")
        z.write(os.path.join(HERE, "release_files", "SETUP.txt"), "CKILS/SETUP.txt")
    with open(zip_path, "rb") as f:
        blob = f.read()
    digest = hashlib.sha256(blob).hexdigest()
    with open(os.path.join(OUT, sum_name), "w", encoding="ascii") as f:
        f.write(f"{digest}  {zip_name}\n")
    with open(os.path.join(OUT, sig_name), "w", encoding="ascii") as f:
        f.write(sign(blob) + "\n")
    with zipfile.ZipFile(zip_path) as z:
        contents = z.namelist()
    print(f"{zip_name}: {contents}\nSHA-256 {digest}\nSigned: {sig_name}")
    files = " ".join(f'"{os.path.join(OUT, n)}"' for n in (zip_name, sum_name, sig_name))
    print("\nNot published. When approved:\n"
          f'  gh release create {tag} {files} '
          f'--target master --title "CKILS {tag}" --notes-file <notes> --latest')


if __name__ == "__main__":
    make()
