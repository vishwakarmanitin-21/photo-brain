"""Build PhotoBrain Desktop into a distributable package.

Usage:
    venv\\Scripts\\python scripts\\build.py

Outputs:
    dist/PhotoBrain/           — folder with the executable and all dependencies
    dist/PhotoBrain.zip        — zip archive ready for distribution
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT, "dist")
BUILD_DIR = os.path.join(ROOT, "build")
SPEC_FILE = os.path.join(ROOT, "photobrain.spec")
OUTPUT_DIR = os.path.join(DIST_DIR, "PhotoBrain")
ZIP_PATH = os.path.join(DIST_DIR, "PhotoBrain.zip")


def clean():
    """Remove previous build artifacts."""
    for d in [DIST_DIR, BUILD_DIR]:
        if os.path.exists(d):
            print(f"Cleaning {d}...")
            shutil.rmtree(d)


def build():
    """Run PyInstaller."""
    print("Building with PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        SPEC_FILE,
        "--noconfirm",
        "--clean",
    ]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed!")
        sys.exit(1)
    print(f"Build complete: {OUTPUT_DIR}")


def make_zip():
    """Create a zip archive for distribution."""
    if not os.path.exists(OUTPUT_DIR):
        print("ERROR: Build output not found. Run build first.")
        sys.exit(1)

    print(f"Creating {ZIP_PATH}...")
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(OUTPUT_DIR):
            for f in files:
                filepath = os.path.join(root, f)
                arcname = os.path.relpath(filepath, DIST_DIR)
                zf.write(filepath, arcname)

    size_mb = os.path.getsize(ZIP_PATH) / (1024 * 1024)
    print(f"Zip created: {ZIP_PATH} ({size_mb:.1f} MB)")


def verify():
    """Check that critical files exist in the output."""
    exe_path = os.path.join(OUTPUT_DIR, "PhotoBrain.exe")
    if not os.path.exists(exe_path):
        print("ERROR: PhotoBrain.exe not found in output!")
        sys.exit(1)

    # Check for mediapipe DLL
    dll_found = False
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            if f == "libmediapipe.dll":
                dll_found = True
                break
    if not dll_found:
        print("WARNING: libmediapipe.dll not found — mediapipe may not work at runtime")

    print("Verification passed: PhotoBrain.exe found")


if __name__ == "__main__":
    clean()
    build()
    verify()
    make_zip()
    print("\nDone! Distribute dist/PhotoBrain.zip to users.")
    print("Users extract the zip and run PhotoBrain/PhotoBrain.exe — no Python needed.")
