from __future__ import annotations

from pathlib import Path
from io import BytesIO
from filesearch.domain.models import DocumentPart
from docx import Document
from openpyxl import load_workbook

TEXT_EXTENSIONS = {".docx", ".xlsx", ".txt", ".md"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | {".pdf"}

PART_CHARS = 1800
PART_OVERLAP = 180
# Rough bytes-per-part divisors used only for the initial ETA. The real part
# count replaces the estimate as soon as a file is actually opened, so these
# never have to be accurate — only cheap, because they run over every file in
# the tree before any work starts.
ESTIMATE_DIVISOR = {".txt": PART_CHARS, ".md": PART_CHARS, ".docx": 2000, ".xlsx": 2000}

def preview(value: str) -> str:
    return " ".join(value.split())

def pdf_pages(path: Path):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        for number in range(len(doc)):
            page = doc[number]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded()
                finally:
                    text_page.close()
                bitmap = page.render(scale=200/72)
                try:
                    image = bitmap.to_pil()
                    image_data = _jpeg(image, 75); data = _one_page_pdf(image, 75, 200)
                finally:
                    bitmap.close()
                if max(len(data), len(image_data)) > 18 * 1024 * 1024:
                    bitmap = page.render(scale=150/72)
                    try:
                        image = bitmap.to_pil()
                        image_data = _jpeg(image, 70); data = _one_page_pdf(image, 70, 150)
                    finally:
                        bitmap.close()
                if max(len(data), len(image_data)) > 20 * 1024 * 1024:
                    raise ValueError(f"{path.name}: страница {number + 1} больше 20 МБ даже при 150 DPI.")
                yield DocumentPart(
                    number + 1,
                    f"Страница {number + 1}",
                    preview(text),
                    payload=data,
                    media_type="application/pdf",
                    visual_payload=image_data,
                )
            finally:
                page.close()
    finally:
        doc.close()

def _one_page_pdf(image, quality: int, resolution: int) -> bytes:
    image = image.convert("RGB")
    out = BytesIO(); image.save(out, format="PDF", resolution=float(resolution), quality=quality)
    return out.getvalue()

def _jpeg(image, quality: int) -> bytes:
    out=BytesIO(); image.convert("RGB").save(out,format="JPEG",quality=quality,optimize=True); return out.getvalue()

def text_parts(path: Path, max_chars=PART_CHARS):
    ext=path.suffix.lower()
    if ext in {".txt", ".md"}:
        yield from _text_file_parts(path, max_chars, markdown=ext == ".md"); return
    if ext == ".docx":
        yield from _docx_parts(path, max_chars); return
    if ext == ".xlsx":
        yield from _xlsx_parts(path, max_chars); return
    raise ValueError("Неподдерживаемый формат")


def _text_file_parts(path: Path, max_chars: int, markdown: bool):
    prefix = "Markdown" if markdown else "Текст"
    buffer: list[tuple[int, str]] = []
    active_heading = ""
    page_heading = ""
    number = 1

    def build(current: list[tuple[int, str]], heading: str):
        nonlocal number
        content = "\n".join(value for _, value in current)
        if heading and heading not in content:
            content = heading + "\n" + content
        part = DocumentPart(number, f"{prefix} · строки {current[0][0]}–{current[-1][0]}", content)
        number += 1
        return part

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            is_heading = markdown and line.startswith("#") and line.lstrip("#").startswith(" ")
            if is_heading and buffer:
                yield build(buffer, page_heading)
                buffer = []
            if is_heading:
                active_heading = line
            context_room = len(active_heading) + 1 if active_heading and active_heading != line else 0
            if len(line) + context_room > max_chars:
                if buffer:
                    yield build(buffer, page_heading)
                    buffer = []
                for chunk in _bounded_chunks(line, max_chars - context_room):
                    content = chunk
                    if active_heading and active_heading not in content:
                        content = active_heading + "\n" + content
                    yield DocumentPart(number, f"{prefix} · строки {line_number}–{line_number}", content)
                    number += 1
                page_heading = active_heading
                continue
            projected = sum(len(value) + 1 for _, value in buffer) + len(line)
            if buffer and projected > max_chars:
                yield build(buffer, page_heading)
                overlap: list[tuple[int, str]] = []
                overlap_size = 0
                for item in reversed(buffer):
                    if overlap and overlap_size + len(item[1]) + 1 > min(PART_OVERLAP, max_chars // 3):
                        break
                    overlap.insert(0, item)
                    overlap_size += len(item[1]) + 1
                buffer = overlap
                page_heading = active_heading
            if not buffer:
                page_heading = active_heading
            buffer.append((line_number, line))
    if buffer:
        yield build(buffer, page_heading)


def _paragraph_events(paragraph):
    """Return text fragments separated by explicit Word page breaks."""
    fragments: list[str | None] = []
    current: list[str] = []
    for node in paragraph._p.iter():
        local = node.tag.rsplit("}", 1)[-1]
        if local == "t" and node.text:
            current.append(node.text)
        elif local == "tab":
            current.append("\t")
        elif local == "br":
            if node.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type") == "page":
                fragments.append("".join(current).strip())
                fragments.append(None)
                current = []
            else:
                current.append("\n")
        elif local == "lastRenderedPageBreak":
            fragments.append("".join(current).strip())
            fragments.append(None)
            current = []
    fragments.append("".join(current).strip())
    return fragments


def _docx_parts(path: Path, max_chars: int):
    document = Document(path)
    paragraphs = {id(paragraph._p): paragraph for paragraph in document.paragraphs}
    tables = {id(table._tbl): table for table in document.tables}
    buffer: list[str] = []
    size = 0
    heading = ""
    page_heading = ""
    physical_page = 1
    page_part = 1
    number = 1

    def emit():
        nonlocal buffer, size, page_part, number
        if not buffer:
            return None
        content = "\n".join(buffer)
        context = page_heading or heading
        if context and context not in content:
            content = context + "\n" + content
        part = DocumentPart(number, f"Документ · страница {physical_page} · часть {page_part}", content)
        number += 1; page_part += 1; buffer = []; size = 0
        return part

    def add_line(value: str):
        nonlocal size, page_heading
        value = value.strip()
        if not value:
            return None
        ready = None
        if buffer and size + len(value) + 1 > max_chars:
            ready = emit()
        if not buffer:
            page_heading = heading
        buffer.append(value); size += len(value) + 1
        return ready

    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = paragraphs.get(id(child))
            if paragraph is None:
                continue
            style = paragraph.style.name if paragraph.style is not None else ""
            is_heading = style.casefold().startswith(("heading", "заголовок"))
            for fragment in _paragraph_events(paragraph):
                if fragment is None:
                    ready = emit()
                    if ready: yield ready
                    physical_page += 1; page_part = 1; page_heading = heading
                    continue
                if is_heading and fragment:
                    ready = emit()
                    if ready: yield ready
                    heading = fragment
                ready = add_line(fragment)
                if ready: yield ready
        elif child.tag.endswith("}tbl"):
            table = tables.get(id(child))
            if table:
                for row in table.rows:
                    line = " | ".join(" ".join(cell.text.split()) for cell in row.cells)
                    ready = add_line(line)
                    if ready: yield ready
    ready = emit()
    if ready: yield ready


def _bounded_chunks(value: str, limit: int):
    limit = max(32, limit)
    start = 0
    while start < len(value):
        end = min(len(value), start + limit)
        if end < len(value):
            boundary = value.rfind(" ", start, end)
            if boundary > start + limit // 2:
                end = boundary
        yield value[start:end].strip()
        start = max(start + 1, end)


def _xlsx_parts(path: Path, max_chars: int):
    workbook = load_workbook(path, read_only=True, data_only=True)
    number = 1
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            raw_headers = next(rows, ())
            headers = [str(value) if value is not None else f"Колонка {index + 1}" for index, value in enumerate(raw_headers)]
            header_line = "; ".join(headers)
            window: list[tuple[int, str]] = []
            window_size = len(header_line) + 1

            def emit_window():
                nonlocal number, window, window_size
                if not window:
                    return None
                text = header_line + "\n" + "\n".join(line for _, line in window)
                part = DocumentPart(number, f"Лист «{sheet.title}» · строки {window[0][0]}–{window[-1][0]}", text)
                number += 1; window = []; window_size = len(header_line) + 1
                return part

            for row_number, row in enumerate(rows, 2):
                line = "; ".join(
                    f"{headers[index] if index < len(headers) else f'Колонка {index + 1}'}: {value}"
                    for index, value in enumerate(row) if value is not None
                )
                if not line:
                    continue
                if window and window_size + len(line) + 1 > max_chars:
                    ready = emit_window()
                    if ready: yield ready
                available = max_chars - len(header_line) - 1
                if not window and len(line) > available:
                    for continuation, chunk in enumerate(_bounded_chunks(line, available), 1):
                        yield DocumentPart(
                            number,
                            f"Лист «{sheet.title}» · строки {row_number}–{row_number} · продолжение {continuation}",
                            header_line + "\n" + chunk,
                        )
                        number += 1
                    continue
                window.append((row_number, line)); window_size += len(line) + 1
            ready = emit_window()
            if ready: yield ready
    finally:
        workbook.close()

def part_count(path: Path) -> int:
    """Estimate how many embeddings a file will produce, without parsing it.

    Only PDFs and images report an exact number, because their page count is
    cheap to read. Everything else is a size-based guess that ``sync`` corrects
    as soon as the document is opened for real — fully parsing every DOCX and
    XLSX in the tree just to draw a progress bar left the window frozen on
    "0/0" for minutes on a large archive.
    """
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return 1
    if ext == ".pdf":
        try:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(path))
            try:
                return max(1, len(doc))
            finally:
                doc.close()
        except Exception:
            return 1
    divisor = ESTIMATE_DIVISOR.get(ext)
    if divisor:
        try:
            return max(1, path.stat().st_size // divisor)
        except OSError:
            return 1
    return 1


def split(text, location, max_chars: int = PART_CHARS):
    text = "\n".join(x.strip() for x in text.splitlines() if x.strip())
    start = 0
    number = 1
    while start < len(text):
        end = min(len(text), start + max_chars)
        cut = max(text.rfind("\n", start, end), text.rfind(". ", start, end))
        if cut > start + max_chars // 2:
            end = cut + 1
        value = text[start:end].strip()
        if value:
            yield DocumentPart(number, f"{location} · часть {number}", value)
            number += 1
        start = end if end == len(text) else max(start + 1, end - PART_OVERLAP)
