from filesearch.domain.models import SourceChunk
from filesearch.storage.database import Database


def test_database_removes_only_missing_root_files(tmp_path):
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir(); second.mkdir()
    a = first / "a.txt"; b = second / "b.txt"
    a.write_text("a"); b.write_text("b")
    db = Database(tmp_path / "index.sqlite3")
    db.add_root(first); db.add_root(second)
    db.replace(first, a, "a", "txt", [SourceChunk("Текст", "договор", [1, 0])], "model")
    db.replace(second, b, "b", "txt", [SourceChunk("Текст", "отчёт", [0, 1])], "model")
    assert db.remove_missing(first, set()) == 1
    assert len(db.search([0, 1], 5)) == 1
    db.close()


def test_replace_and_search(tmp_path):
    root = tmp_path / "docs"; root.mkdir(); path = root / "doc.txt"; path.write_text("x")
    db = Database(tmp_path / "index.sqlite3"); db.add_root(root)
    db.replace(root, path, "digest", "txt", [SourceChunk("Текст", "договор аренды", [1.0, 0.0])], "model")
    assert db.search([1.0, 0.0], 1)[0].path == path
    db.close()
