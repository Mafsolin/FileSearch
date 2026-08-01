from __future__ import annotations

import heapq
import json
import sqlite3
from pathlib import Path

import numpy as np

from filesearch.domain.models import IndexMetadata, SearchResult, SourceChunk

# Embeddings are stored as raw little-endian float32 and normalised to unit
# length on write, so a cosine similarity is a plain dot product at read time.
# JSON text cost one parse per chunk per query and dominated search latency.
VECTOR_DTYPE = np.dtype("<f4")
VECTOR_FORMAT = "f32"
SCAN_BATCH = 2048
MATCHES_PER_FILE = 5


def encode_vector(values) -> bytes:
    """Normalise a raw embedding and pack it for storage."""
    array = np.asarray(values, dtype=VECTOR_DTYPE)
    if array.ndim != 1 or not array.size:
        raise ValueError("Embedding должен быть непустым списком чисел.")
    if not np.all(np.isfinite(array)):
        raise ValueError("Embedding содержит NaN или бесконечность.")
    norm = float(np.linalg.norm(array))
    if not norm:
        raise ValueError("Embedding состоит из нулей.")
    return (array / norm).astype(VECTOR_DTYPE).tobytes()


def decode_vector(blob) -> np.ndarray:
    if isinstance(blob, str):  # index written before the float32 migration
        return np.asarray(json.loads(blob), dtype=VECTOR_DTYPE)
    return np.frombuffer(blob, dtype=VECTOR_DTYPE)


