"""Bundle 展開・validation の smoke test。"""

from __future__ import annotations

from pathlib import Path

import pytest

from kage_pipeline.bundle import BundleError, load_bundle, read_jsonl


def test_load_extracted_bundle(hn_minimal_dir: Path) -> None:
    b = load_bundle(hn_minimal_dir)
    assert b.root == hn_minimal_dir
    assert b.har_path.is_file()
    assert b.events_path.is_file()
    assert b.dom_snapshots_path.is_file()
    assert b.a11y_snapshots_path.is_file()
    assert b.metadata["captureTool"] == "kage-capture"
    # 動画は fixture では省いているので missing に入る
    assert "recording.webm" in b.missing


def test_missing_required_raises(tmp_path: Path) -> None:
    (tmp_path / "metadata.json").write_text('{"captureTool":"kage-capture"}', encoding="utf-8")
    with pytest.raises(BundleError):
        load_bundle(tmp_path)


def test_bad_metadata_raises(tmp_path: Path, hn_minimal_dir: Path) -> None:
    import shutil

    for f in ("network.har", "events.jsonl", "dom_snapshots.jsonl", "a11y_snapshots.jsonl"):
        shutil.copy2(hn_minimal_dir / f, tmp_path / f)
    (tmp_path / "metadata.json").write_text('{"captureTool":"WRONG"}', encoding="utf-8")
    with pytest.raises(BundleError):
        load_bundle(tmp_path)


def test_read_jsonl_events(hn_minimal_dir: Path) -> None:
    events = read_jsonl(hn_minimal_dir / "events.jsonl")
    assert len(events) > 0
    # HN smoke では navigation が必ず1件以上ある
    assert any(e["type"] == "navigation" for e in events)
