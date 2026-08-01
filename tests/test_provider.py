from __future__ import annotations

from threading import Event
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

import httpx
import pytest

from filesearch.domain.models import ProviderProfile, VisionProfile
from filesearch.providers.base import ProviderError
from filesearch.providers.openai_compatible import TIMEOUT, OpenAICompatibleProvider
from filesearch.providers.validation import normalize_base_url

PROFILE = ProviderProfile("p1", "Provider", "https://example.invalid/v1", "embed-1", "KEY")


def build(handler, profile: ProviderProfile = PROFILE) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(profile, "secret")
    provider._runner.run(provider._client.aclose())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=provider.base_url)
    return provider


def test_requests_carry_a_bounded_timeout():
    """timeout=None used to let a hung socket freeze the whole application."""
    provider = OpenAICompatibleProvider(PROFILE, "secret")
    try:
        assert provider._client.timeout == TIMEOUT
        assert provider._client.timeout.read is not None
        assert provider._client.timeout.connect is not None
    finally:
        provider.close()


def test_embed_text_returns_the_vector():
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.25]}]})

    provider = build(handler)
    try:
        assert provider.embed_text("договор") == [0.5, 0.25]
    finally:
        provider.close()


def test_embed_texts_restores_provider_ordering():
    def handler(request):
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]},
        )

    provider = build(handler)
    try:
        assert provider.embed_texts(["a", "b"]) == [[1.0], [2.0]]
    finally:
        provider.close()


def test_incomplete_embedding_set_is_an_error():
    def handler(request):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    provider = build(handler)
    try:
        with pytest.raises(ProviderError, match="неполный набор"):
            provider.embed_texts(["a", "b"])
    finally:
        provider.close()


def test_a_rejected_pdf_page_explains_the_provider_limitation():
    """Plain /embeddings endpoints cannot take files; say so instead of 400."""

    def handler(request):
        return httpx.Response(400, text="input must be a string")

    provider = build(handler)
    try:
        with pytest.raises(ProviderError, match="не принимает файлы и изображения"):
            provider.embed_pdf_page(b"%PDF-1.4", "page.pdf")
    finally:
        provider.close()


def test_server_errors_are_retried_then_reported():
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(503, text="busy")

    provider = build(handler)
    try:
        with pytest.raises(ProviderError):
            provider.embed_text("договор")
        assert len(attempts) == 3
    finally:
        provider.close()


def test_cancellation_stops_before_the_request():
    """Cancellation is InterruptedError so workers can report it separately."""
    cancel = Event()
    cancel.set()
    provider = OpenAICompatibleProvider(PROFILE, "secret", cancel)
    called = []
    provider._runner.run(provider._client.aclose())
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: called.append(request) or httpx.Response(200, json={"data": []})),
        base_url=provider.base_url,
    )
    try:
        with pytest.raises(InterruptedError):
            provider.embed_text("договор")
        assert not called
    finally:
        provider.close()


def test_cancellation_interrupts_an_in_flight_request():
    entered = Event()
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib callback name
            entered.set()
            release.wait(2)
            body = json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    cancel = Event()
    profile = ProviderProfile("local", "Local", f"http://127.0.0.1:{server.server_port}/v1", "embed", "KEY")
    provider = OpenAICompatibleProvider(profile, "secret", cancel)
    errors = []
    request_thread = Thread(target=lambda: _capture_error(errors, lambda: provider.embed_text("query")))
    request_thread.start()
    try:
        assert entered.wait(1)
        cancel.set()
        request_thread.join(0.5)
        assert not request_thread.is_alive()
        assert errors and isinstance(errors[0], InterruptedError)
    finally:
        release.set()
        request_thread.join(3)
        provider.close()
        server.shutdown()
        server.server_close()


