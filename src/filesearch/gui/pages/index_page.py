from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QThread, QTimer, Slot
import time
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QInputDialog,
    QMessageBox,
    QProgressBar,
    QCheckBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from filesearch.gui.theme import SPACE
from filesearch.gui.widgets.busy_bars import BusyBars
from filesearch.gui.widgets.common import (
    Divider,
    EmptyState,
    IconButton,
    WrapLabel,
    page_header,
)
from filesearch.gui.workers import IndexWorker, RebuildWorker


class IndexPage(QWidget):
    def __init__(self, settings, db, provider_factory, on_index_changed=None, on_index_selected=None, on_root_remap=None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.provider_factory = provider_factory
        self.on_index_changed = on_index_changed
        self.on_index_selected = on_index_selected
        self.on_root_remap = on_root_remap
        self.cancel = Event()
        self.thread: QThread | None = None
        self.worker = None
        self._rebuilding = False
        self._started_at = 0.0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["2xl"], SPACE["2xl"], SPACE["2xl"], SPACE["xl"])
        layout.setSpacing(0)

        layout.addWidget(
            page_header(
                "Папки и индекс",
                "Синхронизация добавляет новые файлы, обновляет изменённые "
                "и убирает из индекса удалённые с диска.",
            )
        )
        layout.addSpacing(SPACE["xl"])

        # The list and its empty state occupy the same slot: one folder should
        # not leave a page-height blank rectangle.
        self.folders = QStackedWidget()
        self.list = QTableWidget(0, 3)
        self.list.setObjectName("indexTable")
        self.list.setHorizontalHeaderLabels(["Поиск", "Папка", "SQLite-индекс"])
        self.list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.list.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.list.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.list.setWordWrap(True)
        self.list.verticalHeader().hide()
        self.list.setShowGrid(False)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setCornerButtonEnabled(False)
        self.list.setSelectionBehavior(QTableWidget.SelectRows)
        self.list.setSelectionMode(QTableWidget.SingleSelection)
        self.list.setEditTriggers(QTableWidget.NoEditTriggers)
        self.list.itemChanged.connect(self._search_root_changed)
        self.list.setAlternatingRowColors(False)
        self.folders.addWidget(self.list)

        self.empty = EmptyState(
            "folder-tree",
            "Папки ещё не добавлены",
            "Добавьте папку с документами — FileSearch проиндексирует "
            "её содержимое и будет искать по нему.",
        )
        # The empty state gets the same bounded surface the table has. Floating
        # centred text in an open page reads as a rendering failure; inside a
        # panel it reads as a container that is waiting for content.
        empty_holder = QWidget()
        empty_holder.setObjectName("panel")
        empty_holder.setAttribute(Qt.WA_StyledBackground, True)
        empty_box = QVBoxLayout(empty_holder)
        empty_box.setContentsMargins(0, 0, 0, 0)
        empty_box.addWidget(self.empty)
        self.folders.addWidget(empty_holder)

        # Two rarely-used, wordy actions. At full button weight they outrank the
        # primary action below them, so they sit quiet until hovered.
        portable = QHBoxLayout()
        portable.setContentsMargins(0, 0, 0, SPACE["sm"])
        portable.setSpacing(SPACE["xs"])
        portable.addStretch(1)
        self.select_index_button = IconButton("database", "Подключить SQLite-индекс")
        self.select_index_button.setObjectName("quiet")
        self.select_index_button.setMinimumHeight(32)
        self.select_index_button.clicked.connect(self._select_index)
        portable.addWidget(self.select_index_button)
        self.remap_button = IconButton("folder-tree", "Указать новое расположение файлов")
        self.remap_button.setObjectName("quiet")
        self.remap_button.setMinimumHeight(32)
        self.remap_button.clicked.connect(self._remap_root)
        portable.addWidget(self.remap_button)
        layout.addLayout(portable)
        layout.addWidget(self.folders, 1)

        layout.addSpacing(SPACE["md"])

        # Folder-scoped actions on the left, index-scoped on the right. The
        # stretch between them keeps "Перестроить" away from "Синхронизировать"
        # so a destructive full rebuild is not a near-miss click.
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(SPACE["sm"])

        self.add_button = IconButton("plus", "Добавить папку")
        self.add_button.clicked.connect(self.add)
        actions.addWidget(self.add_button)

        self.remove_button = IconButton("trash-2", "Убрать")
        self.remove_button.clicked.connect(self.remove)
        actions.addWidget(self.remove_button)

        actions.addSpacing(SPACE["md"])
        self.vision_toggle = QCheckBox("Vision для сканов")
        self.vision_toggle.setChecked(self.settings.vision_indexing_enabled())
        self.vision_toggle.setToolTip(
            "Включено: страницы без текста сначала распознаются Vision-моделью.\n"
            "Выключено: PDF и изображения отправляются сразу только в embeddings."
        )
        self.vision_toggle.toggled.connect(self.settings.set_vision_indexing_enabled)
        actions.addWidget(self.vision_toggle)

        actions.addStretch(1)

        self.rebuild_button = IconButton("rotate-cw", "Перестроить")
        self.rebuild_button.setObjectName("destructive")
        self.rebuild_button.setToolTip(
            "Заново переиндексировать все папки. Нужно после смены модели embeddings."
        )
        self.rebuild_button.clicked.connect(self.rebuild)
        actions.addWidget(self.rebuild_button)

        self.cancel_button = IconButton("square", "Отменить")
        self.cancel_button.clicked.connect(self.cancel.set)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)

        self.sync_button = IconButton("play", "Синхронизировать")
        self.sync_button.setObjectName("primary")
        self.sync_button.clicked.connect(self.sync)
        actions.addWidget(self.sync_button)

        layout.addLayout(actions)

        status_strip = QWidget()
        status_strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        status_layout = QVBoxLayout(status_strip)
        status_layout.setContentsMargins(0, SPACE["lg"], 0, 0)
        status_layout.setSpacing(0)
        status_layout.addWidget(Divider())
        status_layout.addSpacing(SPACE["md"])

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        status_layout.addWidget(self.progress)

        status_layout.addSpacing(SPACE["sm"])

        current_row = QHBoxLayout()
        current_row.setContentsMargins(0, 0, 0, 0)
        current_row.setSpacing(SPACE["sm"])
        self.busy = BusyBars()
        current_row.addWidget(self.busy)
        self.current = QLabel("")
        self.current.setObjectName("muted")
        self.current.setTextFormat(Qt.PlainText)
        current_row.addWidget(self.current, 1)
        self.elapsed = QLabel("")
        self.elapsed.setObjectName("muted")
        current_row.addWidget(self.elapsed)
        status_layout.addLayout(current_row)

        self.summary = WrapLabel("")
        self.summary.setObjectName("faint")
        status_layout.addWidget(self.summary)

        # A QVBoxLayout hands leftover height to any item that can grow, so
        # without pinning these the slack is split between the progress rows and
        # the summary drifts away from the divider it belongs under. Pinned, the
        # folder list is the only item left that can grow, which is correct: it
        # is the content, everything below it is a fixed status strip.
        for widget in (self.progress, self.current, self.elapsed, self.summary):
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout.addWidget(status_strip)

        self.reload()

    # ------------------------------------------------------------------ data

    def reload(self) -> None:
        self.list.blockSignals(True)
        configured = self.settings.load_roots()
        indexed = self.db.roots()
        roots = list(dict.fromkeys(configured + indexed))
        self.list.setRowCount(len(roots))
        for row, path in enumerate(roots):
            exists = path.is_dir()
            paired = path in indexed
            state = "Готово" if exists and paired else ("Папка не найдена — укажите новое расположение" if paired and not exists else "Требуется синхронизация")
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            enabled_item.setCheckState(Qt.Checked if self.settings.search_root_enabled(path) else Qt.Unchecked)
            enabled_item.setData(Qt.UserRole, str(path))
            enabled_item.setToolTip("Учитывать эту папку при поиске")
            folder_item = QTableWidgetItem(f"{path}\n{state}")
            folder_item.setToolTip(str(path))
            folder_item.setData(Qt.UserRole, str(path))
            index_text = str(self.db.path) if paired else "Индекс ещё не создан — нажмите «Синхронизировать»"
            index_item = QTableWidgetItem(index_text)
            index_item.setToolTip(index_text)
            self.list.setItem(row, 0, enabled_item)
            self.list.setItem(row, 1, folder_item)
            self.list.setItem(row, 2, index_item)
            self.list.setRowHeight(row, 66)
        if roots and self.list.currentRow() < 0: self.list.selectRow(0)
        self.list.blockSignals(False)
        self.folders.setCurrentIndex(0 if roots else 1)
        self._fit_list(len(roots))
        self._update_action_state(bool(roots))

        files, chunks = self.db.stats()
        if files:
            self.summary.setText(
                f"В индексе: {files} файлов, {chunks} фрагментов и страниц."
            )
        else:
            self.summary.setText(
                "Индекс пуст. Добавьте папку и запустите синхронизацию."
            )
        if self.on_index_changed:
            self.on_index_changed()

    def _fit_list(self, count: int) -> None:
        """Size the list to its rows so a short list is not a tall empty box."""
        row_height = self.list.sizeHintForRow(0) if count else 34
        if row_height <= 0:
            row_height = 34
        height = row_height * max(count, 4) + 2 * SPACE["xs"] + 2
        height = min(height, 420)
        self.list.setMinimumHeight(min(height, 260))
        self.list.setMaximumHeight(16777215)
        self.folders.setMinimumHeight(240)
        self.folders.setMaximumHeight(16777215)

    def add(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Выберите папку")
        if not value:
            return
        path = Path(value).resolve()
        roots = [root.resolve() for root in self.settings.load_roots()]
        try:
            already_added = path in roots
            if path not in roots:
                roots.append(path)
            self.settings.save_roots(roots)
            self.reload()
            for row in range(self.list.rowCount()):
                if Path(self.list.item(row, 1).data(Qt.UserRole)).resolve() == path:
                    self.list.selectRow(row)
                    self.list.scrollToItem(self.list.item(row, 1))
                    break
            if already_added:
                QMessageBox.information(self, "Папка уже добавлена", "Эта папка уже есть в таблице и была выделена.")
        except Exception as error:
            QMessageBox.warning(self, "Не удалось добавить папку", str(error))

    def remove(self) -> None:
        path = self._selected_root()
        if path is None:
            QMessageBox.information(self, "FileSearch", "Выберите папку в списке.")
            return
        confirm = QMessageBox.question(self, "Убрать папку", "Папка будет убрана из FileSearch, а её документы — из индекса. Исходные файлы на диске не изменятся.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        path = path.resolve()
        self.db.remove_root(path)
        roots = [p for p in self.settings.load_roots() if p.resolve() != path]
        self.settings.save_roots(roots)
        self.reload()

    def _selected_root(self) -> Path | None:
        row = self.list.currentRow()
        item = self.list.item(row, 1) if row >= 0 else None
        return Path(item.data(Qt.UserRole)) if item else None

    def _search_root_changed(self, item) -> None:
        if item.column() != 0: return
        path=item.data(Qt.UserRole)
        if path: self.settings.set_search_root_enabled(Path(path), item.checkState() == Qt.Checked)

    def _select_index(self) -> None:
        value, _ = QFileDialog.getOpenFileName(self, "Выберите индекс FileSearch", "", "SQLite (*.sqlite3 *.sqlite *.db);;Все файлы (*)")
        if not value or self.on_index_selected is None: return
        try:
            self.on_index_selected(value)
            QMessageBox.information(self, "FileSearch", "Индекс подключён. При переносе на другой компьютер переназначьте пути к папкам.")
        except Exception as error:
            QMessageBox.warning(self, "Не удалось подключить индекс", str(error))

    def _remap_root(self) -> None:
        if self.on_root_remap is None: return
        roots = self.on_root_remap(None, None)
        if not roots:
            QMessageBox.information(self, "FileSearch", "В индексе нет папок."); return
        old, ok = QInputDialog.getItem(self, "Исходная папка", "Путь, записанный в индексе:", [str(x) for x in roots], 0, False)
        if not ok: return
        new = QFileDialog.getExistingDirectory(self, "Новое расположение этой папки")
        if not new: return
        try:
            self.on_root_remap(old, new)
            QMessageBox.information(self, "FileSearch", "Пути обновлены без повторной индексации.")
        except Exception as error:
            QMessageBox.warning(self, "Не удалось обновить пути", str(error))

    # --------------------------------------------------------------- syncing

    def sync(self) -> None:
        """Incrementally update the index for the selected folder."""
        selected = self._selected_root()
        if selected is None:
            QMessageBox.information(self, "FileSearch", "Выберите папку в списке.")
            return
        profile, vision = self._active_profiles()
        if profile is None:
            return
        worker = IndexWorker(
            selected,
            self.db.path,
            profile,
            self.settings.get_key(profile),
            self.cancel,
            vision_profile=vision,
            vision_key=self.settings.get_key(vision) if vision else "",
        )
        self._start(worker)

    def rebuild(self) -> None:
        """Re-embed every folder from scratch and publish the result at the end.

        Required after changing the embedding model: vectors from two models are
        not comparable, so a partial index is worse than none.
        """
        roots = [root for root in self.settings.load_roots() if root.is_dir()]
        missing = [root for root in self.settings.load_roots() if not root.is_dir()]
        if not roots:
            QMessageBox.information(self, "FileSearch", "Нет доступных папок для перестройки.")
            return
        listing = "\n".join(f"  • {root}" for root in roots)
        warning = (
            "\n\nЭти папки недоступны и будут потеряны из индекса:\n"
            + "\n".join(f"  • {root}" for root in missing)
            if missing
            else ""
        )
        confirm = QMessageBox.question(
            self,
            "Перестроить весь индекс",
            "Все папки будут заново отправлены провайдеру и переиндексированы:\n"
            f"{listing}{warning}\n\n"
            "Текущий индекс останется рабочим до самого конца и будет заменён "
            "одной операцией. Отмена ничего не испортит. Продолжить?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        profile, vision = self._active_profiles()
        if profile is None:
            return
        worker = RebuildWorker(
            roots,
            self.db.path,
            profile,
            self.settings.get_key(profile),
            self.cancel,
            vision_profile=vision,
            vision_key=self.settings.get_key(vision) if vision else "",
        )
        self._start(worker, rebuild=True)

    def _active_profiles(self):
        """Resolve the active profiles, taking consent via provider_factory."""
        include_vision = self.vision_toggle.isChecked()
        try:
            provider = self.provider_factory(include_vision)
        except Exception as error:
            QMessageBox.warning(self, "Провайдер", str(error))
            return None, None
        # The factory exists to run the consent prompt on the GUI thread; the
        # worker builds its own client, so this one is not needed.
        provider.close()
        profiles = self.settings.load_profiles()
        profile = next((p for p in profiles if p.id == self.settings.active_provider_id()), profiles[0])
        vision = None
        if include_vision:
            vision = next(
                (p for p in self.settings.load_vision_profiles() if p.id == self.settings.active_vision_provider_id()), None
            )
        return profile, vision

    def _start(self, worker, rebuild: bool = False) -> None:
        self.cancel.clear()
        self._rebuilding = rebuild
        self._started_at = time.monotonic()
        self._elapsed_timer.start(250)
        self._update_elapsed()
        self._set_running(True)
        self.thread = QThread(self)
        self.worker = worker
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.progress.connect(self.update_progress)
        worker.finished.connect(self.done)
        worker.failed.connect(self.error)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _update_action_state(self, has_roots: bool) -> None:
        """Disable folder-scoped actions when there is no folder to act on."""
        for button in (self.remove_button, self.sync_button, self.rebuild_button):
            button.setEnabled(has_roots)

    def _set_running(self, running: bool) -> None:
        has_roots = self.list.rowCount() > 0
        self.sync_button.setEnabled(not running and has_roots)
        self.rebuild_button.setEnabled(not running and has_roots)
        self.remove_button.setEnabled(not running and has_roots)
        self.add_button.setEnabled(not running)
        self.vision_toggle.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.progress.setVisible(running)
        if running:
            self.busy.start()
        else:
            self.busy.stop()
            self._elapsed_timer.stop()

    def _update_elapsed(self) -> None:
        seconds = int(time.monotonic() - self._started_at)
        self.elapsed.setText(f"Прошло {seconds // 60:02d}:{seconds % 60:02d}")

    def update_progress(self, p) -> None:
        self.progress.setMaximum(max(1, p.total_files))
        self.progress.setValue(p.current_file)
        name = Path(p.current_path).name if p.current_path else ""
        if not p.total_parts:
            # Still walking the tree: there is no meaningful ETA yet, so show
            # what is being counted rather than a frozen "0 из 0".
            self.current.setText(name)
            self.summary.setText(p.detail or "Готовим список файлов…")
            return
        self.current.setText(f"{p.current_file}/{p.total_files}  ·  {name}")
        remaining = max(0, p.total_parts - p.completed_parts)
        eta = max(0, int(p.estimated_seconds))
        hours, rest = divmod(eta, 3600)
        minutes, seconds = divmod(rest, 60)
        eta_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        prefix = f"{p.detail} · " if p.detail else ""
        scope = "Перестройка · " if self._rebuilding else ""
        self.summary.setText(
            f"{scope}{prefix}Страниц обработано {p.completed_parts} из {p.total_parts} · "
            f"осталось {remaining} · примерно {eta_text}"
        )

    @Slot(object)
    def done(self, p) -> None:
        self._finish_job()
        self._set_running(False)
        self.current.setText("Готово")
        self.reload()
        self.summary.setText(
            f"Обработано {p.processed}, пропущено {p.skipped}, "
            f"удалено {p.removed}, ошибок {p.failed}. Страниц обработано: {p.completed_parts}/{p.total_parts}."
        )
        if p.errors:
            shown = "\n".join(p.errors[:10])
            extra = f"\n… и ещё {len(p.errors) - 10}." if len(p.errors) > 10 else ""
            QMessageBox.warning(self, "Часть файлов не проиндексирована", shown + extra)

    @Slot(str)
    def error(self, message: str) -> None:
        self._finish_job()
        self._set_running(False)
        self.current.setText("")
        self.summary.setText(message)

    def _finish_job(self) -> None:
        """Ask the event-loop-driven thread to stop once its work has ended."""
        if self.thread is not None:
            self.thread.quit()
        self.worker = None
        self._rebuilding = False

    @Slot()
    def _thread_finished(self) -> None:
        self.thread = None

    def shutdown(self) -> bool:
        """Request cancellation without blocking or terminating the worker."""
        self.cancel.set()
        if self.thread is not None:
            self.thread.quit()
        return self.is_running()

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.isRunning()

    # ----------------------------------------------------------------- theme

    def apply_theme(self, colors, ratio: float = 1.0) -> None:
        self.busy.set_color(colors.accent)
        self.empty.apply_theme(colors.text_faint, ratio)
        self.sync_button.apply_theme(colors.accent_text, ratio)
        for button in (self.add_button, self.remove_button, self.cancel_button):
            button.apply_theme(colors.text_muted, ratio)
        self.rebuild_button.apply_theme(colors.text_muted, ratio)
        self.select_index_button.apply_theme(colors.text_muted, ratio)
        self.remap_button.apply_theme(colors.text_muted, ratio)
