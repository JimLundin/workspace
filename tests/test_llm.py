"""The AI endpoint client: settings, transcription, chat (plain or with tools).
Against a local fake endpoint; runs anywhere."""

import json
from typing import cast

import tests.fake_endpoint
from assistant.llm import (
    AgentClass,
    Failure,
    Missing,
    Models,
    Reply,
    Settings,
    ToolCall,
    assistant_message,
    chat,
    settings_from,
    system_message,
    tool_result,
    tool_spec,
    transcribe,
    user_message,
    wav,
)
from tests.fake_endpoint import fake_endpoint
from winapi.pcm import RATE

ENV = {"OPENAI_BASE_URL": "https://ai.example/v1/", "OPENAI_API_KEY": "k"}


def settings(url: str, vocabulary: str = "", language: str = "") -> Settings:
    return Settings(url, "secret", "gpt-4o-transcribe", vocabulary, language, models=Models(small="chat-model"))


def body_json(raw: bytes) -> dict[str, object]:
    data: object = json.loads(raw)
    assert isinstance(data, dict)
    return {str(k): v for k, v in cast("dict[object, object]", data).items()}


# ---- settings --------------------------------------------------------------------------


def test_settings_need_the_endpoint_and_key() -> None:
    assert settings_from({}) == Missing(("OPENAI_BASE_URL", "OPENAI_API_KEY"))
    assert settings_from({"OPENAI_BASE_URL": "https://ai.example/v1"}) == Missing(("OPENAI_API_KEY",))


def test_settings_defaults() -> None:
    # Defect: a role defaults to the wrong workload size or model mapping.
    result = settings_from(ENV)
    assert isinstance(result, Settings)
    assert result == Settings("https://ai.example/v1", "k", "gpt-4o-transcribe", "", "")
    assert result.agent_reasoning_effort == "low"
    assert result.models == Models("gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-astra")


def test_settings_overrides() -> None:
    # Defect: independently configured roles or shared model IDs are ignored.
    env = {
        **ENV,
        "WORKSPACE_TRANSCRIBE_MODEL": "whisper-1",
        "WORKSPACE_CHAT_CLASS": "medium",
        "WORKSPACE_AGENT_CLASS": "large",
        "WORKSPACE_NOTIFICATION_SCREEN_CLASS": "large",
        "WORKSPACE_NOTIFICATION_RESEARCH_CLASS": "extra_large",
        "WORKSPACE_PERSONAL_WORK_CLASS": "small",
        "WORKSPACE_MODEL_SMALL": "extractor",
        "WORKSPACE_MODEL_MEDIUM": "fast",
        "WORKSPACE_MODEL_LARGE": "smart",
        "WORKSPACE_MODEL_EXTRA_LARGE": "deep",
        "WORKSPACE_AGENT_REASONING_EFFORT": "high",
        "WORKSPACE_VOCABULARY": "Miryoku, Colemak",
        "WORKSPACE_LANGUAGE": "sv",
    }
    assert settings_from(env) == Settings(
        "https://ai.example/v1",
        "k",
        "whisper-1",
        "Miryoku, Colemak",
        "sv",
        chat_class=AgentClass.MEDIUM,
        agent_class=AgentClass.LARGE,
        notification_screen_class=AgentClass.LARGE,
        notification_research_class=AgentClass.EXTRA_LARGE,
        personal_work_class=AgentClass.SMALL,
        agent_reasoning_effort="high",
        models=Models("extractor", "fast", "smart", "deep"),
    )


def test_unknown_role_sizes_are_rejected_at_configuration_entry() -> None:
    # Defect: a misspelled role silently selects another, potentially costly size.
    for role in ("CHAT", "AGENT", "NOTIFICATION_SCREEN", "NOTIFICATION_RESEARCH", "PERSONAL_WORK"):
        try:
            settings_from({**ENV, f"WORKSPACE_{role}_CLASS": "huge"})
        except ValueError:
            pass
        else:
            raise AssertionError(f"The unknown {role} size was accepted.")


def test_empty_model_overrides_are_rejected_at_configuration_entry() -> None:
    # Defect: an empty model ID reaches a delegated provider request instead of
    # being rejected where Workspace reads its external configuration.
    for agent_class in ("SMALL", "MEDIUM", "LARGE", "EXTRA_LARGE"):
        try:
            settings_from({**ENV, f"WORKSPACE_MODEL_{agent_class}": "  "})
        except ValueError as error:
            assert str(error) == "Model IDs must not be empty."
        else:
            raise AssertionError(f"The empty {agent_class} model override was accepted.")


# ---- transcription ---------------------------------------------------------------------


def test_truncated_success_and_error_responses_are_retriable_failures() -> None:
    with fake_endpoint() as endpoint:
        for status in (200, 503):
            endpoint.replies = [tests.fake_endpoint.Reply(b'{"text":"incomplete', status=status, content_length=1000)]
            result = transcribe(settings(endpoint.url), wav(bytes(RATE * 2), RATE))
            assert isinstance(result, Failure)
            assert "connection dropped" in result.message if status == 200 else "HTTP 503" in result.message


