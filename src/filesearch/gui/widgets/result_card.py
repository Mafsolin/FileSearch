"""A single search result.

One surface, no nested boxes. Grouping comes from spacing: the score, meta
line, filename and snippet sit close because they describe one file, and the
actions are pushed away because they do something different.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from filesearch.domain.models import SearchResult
from filesearch.gui.theme import SPACE
from filesearch.gui.widgets.common import ElidedLabel, IconButton

SNIPPET_LIMIT = 320


class ResultCard(QFrame):
    def __init__(self, result: SearchResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._result = result

        grid = QGridLayout(self)
        # Inner padding is 16 and the card radius is 14, so a 7px control inside
        # sits concentrically (inner + padding ≈ outer).
        grid.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["lg"])
        grid.setHorizontalSpacing(SPACE["lg"])
        grid.setVerticalSpacing(0)

        # The score sits in a washed pill so the card's strongest colour has a
        # container. Fixed width plus tabular figures means 8% and 94% occupy
        # the same space and the text column never shifts between results.
        self._badge = QWidget()
        self._badge.setObjectName("scoreBadge")
        self._badge.setAttribute(Qt.WA_StyledBackground, True)
        self._badge.setFixedWidth(56)
        badge_box = QVBoxLayout(self._badge)
        badge_box.setContentsMargins(0, SPACE["xs"], 0, SPACE["xs"])
        badge_box.setSpacing(0)
        score = QLabel(f"{result.score:.0%}")
        score.setObjectName("score")
        score.setAlignment(Qt.AlignCenter)
        score.setToolTip(f"Схожесть: {result.score:.1%}")
        badge_box.addWidget(score)
        grid.addWidget(self._badge, 0, 0, 2, 1, Qt.AlignTop)

        locations = ", ".join(dict.fromkeys(x[0] for x in result.matches)) if result.matches else result.location
        meta_text = f"{result.kind.upper()} · {locations}"
        meta = ElidedLabel(meta_text)
        meta.setObjectName("resultMeta")
        meta.setToolTip(meta_text)
        grid.addWidget(meta, 0, 1)

        name = ElidedLabel(Path(result.path).name)
        name.setObjectName("resultName")
        name.setToolTip(Path(result.path).name)
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        grid.addWidget(name, 1, 1)

        body = QWidget()
        body_box = QVBoxLayout(body)
        body_box.setContentsMargins(0, SPACE["sm"], 0, 0)
        body_box.setSpacing(SPACE["sm"])

        snippet = QLabel(self._snippet(result))
        snippet.setObjectName("resultSnippet")
        snippet.setWordWrap(True)
        snippet.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body_box.addWidget(snippet)

        self._path_label = ElidedLabel(str(result.path))
        self._path_label.setObjectName("resultPath")
        self._path_label.setToolTip(str(result.path))
        body_box.addWidget(self._path_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, SPACE["sm"], 0, 0)
        actions.setSpacing(SPACE["sm"])
        self._open = IconButton("external-link", "Открыть")
        self._open.clicked.connect(self._open_file)
        self._reveal = IconButton("folder-open", "В проводнике")
        self._reveal.clicked.connect(self._open_folder)
        actions.addWidget(self._open)
        actions.addWidget(self._reveal)
        actions.addStretch(1)
        body_box.addLayout(actions)

        grid.addWidget(body, 2, 1)
        grid.setColumnStretch(1, 1)

    @staticmethod
    def _snippet(result: SearchResult) -> str:
        if result.matches:
            content = "\n\n".join(f"{location}: {text}" for location,text,_ in result.matches[:3])
        else:
            content = (result.content or "").strip()
        if not content:
            return "Сканированная страница: текстовый слой отсутствует."
        collapsed = " ".join(content.split())
        if len(collapsed) <= SNIPPET_LIMIT:
            return collapsed
        # Cut on a word boundary so the ellipsis does not land mid-word.
        cut = collapsed[:SNIPPET_LIMIT]
        space = cut.rfind(" ")
        if space > SNIPPET_LIMIT * 0.6:
            cut = cut[:space]
        return cut + "…"

    def _open_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._result.path)))

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._result.path).parent)))

    def apply_theme(self, colors, ratio: float = 1.0) -> None:
        self._open.apply_theme(colors.text_muted, ratio)
        self._reveal.apply_theme(colors.text_muted, ratio)
