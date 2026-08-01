from __future__ import annotations

from threading import Event

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from filesearch.gui import animations
from filesearch.gui.theme import SPACE
from filesearch.gui.widgets.busy_bars import BusyBars
from filesearch.gui.widgets.common import EmptyState, IconButton, page_header
from filesearch.gui.widgets.result_card import ResultCard

# Every control on the search row shares one height so their centres line up
# across the row; the stepper's inner buttons are that height minus the 4px
# track padding on each side.
CONTROL_HEIGHT = 44
STEP_BUTTON = CONTROL_HEIGHT - 2 * SPACE["xs"] - 2

# Room around a card for its drop shadow to fall in. Must clear the largest
# blur radius in ELEVATION plus its y-offset.
SHADOW_ROOM = SPACE["md"]


class SearchPage(QWidget):
    # Worker signals are first relayed through signals owned by the page.
    # Connecting a worker signal directly to a Python lambda makes the lambda
    # run in the worker thread; touching widgets there is undefined behaviour
    # and previously made result cards disappear in real/screenshot runs.
    _result_ready = Signal(int, object)
    _error_ready = Signal(int, str)
    _cancel_ready = Signal(int)

    def __init__(self, search, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # `search` builds a configured SearchWorker; running it on a thread is
        # this page's job, so a slow provider never blocks the window.
        self.search = search
        self._cards: list[ResultCard] = []
        self.empty: EmptyState | None = None
        self._colors = None
        self._ratio = 1.0
        self._count_value = 8
        self._kind_value = None
        self._thread: QThread | None = None
        self._worker = None
        self._cancel = Event()
        self._generation = 0
        self._active_generation: int | None = None
        self._result_ready.connect(self._succeeded_generation)
        self._error_ready.connect(self._failed_generation)
        self._cancel_ready.connect(self._cancelled_generation)

        # Snippets are prose; a line running the full width of a maximised
        # window is hard to track back to the start of the next one. The column
        # is centred by equal side stretches so it still expands up to its cap
        # instead of collapsing to its minimum.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(1040)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(column, 100)
        outer.addStretch(1)

        box = QVBoxLayout(column)
        box.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["xl"])
        box.setSpacing(0)

        box.addWidget(
            page_header(
                "Поиск по файлам",
                "Запрос ищется по смыслу, а не по точному совпадению слов.",
            )
        )
        box.addSpacing(SPACE["xl"])

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(SPACE["sm"])

        self.query = QLineEdit()
        self.query.setObjectName("heroInput")
        self.query.setPlaceholderText("Например: сертификат гидроизоляции")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.run)
        controls.addWidget(self.query, 1)

        filters = QWidget()
        filters.setObjectName("searchFilters")
        filter_box = QHBoxLayout(filters)
        filter_box.setContentsMargins(0, 0, 0, 0)
        filter_box.setSpacing(SPACE["sm"])

        # One segmented control on a sunk track, not three loose buttons. The
        # 4px track padding is what makes the inner radius concentric.
        stepper = QWidget()
        stepper.setObjectName("stepper")
        stepper.setAttribute(Qt.WA_StyledBackground, True)
        stepper.setFixedHeight(CONTROL_HEIGHT)
        step_box = QHBoxLayout(stepper)
        step_box.setContentsMargins(SPACE["xs"], SPACE["xs"], SPACE["xs"], SPACE["xs"])
        step_box.setSpacing(0)

        self.count_down = IconButton("minus", "")
        self.count_down.setObjectName("quiet")
        self.count_down.setFixedSize(STEP_BUTTON, STEP_BUTTON)
        self.count_down.setToolTip("Уменьшить число результатов")
        self.count_down.clicked.connect(lambda: self._change_count(-1))
        step_box.addWidget(self.count_down)
        self.count_value = QLabel("8")
        self.count_value.setObjectName("filterValue")
        self.count_value.setAlignment(Qt.AlignCenter)
        self.count_value.setFixedWidth(26)
        self.count_value.setToolTip("Сколько результатов показывать")
        step_box.addWidget(self.count_value)
        self.count_up = IconButton("plus", "")
        self.count_up.setObjectName("quiet")
        self.count_up.setFixedSize(STEP_BUTTON, STEP_BUTTON)
        self.count_up.setToolTip("Увеличить число результатов")
        self.count_up.clicked.connect(lambda: self._change_count(1))
        step_box.addWidget(self.count_up)
        filter_box.addWidget(stepper)

        self.kind = IconButton("chevron-down", "Все типы")
        self.kind.setObjectName("filterMenu")
        self.kind.setMinimumWidth(132)
        self.kind.setFixedHeight(CONTROL_HEIGHT)
        # Chevron on the right: it points at the menu it opens, and the label
        # stays flush with the other controls' left edges.
        self.kind.setLayoutDirection(Qt.RightToLeft)
        self.kind.clicked.connect(self._show_kind_menu)
        filter_box.addWidget(self.kind)
        controls.addWidget(filters)

        self.submit = IconButton("search", "Найти")
        self.submit.setObjectName("primary")
        self.submit.setMinimumWidth(120)
        self.submit.setFixedHeight(CONTROL_HEIGHT)
        self.submit.clicked.connect(self.run)
        controls.addWidget(self.submit)

        self.cancel_button = IconButton("square", "Отменить")
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.setFixedHeight(CONTROL_HEIGHT)
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        controls.addWidget(self.cancel_button)
        box.addLayout(controls)

        box.addSpacing(SPACE["lg"])

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(SPACE["sm"])
        self.status = QLabel("")
        self.status.setObjectName("muted")
        status_row.addWidget(self.status)
        self.busy = BusyBars()
        status_row.addWidget(self.busy)
        status_row.addStretch(1)
        box.addLayout(status_row)

        box.addSpacing(SPACE["sm"])

        self.results = QVBoxLayout()
        self.results.setAlignment(Qt.AlignTop)
        # A QGraphicsEffect is clipped by the widget's own rect, so every side
        # needs room for the blur or the shadow ends in a hard vertical line.
        # The right margin also clears the scrollbar.
        self.results.setContentsMargins(SHADOW_ROOM, SHADOW_ROOM, SHADOW_ROOM + SPACE["md"], SHADOW_ROOM)
        self.results.setSpacing(SPACE["sm"])

        holder = QWidget()
        holder.setLayout(self.results)
        holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(holder)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setMinimumHeight(360)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        box.addWidget(self.scroll, 1)

        self.empty = EmptyState(
            "inbox",
            "Пока ничего не найдено",
            "Введите запрос выше, чтобы искать по проиндексированным файлам.",
        )
        self.results.addWidget(self.empty)

    # ---------------------------------------------------------------- search

    def run(self) -> None:
        query = self.query.text().strip()
        if not query:
            self.query.setFocus()
            return
        if self._thread is not None:
            return

        self._clear()
        self._set_running(True)
        self.busy.start()
        self.status.setObjectName("muted")
        self._restyle(self.status)
        self.status.setText("Ищем…")

        try:
            self._cancel.clear()
            worker = self.search(query, self._count_value, self._kind_value, self._cancel)
        except Exception as error:
            self._failed(str(error))
            return

        self._generation += 1
        generation = self._generation
        self._active_generation = generation
        self._thread = QThread(self)
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.finished.connect(lambda found, token=generation: self._result_ready.emit(token, found))
        worker.failed.connect(lambda message, token=generation: self._error_ready.emit(token, message))
        cancelled = getattr(worker, "cancelled", None)
        if cancelled is not None:
            cancelled.connect(lambda token=generation: self._cancel_ready.emit(token))
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        if cancelled is not None:
            cancelled.connect(worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _succeeded_generation(self, generation: int, found) -> None:
        if generation == self._active_generation:
            self._succeeded(found)

    def _failed_generation(self, generation: int, message: str) -> None:
        if generation == self._active_generation:
            self._failed(message)

    def _cancelled_generation(self, generation: int) -> None:
        if generation != self._active_generation:
            return
        self._release()
        self._clear()
        self.status.setObjectName("muted")
        self._restyle(self.status)
        self.status.setText("Поиск отменён")
        self._show_empty("square", "Поиск отменён", "Измените запрос или запустите поиск ещё раз.")

    @Slot(object)
    def _succeeded(self, found) -> None:
        self._release()
        self.status.setObjectName("muted")
        self._restyle(self.status)

        if not found:
            self.status.setText("Ничего не найдено")
            self._show_empty(
                "search",
                "Совпадений нет",
                "Попробуйте переформулировать запрос или проверьте, что нужная папка "
                "добавлена и проиндексирована.",
            )
            return

        animations.count_up(self.status, len(found), "Найдено результатов: {}")
        for result in found:
            card = ResultCard(result)
            if self._colors is not None:
                card.apply_theme(self._colors, self._ratio)
            self.results.addWidget(card)
            self._cards.append(card)
        # Search results must be immediately visible. Delayed opacity effects
        # can leave later cards transparent while they still occupy space in
        # the scroll layout, which looks like only one result was returned.

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._release()
        self._clear()
        self.status.setObjectName("danger")
        self._restyle(self.status)
        self.status.setText(f"Ошибка: {message}")
        self._show_empty(
            "triangle-alert",
            "Поиск не выполнен",
            "Проверьте активный профиль и API-ключ на странице «Провайдеры».",
        )

    def _release(self) -> None:
        self.busy.stop()
        self._set_running(False)
        if self._thread is not None:
            self._thread.quit()
        self._worker = None
        self._active_generation = None

    @Slot()
    def _thread_finished(self) -> None:
        self._thread = None

    def cancel(self) -> None:
        if self._thread is None:
            return
        self._cancel.set()
        self.cancel_button.setEnabled(False)
        self.status.setText("Отменяем поиск…")

    def shutdown(self) -> bool:
        """Request cancellation without ever blocking the GUI thread."""
        self.cancel()
        if self._thread is not None:
            self._thread.quit()
        return self.is_running()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _set_running(self, running: bool) -> None:
        self.query.setEnabled(not running)
        self.count_down.setEnabled(not running and self._count_value > 1)
        self.count_up.setEnabled(not running and self._count_value < 30)
        self.kind.setEnabled(not running)
        self.submit.setVisible(not running)
        self.submit.setEnabled(not running)
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(running)

    def _clear(self) -> None:
        self._cards.clear()
        self.empty = None
        while self.results.count():
            item = self.results.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.scroll.verticalScrollBar().setValue(0)

    def _change_count(self, delta: int) -> None:
        self._count_value = max(1, min(30, self._count_value + delta))
        self.count_value.setText(str(self._count_value))
        self.count_down.setEnabled(self._count_value > 1)
        self.count_up.setEnabled(self._count_value < 30)

    def _show_kind_menu(self) -> None:
        menu = QMenu(self)
        for title, value in (("Все типы", None), ("PDF", "pdf"), ("Изображения", "images"), ("DOCX", "docx"), ("XLSX", "xlsx"), ("TXT / Markdown", "text")):
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(value == self._kind_value)
            action.triggered.connect(lambda _checked=False, t=title, v=value: self._select_kind(t, v))
        menu.exec(self.kind.mapToGlobal(self.kind.rect().bottomLeft()))

    def _select_kind(self, title: str, value) -> None:
        self._kind_value = value
        self.kind.setText(title)

    def _show_empty(self, icon_name: str, title: str, detail: str) -> None:
        self.empty = EmptyState(icon_name, title, detail)
        if self._colors is not None:
            self.empty.apply_theme(self._colors.text_faint, self._ratio)
        self.results.addWidget(self.empty)

    @staticmethod
    def _restyle(widget) -> None:
        """Re-evaluate the stylesheet after changing an object name."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # ----------------------------------------------------------------- theme

    def apply_theme(self, colors, ratio: float = 1.0) -> None:
        self._colors = colors
        self._ratio = ratio
        self.submit.apply_theme(colors.accent_text, ratio)
        for button in (self.count_down, self.count_up, self.kind, self.cancel_button):
            button.apply_theme(colors.text_muted, ratio)
        self.busy.set_color(colors.accent)
        if self.empty is not None:
            self.empty.apply_theme(colors.text_faint, ratio)
        for card in self._cards:
            card.apply_theme(colors, ratio)
