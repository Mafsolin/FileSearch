"""Indeterminate activity indicator: four bars on a phase offset.

Qt's indeterminate QProgressBar sweeps a single block, which reads as a stalled
determinate bar. Four bars breathing out of phase reads unambiguously as work
in progress without implying a percentage the indexer cannot know.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from filesearch.gui.theme import LIGHT, palette

BAR_COUNT = 4
BAR_WIDTH = 3
BAR_GAP = 4
PERIOD_MS = 1000
PHASE_STEP = 0.2  # Fraction of a cycle between adjacent bars.
FRAME_MS = 33  # ~30fps: enough for this, and cheap.


class BusyBars(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._color = QColor(palette(LIGHT).accent)
        self.setFixedSize(BAR_COUNT * BAR_WIDTH + (BAR_COUNT - 1) * BAR_GAP, 16)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def start(self) -> None:
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._phase = (self._phase + FRAME_MS / PERIOD_MS) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        height = self.height()
        for index in range(BAR_COUNT):
            # Sine keeps the ends of the cycle soft, so bars ease rather than
            # snap at their extremes.
            wave = math.sin((self._phase - index * PHASE_STEP) * 2 * math.pi)
            scale = 0.35 + 0.65 * (wave + 1) / 2
            bar_height = height * scale
            x = index * (BAR_WIDTH + BAR_GAP)
            y = (height - bar_height) / 2
            color = QColor(self._color)
            color.setAlphaF(0.45 + 0.55 * scale)
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(x, y, BAR_WIDTH, bar_height), BAR_WIDTH / 2, BAR_WIDTH / 2
            )
        painter.end()
