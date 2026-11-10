"""The AI connection: a loopback pass-through to the provider, against a local fake
provider; runs anywhere."""

import threading
from collections.abc import Iterator
from pathlib import Path

import httpx

from assistant.llm import Failure, Settings, transcribe, wav
from contracts.endpoint import Endpoint, publish
from gateway.proxy import Gateway
from gateway.upstream import Unconfigured, Upstream
from tests.fake_endpoint import FakeEndpoint, Received, fake_endpoint
from winapi.pcm import RATE

TOKEN = "boot-token"


def through(tmp_path: Path, gateway: Gateway) -> Settings:
    """Assistant settings whose requests go through `gateway`'s published endpoint."""
    path = tmp_path / "endpoint-gateway"
    publish(path, Endpoint(gateway.port, TOKEN))
    return Settings("https://provider.invalid/v1", "unused", "gpt-4o-transcribe", "", gateway=path)


def test_requests_reach_the_provider_with_its_key_not_the_gateway_token(tmp_path: Path) -> None:
    # Defect: the gateway forwards the client's token (or no key) to the provider,
    # loses the path, or the assistant still calls the provider directly.
    with fake_endpoint() as provider:
        gateway = Gateway.listen(Upstream(provider.url, "provider-key"), TOKEN)
        gateway.start()
        try:
            assert transcribe(through(tmp_path, gateway), wav(bytes(2 * RATE), RATE)) == "hello there"
        finally:
            gateway.close()
        assert provider.last.path == "/v1/audio/transcriptions"
        assert provider.last.authorization == "Bearer provider-key"


def test_a_wrong_token_is_refused_before_the_provider_is_called(tmp_path: Path) -> None:
    # Defect: any local program reaching the port spends the provider key.
    with fake_endpoint() as provider:
        gateway = Gateway.listen(Upstream(provider.url, "provider-key"), "another-boot")
        gateway.start()
        try:
            result = transcribe(through(tmp_path, gateway), wav(b"", RATE))
        finally:
            gateway.close()
        assert isinstance(result, Failure)
        assert result.message.startswith("HTTP 401")
        assert provider.received == []


def test_an_unconfigured_gateway_names_the_missing_variables(tmp_path: Path) -> None:
    # Defect: a gateway started without credentials crashes (and the keeper gives
    # up on it) or answers with an error that doesn't say what to set.
    gateway = Gateway.listen(Unconfigured(("OPENAI_API_KEY",)), TOKEN)
    gateway.start()
    try:
        result = transcribe(through(tmp_path, gateway), wav(b"", RATE))
    finally:
        gateway.close()
    assert isinstance(result, Failure)
    assert "OPENAI_API_KEY" in result.message


def test_streamed_replies_are_relayed_as_they_arrive() -> None:
    # Defect: the gateway buffers a streamed reply until it ends, so the agent's
    # live text and Stop wait for the whole answer.
    first_read = threading.Event()

    def stream(_: Received) -> Iterator[bytes]:
        yield b"data: first\n\n"
        first_read.wait(timeout=5)
        yield b"data: [DONE]\n\n"

    with fake_endpoint() as provider:
        provider.stream = stream
        gateway = Gateway.listen(Upstream(provider.url, "provider-key"), TOKEN)
        gateway.start()
        try:
            url = f"http://127.0.0.1:{gateway.port}/v1/responses"
            with httpx.stream("POST", url, headers={"Authorization": f"Bearer {TOKEN}"}, content=b"{}") as reply:
                lines = reply.iter_lines()
                assert next(lines) == "data: first"
                arrived_early = not first_read.is_set()
                first_read.set()
                assert "data: [DONE]" in list(lines)
        finally:
            gateway.close()
    assert arrived_early


def test_a_restarted_gateway_takes_back_its_port() -> None:
    # Defect: a gateway restart moves the port, so clients built before it fail.
    first = Gateway.listen(Unconfigured(()), TOKEN)
    port = first.port
    first.close()
    second = Gateway.listen(Unconfigured(()), TOKEN, port=port)
    try:
        assert second.port == port
    finally:
        second.close()


def test_settings_without_a_published_gateway_call_the_provider(tmp_path: Path) -> None:
    # Defect: before the gateway first listens, the assistant's requests go nowhere.
    with fake_endpoint() as provider:
        settings = Settings(provider.url, "provider-key", "gpt-4o-transcribe", "", gateway=tmp_path / "missing")
        assert transcribe(settings, wav(b"", RATE)) == "hello there"
        assert_called(provider)


def assert_called(provider: FakeEndpoint) -> None:
    assert provider.last.authorization == "Bearer provider-key"
