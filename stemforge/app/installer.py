"""Install Stemforge's own Ableton script as a SEPARATE Control Surface. Touches only files on disk; never talks to Live.

It writes exactly one file: <Live prefs>/Live <version>/User Remote Scripts/Stemforge/__init__.py.
It never reads, writes, renames, backs up or deletes any other script folder (AbletonMCP and everyone else's stay as they are).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
import time
from pathlib import Path

PREFS = Path.home() / "Library" / "Preferences" / "Ableton"
BACKUPS = Path.home() / "Documents" / "ableton-backups"
SCRIPT_FOLDER = "Stemforge"


def script_source() -> Path:
    """The Stemforge script shipped with this app (also works inside a PyInstaller bundle)."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "ableton" / SCRIPT_FOLDER / "__init__.py")
    candidates.append(Path(__file__).resolve().parents[2] / "ableton" / SCRIPT_FOLDER / "__init__.py")
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("The Ableton script that ships with Stemforge is missing (ableton/Stemforge/__init__.py).")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_version() -> str | None:
    m = re.search(r'^SCRIPT_VERSION\s*=\s*"([^"]+)"', script_source().read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def _assert_safe(target: Path) -> None:
    """Refuse to write anywhere except .../User Remote Scripts/Stemforge/__init__.py."""
    if target.name != "__init__.py" or target.parent.name != SCRIPT_FOLDER or target.parent.parent.name != "User Remote Scripts":
        raise PermissionError("Stemforge only installs into a folder named '%s' inside 'User Remote Scripts'; refusing %s"
                              % (SCRIPT_FOLDER, target))
    if any(part.lower() in ("abletonmcp",) for part in target.parts):
        raise PermissionError("Refusing to touch an AbletonMCP folder: %s" % target)


def live_script_dirs(prefs: Path = PREFS) -> list[Path]:
    """`User Remote Scripts` folders of installed Live versions, most recently used first (by Log.txt)."""
    found = []
    for d in prefs.glob("Live */"):
        log = d / "Log.txt"
        found.append((log.stat().st_mtime if log.exists() else 0.0, d / "User Remote Scripts"))
    return [s for _, s in sorted(found, key=lambda x: x[0], reverse=True)]


def plan(prefs: Path = PREFS, backups: Path = BACKUPS) -> dict | None:
    """Exactly what install() would do, without doing it. None when no Live preferences folder exists."""
    dirs = live_script_dirs(prefs)
    if not dirs:
        return None
    scripts = dirs[0]
    target = scripts / SCRIPT_FOLDER / "__init__.py"
    _assert_safe(target)
    src = script_source()
    state = "missing" if not target.exists() else ("current" if sha256(target) == sha256(src) else "different")
    others = sorted(p.name for p in scripts.iterdir() if p.is_dir() and p.name != SCRIPT_FOLDER) if scripts.is_dir() else []
    return {"live": scripts.parent.name, "target": str(target), "state": state, "version": source_version(),
            "writes": [str(target)],
            "backup_to": str(backups / "Stemforge-<time>" / "__init__.py") if state == "different" else None,
            "left_alone": others}


def install(prefs: Path = PREFS, backups: Path = BACKUPS) -> dict:
    """Create User Remote Scripts/Stemforge/__init__.py for the most recently used Live version.

    An existing, different Stemforge script is backed up first. Nothing else is read, changed or deleted.
    """
    p = plan(prefs, backups)
    if p is None:
        raise FileNotFoundError("Could not find Ableton's preferences folder (~/Library/Preferences/Ableton). "
                                "Open Ableton Live once, then try again.")
    target = Path(p["target"])
    _assert_safe(target)
    src = script_source()
    if p["state"] == "current":
        return {"installed": False, "reason": "already current", "target": p["target"], "backup": None,
                "version": p["version"], "live": p["live"]}
    backup = None
    if p["state"] == "different":
        backup = backups / ("Stemforge-%s" % time.strftime("%Y%m%d-%H%M%S")) / "__init__.py"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        if sha256(backup) != sha256(target):
            raise OSError("The backup did not match the original, so nothing was changed.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    if sha256(target) != sha256(src):
        raise OSError("The installed file does not match the one Stemforge ships.")
    return {"installed": True, "reason": None, "target": p["target"], "backup": str(backup) if backup else None,
            "version": p["version"], "live": p["live"]}
