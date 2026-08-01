from __future__ import annotations

from dataclasses import replace
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)

from filesearch.gui import icons
from filesearch.gui.theme import SPACE
from filesearch.gui.widgets.common import ChevronComboBox, Divider, IconButton, WrapLabel, page_header
from filesearch.providers.openai_compatible import OpenAICompatibleProvider
from filesearch.providers.validation import normalize_base_url
from filesearch.gui.workers import ProviderTestWorker
from threading import Event
import time


class ProvidersPage(QWidget):
    def __init__(self, settings, on_change, confirm_remote=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_change = on_change
        self.confirm_remote = confirm_remote
        self._colors = None
        self._ratio = 1.0
        self._test_thread = None
        self._test_worker = None
        self._test_cancel = None
        self._test_started = 0.0
        self._test_timer = QTimer(self)
        self._test_timer.timeout.connect(self._update_test_elapsed)
        self._adding_model = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["xl"])
        layout.setSpacing(0)

        layout.addWidget(
            page_header(
                "Провайдеры",
                "RouterAI настроен по умолчанию. Можно добавить любой "
                "OpenAI-совместимый embeddings API.",
            )
        )
        layout.addSpacing(SPACE["xl"])

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(SPACE["xl"])

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(SPACE["sm"])
        self.list = QListWidget()
        self.list.setIconSize(QSize(14, 14))
        self.list.currentRowChanged.connect(self.select)
        self.list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        left.addWidget(self.list)
        self.new_button = IconButton("plus", "Новый профиль")
        self.new_button.clicked.connect(self.new)
        left.addWidget(self.new_button)
        self.delete_button = IconButton("trash-2", "Удалить профиль")
        self.delete_button.clicked.connect(self.delete_profile)
        left.addWidget(self.delete_button)
        # Let the column end after the button instead of stretching a list of
        # two profiles down the whole page.
        left.addStretch(1)
        columns.addLayout(left, 1)

        # Cap the detail column: a URL field spanning a 1600px window puts a
        # forearm of empty space between each label and its input.
        detail = QWidget()
        detail.setMaximumWidth(640)
        right = QVBoxLayout(detail)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(SPACE["md"])
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://example.com/api/v1")
        self.model = ChevronComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("provider/embedding-model")
        self.model.lineEdit().returnPressed.connect(self.add_model)
        model_row = QWidget(); model_box = QHBoxLayout(model_row); model_box.setContentsMargins(0,0,0,0); model_box.setSpacing(SPACE["sm"]); model_box.addWidget(self.model,1)
        self.add_model_button = IconButton("plus", ""); self.add_model_button.setToolTip("Добавить модель"); self.add_model_button.clicked.connect(self.add_model); model_box.addWidget(self.add_model_button)
        self.remove_model_button = IconButton("trash-2", ""); self.remove_model_button.setToolTip("Удалить выбранную модель"); self.remove_model_button.clicked.connect(self.remove_model); model_box.addWidget(self.remove_model_button)

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Ключ хранится локально, вне репозитория")
        key_row = QWidget()
        key_box = QHBoxLayout(key_row)
        key_box.setContentsMargins(0, 0, 0, 0)
        key_box.setSpacing(SPACE["sm"])
        key_box.addWidget(self.key, 1)
        self.reveal = IconButton("eye", "")
        self.reveal.setObjectName("quiet")
        self.reveal.setFixedSize(32, 32)
        self.reveal.setAccessibleName("Показать API-ключ")
        self.reveal.setToolTip("Показать ключ")
        self.reveal.clicked.connect(self.toggle_key)
        key_box.addWidget(self.reveal)

        for label, field in (
            ("Название", self.name),
            ("Base URL", self.url),
            ("Модель embeddings", model_row),
            ("API-ключ", key_row),
        ):
            caption = QLabel(label)
            caption.setObjectName("fieldLabel")
            form.addRow(caption, field)
        right.addLayout(form)

        right.addSpacing(SPACE["lg"])
        right.addWidget(Divider())
        right.addSpacing(SPACE["md"])

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(SPACE["sm"])
        self.test_button = IconButton("plug", "Проверить")
        self.test_button.clicked.connect(self.test)
        buttons.addWidget(self.test_button)
        self.cancel_test_button = IconButton("square", "Отменить")
        self.cancel_test_button.setEnabled(False)
        self.cancel_test_button.clicked.connect(self.cancel_test)
        buttons.addWidget(self.cancel_test_button)
        self.activate_button = IconButton("check", "Сделать активным")
        self.activate_button.clicked.connect(self.activate)
        buttons.addWidget(self.activate_button)
        buttons.addStretch(1)
        self.save_button = IconButton("check", "Сохранить")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        right.addLayout(buttons)

        right.addSpacing(SPACE["md"])
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        right.addSpacing(SPACE["lg"])
        right.addWidget(Divider())
        right.addSpacing(SPACE["md"])
        self.privacy_note = WrapLabel("")
        self.privacy_note.setObjectName("faint")
        self.privacy_note.setTextFormat(Qt.PlainText)
        right.addWidget(self.privacy_note)
        right.addStretch(1)

        columns.addWidget(detail, 2)
        columns.addStretch(0)
        layout.addLayout(columns, 1)

        self.reload()

    # ------------------------------------------------------------------ data

    def profiles(self):
        return self.settings.load_profiles()

    def reload(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        active = self.settings.active_provider_id()
        profiles = self.profiles()
        for profile in profiles:
            item = QListWidgetItem(profile.name)
            if profile.id == active and self._colors is not None:
                item.setIcon(icons.icon("check", self._colors.accent, 14, 2.25, self._ratio))
                item.setToolTip("Активный профиль")
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._fit_list(len(profiles))
        row = next((i for i, p in enumerate(profiles) if p.id == active), 0)
        self.list.setCurrentRow(row)

    def _fit_list(self, count: int) -> None:
        """Size the list to its rows, within sane bounds."""
        row_height = self.list.sizeHintForRow(0) if count else 34
        if row_height <= 0:
            row_height = 34
        padding = 2 * SPACE["xs"] + 2  # List padding plus its 1px border.
        height = row_height * max(count, 3) + padding
        self.list.setMinimumHeight(min(height, 460))
        self.list.setMaximumHeight(min(height, 460))

    def select(self, row: int) -> None:
        if row < 0:
            return
        profile = self.profiles()[row]
        self.name.setText(profile.name)
        self.url.setText(profile.base_url)
        self._adding_model = False
        self.model.clear(); self.model.addItems(self.settings.provider_models(profile, self._vision_mode())); self.model.setCurrentText(profile.model)
        self.key.setText(self.settings.get_key(profile))
        self._update_privacy_note(profile)
        # The built-in profile is a supported preset. Since SettingsStore does
        # not serialize built-ins, make every non-persistent field read-only
        # instead of presenting edits that vanish on restart.
        for field in (self.name, self.url):
            field.setReadOnly(profile.builtin)
        self.status.setText("")
        self.delete_button.setEnabled(not profile.builtin)

    def _update_privacy_note(self, profile) -> None:
        self.privacy_note.setText(
            "Передача данных\n"
            "• Поиск отправляет текст запроса выбранному внешнему провайдеру.\n"
            "• Индексация отправляет одну логическую или физическую страницу за запрос.\n"
            "• Для PDF и изображений могут передаваться визуальные данные страницы.\n"
            f"• Выбранный endpoint: {profile.base_url}\n"
            "• API-ключ хранится локально в plaintext-файле .env и не включается в Git."
        )

    def new(self) -> None:
        self.list.setCurrentRow(-1)
        self.name.clear()
        self.url.setText("https://")
        self._adding_model = True; self.model.clearEditText()
        self.key.clear()
        for field in (self.name, self.url):
            field.setReadOnly(False)
        self.name.setFocus()
        self.delete_button.setEnabled(False)
        self.status.setText("Заполните поля и нажмите «Сохранить».")

    def selected(self):
        row = self.list.currentRow()
        return self.profiles()[row] if row >= 0 else None

    def _vision_mode(self) -> bool:
        return False

    def model_values(self) -> list[str]:
        values = [self.model.itemText(i).strip() for i in range(self.model.count())]
        current = self.model.currentText().strip()
        if current: values.append(current)
        return list(dict.fromkeys(x for x in values if x))

    def add_model(self) -> None:
        value = self.model.currentText().strip()
        if not self._adding_model:
            self._adding_model = True
            self.model.clearEditText()
            self.model.lineEdit().setPlaceholderText("Введите идентификатор модели и нажмите +")
            self.model.setFocus()
            return
        if not value:
            self.model.setFocus()
            return
        if self.model.findText(value) < 0:
            self.model.addItem(value)
        self.model.setCurrentText(value)
        self._adding_model = False

    def remove_model(self) -> None:
        values = self.model_values(); current = self.model.currentText().strip()
        if len(values) <= 1:
            self._set_status("У провайдера должна остаться хотя бы одна модель.", error=True); return
        answer = QMessageBox.question(self, "Удалить модель", f"Удалить модель «{current}» из профиля?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes: return
        values = [x for x in values if x != current]; self.model.clear(); self.model.addItems(values); self.model.setCurrentIndex(0)
        self._adding_model = False

    def delete_profile(self) -> None:
        profile = self.selected()
        if not profile or profile.builtin:
            self._set_status("Встроенный профиль удалить нельзя.", error=True)
            return
        answer = QMessageBox.question(self, "Удалить профиль", f"Удалить профиль «{profile.name}» и его локальный API-ключ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes: return
        profiles = [p for p in self.profiles() if p.id != profile.id]
        self.settings.save_profiles(profiles); self.settings.delete_key(profile)
        if self.settings.active_provider_id() == profile.id:
            self.settings.set_active_provider_id("routerai")
        self.reload(); self._set_status("Профиль удалён."); self.on_change()

    def toggle_key(self) -> None:
        hidden = self.key.echoMode() == QLineEdit.Password
        self.key.setEchoMode(QLineEdit.Normal if hidden else QLineEdit.Password)
        self.reveal._icon_name = "eye-off" if hidden else "eye"
        self.reveal.setAccessibleName("Скрыть API-ключ" if hidden else "Показать API-ключ")
        self.reveal.setToolTip("Скрыть ключ" if hidden else "Показать ключ")
        if self._colors is not None:
            self.reveal.apply_theme(self._colors.text_muted, self._ratio)

    # --------------------------------------------------------------- actions

    def save(self) -> None:
        old = self.selected()
        profiles = self.profiles()
        if old and old.builtin:
            active_model = self.model.currentText().strip()
            if not active_model:
                self._set_status("Укажите модель.", error=True); return
            self.settings.save_provider_models(old.id, self.model_values(), active_model, self._vision_mode())
            self.settings.set_key(old, self.key.text())
            self.reload(); self._set_status("Модели и API-ключ сохранены.")
            self.on_change()
            return
        elif old:
            try:
                profile = old.__class__(old.id, self.name.text().strip(), normalize_base_url(self.url.text()), self.model.currentText().strip(), old.key_name)
            except ValueError as error:
                self._set_status(str(error), error=True)
                return
        else:
            try:
                profile = self.settings.new_profile(self.name.text(), self.url.text(), self.model.currentText())
            except ValueError as error:
                self._set_status(str(error), error=True)
                return
            profiles.append(profile)

        if not profile.name or not profile.base_url or not profile.model:
            self._set_status("Заполните название, URL и модель.", error=True)
            return

        profiles = [profile if x.id == profile.id else x for x in profiles]
        self.settings.save_profiles(profiles)
        self.settings.save_provider_models(profile.id, self.model_values(), profile.model, self._vision_mode())
        self.settings.set_key(profile, self.key.text())
        self.reload()
        self._set_status("Профиль сохранён.")
        self.on_change()

    def activate(self) -> None:
        profile = self.selected()
        if not profile:
            self._set_status("Сначала выберите профиль в списке.", error=True)
            return
        active_model = self.model.currentText().strip()
        if not active_model:
            self._set_status("Выберите модель.", error=True); return
        self.settings.save_provider_models(profile.id, self.model_values(), active_model, self._vision_mode())
        self.settings.set_active_provider_id(profile.id)
        self.reload()
        self._set_status(f"Активный провайдер: {profile.name}")
        self.on_change()

    def test(self) -> None:
        if self._test_thread is not None:
            return
        profile = self.selected()
        if not profile:
            self._set_status("Сначала выберите профиль в списке.", error=True)
            return
        try:
            profile = replace(
                profile,
                name=self.name.text().strip() or profile.name,
                base_url=normalize_base_url(self.url.text()),
                model=self.model.currentText().strip(),
            )
            if not profile.model:
                raise ValueError("Выберите модель.")
        except ValueError as error:
            self._set_status(str(error), error=True)
            return
        if self.confirm_remote is not None and not self.confirm_remote(profile, None):
            self._set_status("Проверка отменена: передача данных не разрешена.")
            return
        self._set_status("Проверяем подключение · 00:00")
        self._test_cancel = Event(); self._test_started = time.monotonic(); self._test_timer.start(250)
        self._set_test_running(True)
        self._test_thread = QThread(self)
        self._test_worker = ProviderTestWorker(profile, self.key.text(), self._test_cancel)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self.test_done)
        self._test_worker.failed.connect(self.test_failed)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_worker.failed.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread_done)
        self._test_thread.start()

    def cancel_test(self):
        if self._test_cancel: self._test_cancel.set()

    def shutdown(self) -> bool:
        self.cancel_test()
        if self._test_thread is not None:
            self._test_thread.quit()
        return self.is_running()

    def is_running(self) -> bool:
        return self._test_thread is not None and self._test_thread.isRunning()

    def _set_test_running(self, running):
        for widget in (self.name, self.url, self.model, self.key, self.test_button, self.add_model_button, self.remove_model_button): widget.setEnabled(not running)
        self.cancel_test_button.setEnabled(running)

    def _update_test_elapsed(self):
        elapsed = int(time.monotonic() - self._test_started)
        self._set_status(f"Проверяем подключение · {elapsed // 60:02d}:{elapsed % 60:02d}")

    @Slot(int)
    def test_done(self, dims):
        self._finish_test(); self._set_status(f"Подключение работает. Размерность вектора: {dims}.")

    @Slot(str)
    def test_failed(self, message):
        self._finish_test(); self._set_status(f"Ошибка: {message}", error=True)

    def _finish_test(self):
        self._test_timer.stop(); self._set_test_running(False)
        if self._test_thread: self._test_thread.quit()

    def _test_thread_done(self):
        self._test_thread.deleteLater(); self._test_thread = None; self._test_worker = None; self._test_cancel = None

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setObjectName("danger" if error else "muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)

    # ----------------------------------------------------------------- theme

    def apply_theme(self, colors, ratio: float = 1.0) -> None:
        self._colors = colors
        self._ratio = ratio
        self.save_button.apply_theme(colors.accent_text, ratio)
        self.model.apply_theme(colors.text_muted, ratio)
        for button in (
            self.new_button,
            self.delete_button,
            self.add_model_button,
            self.remove_model_button,
            self.test_button,
            self.cancel_test_button,
            self.activate_button,
            self.reveal,
        ):
            button.apply_theme(colors.text_muted, ratio)
        self._apply_profile_icons()

    def _apply_profile_icons(self) -> None:
        """Repaint active-state icons without reloading unsaved form values."""
        active = self.settings.active_provider_id()
        profiles = self.profiles()
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setIcon(QIcon())
            item.setToolTip("")
            if (
                self._colors is not None
                and row < len(profiles)
                and profiles[row].id == active
            ):
                item.setIcon(
                    icons.icon("check", self._colors.accent, 14, 2.25, self._ratio)
                )
                item.setToolTip("Активный профиль")
