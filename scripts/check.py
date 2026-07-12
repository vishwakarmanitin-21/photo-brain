"""Local CI — run the same checks as GitHub Actions, before you push.

Usage:
    venv\\Scripts\\python scripts\\check.py

Exits non-zero if anything fails, so it also works as a git pre-push hook:
    # .git/hooks/pre-push  (make it executable)
    #!/bin/sh
    exec venv/Scripts/python scripts/check.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(label: str, args: list[str]) -> bool:
    print(f"\n=== {label} ===", flush=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(args, cwd=ROOT, env=env)
    ok = result.returncode == 0
    print(f"--- {label}: {'PASS' if ok else 'FAIL'} ---", flush=True)
    return ok


def main() -> int:
    py = sys.executable
    print(f"Local CI on Python {sys.version.split()[0]}")
    steps = [
        ("Byte-compile", [py, "-m", "compileall", "-q", "app", "run.py"]),
        ("Unit tests", [py, "-m", "unittest", "discover", "-s", "tests"]),
    ]
    results = [run(label, args) for label, args in steps]
    if all(results):
        print("\nAll checks passed. Safe to push.")
        return 0
    print("\nChecks FAILED — fix before pushing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