class Database:
    REQUIRED_TABLES = {"roots", "files", "chunks", "meta"}

    @classmethod
    def validate_index(cls, path: Path) -> None:
        path = Path(path)
        if not path.is_file():
            raise ValueError("Файл SQLite не найден.")
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = None
        try:
            connection = sqlite3.connect(uri, uri=True)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as error:
            raise ValueError(f"Не удалось открыть SQLite-индекс: {error}") from error
        finally:
            if connection is not None:
                connection.close()
        if not cls.REQUIRED_TABLES.issubset(tables):
            raise ValueError("Это не индекс FileSearch: отсутствуют обязательные таблицы.")
        if integrity != "ok":
            raise ValueError(f"SQLite-индекс повреждён: {integrity}")

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=True, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS roots (path TEXT PRIMARY KEY, last_sync TEXT);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, root_path TEXT NOT NULL REFERENCES roots(path) ON DELETE CASCADE, digest TEXT NOT NULL, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE, location TEXT NOT NULL, content TEXT NOT NULL, embedding BLOB NOT NULL);
            CREATE INDEX IF NOT EXISTS chunks_path_idx ON chunks(path);
        """)
        self._migrate()

    # ------------------------------------------------------------- migration

    def _migrate(self) -> None:
        """Bring an index written by an older build up to the current format."""
        if self._meta("vector_format") == VECTOR_FORMAT and self._meta("dimensions"):
            return
        dimensions = None
        last_id = -1
        while True:
            # Walking by id keeps the loop finite even if a row refuses to
            # convert, instead of re-selecting the same batch forever.
            rows = self.connection.execute(
                "SELECT id, embedding FROM chunks WHERE typeof(embedding)='text' AND id>? ORDER BY id LIMIT ?",
                (last_id, SCAN_BATCH),
            ).fetchall()
            if not rows:
                break
            converted = []
            for row in rows:
                vector = decode_vector(row["embedding"])
                dimensions = dimensions or int(vector.size)
                converted.append((encode_vector(vector), row["id"]))
            last_id = rows[-1]["id"]
            # Each batch is independently durable. If migration is interrupted,
            # the next open resumes at the remaining text rows instead of
            # rolling back a multi-minute transaction over the whole index.
            with self.connection:
                self.connection.executemany("UPDATE chunks SET embedding=? WHERE id=?", converted)

        if dimensions is None:
            sample = self.connection.execute("SELECT embedding FROM chunks LIMIT 1").fetchone()
            if sample is not None:
                dimensions = int(decode_vector(sample[0]).size)
        with self.connection:
            if dimensions:
                self.connection.execute(
                    "INSERT INTO meta(key,value) VALUES('dimensions',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(dimensions),),
                )
            if self.connection.execute("SELECT 1 FROM meta LIMIT 1").fetchone() is not None:
                self.connection.execute(
                    "INSERT INTO meta(key,value) VALUES('vector_format',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (VECTOR_FORMAT,),
                )

    def _meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        if self.connection:
            self.connection.close()

    # ----------------------------------------------------------------- roots

    @staticmethod
    def normalize_root(root: Path) -> Path:
        return Path(root).expanduser().resolve()

    def add_root(self, root: Path) -> None:
        root = self.normalize_root(root)
        existing = self.roots()
        if any(root == item or root in item.parents or item in root.parents for item in existing):
            if root not in existing:
                raise ValueError("Нельзя добавлять одинаковые или вложенные папки в один индекс.")
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO roots(path) VALUES (?)", (str(root),))

    def remove_root(self, root: Path) -> None:
        root = self.normalize_root(root)
        with self.connection:
            self.connection.execute("DELETE FROM roots WHERE path=?", (str(root),))
            self._clear_meta_if_empty()

    def roots(self) -> list[Path]:
        return [Path(r["path"]) for r in self.connection.execute("SELECT path FROM roots ORDER BY path")]

    def remap_root(self, old_root: Path, new_root: Path) -> None:
        """Relocate an indexed tree without rebuilding its embeddings."""
        old_root = Path(old_root)
        new_root = self.normalize_root(new_root)
        if not new_root.is_dir():
            raise ValueError("Новая папка не существует.")
        roots = self.roots()
        if old_root not in roots:
            raise ValueError("Исходная папка отсутствует в индексе.")
        if any(item != old_root and (new_root == item or new_root in item.parents or item in new_root.parents) for item in roots):
            raise ValueError("Новая папка пересекается с другой папкой индекса.")
        rows = self.connection.execute("SELECT path,digest,kind FROM files WHERE root_path=?", (str(old_root),)).fetchall()
        mapped = []
        for row in rows:
            try:
                relative = Path(row["path"]).relative_to(old_root)
            except ValueError:
                raise ValueError(f"Файл {row['path']} находится вне своей исходной папки.")
            mapped.append((row, new_root / relative))
        with self.connection:
            self.connection.execute("INSERT INTO roots(path,last_sync) SELECT ?,last_sync FROM roots WHERE path=?", (str(new_root), str(old_root)))
            for row, target in mapped:
                self.connection.execute("INSERT INTO files(path,root_path,digest,kind) VALUES(?,?,?,?)", (str(target), str(new_root), row["digest"], row["kind"]))
                self.connection.execute("UPDATE chunks SET path=? WHERE path=?", (str(target), row["path"]))
                self.connection.execute("DELETE FROM files WHERE path=?", (row["path"],))
            self.connection.execute("DELETE FROM roots WHERE path=?", (str(old_root),))

    # ----------------------------------------------------------------- files

    def current(self, path: Path, digest: str) -> bool:
        row = self.connection.execute("SELECT digest FROM files WHERE path=?", (str(path),)).fetchone()
        return bool(row and row["digest"] == digest)

    def remove_missing(self, root: Path, existing: set[Path]) -> int:
        root = self.normalize_root(root)
        stale = [(r["path"],) for r in self.connection.execute("SELECT path FROM files WHERE root_path=?", (str(root),)) if Path(r["path"]) not in existing]
        with self.connection:
            self.connection.executemany("DELETE FROM files WHERE path=?", stale)
            self._clear_meta_if_empty()
        return len(stale)

    def _clear_meta_if_empty(self) -> None:
        if self.connection.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is None:
            self.connection.execute("DELETE FROM meta")

    # -------------------------------------------------------------- metadata

    def index_metadata(self) -> IndexMetadata:
        model = self._meta("model")
        dimensions = self._meta("dimensions")
        return IndexMetadata(
            model,
            int(dimensions) if dimensions else None,
            self.connection.execute("SELECT count(*) FROM files").fetchone()[0],
            self.connection.execute("SELECT count(*) FROM chunks").fetchone()[0],
        )

    def require_model(self, model: str) -> None:
        current = self.index_metadata().model
        if current and current != model:
            raise ValueError(
                f"Один индекс должен использовать одну embedding-модель. Индекс создан моделью {current}, "
                f"активна {model}. Выполните «Перестроить весь индекс» или верните прежнюю модель."
            )

    def require_vector(self, model: str, dimensions: int) -> None:
        self.require_model(model)
        current = self.index_metadata().dimensions
        if current is not None and current != dimensions:
            raise ValueError(f"Размерность embedding не совпадает: индекс {current}, получено {dimensions}.")

    def stats(self) -> tuple[int, int]:
        m = self.index_metadata()
        return m.file_count, m.chunk_count

    # --------------------------------------------------------------- writing

    def replace(self, root: Path, path: Path, digest: str, kind: str, chunks, model: str) -> None:
        iterator = iter(chunks)
        try:
            first = next(iterator)
        except StopIteration:
            raise ValueError("Нет embeddings для сохранения (пустой документ пропущен).")
        first_blob = encode_vector(first.embedding)
        dims = len(first_blob) // VECTOR_DTYPE.itemsize
        expected_bytes = len(first_blob)
        self.require_vector(model, dims)
        root, path = self.normalize_root(root), Path(path).resolve()
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO roots(path) VALUES (?)", (str(root),))
            self.connection.execute("DELETE FROM files WHERE path=?", (str(path),))
            self.connection.execute("INSERT INTO files(path,root_path,digest,kind) VALUES (?,?,?,?)", (str(path), str(root), digest, kind))
            rows = [(str(path), first.location, first.content, first_blob)]
            for chunk in iterator:
                blob = encode_vector(chunk.embedding)
                if len(blob) != expected_bytes:
                    raise ValueError("Разная размерность embeddings.")
                rows.append((str(path), chunk.location, chunk.content, blob))
                if len(rows) >= 256:
                    self.connection.executemany(
                        "INSERT INTO chunks(path,location,content,embedding) VALUES (?,?,?,?)", rows
                    )
                    rows.clear()
            if rows:
                self.connection.executemany(
                    "INSERT INTO chunks(path,location,content,embedding) VALUES (?,?,?,?)", rows
                )
            for key, value in (("model", model), ("dimensions", str(dims)), ("vector_format", VECTOR_FORMAT)):
                self.connection.execute(
                    "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )

    # --------------------------------------------------------------- reading

    def search(self, vector, limit: int, model: str | None = None, kinds: set[str] | None = None, roots: set[Path] | None = None) -> list[SearchResult]:
        if model is not None:
            self.require_model(model)
        query = np.asarray(vector, dtype=VECTOR_DTYPE)
        metadata = self.index_metadata()
        if metadata.dimensions is None:
            return []
        if query.size != metadata.dimensions:
            raise ValueError(f"Размерность query embedding не совпадает: индекс {metadata.dimensions}, получено {query.size}.")
        if query.ndim != 1 or not np.all(np.isfinite(query)):
            raise ValueError("Query embedding должен содержать только конечные числа.")
        norm = float(np.linalg.norm(query))
        if not norm:
            raise ValueError("Query embedding состоит из нулей.")
        query = query / norm

        params: list = []
        clauses: list[str] = []
        if kinds:
            clauses.append(f"f.kind IN ({','.join('?' for _ in kinds)})")
            params.extend(kinds)
        if roots is not None:
            if not roots:
                return []
            clauses.append(f"f.root_path IN ({','.join('?' for _ in roots)})")
            params.extend(str(Path(x).resolve()) for x in roots)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        # Scores are computed over embeddings only; chunk text is fetched at the
        # end for the handful of rows that actually make it into the answer.
        cursor = self.connection.execute(
            "SELECT c.id, c.path, f.kind, c.embedding FROM chunks c JOIN files f ON f.path=c.path" + where, params
        )
        expected = metadata.dimensions * VECTOR_DTYPE.itemsize
        best: dict[str, list[tuple[float, int]]] = {}
        kinds_by_path: dict[str, str] = {}
        while True:
            rows = cursor.fetchmany(SCAN_BATCH)
            if not rows:
                break
            blobs = []
            for row in rows:
                blob = row["embedding"]
                if isinstance(blob, str) or len(blob) != expected:
                    raise ValueError("Индекс содержит embedding другой размерности. Выполните «Перестроить весь индекс».")
                blobs.append(blob)
            matrix = np.frombuffer(b"".join(blobs), dtype=VECTOR_DTYPE).reshape(len(rows), metadata.dimensions)
            scores = matrix @ query
            for row, score in zip(rows, scores.tolist()):
                path = row["path"]
                kinds_by_path.setdefault(path, row["kind"])
                bucket = best.setdefault(path, [])
                if len(bucket) < MATCHES_PER_FILE:
                    heapq.heappush(bucket, (score, row["id"]))
                elif score > bucket[0][0]:
                    heapq.heapreplace(bucket, (score, row["id"]))

        if not best:
            return []
        ranked = sorted(best.items(), key=lambda item: max(x[0] for x in item[1]), reverse=True)[: max(0, limit)]
        wanted = [chunk_id for _, bucket in ranked for _, chunk_id in bucket]
        details = {
            row["id"]: (row["location"], row["content"])
            for row in self._fetch_chunks(wanted)
        }

        results = []
        for path, bucket in ranked:
            ordered = sorted(bucket, key=lambda x: x[0], reverse=True)
            matches = tuple((details[cid][0], details[cid][1], score) for score, cid in ordered if cid in details)
            if not matches:
                continue
            results.append(SearchResult(ordered[0][0], Path(path), kinds_by_path[path], matches[0][0], matches[0][1], matches))
        return results

    def _fetch_chunks(self, ids: list[int]):
        for start in range(0, len(ids), SCAN_BATCH):
            batch = ids[start : start + SCAN_BATCH]
            yield from self.connection.execute(
                f"SELECT id, location, content FROM chunks WHERE id IN ({','.join('?' for _ in batch)})", batch
            )

    # --------------------------------------------------------------- staging

    def swap_from(self, staging: Path) -> None:
        """Atomically replace the live index contents from a completed staging DB."""
        staging = Path(staging).resolve()
        self.connection.execute("ATTACH DATABASE ? AS staging", (str(staging),))
        try:
            with self.connection:
                for table in ("chunks", "files", "roots", "meta"):
                    self.connection.execute(f"DELETE FROM {table}")
                for table, columns in (
                    ("roots", "path,last_sync"),
                    ("files", "path,root_path,digest,kind"),
                    ("chunks", "id,path,location,content,embedding"),
                    ("meta", "key,value"),
                ):
                    self.connection.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM staging.{table}")
        finally:
            self.connection.execute("DETACH DATABASE staging")
