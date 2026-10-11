"""Install / update the AbletonMCP Remote Script. Touches only files on disk; never talks to Live."""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
import time
from pathlib import Path

PREFS = Path.home() / "Library" / "Preferences" / "Ableton"
BACKUPS = Path.home() / "Documents" / "ableton-backups"


def script_source() -> Path:
    """The Remote Script shipped with this version of Stemforge (also works inside a PyInstaller bundle)."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "ableton" / "AbletonMCP" / "__init__.py")
    candidates.append(Path(__file__).resolve().parents[2] / "ableton" / "AbletonMCP" / "__init__.py")
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("The Remote Script file that ships with Stemforge is missing (ableton/AbletonMCP/__init__.py).")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_version() -> str | None:
    m = re.search(r'^SCRIPT_VERSION\s*=\s*"([^"]+)"', script_source().read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def live_script_dirs(prefs: Path = PREFS) -> list[Path]:
    """`User Remote Scripts` folders of installed Live versions, most recently used first (by Log.txt)."""
    found = []
    for d in prefs.glob("Live */"):
        scripts = d / "User Remote Scripts"
        if scripts.is_dir() or d.is_dir():
            log = d / "Log.txt"
            found.append((log.stat().st_mtime if log.exists() else 0.0, scripts))
    return [s for _, s in sorted(found, key=lambda x: x[0], reverse=True)]


def status(prefs: Path = PREFS) -> list[dict]:
    """For each Live version folder: where the script would go and whether what is there is current."""
    src = sha256(script_source())
    out = []
    for scripts in live_script_dirs(prefs):
        target = scripts / "AbletonMCP" / "__init__.py"
        state = "missing" if not target.exists() else ("current" if sha256(target) == src else "old")
        out.append({"live": scripts.parent.name, "target": str(target), "state": state})
    return out


def install(prefs: Path = PREFS, backups: Path = BACKUPS) -> dict:
    """Back up what is installed, then copy the shipped script into the most recently used Live version's folder.

    Never deletes anything. Raises a plain-English error if no Live preferences folder exists.
    """
    dirs = live_script_dirs(prefs)
    if not dirs:
        raise FileNotFoundError("Could not find Ableton's preferences folder (~/Library/Preferences/Ableton). "
                                "Open Ableton Live once, then try again.")
    src = script_source()
    target_dir = dirs[0] / "AbletonMCP"
    target = target_dir / "__init__.py"
    backup = None
    if target.exists():
        if sha256(target) == sha256(src):
            return {"installed": False, "reason": "already current", "target": str(target), "backup": None,
                    "version": source_version(), "live": dirs[0].parent.name, "sha256": sha256(src)}
        backup = backups / ("AbletonMCP-%s" % time.strftime("%Y%m%d-%H%M%S")) / "__init__.py"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        if sha256(backup) != sha256(target):
            raise OSError("The backup did not match the original, so nothing was changed.")
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    if sha256(target) != sha256(src):
        raise OSError("The installed file does not match the one Stemforge ships.")
    return {"installed": True, "reason": None, "target": str(target), "backup": str(backup) if backup else None,
            "version": source_version(), "live": dirs[0].parent.name, "sha256": sha256(src)}
