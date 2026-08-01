"""Left navigation rail: brand, page buttons, live status footer."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from filesearch.gui import icons
from filesearch.gui.theme import SPACE

RAIL_WIDTH = 216
NAV_INSET = SPACE["sm"]
NAV_ITEM_HEIGHT = 40


class NavRail(QWidget):
    """Vertical navigation with a status footer.

    Emits `selected(index)` when a page button is activated and `theme_toggled`
    when the light/dark button is pressed.
    """

    selected = Signal(int)
    theme_toggled = Signal()

    def __init__(self, items: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setFixedWidth(RAIL_WIDTH)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._items = items
        self._buttons: list[QToolButton] = []

        layout = QVBoxLayout(self)
        # Nav items are inset pills, so the rail carries the horizontal padding
        # and the pill radius stays concentric with it.
        layout.setContentsMargins(NAV_INSET, SPACE["lg"], NAV_INSET, SPACE["md"])
        layout.setSpacing(2)

        layout.addWidget(self._build_brand())
        layout.addSpacing(SPACE["xl"])

        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (name, label) in enumerate(items):
            button = QToolButton()
            button.setObjectName("navItem")
            button.setText("  " + label)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            # Comfortably past the 40px hit-area floor for a primary target.
            button.setMinimumHeight(NAV_ITEM_HEIGHT)
            button.clicked.connect(lambda _=False, i=index: self.selected.emit(i))
            group.addButton(button, index)
            layout.addWidget(button)
            self._buttons.append(button)

        layout.addStretch(1)

        self._divider = QFrame()
        self._divider.setObjectName("navDivider")
        layout.addWidget(self._divider)
        layout.addSpacing(SPACE["md"])

        # The footer is two labelled readings, not two loose lines: a caps
        # caption names each one so the numbers are not left to be guessed at.
        for caption, attribute in (("ИНДЕКС", "_stats"), ("ПРОВАЙДЕР", "_provider")):
            title = QLabel(caption)
            title.setObjectName("navFooterCaption")
            title.setContentsMargins(SPACE["sm"], 0, SPACE["sm"], 0)
            layout.addWidget(title)
            value = QLabel("—")
            value.setObjectName("navFooterLabel")
            value.setContentsMargins(SPACE["sm"], 0, SPACE["sm"], 0)
            value.setWordWrap(True)
            layout.addWidget(value)
            setattr(self, attribute, value)
            layout.addSpacing(SPACE["sm"])

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self._theme_button = QPushButton()
        self._theme_button.setObjectName("quiet")
        self._theme_button.setCursor(Qt.PointingHandCursor)
        self._theme_button.setIconSize(QSize(16, 16))
        # 40×40 hit area for a 16px glyph: the visible button is the icon, the
        # target is the square around it.
        self._theme_button.setFixedSize(40, 40)
        self._theme_button.setAccessibleName("Переключить тему")
        self._theme_button.clicked.connect(self.theme_toggled.emit)
        footer.addWidget(self._theme_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        if self._buttons:
            self._buttons[0].setChecked(True)

    def _build_brand(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        # Optically aligned with the nav item labels: the pill's own 12px text
        # padding sits inside the rail inset, so the mark matches at 6px here.
        row.setContentsMargins(SPACE["sm"] - 2, 0, SPACE["sm"], 0)
        row.setSpacing(SPACE["sm"])
        self._mark = QLabel()
        self._mark.setFixedSize(20, 20)
        row.addWidget(self._mark)
        title = QLabel("FileSearch")
        title.setObjectName("navBrand")
        row.addWidget(title)
        row.addStretch(1)
        return holder

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def set_stats(self, text: str) -> None:
        self._stats.setText(text)

    def set_provider(self, text: str) -> None:
        self._provider.setText(text)

    def apply_theme(self, colors, is_dark: bool, ratio: float) -> None:
        """Repaint icons in the active theme's colours."""
        self._mark.setPixmap(icons.brand_pixmap(colors.accent, 20, ratio))
        for button, (name, _) in zip(self._buttons, self._items):
            button.setIcon(icons.icon(name, colors.text_muted, 18, 1.75, ratio))
        # Show where the toggle leads, not where it is.
        self._theme_button.setIcon(
            icons.icon("sun" if is_dark else "moon", colors.text_muted, 16, 1.75, ratio)
        )
        self._theme_button.setToolTip(
            "Светлая тема" if is_dark else "Тёмная тема"
        )
