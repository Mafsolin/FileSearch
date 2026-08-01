from PySide6.QtGui import QIcon
from dataclasses import replace
from threading import Event
import time

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QLabel, QMessageBox

from filesearch.gui import icons
from filesearch.gui.pages.providers_page import ProvidersPage
from filesearch.gui.workers import VisionTestWorker
from filesearch.providers.validation import normalize_base_url


class VisionPage(ProvidersPage):
    """Vision provider editor using exactly the same UI contract as embeddings."""

    def __init__(self, settings, on_change, confirm_remote=None, parent=None):
        super().__init__(settings, on_change, confirm_remote, parent)
        for label in self.findChildren(QLabel):
            text = label.text()
            if text == "Провайдеры": label.setText("Vision-модели")
            elif "RouterAI настроен" in text: label.setText("RouterAI Vision настроен по умолчанию. Можно добавить любой OpenAI-совместимый vision API.")
            elif text == "Модель embeddings": label.setText("Vision-модель")
        self.new_button.setText("Новый профиль")

    def profiles(self):
        return self.settings.load_vision_profiles()

    def _vision_mode(self):
        return True

    def reload(self):
        self.list.blockSignals(True); self.list.clear()
        active = self.settings.active_vision_provider_id(); profiles = self.profiles()
        for profile in profiles: self.list.addItem(profile.name)
        self.list.blockSignals(False); self._fit_list(len(profiles))
        self.list.setCurrentRow(next((i for i,p in enumerate(profiles) if p.id == active), 0))
        if self._colors is not None: self._apply_profile_icons()

    def save(self):
        old = self.selected(); profiles = self.profiles()
        try:
            active_model = self.model.currentText().strip()
            if old and old.builtin:
                self.settings.save_provider_models(old.id, self.model_values(), active_model, True)
                self.settings.set_key(old, self.key.text()); self.reload(); self._set_status("Модели и API-ключ сохранены."); self.on_change(); return
            elif old:
                profile = old.__class__(old.id, self.name.text().strip(), normalize_base_url(self.url.text()), active_model, old.key_name)
            else:
                profile = self.settings.new_vision_profile(self.name.text(), self.url.text(), active_model); profiles.append(profile)
            if not profile.name or not profile.model: raise ValueError("Заполните название, URL и vision-модель.")
            profiles = [profile if p.id == profile.id else p for p in profiles]
            self.settings.save_vision_profiles(profiles); self.settings.save_provider_models(profile.id, self.model_values(), profile.model, True); self.settings.set_key(profile, self.key.text()); self.reload()
            self._set_status("Vision-профиль сохранён."); self.on_change()
        except Exception as error:
            QMessageBox.warning(self, "Vision-провайдер", str(error))

    def activate(self):
        profile = self.selected()
        if not profile: return
        self.settings.save_provider_models(profile.id, self.model_values(), self.model.currentText().strip(), True)
        self.settings.set_active_vision_provider_id(profile.id); self.reload()
        self._set_status(f"Активная vision-модель: {profile.name} · {profile.model}"); self.on_change()

    def delete_profile(self):
        profile = self.selected()
        if not profile or profile.builtin:
            self._set_status("Встроенный профиль удалить нельзя.", error=True); return
        answer = QMessageBox.question(self, "Удалить профиль", f"Удалить vision-профиль «{profile.name}» и его локальный API-ключ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes: return
        self.settings.save_vision_profiles([p for p in self.profiles() if p.id != profile.id]); self.settings.delete_key(profile)
        if self.settings.active_vision_provider_id() == profile.id: self.settings.set_active_vision_provider_id("routerai-vision")
        self.reload(); self._set_status("Vision-профиль удалён."); self.on_change()

    def test(self):
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
                raise ValueError("Выберите vision-модель.")
        except ValueError as error:
            self._set_status(str(error), error=True)
            return
        if self.confirm_remote is not None and not self.confirm_remote(profile):
            self._set_status("Проверка отменена: передача данных не разрешена.")
            return
        self._set_status("Проверяем vision-модель · 00:00")
        self._test_cancel = Event()
        self._test_started = time.monotonic()
        self._test_timer.start(250)
        self._set_test_running(True)
        self._test_thread = QThread(self)
        self._test_worker = VisionTestWorker(profile, self.key.text(), self._test_cancel)
        self._test_worker.moveToThread(self._test_thread)
        self._test_thread.started.connect(self._test_worker.run)
        self._test_worker.finished.connect(self.test_done)
        self._test_worker.failed.connect(self.test_failed)
        self._test_worker.finished.connect(self._test_worker.deleteLater)
        self._test_worker.failed.connect(self._test_worker.deleteLater)
        self._test_thread.finished.connect(self._test_thread_done)
        self._test_thread.start()

    def test_done(self, transcript_length):
        self._finish_test()
        self._set_status(f"Vision-подключение работает. Получено символов: {transcript_length}.")

    def _apply_profile_icons(self):
        active = self.settings.active_vision_provider_id(); profiles = self.profiles()
        for row in range(self.list.count()):
            item=self.list.item(row); item.setIcon(QIcon()); item.setToolTip("")
            if self._colors is not None and row < len(profiles) and profiles[row].id == active:
                item.setIcon(icons.icon("check", self._colors.accent, 14, 2.25, self._ratio)); item.setToolTip("Активный vision-профиль")
