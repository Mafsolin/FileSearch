from __future__ import annotations

import time

import pytest
from docx import Document
from docx.enum.text import WD_BREAK
from openpyxl import Workbook
from PIL import Image

from filesearch.services import extraction
from filesearch.services.extraction import PART_CHARS, _one_page_pdf, part_count, split, text_parts
from filesearch.domain.models import DocumentPart


def test_split_covers_the_whole_text():
    text = "\n".join(f"строка номер {n} с содержанием" for n in range(400))
    parts = list(split(text, "Текст", PART_CHARS))
    assert len(parts) > 1
    assert "строка номер 0" in parts[0].text
    assert "строка номер 399" in parts[-1].text
    assert all(part.text.strip() for part in parts)


def test_split_numbers_parts_consecutively():
    parts = list(split("абзац. " * 2000, "Текст", PART_CHARS))
    assert [p.number for p in parts] == list(range(1, len(parts) + 1))


def test_split_overlaps_consecutive_parts():
    """Overlap keeps a sentence that straddles a boundary findable."""
    parts = list(split("слово " * 1200, "Текст", PART_CHARS))
    assert len(parts) >= 2
    total = sum(len(p.text) for p in parts)
    assert total > len("слово " * 1200) * 0.99  # nothing dropped between parts


def test_split_of_short_text_is_one_part():
    parts = list(split("короткий договор", "Текст", PART_CHARS))
    assert len(parts) == 1
    assert parts[0].location == "Текст · часть 1"


def test_split_of_blank_text_yields_nothing():
    assert list(split("   \n\n  ", "Текст", PART_CHARS)) == []


def test_part_count_does_not_parse_text_documents(tmp_path):
    """The pre-scan must stay cheap: it runs over every file before any work."""
    path = tmp_path / "big.txt"
    path.write_text("строка текста. " * 200_000, encoding="utf-8")

    started = time.monotonic()
    estimate = part_count(path)
    elapsed = time.monotonic() - started

    assert estimate > 1
    assert elapsed < 0.2  # a full parse of this file takes far longer


def test_part_count_estimate_is_in_the_right_ballpark(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("а" * (PART_CHARS * 10), encoding="utf-8")
    actual = sum(1 for _ in text_parts(path))
    estimate = part_count(path)
    assert 0.3 <= estimate / actual <= 3.0


def test_part_count_of_an_unreadable_file_is_one(tmp_path):
    assert part_count(tmp_path / "missing.txt") == 1


def test_text_parts_reads_utf8_with_replacement(tmp_path):
    """A file with a broken byte must still be indexed, not skipped."""
    path = tmp_path / "broken.txt"
    path.write_bytes(b"\xff\xfe " + "договор аренды".encode("utf-8"))
    parts = list(text_parts(path))
    assert parts
    assert "договор" in parts[0].text


def test_document_part_can_carry_a_single_api_payload():
    payload = b"one physical page"
    part = DocumentPart(2, "Страница 2", "текст", payload=payload, media_type="application/pdf")

    assert part.payload is payload
    assert part.media_type == "application/pdf"


def test_markdown_repeats_heading_context_and_reports_line_ranges(tmp_path):
    path = tmp_path / "manual.md"
    path.write_text("# Монтаж\n" + "важная длинная строка\n" * 40, encoding="utf-8")

    parts = list(text_parts(path, max_chars=120))

    assert len(parts) > 2
    assert all("# Монтаж" in part.text for part in parts)
    assert all("строки" in part.location for part in parts)


def test_txt_parts_report_source_line_ranges(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("\n".join(f"строка {number}" for number in range(30)), encoding="utf-8")

    parts = list(text_parts(path, max_chars=80))

    assert len(parts) > 1
    assert all("строки" in part.location for part in parts)


def test_docx_page_break_is_a_hard_boundary_with_heading_context(tmp_path):
    path = tmp_path / "document.docx"
    document = Document()
    document.add_heading("Раздел договора", level=1)
    document.add_paragraph("Текст до разрыва")
    run = document.add_paragraph().add_run()
    run.add_break(WD_BREAK.PAGE)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "После"
    table.cell(0, 1).text = "разрыва"
    document.save(path)

    parts = list(text_parts(path, max_chars=1000))

    assert len(parts) == 2
    assert "Текст до разрыва" in parts[0].text
    assert "После | разрыва" in parts[1].text
    assert "Раздел договора" in parts[1].text


def test_xlsx_streams_bounded_row_windows_with_repeated_headers(tmp_path):
    path = tmp_path / "book.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Смета"
    sheet.append(["Код", "Описание"])
    for number in range(1, 12):
        sheet.append([number, f"работа номер {number} с материалами"])
    workbook.save(path)

    parts = list(text_parts(path, max_chars=120))

    assert len(parts) > 1
    assert all("Лист «Смета» · строки" in part.location for part in parts)
    assert all(part.text.startswith("Код; Описание") for part in parts)
    assert "работа номер 1" in parts[0].text
    assert "работа номер 11" in parts[-1].text


def test_one_page_pdf_preserves_the_requested_render_dpi():
    import pypdfium2 as pdfium

    data = _one_page_pdf(Image.new("RGB", (200, 200), "white"), 75, 200)
    document = pdfium.PdfDocument(data)
    try:
        width, height = document[0].get_size()
    finally:
        document.close()

    assert width == pytest.approx(72.0, abs=0.5)
    assert height == pytest.approx(72.0, abs=0.5)


def test_pdf_retries_and_rejects_an_oversized_visual_payload(tmp_path, monkeypatch):
    path = tmp_path / "page.pdf"
    Image.new("RGB", (100, 100), "white").save(path, format="PDF")
    calls = []

    def huge_jpeg(image, quality):
        calls.append(quality)
        return b"x" * (21 * 1024 * 1024)

    monkeypatch.setattr(extraction, "_jpeg", huge_jpeg)

    with pytest.raises(ValueError, match="20 МБ"):
        next(extraction.pdf_pages(path))
    assert calls == [75, 70]  # 200 DPI, then 150 DPI fallback
