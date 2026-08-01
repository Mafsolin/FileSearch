from __future__ import annotations

from threading import Event
import os

import pytest

from filesearch.services.indexing import ChunkSpool, SyncState, rebuild_all, sync
from filesearch.domain.models import SourceChunk
from filesearch.storage.database import Database
from conftest import FakeProvider


def make_tree(tmp_path, count: int = 3):
    root = tmp_path / "docs"
    root.mkdir(parents=True)
    for index in range(count):
        (root / f"file{index}.txt").write_text(f"договор аренды номер {index}", encoding="utf-8")
    return root


def test_sync_indexes_every_file(tmp_path):
    root = make_tree(tmp_path)
    db = Database(tmp_path / "index.sqlite3")
    provider = FakeProvider()
    progress = sync(root, db, provider, Event(), lambda p: None)
    assert progress.processed == 3
    assert progress.failed == 0
    assert db.stats() == (3, 3)
    db.close()


def test_sync_skips_unchanged_files_on_second_run(tmp_path):
    root = make_tree(tmp_path)
    db = Database(tmp_path / "index.sqlite3")
    provider = FakeProvider()
    sync(root, db, provider, Event(), lambda p: None)
    calls = len(provider.text_calls)
    second = sync(root, db, provider, Event(), lambda p: None)
    assert second.skipped == 3
    assert second.processed == 0
    assert len(provider.text_calls) == calls  # nothing re-embedded


def test_sync_totals_converge_on_real_part_counts(tmp_path):
    """The size-based estimate must be reconciled with what was produced."""
    root = tmp_path / "docs"
    root.mkdir()
    (root / "long.txt").write_text("абзац текста. " * 900, encoding="utf-8")
    db = Database(tmp_path / "index.sqlite3")
    progress = sync(root, db, FakeProvider(), Event(), lambda p: None)
    assert progress.total_parts == progress.completed_parts
    assert progress.completed_parts == progress.chunks
    db.close()


def test_sync_reports_progress_during_scan(tmp_path):
    root = make_tree(tmp_path)
    db = Database(tmp_path / "index.sqlite3")
    seen = []
    sync(root, db, FakeProvider(), Event(), lambda p: seen.append(p.detail))
    assert "Оцениваем объём работы" in seen  # window is not frozen before the first request
    db.close()


def test_progress_reports_are_immutable_snapshots(tmp_path):
    root = make_tree(tmp_path, 2)
    db = Database(tmp_path / "index.sqlite3")
    seen = []

    sync(root, db, FakeProvider(), Event(), seen.append)

    assert len({id(item) for item in seen}) == len(seen)
    assert seen[0].current_file == 0
    assert seen[-1].current_file == 2
    db.close()


def test_sync_honours_cancellation(tmp_path):
    root = make_tree(tmp_path)
    db = Database(tmp_path / "index.sqlite3")
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        sync(root, db, FakeProvider(), cancel, lambda p: None)
    db.close()


def test_shared_state_accumulates_across_roots(tmp_path):
    first = make_tree(tmp_path / "a", 2)
    second = make_tree(tmp_path / "b", 3)
    db = Database(tmp_path / "index.sqlite3")
    provider = FakeProvider()
    state = SyncState()
    sync(first, db, provider, Event(), lambda p: None, state=state)
    sync(second, db, provider, Event(), lambda p: None, state=state)
    assert state.progress.total_files == 5
    assert state.progress.processed == 5
    assert state.progress.current_file == 5
    db.close()


def test_sync_rejects_model_mismatch_before_scanning_or_embedding(tmp_path):
    root = make_tree(tmp_path, 1)
    db = Database(tmp_path / "index.sqlite3")
    old = FakeProvider(model="old")
    sync(root, db, old, Event(), lambda p: None)
    (root / "file0.txt").write_text("изменённый договор", encoding="utf-8")
    new = FakeProvider(model="new")

    with pytest.raises(ValueError, match="одну embedding-модель"):
        sync(root, db, new, Event(), lambda p: None)

    assert new.text_calls == []
    assert db.index_metadata().model == "old"
    db.close()


def test_sync_of_a_missing_root_preserves_its_old_index(tmp_path):
    root = make_tree(tmp_path, 1)
    db = Database(tmp_path / "index.sqlite3")
    sync(root, db, FakeProvider(), Event(), lambda p: None)
    moved = tmp_path / "moved"
    root.rename(moved)

    with pytest.raises(ValueError, match="недоступна|не существует"):
        sync(root, db, FakeProvider(), Event(), lambda p: None)

    assert db.stats() == (1, 1)
    db.close()


def test_sync_rejects_a_stat_change_even_when_digest_is_unchanged(tmp_path, monkeypatch):
    root = make_tree(tmp_path, 1)
    path = root / "file0.txt"
    db = Database(tmp_path / "index.sqlite3")
    sync(root, db, FakeProvider(), Event(), lambda p: None)
    old_content = db.connection.execute("SELECT content FROM chunks").fetchone()[0]
    path.write_text("новая версия договора", encoding="utf-8")

    from filesearch.services import indexing

    real_digest = indexing.digest
    calls = 0

    def digest_and_touch(candidate):
        nonlocal calls
        calls += 1
        value = real_digest(candidate)
        if calls == 2:
            stat = candidate.stat()
            os.utime(candidate, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        return value

    monkeypatch.setattr(indexing, "digest", digest_and_touch)
    progress = sync(root, db, FakeProvider(), Event(), lambda p: None)

    assert progress.failed == 1
    assert "изменился" in progress.errors[0]
    assert db.connection.execute("SELECT content FROM chunks").fetchone()[0] == old_content
    db.close()


def test_chunk_spool_spills_to_disk_and_replays_in_order():
    spool = ChunkSpool(max_memory=1)
    chunks = [
        SourceChunk("часть 1", "первый", [1.0, 0.0]),
        SourceChunk("часть 2", "второй", [0.0, 1.0]),
    ]
    try:
        for chunk in chunks:
            spool.append(chunk)

        assert spool.rolled_to_disk
        assert spool.count == 2
        assert list(spool) == chunks
    finally:
        spool.close()
