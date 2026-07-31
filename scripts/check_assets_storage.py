#!/usr/bin/env python3
"""Verify ASSETS_ROOT_PATH is reachable and writable."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.integrations import asset_storage


def main() -> int:
    settings = get_settings()
    root = Path(settings.assets_root_path)
    probe_name = f".write_probe_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.tmp"
    relative_probe = f"_healthcheck/{probe_name}"

    print(f"ASSETS_ROOT_PATH: {root}")
    print(f"Resolved root:    {root.resolve()}")

    try:
        if not root.exists():
            print("Root folder does not exist — attempting to create it...")
            root.mkdir(parents=True, exist_ok=True)
            print("Root folder created.")

        if not root.is_dir():
            print("ERROR: Path exists but is not a directory.")
            return 1

        target = asset_storage.write_file(relative_probe, b"agency-crm write probe")
        print(f"Write OK:  {target}")

        if not target.is_file():
            print("ERROR: Probe file missing after write.")
            return 1

        content = target.read_bytes()
        if content != b"agency-crm write probe":
            print("ERROR: Read-back content mismatch.")
            return 1
        print("Read OK:   content verified")

        target.unlink()
        print("Delete OK: probe file removed")

        parent = target.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            print("Cleanup OK: empty _healthcheck folder removed")

    except PermissionError as exc:
        print(f"ERROR: Permission denied — {exc}")
        print("Ensure the user running this script has read/write access to the share.")
        return 1
    except OSError as exc:
        print(f"ERROR: {exc}")
        print("Check network connectivity and UNC path access to the share.")
        return 1
    except Exception as exc:  # noqa: BLE001 — CLI diagnostic script
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1

    print("\nShared folder is writable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
