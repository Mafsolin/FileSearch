from __future__ import annotations

import asyncio
import base64
import math
import mimetypes
from contextlib import suppress
from threading import Event, Lock

import httpx

from filesearch.domain.models import ProviderProfile
from filesearch.providers.base import ProviderError
from filesearch.providers.validation import normalize_base_url


# Individual document requests may legitimately take several minutes. The
# network deadline is therefore generous, while cancellation is handled by an
# asyncio task and remains responsive independently of this value.
TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=300.0, pool=30.0)
RETRYABLE = {429, 500, 502, 503, 504}


class OpenAICompatibleProvider:
    def __init__(
        self,
        profile: ProviderProfile,
        api_key: str,
        cancel: Event | None = None,
        vision_profile=None,
        vision_api_key: str = "",
    ) -> None:
        if not api_key:
            raise ProviderError(f"Для провайдера «{profile.name}» не задан API-ключ.")
        self.model = profile.model
        self.vision_model = vision_profile.model if vision_profile else None
        self.cancel = cancel or Event()
        self.base_url = normalize_base_url(profile.base_url)
        self._runner = asyncio.Runner()
        self._runner_lock = Lock()
        self._closed = False
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT,
            trust_env=False,
        )
        self._vision_client = (
            httpx.AsyncClient(
                base_url=normalize_base_url(vision_profile.base_url),
                headers={"Authorization": f"Bearer {vision_api_key}"},
                timeout=TIMEOUT,
                trust_env=False,
            )
            if vision_profile and vision_api_key
            else None
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.cancel.set()

        async def close_clients() -> None:
            await self._client.aclose()
            if self._vision_client is not None:
                await self._vision_client.aclose()

        with self._runner_lock:
            try:
                self._runner.run(close_clients())
            finally:
                self._runner.close()

    def test_connection(self) -> int:
        return len(self.embed_text("Проверка подключения FileSearch"))

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts) -> list[list[float]]:
        if not texts:
            return []
        response = self._request({"model": self.model, "input": texts, "encoding_format": "float"})
        try:
            vectors = [self._vector(item["embedding"]) for item in sorted(response["data"], key=lambda x: x["index"])]
        except (KeyError, TypeError) as error:
            raise ProviderError("Некорректный ответ embeddings.") from error
        if len(vectors) != len(texts):
            raise ProviderError("Провайдер вернул неполный набор embeddings.")
        self._same_dimensions(vectors)
        return vectors

    def embed_pdf_page(self, pdf_bytes, filename, context_text=""):
        return self._embed_file("application/pdf", pdf_bytes, filename, "input_file", "input_file", context_text)

    def embed_image(self, image_bytes, filename, context_text=""):
        mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
        return self._embed_file(mime, image_bytes, filename, "image_url", "image_url", context_text)

    def transcribe_image(self, image_bytes, filename):
        mime = mimetypes.guess_type(filename)[0] or "image/jpeg"
        return self._transcribe(mime, image_bytes, filename)

    def _embed_file(self, mime, content, filename, kind, field, context_text=""):
        if len(content) > 20 * 1024 * 1024:
            raise ProviderError(f"{filename}: страница больше 20 МБ.")
        data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
        item = {"type": kind, field: {"data": data_url, "filename": filename}}
        if kind == "image_url":
            item = {"type": kind, field: {"url": data_url}}
        items = ([{"type": "text", "text": context_text}] if context_text else []) + [item]
        try:
            response = self._request(
                {"model": self.model, "input": [{"content": items}], "encoding_format": "float"}
            )
        except ProviderError as error:
            if "HTTP 4" in str(error):
                raise ProviderError(
                    f"{filename}: провайдер {self.base_url} не принимает файлы и изображения в /embeddings "
                    f"({error}). Для PDF и сканов нужен endpoint с мультимодальными embeddings, например RouterAI."
                ) from error
            raise
        try:
            return self._vector(response["data"][0]["embedding"])
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(f"Некорректный embedding для {filename}.") from error

    def _transcribe(self, mime, content, filename):
        if not self.vision_model or not self._vision_client:
            return ""
        if len(content) > 20 * 1024 * 1024:
            raise ProviderError(f"{filename}: страница или изображение больше 20 МБ.")
        data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
        response = self._request_chat(
            {
                "model": self.vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Точно транскрибируй весь видимый текст документа. Верни только текст без пояснений и без повторения одинаковых фрагментов.",
                            },
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
                ],
                "temperature": 0,
                "max_tokens": 4096,
            }
        )
        try:
            value = response["choices"][0]["message"]["content"]
            text = value if isinstance(value, str) else " ".join(
                item.get("text", "") for item in value if isinstance(item, dict)
            )
            return self._clean_transcription(text)
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(f"Некорректная транскрипция для {filename}.") from error

    def _request(self, payload):
        return self._request_path("/embeddings", payload)

    def _request_chat(self, payload):
        return self._request_path("/chat/completions", payload, self._vision_client)

    def _request_path(self, path, payload, client=None):
        if self._closed:
            raise ProviderError("Провайдер уже закрыт.")
        with self._runner_lock:
            if self._closed:
                raise ProviderError("Provider is already closed.")
            return self._runner.run(self._request_path_async(path, payload, client or self._client))

    async def _request_path_async(self, path, payload, client):
        last_error = None
        for attempt in range(3):
            if self.cancel.is_set():
                raise InterruptedError("Операция отменена")
            try:
                response = await self._post_cancel_aware(client, path, payload)
                if response.status_code in RETRYABLE and attempt < 2:
                    await self._backoff(1.5 * (attempt + 1))
                    continue
                if response.is_error:
                    raise ProviderError(f"HTTP {response.status_code}: {response.text[:600]}")
                return response.json()
            except InterruptedError:
                raise
            except ProviderError:
                raise
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
                if attempt < 2:
                    await self._backoff(1.5 * (attempt + 1))
        raise ProviderError(f"Не удалось получить ответ: {last_error}")

    async def _post_cancel_aware(self, client, path, payload):
        request = asyncio.create_task(client.post(path, json=payload))
        try:
            while not request.done():
                if self.cancel.is_set():
                    request.cancel()
                    with suppress(asyncio.CancelledError):
                        await request
                    raise InterruptedError("Операция отменена")
                await asyncio.sleep(0.05)
            response = await request
            if self.cancel.is_set():
                raise InterruptedError("Операция отменена")
            return response
        finally:
            if not request.done():
                request.cancel()

    async def _backoff(self, seconds: float) -> None:
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            if self.cancel.is_set():
                raise InterruptedError("Операция отменена")
            await asyncio.sleep(min(0.05, max(0.0, deadline - asyncio.get_running_loop().time())))

    @staticmethod
    def _vector(value):
        if not isinstance(value, list) or not value or not all(isinstance(x, (int, float)) for x in value):
            raise ProviderError("Embedding должен быть непустым списком чисел.")
        if not all(math.isfinite(float(x)) for x in value):
            raise ProviderError("Embedding должен содержать только конечные числа.")
        return [float(x) for x in value]

    @staticmethod
    def _same_dimensions(vectors):
        if any(len(item) != len(vectors[0]) for item in vectors):
            raise ProviderError("Embeddings разной размерности.")

    @staticmethod
    def _clean_transcription(value: str) -> str:
        """Bound pathological vision loops before they reach embeddings."""
        result = []
        occurrences = {}
        length = 0
        for raw in value.splitlines():
            line = " ".join(raw.split())
            if not line:
                continue
            key = line.casefold()
            count = occurrences.get(key, 0)
            if count >= 3:
                continue
            occurrences[key] = count + 1
            result.append(line)
            length += len(line) + 1
            if length >= 20000:
                break
        text = "\n".join(result)[:20000].strip()
        if not text:
            raise ProviderError("Vision-модель вернула пустую транскрипцию.")
        return text
