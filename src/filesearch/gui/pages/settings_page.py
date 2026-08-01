from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from filesearch.app_paths import app_data_dir, database_path, env_path, settings_path
from filesearch.gui import theme
from filesearch.gui.theme import SPACE
from filesearch.gui.widgets.common import Divider, ElidedLabel, IconButton, page_header

LICENSE_NOTE = (
    "Иконки интерфейса и логотип — Lucide (ISC, © Lucide Contributors); "
    "часть из них происходит из Feather (MIT, © Cole Bemis). "
    "Полные тексты лицензий — в файле THIRD-PARTY-NOTICES.txt в составе сборки."
)


class SettingsPage(QWidget):
    def __init__(self, settings, on_theme, on_animations, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_theme = on_theme
        self.on_animations = on_animations
        self._path_buttons: list[IconButton] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["xl"])
        layout.setSpacing(0)
        scroll.setWidget(content)

        layout.addWidget(
            page_header(
                "Настройки",
                "Данные, ключи и индекс хранятся отдельно от программы.",
            )
        )
        layout.addSpacing(SPACE["xl"])

        # --- appearance
        layout.addWidget(self._section_title("Внешний вид"))
        layout.addSpacing(SPACE["md"])

        self.dark_toggle = QCheckBox("Тёмная тема")
        self.dark_toggle.setChecked(self.settings.theme() == theme.DARK)
        self.dark_toggle.toggled.connect(self._theme_toggled)
        layout.addWidget(self.dark_toggle)

        # Larger gap between the two options than between the second option and
        # its own description, so the note reads as belonging to the checkbox.
        layout.addSpacing(SPACE["lg"])

        self.motion_toggle = QCheckBox("Анимации интерфейса")
        self.motion_toggle.setChecked(self.settings.animations_enabled())
        self.motion_toggle.toggled.connect(self.on_animations)
        layout.addWidget(self.motion_toggle)

        layout.addSpacing(SPACE["xs"])

        motion_note = QLabel("Появление результатов и индикаторы загрузки.")
        motion_note.setObjectName("faint")
        motion_note.setContentsMargins(SPACE["xl"], 0, 0, 0)
        layout.addWidget(motion_note)

        layout.addSpacing(SPACE["xl"])
        layout.addWidget(Divider())
        layout.addSpacing(SPACE["xl"])

        # --- storage
        layout.addWidget(self._section_title("Расположение данных"))
        layout.addSpacing(SPACE["md"])

        for caption, path in (
            ("Папка данных", app_data_dir()),
            ("Настройки", settings_path()),
            ("Ключи API", env_path()),
            ("SQLite-индекс", self.settings.index_path()),
        ):
            layout.addWidget(self._path_row(caption, str(path)))
            layout.addSpacing(SPACE["sm"])

        layout.addSpacing(SPACE["sm"])
        self.open_button = IconButton("folder-open", "Открыть папку данных")
        self.open_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir())))
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.open_button)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addSpacing(SPACE["xl"])
        layout.addWidget(Divider())
        layout.addSpacing(SPACE["xl"])

        # --- about
        layout.addWidget(self._section_title("О программе"))
        layout.addSpacing(SPACE["md"])

        note = QLabel(
            "Страницы PDF готовятся для поиска в памяти: 200 DPI, "
            "для крупных файлов — 150 DPI. Исходные файлы не изменяются."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        note.setMaximumWidth(720)
        layout.addWidget(note)

        layout.addSpacing(SPACE["md"])

        licenses = QLabel(LICENSE_NOTE)
        licenses.setObjectName("faint")
        licenses.setWordWrap(True)
        licenses.setMaximumWidth(720)
        layout.addWidget(licenses)

        layout.addStretch(1)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _path_row(self, caption: str, value: str) -> QWidget:
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        label = QLabel(caption)
        label.setObjectName("fieldLabel")
        box.addWidget(label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["sm"])

        # One line, elided in the middle: wrapping a path over three lines
        # costs vertical space and still reads worse than "C:\...\file.db".
        path = ElidedLabel(value)
        path.setObjectName("muted")
        path.setToolTip(value)
        path.setMaximumWidth(620)
        row.addWidget(path, 1)

        copy = IconButton("copy", "")
        copy.setObjectName("quiet")
        copy.setFixedSize(28, 26)
        copy.setAccessibleName(f"Скопировать путь: {caption}")
        copy.setToolTip("Скопировать путь")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(value))
        row.addWidget(copy, 0, Qt.AlignVCenter)
        row.addStretch(0)
        self._path_buttons.append(copy)

        box.addLayout(row)
        return holder

    def _theme_toggled(self, checked: bool) -> None:
        self.on_theme(theme.DARK if checked else theme.LIGHT)

    def sync_theme(self, name: str) -> None:
        """Reflect a theme change made from the nav rail."""
        self.dark_toggle.blockSignals(True)
        self.dark_toggle.setChecked(name == theme.DARK)
        self.dark_toggle.blockSignals(False)

    def apply_theme(self, colors, ratio: float = 1.0) -> None:
        self.open_button.apply_theme(colors.text_muted, ratio)
        for button in self._path_buttons:
            button.apply_theme(colors.text_faint, ratio)