def test_close_cancels_an_in_flight_request_without_closing_a_running_loop():
    entered = Event()
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib callback name
            entered.set()
            release.wait(2)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    profile = ProviderProfile("local", "Local", f"http://127.0.0.1:{server.server_port}/v1", "embed", "KEY")
    provider = OpenAICompatibleProvider(profile, "secret")
    request_errors = []
    close_errors = []
    request_thread = Thread(target=lambda: _capture_error(request_errors, lambda: provider.embed_text("query")))
    request_thread.start()
    try:
        assert entered.wait(2)
        close_thread = Thread(target=lambda: _capture_error(close_errors, provider.close))
        close_thread.start()
        close_thread.join(1)
        request_thread.join(1)

        assert not close_thread.is_alive()
        assert not request_thread.is_alive()
        assert close_errors == []
        assert request_errors and isinstance(request_errors[0], InterruptedError)
    finally:
        release.set()
        request_thread.join(3)
        if "close_thread" in locals():
            close_thread.join(3)
        server.shutdown()
        server.server_close()


def _capture_error(errors, action):
    try:
        action()
    except Exception as error:  # the assertion checks the exact cancellation type
        errors.append(error)


def test_a_missing_key_is_rejected_up_front():
    with pytest.raises(ProviderError, match="не задан API-ключ"):
        OpenAICompatibleProvider(PROFILE, "")


def test_oversized_pages_are_refused_without_a_request():
    provider = build(lambda request: httpx.Response(200, json={"data": []}))
    try:
        with pytest.raises(ProviderError, match="больше 20 МБ"):
            provider.embed_pdf_page(b"x" * (21 * 1024 * 1024), "huge.pdf")
    finally:
        provider.close()


def test_oversized_image_is_refused_before_vision_request():
    vision = VisionProfile("v", "Vision", "https://vision.invalid/v1", "vision-1", "VKEY")
    provider = OpenAICompatibleProvider(PROFILE, "secret", vision_profile=vision, vision_api_key="vision-secret")
    provider._runner.run(provider._client.aclose())
    provider._runner.run(provider._vision_client.aclose())
    called = []
    transport = httpx.MockTransport(lambda request: called.append(request) or httpx.Response(200, json={}))
    provider._client = httpx.AsyncClient(transport=transport, base_url=provider.base_url)
    provider._vision_client = httpx.AsyncClient(transport=transport, base_url=vision.base_url)
    try:
        with pytest.raises(ProviderError, match="больше 20 МБ"):
            provider.transcribe_image(b"x" * (21 * 1024 * 1024), "huge.png")
        assert called == []
    finally:
        provider.close()


def test_transcription_repetition_is_bounded():
    cleaned = OpenAICompatibleProvider._clean_transcription("строка\n" * 50)
    assert cleaned.count("строка") == 3  # vision loops are collapsed


def test_transcription_is_length_capped():
    cleaned = OpenAICompatibleProvider._clean_transcription("\n".join(f"строка {n}" for n in range(20000)))
    assert len(cleaned) <= 20000


def test_empty_transcription_is_an_error():
    with pytest.raises(ProviderError, match="пустую транскрипцию"):
        OpenAICompatibleProvider._clean_transcription("   \n\n ")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_provider_rejects_non_finite_embedding_values(bad):
    with pytest.raises(ProviderError, match="конечные числа"):
        OpenAICompatibleProvider._vector([1.0, bad])


@pytest.mark.parametrize(
    "value",
    ["http://example.invalid/v1", "ftp://example.invalid", "https://user:pw@example.invalid", "not-a-url"],
)
def test_unsafe_base_urls_are_rejected(value):
    with pytest.raises(ValueError):
        normalize_base_url(value)


@pytest.mark.parametrize("value", ["http://localhost:8080/v1", "http://127.0.0.1:1234/v1"])
def test_loopback_may_use_plain_http(value):
    assert normalize_base_url(value) == value


def test_trailing_slash_is_normalised():
    assert normalize_base_url("https://example.invalid/v1/") == "https://example.invalid/v1"
