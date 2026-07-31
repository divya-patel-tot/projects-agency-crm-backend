#!/usr/bin/env python3
"""
Run the complete automated verification pipeline for Phases 0–6.

Steps (in order):
  1. Environment check (.env vs .env.example)
  2. Shared assets folder writable
  3. Alembic migrations at HEAD
  4. Full pytest suite
  5. In-depth smoke test (positive + negative + security)

Usage:
    cd backend
    .\\venv\\Scripts\\python scripts\\run_full_verification.py
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = BACKEND_ROOT / "venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = BACKEND_ROOT / "venv" / "bin" / "python"


def _run_step(name: str, cmd: list[str]) -> int:
    print("\n" + "=" * 72)
    print(f"STEP: {name}")
    print("=" * 72)
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=BACKEND_ROOT)
    if result.returncode != 0:
        print(f"\nFAILED: {name} (exit {result.returncode})")
    else:
        print(f"\nPASSED: {name}")
    return result.returncode


def main() -> int:
    started = datetime.now(UTC).isoformat()
    print("=" * 72)
    print("Agency CRM — Full Verification Pipeline")
    print(f"Started: {started}")
    print("=" * 72)

    python = str(VENV_PYTHON if VENV_PYTHON.exists() else sys.executable)
    steps: list[tuple[str, list[str]]] = [
        ("Environment check", [python, "scripts/check_env.py"]),
        ("Assets storage check", [python, "scripts/check_assets_storage.py"]),
        ("Alembic upgrade head", [python, "-m", "alembic", "upgrade", "head"]),
        ("Pytest full suite", [python, "-m", "pytest", "tests/", "-v", "--tb=short"]),
        ("Smoke test (Phases 0–6 + security)", [python, "scripts/smoke_test_full.py"]),
    ]

    results: list[tuple[str, int]] = []
    for name, cmd in steps:
        code = _run_step(name, cmd)
        results.append((name, code))
        if code != 0:
            print("\n" + "!" * 72)
            print(f"Pipeline aborted after failure in: {name}")
            break

    print("\n" + "=" * 72)
    print("VERIFICATION SUMMARY")
    print("=" * 72)
    for name, code in results:
        status = "PASS" if code == 0 else "FAIL"
        print(f"  [{status}] {name}")
    skipped = len(steps) - len(results)
    if skipped:
        print(f"  [SKIP] {skipped} step(s) not run due to earlier failure")
    print(f"Finished: {datetime.now(UTC).isoformat()}")
    print("=" * 72)

    return 0 if all(code == 0 for _, code in results) and len(results) == len(steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
