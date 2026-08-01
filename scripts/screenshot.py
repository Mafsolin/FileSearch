"""Render every page in both themes to PNG for visual review.

Development helper. Uses a throwaway LOCALAPPDATA so it never touches real
settings or the real index, and feeds the search page fabricated results so the
result card can be inspected without calling an embeddings API.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="filesearch-shot-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QObject, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from filesearch.domain.models import SearchResult  # noqa: E402
from filesearch.gui import animations, theme  # noqa: E402
from filesearch.gui.main_window import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "_shots"
PAGES = [(0, "search"), (1, "index"), (2, "providers"), (3, "vision"), (4, "settings")]

SAMPLE = [
    SearchResult(
        0.94,
        Path(r"D:\Архив\Объекты\Северный\акт_приёмки_гидроизоляции.pdf"),
        "pdf",
        "стр. 12",
        "Работы по устройству гидроизоляции фундаментной плиты выполнены в полном "
        "объёме согласно проекту 21-084-АР. Применён материал Технониколь Техноэласт "
        "ЭПП в два слоя с нахлёстом 100 мм. Сертификат соответствия приложен.",
    ),
    SearchResult(
        0.81,
        Path(r"D:\Архив\Договоры\подряд_кровля_2024.docx"),
        "docx",
        "фрагмент 3",
        "Подрядчик обязуется выполнить работы по устройству кровельного покрытия "
        "с гидроизоляционным слоем в срок до 30 ноября 2024 года.",
    ),
    SearchResult(
        0.67,
        Path(r"D:\Архив\Сканы\сертификат_2019_стр4.jpg"),
        "image",
        "страница",
        "",
    ),
]


class FakeSearchWorker(QObject):
    """Stand in for SearchWorker: emit canned results without a provider."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, results) -> None:
        super().__init__()
        self.results = results

    @Slot()
    def run(self) -> None:
        self.finished.emit(self.results)


def fake_search(results):
    return lambda query, count, kind, cancel: FakeSearchWorker(results)


def shoot(window: MainWindow, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    window.grab().save(str(OUT / f"{name}.png"), "PNG")


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(theme.base_font())
    animations.set_enabled(False)  # Capture settled state, not mid-transition.

    window = MainWindow()
    window.resize(1180, 780)
    window.show()

    # Populate the search page without touching a provider.
    window.search.query.setText("гидроизоляция фундамента сертификат")
    window.search.search = fake_search(SAMPLE)
    window.search.run()

    def settle(rounds: int = 6) -> None:
        for _ in range(rounds):
            app.processEvents()
            time.sleep(0.02)

    # Results now arrive from a worker thread, so give the signal time to land.
    settle(20)
    count = 0
    for theme_name in (theme.LIGHT, theme.DARK):
        window.apply_theme(theme_name)
        window.settings_page.sync_theme(theme_name)
        for index, page in PAGES:
            window._go_to(index)
            settle()
            shoot(window, f"{theme_name}-{page}")
            count += 1

    # Empty search state, worth checking separately.
    window.apply_theme(theme.LIGHT)
    window._go_to(0)
    window.search.search = fake_search([])
    window.search.run()
    settle(20)
    shoot(window, "light-search-empty")
    count += 1

    print(f"wrote {count} images to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
