from __future__ import annotations

import hashlib
import pickle
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event
from tempfile import SpooledTemporaryFile

from filesearch.domain.models import IndexProgress, SourceChunk
from filesearch.providers.base import EmbeddingProvider
from filesearch.services.extraction import IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS, pdf_pages, part_count, text_parts
from filesearch.storage.database import Database

# Seconds per part, used only until enough real timings accumulate.
REMOTE_SECONDS = 8.0
LOCAL_SECONDS = 2.0
SCAN_REPORT_EVERY = 50
CHUNK_SPOOL_MEMORY = 8 * 1024 * 1024


class ChunkSpool:
    """Bound per-file chunk memory while preserving atomic file replacement."""

    def __init__(self, max_memory: int = CHUNK_SPOOL_MEMORY) -> None:
        self._file = SpooledTemporaryFile(max_size=max_memory, mode="w+b")
        self.count = 0

    @property
    def rolled_to_disk(self) -> bool:
        return bool(getattr(self._file, "_rolled", False))

    def append(self, chunk: SourceChunk) -> None:
        pickle.dump(chunk, self._file, protocol=pickle.HIGHEST_PROTOCOL)
        self.count += 1

    def __iter__(self):
        self._file.flush()
        self._file.seek(0)
        while True:
            try:
                yield pickle.load(self._file)
            except EOFError:
                return

    def close(self) -> None:
        self._file.close()


def _report(callback: Callable[[IndexProgress], None], progress: IndexProgress) -> None:
    """Cross the worker/GUI boundary with a stable point-in-time value."""
    callback(replace(progress, errors=list(progress.errors)))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class SyncState:
    """Progress and timing shared by every root of one indexing run."""

    progress: IndexProgress = field(default_factory=lambda: IndexProgress(total_files=0))
    default_average: float = REMOTE_SECONDS
    timed_parts: int = 0
    timed_seconds: float = 0.0

    @property
    def average(self) -> float:
        return self.timed_seconds / self.timed_parts if self.timed_parts else self.default_average

    def reestimate(self) -> None:
        remaining = max(0, self.progress.total_parts - self.progress.completed_parts)
        self.progress.estimated_seconds = remaining * self.average


def _embed_text(provider, text: str):
    method = getattr(provider, "embed_text", None)
    return method(text) if method is not None else provider.embed_texts([text])[0]


def _embed_page(provider, payload, filename, context):
    try:
        return provider.embed_pdf_page(payload, filename, context)
    except TypeError:
        return provider.embed_pdf_page(payload, filename)


def _embed_image(provider, payload, filename, context):
    try:
        return provider.embed_image(payload, filename, context)
    except TypeError:
        return provider.embed_image(payload, filename)


def _scan(root: Path, cancel: Event, report, progress: IndexProgress):
    """Collect files and their estimated part counts, reporting as we go.

    Counting is cheap per file but not free across a large tree, so the window
    shows a live counter instead of sitting frozen before the first request.
    """
    files = sorted(x for x in root.rglob("*") if x.is_file() and x.suffix.lower() in SUPPORTED_EXTENSIONS)
    counts: dict[Path, int] = {}
    progress.detail = "Оцениваем объём работы"
    for number, path in enumerate(files, 1):
        if cancel.is_set():
            raise InterruptedError("Индексация отменена пользователем")
        counts[path] = part_count(path)
        if number % SCAN_REPORT_EVERY == 0 or number == len(files):
            progress.current_path = str(path)
            _report(report, progress)
    progress.detail = ""
    progress.current_path = ""
    _report(report, progress)
    return files, counts


