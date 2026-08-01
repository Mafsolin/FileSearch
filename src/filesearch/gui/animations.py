"""Motion helpers.

Qt stylesheets have no transitions, so every animation here is an explicit
property animation. The rules applied throughout:

- Ease out on anything entering or settling. Never ease in on UI: the delay
  lands exactly when the user is watching most closely.
- Under 300ms for interface feedback.
- Animate what is seen rarely. Results arriving are worth a transition;
  switching pages, hovering and pressing are not.

`set_enabled(False)` turns all of it off, since Windows exposes no reliable
reduced-motion hint to Qt.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect

# Roughly cubic-bezier(0.23, 1, 0.32, 1): a fast start that settles gently.
ENTER_CURVE = QEasingCurve.OutQuint
COUNT_CURVE = QEasingCurve.OutCubic

ENTER_DURATION = 180
ENTER_RISE = 8
STAGGER_STEP = 40
STAGGER_MAX = 8  # Past this many rows the stagger reads as lag, not rhythm.
COUNT_DURATION = 450

_enabled = True


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def is_enabled() -> bool:
    return _enabled


def fade_in(widget, delay: int = 0, duration: int = ENTER_DURATION, rise: int = ENTER_RISE):
    """Fade a widget in while it rises into place.

    A widget carries at most one QGraphicsEffect, so opacity goes through the
    effect and movement through `pos`. The effect is removed on completion:
    leaving it attached costs a repaint on every update and can leave the
    widget subtly blurred against its neighbours.
    """
    if not _enabled:
        return None

    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    group = QParallelAnimationGroup(widget)

    opacity = QPropertyAnimation(effect, b"opacity", group)
    opacity.setDuration(duration)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(ENTER_CURVE)
    group.addAnimation(opacity)

    if rise:
        target = widget.pos()
        move = QPropertyAnimation(widget, b"pos", group)
        move.setDuration(duration)
        move.setStartValue(QPoint(target.x(), target.y() + rise))
        move.setEndValue(target)
        move.setEasingCurve(ENTER_CURVE)
        group.addAnimation(move)

    def cleanup():
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    group.finished.connect(cleanup)

    if delay:
        QTimer.singleShot(delay, lambda: group.start(QAbstractAnimation.DeleteWhenStopped))
    else:
        group.start(QAbstractAnimation.DeleteWhenStopped)
    return group


def stagger_in(widgets, step: int = STAGGER_STEP) -> None:
    """Fade a sequence of widgets in one after another."""
    if not _enabled:
        return
    for index, widget in enumerate(widgets):
        fade_in(widget, delay=min(index, STAGGER_MAX) * step)


def count_up(label, total: int, template: str = "{}", duration: int = COUNT_DURATION):
    """Animate a label from zero to `total`.

    Small totals are not worth animating: counting to 3 reads as a glitch.
    """
    text = lambda value: template.format(value)  # noqa: E731
    if not _enabled or total < 5:
        label.setText(text(total))
        return None

    animation = QVariantAnimation(label)
    animation.setDuration(duration)
    animation.setStartValue(0)
    animation.setEndValue(int(total))
    animation.setEasingCurve(COUNT_CURVE)
    animation.valueChanged.connect(lambda value: label.setText(text(int(value))))
    animation.finished.connect(lambda: label.setText(text(total)))
    animation.start(QAbstractAnimation.DeleteWhenStopped)
    return animation
