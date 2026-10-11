"""Installer tests use temp dirs only: they never touch the real ~/Library/Preferences/Ableton."""
import hashlib
import os
from pathlib import Path

import pytest

from stemforge.app import installer


def _live(tmp_path, with_abletonmcp=True, stemforge_text=None):
    d = tmp_path / "prefs" / "Live 12.2.1"
    scripts = d / "User Remote Scripts"
    scripts.mkdir(parents=True)
    (d / "Log.txt").write_text("x")
    if with_abletonmcp:
        (scripts / "AbletonMCP").mkdir()
        (scripts / "AbletonMCP" / "__init__.py").write_text("THE OWNER'S WORKING SCRIPT")
        (scripts / "AbletonMCP" / "notes.txt").write_text("keep")
    if stemforge_text is not None:
        (scripts / "Stemforge").mkdir()
        (scripts / "Stemforge" / "__init__.py").write_text(stemforge_text)
    return tmp_path / "prefs", scripts


def _snapshot(folder: Path):
    return {str(p.relative_to(folder)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_abletonmcp_is_never_touched(tmp_path):
    prefs, scripts = _live(tmp_path)
    before = _snapshot(scripts / "AbletonMCP")
    r = installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert r["installed"] and r["backup"] is None
    assert _snapshot(scripts / "AbletonMCP") == before           # byte-identical, same mtimes
    assert sorted(p.name for p in scripts.iterdir()) == ["AbletonMCP", "Stemforge"]
    assert not (tmp_path / "bk").exists()                         # nothing of the owner's was backed up or moved


def test_writes_exactly_one_file(tmp_path):
    prefs, scripts = _live(tmp_path)
    all_before = _snapshot(tmp_path)
    installer.install(prefs=prefs, backups=tmp_path / "bk")
    added = set(_snapshot(tmp_path)) - set(all_before)
    assert added == {os.path.join("prefs", "Live 12.2.1", "User Remote Scripts", "Stemforge", "__init__.py")}
    assert (scripts / "Stemforge" / "__init__.py").read_bytes() == installer.script_source().read_bytes()


def test_refuses_any_target_that_is_not_the_stemforge_folder(tmp_path):
    scripts = tmp_path / "User Remote Scripts"
    for bad in (scripts / "AbletonMCP" / "__init__.py", scripts / "Other" / "__init__.py",
                scripts / "Stemforge" / "other.py", tmp_path / "Stemforge" / "__init__.py",
                scripts / "AbletonMCP" / "Stemforge" / "__init__.py"):
        with pytest.raises(PermissionError):
            installer._assert_safe(bad)
    installer._assert_safe(scripts / "Stemforge" / "__init__.py")


def test_different_stemforge_script_is_backed_up_first(tmp_path):
    prefs, scripts = _live(tmp_path, stemforge_text="OLD STEMFORGE")
    r = installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert r["installed"] and Path(r["backup"]).read_text() == "OLD STEMFORGE"
    assert "Stemforge-" in r["backup"] and "AbletonMCP" not in r["backup"]


def test_install_twice_is_a_noop(tmp_path):
    prefs, _ = _live(tmp_path)
    installer.install(prefs=prefs, backups=tmp_path / "bk")
    r = installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert not r["installed"] and r["reason"] == "already current"
    assert not (tmp_path / "bk").exists()


def test_plan_shows_what_will_be_written_and_left_alone(tmp_path):
    prefs, scripts = _live(tmp_path)
    p = installer.plan(prefs=prefs, backups=tmp_path / "bk")
    assert p["state"] == "missing" and p["writes"] == [str(scripts / "Stemforge" / "__init__.py")]
    assert p["left_alone"] == ["AbletonMCP"] and p["backup_to"] is None
    assert not (scripts / "Stemforge").exists()                  # planning writes nothing


def test_no_ableton_prefs_is_a_plain_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Open Ableton Live once"):
        installer.install(prefs=tmp_path / "nothing", backups=tmp_path / "bk")


def test_shipped_script_is_stemforges_own():
    src = installer.script_source().read_text()
    assert installer.script_source().parent.name == "Stemforge"
    assert "DEFAULT_PORT = 9878" in src and 'SCRIPT_NAME = "Stemforge"' in src
    assert "9877" not in src and "AbletonMCP" not in src.replace("NOT AbletonMCP", "").replace("it is NOT AbletonMCP", "")
