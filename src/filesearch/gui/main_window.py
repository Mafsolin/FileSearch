from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget, QMessageBox

from filesearch.gui import animations, icons, theme
from filesearch.gui.pages.index_page import IndexPage
from filesearch.gui.pages.providers_page import ProvidersPage
from filesearch.gui.pages.search_page import SearchPage
from filesearch.gui.pages.settings_page import SettingsPage
from filesearch.gui.pages.vision_page import VisionPage
from filesearch.gui.widgets.nav_rail import NavRail
from filesearch.gui.workers import SearchWorker
from filesearch.providers.openai_compatible import OpenAICompatibleProvider
from filesearch.storage.database import Database
from filesearch.storage.settings_store import SettingsStore

NAV_ITEMS = [
    ("search", "Поиск"),
    ("folder-tree", "Папки и индекс"),
    ("plug", "Провайдеры"),
    ("eye", "Vision-модели"),
    ("settings-2", "Настройки"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsStore()
        self.database = Database(self.settings.index_path())
        self.theme_name = self.settings.theme()
        self._closing = False
        self._allow_close = False
        animations.set_enabled(self.settings.animations_enabled())

        self.setWindowTitle("FileSearch")
        self.resize(1180, 780)
        self.setMinimumSize(940, 620)

        root = QWidget()
        root.setObjectName("shell")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav = NavRail(NAV_ITEMS)
        self.nav.selected.connect(self._go_to)
        self.nav.theme_toggled.connect(self.toggle_theme)
        layout.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.search = SearchPage(self.perform_search)
        self.index = IndexPage(self.settings, self.database, self.provider, self.refresh_status, self.select_index, self.remap_root)
        self.providers = ProvidersPage(self.settings, self.provider_changed, self._confirm_consent)
        self.vision = VisionPage(self.settings, self.provider_changed, self._confirm_vision_consent)
        self.settings_page = SettingsPage(self.settings, self.apply_theme, self.set_animations)
        for page in (self.search, self.index, self.providers, self.vision, self.settings_page):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(root)
        self.apply_theme(self.theme_name)
        self.refresh_status()
        warning = self.settings.pop_warning()
        if warning:
            QTimer.singleShot(0, lambda message=warning: QMessageBox.warning(self, "Настройки восстановлены", message))

    # ------------------------------------------------------------------ theme

    def apply_theme(self, name: str) -> None:
        """Restyle the whole application in place.

        Icons are raster, so the cache has to be dropped and every widget that
        owns one asked to repaint it. Qt has no cascade to do this for us.
        """
        self.theme_name = name
        self.settings.set_theme(name)

        app = self.window().windowHandle()
        ratio = self.devicePixelRatioF()
        if app is not None:
            ratio = app.devicePixelRatio()

        from PySide6.QtWidgets import QApplication

        instance = QApplication.instance()
        if instance is not None:
            instance.setPalette(theme.qt_palette(name))
            instance.setStyleSheet(theme.stylesheet(name))

        icons.clear_cache()
        colors = theme.palette(name)
        is_dark = name == theme.DARK

        self.nav.apply_theme(colors, is_dark, ratio)
        for page in (self.search, self.index, self.providers, self.vision, self.settings_page):
            if hasattr(page, "apply_theme"):
                page.apply_theme(colors, ratio)

    def toggle_theme(self) -> None:
        self.apply_theme(theme.LIGHT if self.theme_name == theme.DARK else theme.DARK)
        self.settings_page.sync_theme(self.theme_name)

    def set_animations(self, enabled: bool) -> None:
        animations.set_enabled(enabled)
        self.settings.set_animations_enabled(enabled)

    # ------------------------------------------------------------- navigation

    def _go_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav.set_current(index)

    def refresh_status(self) -> None:
        """Update the rail footer with measured counts, never estimates."""
        try:
            files, chunks = self.database.stats()
            self.nav.set_stats(f"{files:,} файлов · {chunks:,} фрагментов".replace(",", " "))
        except Exception:
            self.nav.set_stats("Индекс недоступен")
        try:
            profiles = self.settings.load_profiles()
            active = self.settings.active_provider_id()
            profile = next((p for p in profiles if p.id == active), profiles[0])
            self.nav.set_provider(profile.name)
        except Exception:
            self.nav.set_provider("Провайдер не выбран")

    # --------------------------------------------------------------- backend

    def provider(self, include_vision: bool = True):
        profile, vision = self._active_profiles(include_vision)
        return OpenAICompatibleProvider(
            profile,
            self.settings.get_key(profile),
            vision_profile=vision,
            vision_api_key=self.settings.get_key(vision) if vision else "",
        )

    def _active_profiles(self, include_vision: bool = True):
        """Resolve the active profiles, asking for consent when it is new."""
        profiles = self.settings.load_profiles()
        profile = next((x for x in profiles if x.id == self.settings.active_provider_id()), profiles[0])
        vision = None
        if include_vision:
            vision = next(
                (p for p in self.settings.load_vision_profiles() if p.id == self.settings.active_vision_provider_id()), None
            )
        if not self._confirm_consent(profile, vision):
            raise RuntimeError("Передача данных отменена пользователем.")
        return profile, vision

    def _confirm_consent(self, profile, vision=None) -> bool:
        if not self.settings.has_consent(profile, vision):
            destinations = f"{profile.base_url} (модель {profile.model})"
            if vision is not None:
                destinations += f"\nСканы и изображения: {vision.base_url} (модель {vision.model})"
            answer = QMessageBox.question(
                self,
                "Передача данных",
                "Поиск и индексация будут отправлять содержимое файлов и текст запроса:\n"
                f"{destinations}\n\nПродолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return False
            self.settings.grant_consent(profile, vision)
        return True

    def _confirm_vision_consent(self, vision) -> bool:
        profiles = self.settings.load_profiles()
        profile = next((x for x in profiles if x.id == self.settings.active_provider_id()), profiles[0])
        return self._confirm_consent(profile, vision)

    def perform_search(self, query, count, kind_group=None, cancel=None):
        """Build a worker for SearchPage; consent is resolved on this thread."""
        profile, _ = self._active_profiles(False)
        groups = {
            "pdf": {"pdf"},
            "images": {"jpg", "jpeg", "png"},
            "docx": {"docx"},
            "xlsx": {"xlsx"},
            "text": {"txt", "md"},
        }
        return SearchWorker(
            query,
            count,
            profile,
            self.settings.get_key(profile),
            self.database.path,
            cancel if cancel is not None else Event(),
            kinds=groups.get(kind_group),
            roots=set(self.settings.enabled_search_roots()),
        )

    def provider_changed(self):
        self.refresh_status()

    def select_index(self, value: str) -> None:
        path = Path(value).expanduser().resolve()
        Database.validate_index(path)
        if self.index.thread is not None:
            raise RuntimeError("Сначала завершите индексацию.")
        replacement = Database(path)
        try:
            self.settings.set_index(path, replacement.roots())
        except Exception:
            replacement.close()
            raise
        old = self.database
        self.database = replacement
        self.index.db = replacement
        old.close()
        self.index.reload(); self.refresh_status()

    def remap_root(self, old, new):
        if old is None:
            return self.database.roots()
        old_path = Path(old)
        new_path = Path(new)
        self.database.remap_root(old_path, new_path)
        configured = [new_path if path == old_path else path for path in self.settings.load_roots()]
        self.settings.save_roots(configured if configured else self.database.roots())
        self.index.reload(); self.refresh_status()

    def closeEvent(self, event):  # noqa: N802 - Qt naming
        if self._allow_close:
            super().closeEvent(event)
            return
        active = any(
            page.shutdown()
            for page in (self.index, self.search, self.providers, self.vision)
        )
        if not active:
            self.database.close()
            self._allow_close = True
            super().closeEvent(event)
            return
        event.ignore()
        if not self._closing:
            self._closing = True
            self.setWindowTitle("FileSearch — завершаем фоновые операции…")
            self.centralWidget().setEnabled(False)
            QTimer.singleShot(100, self._finish_close_when_idle)

    def _finish_close_when_idle(self) -> None:
        if any(page.is_running() for page in (self.index, self.search, self.providers, self.vision)):
            QTimer.singleShot(100, self._finish_close_when_idle)
            return
        self.database.close()
        self._allow_close = True
        self.close()
