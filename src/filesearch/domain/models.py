from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    name: str
    base_url: str
    model: str
    key_name: str
    builtin: bool = False
    vision_model: str | None = None


@dataclass(frozen=True)
class VisionProfile:
    id: str
    name: str
    base_url: str
    model: str
    key_name: str
    builtin: bool = False


@dataclass(frozen=True)
class SourceChunk:
    location: str
    content: str
    embedding: list[float]


@dataclass(frozen=True)
class IndexMetadata:
    model: str | None
    dimensions: int | None
    file_count: int
    chunk_count: int


@dataclass(frozen=True)
class DocumentPart:
    number: int
    location: str
    text: str = ""
    payload: bytes | None = None
    media_type: str | None = None
    visual_payload: bytes | None = None


@dataclass(frozen=True)
class SearchResult:
    score: float
    path: Path
    kind: str
    location: str
    content: str
    matches: tuple[tuple[str, str, float], ...] = ()


@dataclass
class IndexProgress:
    total_files: int
    current_file: int = 0
    processed: int = 0
    skipped: int = 0
    removed: int = 0
    failed: int = 0
    chunks: int = 0
    current_path: str = ""
    detail: str = ""
    errors: list[str] = field(default_factory=list)
    total_parts: int = 0
    completed_parts: int = 0
    estimated_seconds: float = 0.0
