from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from filesearch.gui import theme
from filesearch.gui.main_window import MainWindow


def run_pdf_smoke(pdf_path: Path, database_path: Path) -> int:
    """Exercise frozen PDFium extraction/rendering and SQLite indexing."""
    from filesearch.domain.models import SourceChunk
    from filesearch.services.extraction import pdf_pages
    from filesearch.services.indexing import digest
    from filesearch.storage.database import Database

    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise ValueError(f"PDF not found: {pdf_path}")
    chunks = []
    for page in pdf_pages(pdf_path):
        if not page.payload or not page.payload.startswith(b"%PDF") or not page.visual_payload:
            raise ValueError(f"Page {page.number} was not rendered correctly")
        chunks.append(
            SourceChunk(
                page.location,
                page.text or f"Rendered PDF page {page.number}",
                [1.0, float(page.number)],
            )
        )
    if not chunks:
        raise ValueError("PDF contains no pages")
    db = Database(database_path)
    try:
        db.replace(pdf_path.parent, pdf_path, digest(pdf_path), "pdf", chunks, "frozen-smoke")
        if db.stats() != (1, len(chunks)):
            raise RuntimeError("Smoke index counts do not match rendered pages")
    finally:
        db.close()
    return 0


def icon_path() -> Path:
    """Locate the app icon in both the source tree and the frozen build."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return base / "assets" / "brand" / "filesearch.ico"


def main() -> int:
    if len(sys.argv) >= 4 and sys.argv[1] == "--smoke-pdf":
        try:
            return run_pdf_smoke(Path(sys.argv[2]), Path(sys.argv[3]))
        except Exception:
            return 1
    app = QApplication(sys.argv)
    app.setApplicationName("FileSearch")
    app.setOrganizationName("FileSearch")

    icon_file = icon_path()
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    app.setFont(theme.base_font())
    # MainWindow reads the stored theme and applies the palette and stylesheet
    # itself, so both stay in sync with the icon cache.
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
