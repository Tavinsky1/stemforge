from stemforge import workflow


def _bp():
    return {"song": {"name": "s"}, "stems": [
        {"name": "a", "transcription": {"skipped": False, "notes": [1]}},
        {"name": "b", "transcription": {"skipped": False, "notes": []}},
        {"name": "c", "transcription": {"skipped": True, "reason": "silent"}},
        {"name": "d", "transcription": {"skipped": False, "notes": [1]}}]}


def test_select_without_report_drops_skipped_and_empty():
    keep, out = workflow.select_stems(_bp(), None)
    assert keep == ["a", "d"] and set(out) == {"b", "c"}


def test_select_with_report_applies_floor_and_include():
    rep = {"a": {"onset_precision": 0.9, "coverage": 0.9}, "d": {"onset_precision": 0.01, "coverage": 0.9},
           "b": {"status": "no notes"}}
    keep, out = workflow.select_stems(_bp(), rep)
    assert keep == ["a"] and "likely false notes" in out["d"]
    keep, _ = workflow.select_stems(_bp(), rep, include={"d"})
    assert keep == ["a", "d"]
    keep, _ = workflow.select_stems(_bp(), rep, only=["a"])
    assert keep == ["a"]


def test_verify_paths_roundtrip(tmp_path):
    bp = tmp_path / "song.blueprint.json"
    assert workflow.load_verify(bp) is None
    workflow.save_verify(bp, {"stems": {"a": {"x": 1}}})
    assert workflow.verify_path(bp).name == "song.verify.json"
    assert workflow.load_verify(bp) == {"a": {"x": 1}}
