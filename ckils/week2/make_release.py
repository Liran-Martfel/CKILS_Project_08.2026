"""
Prepares a release locally — the zip and its SHA-256 fingerprint — from the
current dist/CKILS.exe. It does NOT publish anything: publishing to GitHub
happens only when the user says so (it prints the command to use then).

Every release carries two files, which the in-app updater requires:
    CKILS-vX.Y.Z.zip          CKILS/CKILS.exe + CKILS/SETUP.txt — no personal data
    CKILS-vX.Y.Z.zip.sha256   its fingerprint; the updater refuses a zip that doesn't match

Usage (from ckils/week2):  python make_release.py
"""
import hashlib
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import updater  # noqa: E402

OUT = os.path.join(HERE, "release_out")


def make():
    tag = f"v{updater.VERSION}"
    zip_name, sum_name = updater.asset_names(tag)
    os.makedirs(OUT, exist_ok=True)
    zip_path = os.path.join(OUT, zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(HERE, "dist", "CKILS.exe"), "CKILS/CKILS.exe")
        z.write(os.path.join(HERE, "release_files", "SETUP.txt"), "CKILS/SETUP.txt")
    with open(zip_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(OUT, sum_name), "w", encoding="ascii") as f:
        f.write(f"{digest}  {zip_name}\n")
    with zipfile.ZipFile(zip_path) as z:
        contents = z.namelist()
    print(f"{zip_name}: {contents}\nSHA-256 {digest}")
    print("\nNot published. When approved:\n"
          f'  gh release create {tag} "{zip_path}" "{os.path.join(OUT, sum_name)}" '
          f'--target master --title "CKILS {tag}" --notes-file <notes> --latest')


if __name__ == "__main__":
    make()
