"""Self-update BEFORE the app starts — called by run.bat / install.bat.

Runs before the GUI opens so this very launch uses the latest version, with no
button to press and no manual restart. Works for both git clones and zip installs.

exit codes:
    0 = nothing to do (already latest / offline / update failed) -> just launch
    2 = updated successfully -> caller (.bat) relaunches itself to load new files

Messages are English on purpose (runs in the cmd console; keeps .bat output clean).
"""
from __future__ import annotations

import sys

UPDATED = 2


def main() -> int:
    try:
        from .updater import fetch_remote_version, is_newer, apply_update
        from .version import __version__
    except Exception as e:
        print(f"[update] skip check (import failed): {e}")
        return 0

    remote = fetch_remote_version()
    if not remote:
        print("[update] check failed (offline?) - launching current version")
        return 0
    if not is_newer(remote, __version__):
        print(f"[update] already up to date (v{__version__})")
        return 0

    print(f"[update] new version v{remote} found (current v{__version__}) - updating...")
    try:
        ok, msg = apply_update(print)
    except Exception as e:
        print(f"[update] failed: {e} - launching current version")
        return 0
    print(f"[update] {msg}")
    return UPDATED if ok else 0


if __name__ == "__main__":
    sys.exit(main())