def test_transcribe_posts_the_audio_and_returns_the_text() -> None:
    with fake_endpoint() as endpoint:
        audio = wav(bytes(2 * RATE), RATE)
        assert transcribe(settings(endpoint.url), audio) == "hello there"
        r = endpoint.last
        assert r.path == "/v1/audio/transcriptions"
        assert r.authorization == "Bearer secret"
        assert r.content_type.startswith("multipart/form-data; boundary=")
        assert b'name="model"\r\n\r\ngpt-4o-transcribe\r\n' in r.body
        assert b'name="response_format"\r\n\r\njson\r\n' in r.body
        assert b'filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n' + audio + b"\r\n" in r.body
        assert b'name="prompt"' not in r.body
        assert b'name="language"' not in r.body


def test_transcribe_sends_vocabulary_and_language_when_set() -> None:
    with fake_endpoint() as endpoint:
        transcribe(settings(endpoint.url, vocabulary="Miryoku, Colemak", language="sv"), wav(b"", RATE))
        assert b'name="prompt"\r\n\r\nMiryoku, Colemak\r\n' in endpoint.last.body
        assert b'name="language"\r\n\r\nsv\r\n' in endpoint.last.body


def test_failures_carry_the_servers_message() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [tests.fake_endpoint.Reply(b'{"error": {"message": "Invalid session key", "type": "auth"}}', status=401)]
        assert transcribe(settings(endpoint.url), wav(b"", RATE)) == Failure("HTTP 401: Invalid session key")


def test_failures_for_replies_that_arent_what_was_asked() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [tests.fake_endpoint.Reply(b"<html>proxy login</html>")]
        assert transcribe(settings(endpoint.url), wav(b"", RATE)) == Failure("unexpected reply: <html>proxy login</html>")


def test_failures_for_an_unreachable_endpoint() -> None:
    result = transcribe(settings("http://127.0.0.1:9/v1"), wav(b"", RATE), timeout_s=2)
    assert isinstance(result, Failure)
    assert result.message.startswith("can't reach 127.0.0.1:9")


# ---- chat ------------------------------------------------------------------------------

ANSWER = b'{"choices": [{"message": {"role": "assistant", "content": "Hej!"}}]}'


def test_chat_sends_messages_and_returns_the_answer() -> None:
    # Defect: chat ignores its independently selected size or sends an invalid
    # message contract to the configured endpoint.
    with fake_endpoint() as endpoint:
        endpoint.replies = [tests.fake_endpoint.Reply(ANSWER), tests.fake_endpoint.Reply(ANSWER)]
        for chat_class, model_id in ((AgentClass.SMALL, "chat-model"), (AgentClass.MEDIUM, "selected-model")):
            configured = Settings(
                endpoint.url, "secret", "transcribe", "", "", chat_class=chat_class, models=Models(small="chat-model", medium="selected-model")
            )
            reply = chat(configured, [system_message("Be brief."), user_message("Say hi")])
            assert reply == Reply("Hej!", ())
            assert endpoint.last.path == "/v1/chat/completions"
            body = body_json(endpoint.last.body)
            assert body["model"] == model_id
            assert body["messages"] == [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Say hi"}]
        assert "tools" not in body


def test_chat_can_use_another_model() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [tests.fake_endpoint.Reply(ANSWER)]
        chat(settings(endpoint.url), [user_message("hi")], model="agent-model")
        assert body_json(endpoint.last.body)["model"] == "agent-model"


def test_chat_with_tools_returns_tool_calls() -> None:
    call = '{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\\"path\\": \\"a.txt\\"}"}}'
    answer = f'{{"choices": [{{"message": {{"role": "assistant", "content": null, "tool_calls": [{call}]}}}}]}}'.encode()
    spec = tool_spec("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
    with fake_endpoint() as endpoint:
        endpoint.replies = [tests.fake_endpoint.Reply(answer)]
        reply = chat(settings(endpoint.url), [user_message("read a.txt")], tools=[spec])
        assert reply == Reply("", (ToolCall("call_1", "read_file", '{"path": "a.txt"}'),))
        expected: object = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
                },
            }
        ]
        assert body_json(endpoint.last.body)["tools"] == expected


def test_tool_calls_and_results_go_back_to_the_model() -> None:
    call = ToolCall("call_1", "read_file", '{"path": "a.txt"}')
    with fake_endpoint() as endpoint:
        endpoint.replies = [tests.fake_endpoint.Reply(ANSWER)]
        chat(settings(endpoint.url), [assistant_message("", (call,)), tool_result("call_1", "file contents")])
        expected: object = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
        ]
        assert body_json(endpoint.last.body)["messages"] == expected
