"""Installer tests use temp dirs only: they never touch the real ~/Library/Preferences/Ableton."""
import pytest

from stemforge.app import installer


def _prefs(tmp_path, old_text=None):
    d = tmp_path / "prefs" / "Live 12.2.1"
    (d / "User Remote Scripts" / "AbletonMCP").mkdir(parents=True)
    (d / "Log.txt").write_text("x")
    if old_text is not None:
        (d / "User Remote Scripts" / "AbletonMCP" / "__init__.py").write_text(old_text)
    return tmp_path / "prefs"


def test_install_backs_up_then_copies(tmp_path):
    prefs = _prefs(tmp_path, "OLD SCRIPT")
    sibling = prefs / "Live 12.2.1" / "User Remote Scripts" / "AbletonMCP" / "notes.txt"
    sibling.write_text("keep me")
    r = installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert r["installed"] and r["version"] == installer.source_version()
    assert (tmp_path / "bk").glob("AbletonMCP-*/__init__.py")
    assert open(r["backup"]).read() == "OLD SCRIPT"
    assert installer.sha256(installer.script_source()) == installer.sha256(__import__("pathlib").Path(r["target"]))
    assert sibling.read_text() == "keep me"                 # nothing else in the folder is touched


def test_install_twice_is_a_noop(tmp_path):
    prefs = _prefs(tmp_path, "OLD")
    installer.install(prefs=prefs, backups=tmp_path / "bk")
    r = installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert not r["installed"] and r["reason"] == "already current"
    assert len(list((tmp_path / "bk").iterdir())) == 1       # no second backup


def test_fresh_install_needs_no_backup(tmp_path):
    prefs = _prefs(tmp_path)
    r = installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert r["installed"] and r["backup"] is None


def test_status_states(tmp_path):
    prefs = _prefs(tmp_path, "OLD")
    assert installer.status(prefs)[0]["state"] == "old"
    installer.install(prefs=prefs, backups=tmp_path / "bk")
    assert installer.status(prefs)[0]["state"] == "current"


def test_no_ableton_prefs_is_a_plain_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Open Ableton Live once"):
        installer.install(prefs=tmp_path / "nothing", backups=tmp_path / "bk")


def test_shipped_script_matches_the_source_repo_contract():
    src = installer.script_source().read_text()
    assert 'SCRIPT_VERSION = "stemforge-' in src
    for cmd in ("list_commands", "create_arrangement_clip", "add_notes_to_arrangement_clip", "get_arrangement_clip_notes"):
        assert '"%s"' % cmd in src
    assert ".set_notes(" not in src
