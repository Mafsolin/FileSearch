from __future__ import annotations

import math
from threading import Event


class FakeProvider:
    """Deterministic stand-in for an embedding provider.

    Vectors are derived from the text so semantically identical inputs score
    identically, which is all the indexing and search tests need.
    """

    def __init__(self, model: str = "test-model", dimensions: int = 8) -> None:
        self.model = model
        self.dimensions = dimensions
        self.text_calls: list[str] = []
        self.page_calls: list[str] = []
        self.image_calls: list[str] = []
        self.closed = False

    def _vector(self, seed: str) -> list[float]:
        return [math.sin((index + 1) * (len(seed) + sum(map(ord, seed)) % 97 + 1)) for index in range(self.dimensions)]

    def embed_text(self, text: str) -> list[float]:
        self.text_calls.append(text)
        return self._vector(text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_pdf_page(self, payload: bytes, filename: str, context_text: str = "") -> list[float]:
        self.page_calls.append(filename)
        return self._vector(filename)

    def embed_image(self, payload: bytes, filename: str, context_text: str = "") -> list[float]:
        self.image_calls.append(filename)
        return self._vector(filename)

    def test_connection(self) -> int:
        return self.dimensions

    def close(self) -> None:
        self.closed = True


def collect(reports: list):
    """Report callback that snapshots the mutable IndexProgress it receives."""

    def report(progress):
        reports.append(
            (
                progress.total_files,
                progress.total_parts,
                progress.completed_parts,
                progress.processed,
                progress.skipped,
            )
        )

    return report


def no_cancel() -> Event:
    return Event()
