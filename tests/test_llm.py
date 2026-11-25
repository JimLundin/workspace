from assistant.llm import (
    Failure,
    Missing,
    Settings,
    settings_from,
    transcribe,
    wav,
)
from tests.fake_endpoint import Reply, fake_endpoint
from winapi.pcm import RATE

ENV = {"OPENAI_BASE_URL": "https://ai.example/v1/", "OPENAI_API_KEY": "k"}


def settings(url: str, vocabulary: str = "") -> Settings:
    return Settings(url, "secret", "gpt-4o-transcribe", vocabulary)


def test_settings_need_the_endpoint_and_key() -> None:
    assert settings_from({}) == Missing(("OPENAI_BASE_URL", "OPENAI_API_KEY"))
    assert settings_from(
        {"OPENAI_BASE_URL": "https://ai.example/v1"}
    ) == Missing(("OPENAI_API_KEY",))


def test_settings_take_their_overrides() -> None:
    env = {
        **ENV,
        "WORKSPACE_TRANSCRIBE_MODEL": "whisper-1",
        "WORKSPACE_VOCABULARY": "Miryoku, Colemak",
    }
    assert settings_from(env) == Settings(
        "https://ai.example/v1", "k", "whisper-1", "Miryoku, Colemak"
    )


def test_transcribe_posts_the_audio_and_returns_the_text() -> None:
    with fake_endpoint() as endpoint:
        audio = wav(bytes(2 * RATE), RATE)
        assert transcribe(settings(endpoint.url), audio) == "hello there"
        r = endpoint.last
        assert r.path == "/v1/audio/transcriptions"
        assert r.authorization == "Bearer secret"
        assert b'name="model"\r\n\r\ngpt-4o-transcribe\r\n' in r.body
        assert b'name="response_format"\r\n\r\njson\r\n' in r.body
        assert (
            b'filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'
            + audio
            + b"\r\n"
            in r.body
        )
        assert b'name="prompt"' not in r.body


def test_transcribe_sends_vocabulary_and_context_when_set() -> None:
    with fake_endpoint() as endpoint:
        transcribe(
            settings(endpoint.url, vocabulary="Miryoku, Colemak"),
            wav(b"", RATE),
            context="Earlier words.",
        )
        assert (
            b'name="prompt"\r\n\r\nMiryoku, Colemak\nEarlier words.\r\n'
            in endpoint.last.body
        )


def test_failures_carry_the_servers_message() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [
            Reply(
                b'{"error": {"message": "Invalid session key", "type": "auth"}}',
                status=401,
            )
        ]
        assert transcribe(settings(endpoint.url), wav(b"", RATE)) == Failure(
            "HTTP 401: Invalid session key"
        )


def test_failures_without_a_server_message_carry_the_status() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [
            Reply(b"upstream down", status=502, content_type="text/plain")
        ]
        assert transcribe(settings(endpoint.url), wav(b"", RATE)) == Failure(
            "HTTP 502: Bad Gateway"
        )


def test_failures_for_replies_that_arent_what_was_asked() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [Reply(b"<html>proxy login</html>")]
        assert transcribe(settings(endpoint.url), wav(b"", RATE)) == Failure(
            "unexpected reply: <html>proxy login</html>"
        )


def test_truncated_replies_are_retriable_failures() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [Reply(b'{"text":"incomplete', content_length=1000)]
        result = transcribe(settings(endpoint.url), wav(b"", RATE))
        assert isinstance(result, Failure)
        assert result.message.startswith(
            f"can't reach {endpoint.url.removeprefix('http://').removesuffix('/v1')}: peer closed connection"
        )


def test_failures_for_an_unreachable_endpoint() -> None:
    result = transcribe(
        settings("http://127.0.0.1:9/v1"), wav(b"", RATE), timeout_s=0.2
    )
    assert isinstance(result, Failure)
    assert result.message.startswith("can't reach 127.0.0.1:9: ")
