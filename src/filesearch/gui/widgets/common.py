"""Small shared building blocks used across pages."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from filesearch.gui import icons
from filesearch.gui.theme import SPACE


class Divider(QFrame):
    """A hairline. Cheaper than a border and does not box content in."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("divider")
        self.setFixedHeight(1)
        self.setAttribute(Qt.WA_StyledBackground, True)


WRAP_WIDTH = 420


class WrapLabel(QLabel):
    """A wrapping label that reports its real height for a given width.

    Qt computes a plain wrapping QLabel's `sizeHint` against a guessed width, so
    a one-line subtitle can claim two lines' height. The layout then hands the
    label a cell taller than its text and the text centres inside it, which
    reads as the heading having drifted away from its subtitle. Answering
    `heightForWidth` honestly is what keeps the two locked together.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        if width <= 0:
            return super().heightForWidth(width)
        metrics = QFontMetrics(self.font())
        bounds = metrics.boundingRect(
            0, 0, width, 0, Qt.TextWordWrap | int(self.alignment()), self.text()
        )
        return bounds.height()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        width = self.width()
        if width > 0:
            return QSize(hint.width(), self.heightForWidth(width))
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        # The wrapped height changes with width, so the layout has to be told
        # the old hint is stale or the label keeps its first-pass height.
        self.updateGeometry()


class ElidedLabel(QLabel):
    """A single-line label that elides in the middle.

    File paths are long and unbreakable, and word wrap cannot help with them.
    Eliding the middle keeps both the drive and the filename visible, which are
    the two parts worth reading.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        # Ignored width lets the label shrink below its text; a minimum keeps
        # it from collapsing to nothing when it shares a row with a button.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(120)
        self._apply()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full = text
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, Qt.ElideMiddle, max(0, self.width())))


class IconButton(QPushButton):
    """A button whose icon is re-tinted whenever the theme changes."""

    def __init__(
        self,
        icon_name: str,
        text: str = "",
        parent: QWidget | None = None,
        size: int = 15,
    ) -> None:
        super().__init__(text, parent)
        self._icon_name = icon_name
        self._icon_size = size
        if text:
            self.setAccessibleName(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(size, size))

    def apply_theme(self, color: str, ratio: float = 1.0) -> None:
        self.setIcon(icons.icon(self._icon_name, color, self._icon_size, 1.75, ratio))


class ChevronComboBox(QComboBox):
    """Editable combo with the same real SVG chevron as the rest of the UI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chevron = QPixmap()

    def apply_theme(self, color: str, ratio: float = 1.0) -> None:
        self._chevron = icons.pixmap("chevron-down", color, 14, 2.0, ratio)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().paintEvent(event)
        if self._chevron.isNull():
            return
        painter = QPainter(self)
        logical_width = self._chevron.width() / self._chevron.devicePixelRatio()
        logical_height = self._chevron.height() / self._chevron.devicePixelRatio()
        painter.drawPixmap(
            int(self.width() - SPACE["md"] - logical_width),
            int((self.height() - logical_height) / 2),
            self._chevron,
        )


class PageHeader(QWidget):
    """Page title plus one explanatory line.

    The two sit close together because they belong to each other; the caller
    puts a larger gap before whatever follows. Keeping that 4px gap honest
    means the header must report its own height for a given width: a plain
    holder is sized from the subtitle's width-agnostic hint, which over-reports
    on a long lead and leaves slack the labels then centre inside.
    """

    def __init__(self, title: str, lead: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(SPACE["xs"])

        self._heading = QLabel(title)
        self._heading.setObjectName("pageTitle")
        self._heading.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        box.addWidget(self._heading)

        self._subtitle = WrapLabel(lead)
        self._subtitle.setObjectName("pageLead")
        box.addWidget(self._subtitle)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return (
            self._heading.sizeHint().height()
            + SPACE["xs"]
            + self._subtitle.heightForWidth(width)
        )

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        hint = super().sizeHint()
        width = self.width()
        if width > 0:
            return QSize(hint.width(), self.heightForWidth(width))
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.updateGeometry()


def page_header(title: str, lead: str) -> QWidget:
    return PageHeader(title, lead)


class EmptyState(QWidget):
    """Placeholder shown when a list has nothing in it."""

    def __init__(
        self,
        icon_name: str,
        title: str,
        detail: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name

        box = QVBoxLayout(self)
        box.setContentsMargins(0, SPACE["3xl"], 0, SPACE["3xl"])
        box.setSpacing(SPACE["md"])
        box.setAlignment(Qt.AlignCenter)

        self._glyph = QLabel()
        self._glyph.setAlignment(Qt.AlignCenter)
        self._glyph.setFixedHeight(28)
        box.addWidget(self._glyph, 0, Qt.AlignCenter)

        heading = QLabel(title)
        heading.setObjectName("muted")
        heading.setAlignment(Qt.AlignCenter)
        box.addWidget(heading)

        note = QLabel(detail)
        note.setObjectName("faint")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        note.setFixedWidth(WRAP_WIDTH)
        # A wrapping label reports a single-line height until it has been laid
        # out, so a parent that sizes to its contents clips it. Measuring the
        # wrapped text now gives the layout a height it can trust immediately.
        metrics = QFontMetrics(note.font())
        bounds = metrics.boundingRect(
            0, 0, WRAP_WIDTH, 0, Qt.TextWordWrap | Qt.AlignCenter, detail
        )
        note.setMinimumHeight(bounds.height() + metrics.leading())
        note.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.MinimumExpanding)
        box.addWidget(note, 0, Qt.AlignCenter)

    def apply_theme(self, color: str, ratio: float = 1.0) -> None:
        self._glyph.setPixmap(icons.pixmap(self._icon_name, color, 26, 1.5, ratio))


def row(*widgets, spacing: int = SPACE["sm"], stretch_last: bool = False) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if not stretch_last:
        layout.addStretch(1)
    return layout
