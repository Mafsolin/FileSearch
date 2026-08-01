from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, Signal, Slot

from filesearch.domain.models import ProviderProfile
from filesearch.providers.openai_compatible import OpenAICompatibleProvider
from filesearch.services.indexing import rebuild_all, sync
from filesearch.storage.database import Database


class IndexWorker(QObject):
    """Incrementally sync one root into the live index."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, root, db_path, profile, key, cancel, vision_profile=None, vision_key=""):
        super().__init__()
        self.root = root
        self.db_path = db_path
        self.profile = profile
        self.key = key
        self.cancel = cancel
        self.vision_profile = vision_profile
        self.vision_key = vision_key

    @Slot()
    def run(self):
        db = provider = None
        try:
            db = Database(self.db_path)
            provider = OpenAICompatibleProvider(self.profile, self.key, self.cancel, self.vision_profile, self.vision_key)
            self.finished.emit(sync(self.root, db, provider, self.cancel, self.progress.emit))
        except InterruptedError:
            self.failed.emit("Индексация отменена пользователем.")
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if provider:
                provider.close()
            if db:
                db.close()


class RebuildWorker(QObject):
    """Re-embed every configured root into a staging index, then publish it."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, roots, db_path, profile, key, cancel, vision_profile=None, vision_key=""):
        super().__init__()
        self.roots = list(roots)
        self.db_path = db_path
        self.profile = profile
        self.key = key
        self.cancel = cancel
        self.vision_profile = vision_profile
        self.vision_key = vision_key

    @Slot()
    def run(self):
        try:
            self.finished.emit(
                rebuild_all(
                    self.roots,
                    self.db_path,
                    self.profile,
                    self.key,
                    self.cancel,
                    self.progress.emit,
                    self.vision_profile,
                    self.vision_key,
                )
            )
        except InterruptedError:
            self.failed.emit("Перестройка отменена — прежний индекс сохранён.")
        except Exception as error:
            self.failed.emit(str(error))


class SearchWorker(QObject):
    """Embed the query and score the index off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, query, count, profile, key, db_path, cancel, kinds=None, roots=None):
        super().__init__()
        self.query = query
        self.count = count
        self.db_path = db_path
        self.profile = profile
        self.key = key
        self.cancel = cancel
        self.kinds = kinds
        self.roots = roots

    @Slot()
    def run(self):
        db = provider = None
        try:
            db = Database(self.db_path)
            # A model mismatch is knowable from local metadata. Reject it
            # before constructing the HTTP request so an impossible search
            # never spends money or transmits the user's query.
            db.require_model(self.profile.model)
            provider = OpenAICompatibleProvider(self.profile, self.key, self.cancel)
            vector = provider.embed_text(self.query)
            db.require_vector(provider.model, len(vector))
            self.finished.emit(db.search(vector, self.count, model=provider.model, kinds=self.kinds, roots=self.roots))
        except InterruptedError:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if provider:
                provider.close()
            if db:
                db.close()


class ProviderTestWorker(QObject):
    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, profile, key, cancel):
        super().__init__()
        self.profile = profile
        self.key = key
        self.cancel = cancel

    @Slot()
    def run(self):
        provider = None
        try:
            provider = OpenAICompatibleProvider(self.profile, self.key, self.cancel)
            self.finished.emit(provider.test_connection())
        except InterruptedError:
            self.failed.emit("Проверка отменена.")
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if provider:
                provider.close()


class VisionTestWorker(QObject):
    """Verify a vision profile with one tiny generated image."""

    finished = Signal(int)
    failed = Signal(str)

    def __init__(self, profile, key, cancel):
        super().__init__()
        self.profile = profile
        self.key = key
        self.cancel = cancel

    @Slot()
    def run(self):
        provider = None
        try:
            embedding_profile = ProviderProfile(
                self.profile.id,
                self.profile.name,
                self.profile.base_url,
                self.profile.model,
                self.profile.key_name,
            )
            provider = OpenAICompatibleProvider(
                embedding_profile,
                self.key,
                self.cancel,
                self.profile,
                self.key,
            )
            image = Image.new("RGB", (320, 80), "white")
            ImageDraw.Draw(image).text((18, 28), "FileSearch 123", fill="black")
            output = BytesIO()
            image.save(output, format="PNG")
            transcript = provider.transcribe_image(output.getvalue(), "filesearch-vision-test.png")
            self.finished.emit(len(transcript))
        except InterruptedError:
            self.failed.emit("Проверка отменена.")
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if provider:
                provider.close()