def sync(
    root: Path,
    db: Database,
    provider: EmbeddingProvider,
    cancel: Event,
    report: Callable[[IndexProgress], None],
    state: SyncState | None = None,
) -> IndexProgress:
    """Index one root into ``db``.

    Pass a shared ``state`` to thread one counter and one running ETA through
    several roots; omit it to track this root alone.
    """
    state = state or SyncState()
    progress = state.progress
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Папка недоступна или не существует: {root}. Старый индекс сохранён; укажите новое расположение.")
    # Model compatibility is local metadata. Check before walking the tree,
    # deleting stale rows or transmitting a single document to the provider.
    db.require_model(provider.model)
    db.add_root(root)

    files, counts = _scan(root, cancel, report, progress)
    estimated = sum(
        counts[p] * (REMOTE_SECONDS if p.suffix.lower() in IMAGE_EXTENSIONS | {".pdf"} else LOCAL_SECONDS) for p in files
    )
    total_parts = sum(counts.values())

    progress.total_files += len(files)
    progress.total_parts += total_parts
    progress.removed += db.remove_missing(root, set(files))
    progress.estimated_seconds += estimated
    if total_parts:
        state.default_average = estimated / total_parts
    _report(report, progress)

    def part_done(started: float) -> None:
        state.timed_parts += 1
        state.timed_seconds += time.monotonic() - started
        progress.completed_parts += 1
        state.reestimate()
        _report(report, progress)

    for path in files:
        if cancel.is_set():
            raise InterruptedError("Индексация отменена пользователем")
        progress.current_file += 1
        progress.current_path = str(path)
        _report(report, progress)
        estimate = counts[path]
        records = ChunkSpool()
        try:
            initial_stat = path.stat()
            initial_signature = (initial_stat.st_size, initial_stat.st_mtime_ns)
            file_digest = digest(path)
            if db.current(path, file_digest):
                progress.skipped += 1
                # `finally` reconciles total_parts with the empty record list,
                # which drops this file's unspent estimate exactly once.
                continue
            ext = path.suffix.lower()
            if ext == ".pdf":
                for page in pdf_pages(path):
                    if cancel.is_set():
                        raise InterruptedError("Индексация отменена пользователем")
                    progress.detail = f"Страница {page.number}"
                    _report(report, progress)
                    started = time.monotonic()
                    transcript = (
                        provider.transcribe_image(page.visual_payload or b"", f"{path.stem}-page-{page.number}.jpg")
                        if not page.text and hasattr(provider, "transcribe_image")
                        else ""
                    )
                    content = "\n".join(x for x in (page.text, transcript) if x)
                    records.append(
                        SourceChunk(
                            page.location,
                            content,
                            _embed_page(provider, page.payload, f"{path.stem}-page-{page.number}.pdf", content),
                        )
                    )
                    part_done(started)
            elif ext in IMAGE_EXTENSIONS:
                started = time.monotonic()
                raw = path.read_bytes()
                transcript = provider.transcribe_image(raw, path.name) if hasattr(provider, "transcribe_image") else ""
                records.append(SourceChunk("Изображение", transcript, _embed_image(provider, raw, path.name, transcript)))
                part_done(started)
            else:
                for part in text_parts(path):
                    if cancel.is_set():
                        raise InterruptedError("Индексация отменена пользователем")
                    started = time.monotonic()
                    records.append(SourceChunk(part.location, part.text, _embed_text(provider, part.text)))
                    part_done(started)
            final_digest = digest(path)
            final_stat = path.stat()
            final_signature = (final_stat.st_size, final_stat.st_mtime_ns)
            if final_digest != file_digest or final_signature != initial_signature:
                raise ValueError("Файл изменился во время удалённой индексации; старый индекс сохранён.")
            if not records.count:
                raise ValueError("Пустой документ пропущен: нет текста для embedding.")
            db.replace(root, path, file_digest, ext.lstrip("."), records, provider.model)
            progress.processed += 1
            progress.chunks += records.count
        except InterruptedError:
            raise
        except Exception as error:
            progress.failed += 1
            progress.errors.append(f"{path}: {error}")
        finally:
            record_count = records.count
            records.close()
            # Replace the guess with what the document actually produced, so a
            # long run converges on a truthful "осталось" instead of drifting.
            progress.total_parts += record_count - estimate
            progress.detail = ""
            state.reestimate()
            _report(report, progress)
    return progress


def rebuild_all(
    roots,
    live_path: Path,
    profile,
    key: str,
    cancel: Event,
    report: Callable[[IndexProgress], None],
    vision_profile=None,
    vision_key: str = "",
) -> IndexProgress:
    """Build every configured root in a sibling DB and atomically publish it.

    The live index is only replaced once every root has been embedded, so a
    failure or a cancellation halfway through leaves the current index intact.
    This is what makes switching embedding models safe.
    """
    from filesearch.providers.openai_compatible import OpenAICompatibleProvider

    live_path = Path(live_path)
    staging = live_path.with_name(f"{live_path.stem}.rebuild-{uuid.uuid4().hex}.sqlite3")
    state = SyncState()
    db = provider = None
    try:
        db = Database(staging)
        provider = OpenAICompatibleProvider(profile, key, cancel, vision_profile, vision_key)
        for root in roots:
            sync(Path(root), db, provider, cancel, report, state=state)
        if cancel.is_set():
            raise InterruptedError("Перестройка отменена пользователем")
        if state.progress.failed or state.progress.errors:
            raise RuntimeError(
                f"Перестройка завершилась с ошибками ({state.progress.failed}) — прежний индекс сохранён."
            )
        if not state.progress.processed:
            raise ValueError("Ни один файл не удалось проиндексировать — прежний индекс сохранён.")
        db.close()
        db = None
        if cancel.is_set():
            raise InterruptedError("Перестройка отменена пользователем")
        live = Database(live_path)
        try:
            if cancel.is_set():
                raise InterruptedError("Перестройка отменена пользователем")
            live.swap_from(staging)
        finally:
            live.close()
        return state.progress
    finally:
        if db is not None:
            db.close()
        if provider is not None:
            provider.close()
        _discard(staging)


def _discard(staging: Path) -> None:
    """Remove the staging DB and the journal files SQLite leaves beside it."""
    for suffix in ("", "-wal", "-shm"):
        try:
            staging.with_name(staging.name + suffix).unlink()
        except OSError:
            pass
