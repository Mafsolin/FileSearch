from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest

from filesearch.domain.models import SourceChunk
from filesearch.storage.database import Database, decode_vector, encode_vector


def test_encode_normalises_to_unit_length():
    blob = encode_vector([3.0, 4.0])
    values = decode_vector(blob)
    assert pytest.approx(float(np.linalg.norm(values)), abs=1e-6) == 1.0


def test_encode_rejects_degenerate_vectors():
    with pytest.raises(ValueError):
        encode_vector([])
    with pytest.raises(ValueError):
        encode_vector([0.0, 0.0])
    with pytest.raises(ValueError):
        encode_vector([1.0, float("nan")])


def test_search_ranks_by_cosine_similarity(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    near = root / "near.txt"
    far = root / "far.txt"
    near.write_text("a")
    far.write_text("b")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(root)
    db.replace(root, near, "1", "txt", [SourceChunk("Текст", "договор", [1.0, 0.1])], "model")
    db.replace(root, far, "2", "txt", [SourceChunk("Текст", "погода", [0.0, 1.0])], "model")

    results = db.search([1.0, 0.0], 5)

    assert [r.path for r in results] == [near, far]
    assert results[0].score > results[1].score
    assert results[0].score == pytest.approx(0.995, abs=1e-2)
    db.close()


def test_search_scale_of_query_does_not_change_ranking(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "a.txt"
    path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(root)
    db.replace(root, path, "1", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "model")

    small = db.search([1.0, 0.0], 1)[0].score
    large = db.search([1000.0, 0.0], 1)[0].score

    assert small == pytest.approx(large, abs=1e-6)
    db.close()


def test_search_keeps_several_matches_per_file(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "many.txt"
    path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(root)
    chunks = [SourceChunk(f"часть {n}", f"текст {n}", [1.0, n / 10]) for n in range(8)]
    db.replace(root, path, "1", "txt", chunks, "model")

    result = db.search([1.0, 0.0], 5)[0]

    assert len(result.matches) == 5  # capped, not all eight
    assert [m[2] for m in result.matches] == sorted((m[2] for m in result.matches), reverse=True)
    assert result.score == result.matches[0][2]
    db.close()


def test_legacy_json_index_is_migrated_on_open(tmp_path):
    """An index written before the float32 change must keep working."""
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE roots (path TEXT PRIMARY KEY, last_sync TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE files (path TEXT PRIMARY KEY, root_path TEXT NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, path TEXT NOT NULL, location TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL);
    """)
    root = tmp_path / "docs"
    connection.execute("INSERT INTO roots(path) VALUES (?)", (str(root),))
    connection.execute("INSERT INTO files VALUES (?,?,?,?)", (str(root / "a.txt"), str(root), "d", "txt"))
    connection.execute(
        "INSERT INTO chunks(path,location,content,embedding) VALUES (?,?,?,?)",
        (str(root / "a.txt"), "Текст", "договор", json.dumps([3.0, 4.0])),
    )
    connection.execute("INSERT INTO meta VALUES ('model','old')")
    connection.commit()
    connection.close()

    db = Database(path)
    stored = db.connection.execute("SELECT embedding FROM chunks").fetchone()[0]
    assert isinstance(stored, bytes)
    assert db.index_metadata().dimensions == 2
    assert db.search([3.0, 4.0], 1)[0].score == pytest.approx(1.0, abs=1e-5)
    db.close()


def test_legacy_migration_commits_each_batch_and_can_resume(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE roots (path TEXT PRIMARY KEY, last_sync TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE files (path TEXT PRIMARY KEY, root_path TEXT NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE chunks (id INTEGER PRIMARY KEY, path TEXT NOT NULL, location TEXT NOT NULL, content TEXT NOT NULL, embedding TEXT NOT NULL);
    """)
    connection.executemany(
        "INSERT INTO chunks(path,location,content,embedding) VALUES (?,?,?,?)",
        [(f"p{n}", "Текст", "содержимое", json.dumps([1.0, float(n + 1)])) for n in range(2)],
    )
    connection.commit()
    connection.close()

    import filesearch.storage.database as database_module

    monkeypatch.setattr(database_module, "SCAN_BATCH", 1)
    real_encode = database_module.encode_vector
    calls = 0

    def fail_second(values):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated interruption")
        return real_encode(values)

    monkeypatch.setattr(database_module, "encode_vector", fail_second)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        Database(path)

    connection = sqlite3.connect(path)
    types = [row[0] for row in connection.execute("SELECT typeof(embedding) FROM chunks ORDER BY id")]
    connection.close()
    assert types == ["blob", "text"]

    monkeypatch.setattr(database_module, "encode_vector", real_encode)
    db = Database(path)
    assert [row[0] for row in db.connection.execute("SELECT typeof(embedding) FROM chunks ORDER BY id")] == ["blob", "blob"]
    db.close()


def test_search_rejects_a_query_of_the_wrong_size(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "a.txt"
    path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(root)
    db.replace(root, path, "1", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "model")
    with pytest.raises(ValueError, match="Размерность query embedding"):
        db.search([1.0, 0.0, 0.0], 1)
    db.close()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_search_rejects_non_finite_query_values(tmp_path, bad):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "a.txt"
    path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(root)
    db.replace(root, path, "1", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "model")

    with pytest.raises(ValueError, match="конечные числа"):
        db.search([bad, 0.0], 1)
    db.close()


def test_search_on_an_empty_index_returns_nothing(tmp_path):
    db = Database(tmp_path / "index.sqlite3")
    assert db.search([1.0, 0.0], 5) == []
    db.close()


def test_replace_rejects_a_model_change(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    path = root / "a.txt"
    path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(root)
    db.replace(root, path, "1", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "first")
    with pytest.raises(ValueError, match="одну embedding-модель"):
        db.replace(root, path, "2", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "second")
    db.close()


def test_remove_root_clears_metadata_when_the_last_chunk_disappears(tmp_path):
    full = tmp_path / "full"
    empty = tmp_path / "empty"
    full.mkdir(); empty.mkdir()
    path = full / "a.txt"; path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(empty)
    db.replace(full, path, "1", "txt", [SourceChunk("Текст", "договор", [1.0, 0.0])], "old")

    db.remove_root(full)

    metadata = db.index_metadata()
    assert metadata.chunk_count == 0
    assert metadata.model is None
    assert metadata.dimensions is None
    db.require_model("new")
    db.close()


def test_replace_consumes_a_one_pass_chunk_iterator(tmp_path):
    root = tmp_path / "docs"; root.mkdir()
    path = root / "a.txt"; path.write_text("a")
    db = Database(tmp_path / "index.sqlite3")
    used = False

    def chunks():
        nonlocal used
        if used:
            raise AssertionError("iterator consumed twice")
        used = True
        yield SourceChunk("часть 1", "первый", [1.0, 0.0])
        yield SourceChunk("часть 2", "второй", [0.0, 1.0])

    db.replace(root, path, "digest", "txt", chunks(), "model")

    assert db.stats() == (1, 2)
    db.close()
