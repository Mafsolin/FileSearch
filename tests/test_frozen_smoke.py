from pathlib import Path

from PIL import Image, ImageDraw

from filesearch.__main__ import run_pdf_smoke
from filesearch.storage.database import Database


def make_pdf(path: Path) -> None:
    pages = []
    for number in (1, 2):
        image = Image.new("RGB", (600, 800), "white")
        ImageDraw.Draw(image).text((40, 40), f"FileSearch page {number}", fill="black")
        pages.append(image)
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:], resolution=150)


def test_pdf_smoke_extracts_renders_and_indexes_every_page(tmp_path):
    pdf = tmp_path / "multi.pdf"
    database = tmp_path / "smoke.sqlite3"
    make_pdf(pdf)

    assert run_pdf_smoke(pdf, database) == 0

    db = Database(database)
    assert db.stats() == (1, 2)
    assert [row[0] for row in db.connection.execute("SELECT location FROM chunks ORDER BY id")] == [
        "Страница 1",
        "Страница 2",
    ]
    db.close()
