"""What each tool and app key does, against a fake desktop and a fake endpoint."""

import json
from collections.abc import Callable, Mapping
from typing import cast
lazy from dataclasses import replace

from assistant.features import Assistant
from assistant.llm import MAX_SECONDS, Missing, Settings
from contracts.json_value import Json
from desktop_ui.icons import State
from desktop_ui.island_model import Job
from desktop_ui.navigation import AppKey, Direction, JumpDesktop, Order, Placing, Source, SpatialFocus, Zoom
from protocol import App, Installed, Tool
from tests.fake_endpoint import FakeEndpoint, Reply, fake_endpoint
from usage import Detail
from winapi.pcm import RATE
from winapi.shapes import InputRejectedError

SPEECH = bytes(2 * RATE)  # a second of silence: long enough to send


def dumps(value: Json) -> str:
    return json.dumps(value)


def said(text: str) -> Reply:
    return Reply(dumps({"text": text}).encode())


def answered(text: str) -> Reply:
    return Reply(dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode())


class FakeDesktop:
    __slots__ = ("input_error", "jobs", "log", "orders", "recording_error", "speech")

    def __init__(self, *, input_error: OSError | None = None, recording_error: OSError | None = None) -> None:
        self.input_error, self.recording_error = input_error, recording_error
        self.log: list[str] = []
        self.jobs: list[Job | None] = []
        self.speech = SPEECH
        self.orders: list[Order] = []

    def start_listening(self) -> str | None:
        self.log.append("listen")
        return None

    def stop_listening(self) -> bytes:
        if self.recording_error is not None:
            raise self.recording_error
        self.log.append("stop listening")
        return self.speech

    def type_text(self, text: str) -> None:
        if self.input_error is not None:
            raise self.input_error
        self.log.append(f"type {text!r}")

    def set_clipboard(self, text: str) -> None:
        self.log.append(f"clipboard {text}")

    def show_state(self, state: State) -> None:
        self.log.append(f"state {state.name}")

    def busy(self, job: Job | None) -> None:
        self.jobs.append(job)

    def notify(self, title: str, text: str) -> None:
        self.log.append(f"notify {title}: {text}")

    def problem(self, message: str) -> None:
        self.log.append(f"problem {message}")

    def navigate(self, order: Order) -> None:
        self.orders.append(order)
        self.log.append("navigate")


class FakeControls:
    """Publish control effects to the fixture's action recorder."""

    __slots__ = ("record",)

    def __init__(self, record: Callable[[str], None]) -> None:
        self.record: Callable[[str], None] = record

    def run_agent(self, text: str) -> None:
        self.record(text)

    def show_agent(self) -> None:
        self.record("SHOW")

    def stop_agent(self) -> None:
        self.record("STOP")

    def open_inbox(self) -> None:
        self.record("INBOX")

    def switch_windows(self) -> None:
        self.record("SWITCHER")

    def toggle_meeting(self) -> None:
        self.record("MEETING")


def run_immediately(job: Callable[[], None]) -> None:
    job()


class Rig:
    """An assistant wired to fakes: what it did is in `desktop.log`, `used` and `agent`."""

    __slots__ = ("agent", "assistant", "desktop", "endpoint", "used")

    # The fixture composes endpoint, credential gate, desktop effects and worker scheduling.
    def __init__(
        self,
        endpoint: FakeEndpoint,
        missing: Missing | None = None,
        *,
        desktop: FakeDesktop | None = None,
        submit: Callable[[Callable[[], None]], None] = run_immediately,
    ) -> None:
        self.endpoint = endpoint
        self.desktop = desktop if desktop is not None else FakeDesktop()
        self.used: list[tuple[str, Mapping[str, Detail]]] = []
        self.agent: list[str] = []
        settings = Settings(endpoint.url, "k", "transcribe", "")
        self.assistant = Assistant(
            self.desktop,
            settings,
            record=lambda feature, details: self.used.append((feature, details)),
            submit=submit,
            controls=FakeControls(self.agent.append),
            missing=missing,
        )

    def press(self, request: Tool | App) -> None:
        self.assistant.handle(request, down=True)
        self.assistant.handle(request, down=False)

    def hold(self, tool: Tool) -> None:
        """Down, speak, up."""
        self.assistant.handle(tool, down=True)
        self.assistant.handle(tool, down=False)

    def take(self) -> list[str]:
        log, self.desktop.log = self.desktop.log, []
        return [entry for entry in log if not entry.startswith("state ")]

    def sent(self, index: int = -1) -> dict[str, object]:
        data: object = json.loads(self.endpoint.received[index].body)
        assert isinstance(data, dict)
        return {str(k): v for k, v in cast("dict[object, object]", data).items()}

    def ok(self, feature: str) -> bool:
        details = dict(self.used)[feature]
        return details.get("ok") is True


# ---- dictation -------------------------------------------------------------------------


def test_dictate_types_what_was_said() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("hej på dig\n")]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE)
        assert rig.take() == ["listen", "stop listening", "clipboard hej på dig\n", "type 'hej på dig '"]
        assert rig.ok("dictate")


def test_transcription_shows_on_the_bar_and_ends_when_finished() -> None:
    # Defect: the bar never shows transcription, or the job never ends.
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("hej")]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE)
        assert rig.desktop.jobs[-2:] == [Job.TRANSCRIBING, None]


def test_clipboard_failure_keeps_a_recoverable_transcript_and_still_types() -> None:
    class BusyClipboard(FakeDesktop):
        __slots__ = ("refusing",)

        def __init__(self) -> None:
            super().__init__()
            self.refusing = True

        def set_clipboard(self, text: str) -> None:
            if self.refusing:
                raise OSError("Busy")
            super().set_clipboard(text)

    desktop = BusyClipboard()
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("The complete transcript.")]
        rig = Rig(endpoint, desktop=desktop)
        rig.hold(Tool.DICTATE)
        assert rig.assistant.latest_transcription == "The complete transcript."
        assert "type 'The complete transcript. '" in desktop.log
        desktop.refusing = False
        rig.assistant.handle(Tool.COPY_TRANSCRIPT, down=True)
        assert desktop.log[-1] == "clipboard The complete transcript."


def test_agent_capture_toggle_ignores_releases_and_stops_on_the_second_press() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("Please do this.")]
        rig = Rig(endpoint)
        rig.assistant.handle(Tool.AGENT_VOICE_TOGGLE, down=True)
        rig.assistant.handle(Tool.AGENT_VOICE_TOGGLE, down=False)
        assert rig.take() == ["listen"]
        rig.assistant.handle(Tool.AGENT_VOICE_TOGGLE, down=True)
        rig.assistant.handle(Tool.AGENT_VOICE_TOGGLE, down=False)
        assert rig.assistant.listening is None and rig.agent == ["Please do this."]


def test_space_release_does_not_stop_dictation_started_with_the_toggle() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("Complete capture")]
        rig = Rig(endpoint)
        rig.press(Tool.DICTATE_TOGGLE)
        rig.hold(Tool.DICTATE)
        assert rig.assistant.listening is Tool.DICTATE
        assert not endpoint.received
        rig.press(Tool.DICTATE_TOGGLE)
        assert rig.assistant.listening is None


def test_unexpected_input_error_recovers_and_identifies_the_failed_phase() -> None:
    class BrokenInput(FakeDesktop):
        def type_text(self, text: str) -> None:
            raise RuntimeError("Sensitive transcript must not enter diagnostics")

    with fake_endpoint() as endpoint:
        endpoint.replies = [said("A recoverable transcript")]
        rig = Rig(endpoint, desktop=BrokenInput())
        rig.hold(Tool.DICTATE)
        assert rig.assistant.latest_transcription == "A recoverable transcript"
        assert rig.assistant.listening is None
        details = dict(rig.used)["dictate"]
        assert details["phase"] == "submitting" and details["error_type"] == "RuntimeError" and not details["ok"]
        assert "Sensitive transcript" not in str(rig.used)
        assert "clipboard" in rig.take()[-1].lower()


def test_partial_input_is_logged_without_retrying_or_losing_the_transcript() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("Full transcript")]
        desktop = FakeDesktop(input_error=InputRejectedError(3, 32))
        rig = Rig(endpoint, desktop=desktop)
        rig.hold(Tool.DICTATE)
        details = dict(rig.used)["dictate"]
        assert details["input_accepted"] == 3 and details["input_expected"] == 32
        assert details["phase"] == "submitting" and not details["ok"]
        assert "submitted_characters" not in details
        assert rig.assistant.latest_transcription == "Full transcript"
        desktop.input_error = None
        endpoint.replies = [said("Next dictation")]
        rig.hold(Tool.DICTATE)
        assert rig.ok("dictate") and rig.assistant.latest_transcription == "Next dictation"


def test_lost_voice_release_finishes_at_the_existing_microphone_limit() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("Full limited recording")]
        rig = Rig(endpoint)
        rig.assistant.handle(Tool.DICTATE, down=True)
        capture = rig.assistant.capture
        assert capture is not None
        rig.assistant.expire_capture(capture.started + MAX_SECONDS - 0.01)
        assert rig.assistant.capture is capture and not endpoint.received
        rig.assistant.expire_capture(capture.started + MAX_SECONDS)
        assert rig.assistant.listening is None
        assert dict(rig.used)["dictate"]["stop_reason"] == "limit"
        rig.assistant.handle(Tool.DICTATE, down=False)
        assert len(endpoint.received) == 1


def test_shutdown_discards_active_voice_without_submitting_a_task() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.press(Tool.AGENT_VOICE_TOGGLE)
        rig.assistant.stop_capture(discard=True, reason="shutdown")
        assert rig.assistant.listening is None and rig.agent == [] and not endpoint.received
        assert rig.take() == ["listen", "stop listening"]


def test_unexpected_microphone_stop_error_clears_capture_and_allows_another_recording() -> None:
    class BrokenStop(FakeDesktop):
        def __init__(self) -> None:
            super().__init__()
            self.broken = True

        def stop_listening(self) -> bytes:
            if self.broken:
                raise RuntimeError("Device crashed")
            return super().stop_listening()

    with fake_endpoint() as endpoint:
        desktop = BrokenStop()
        rig = Rig(endpoint, desktop=desktop)
        rig.hold(Tool.DICTATE)
        assert rig.assistant.capture is None and not endpoint.received
        details = dict(rig.used)["dictate"]
        assert details["phase"] == "stopping" and details["error_type"] == "RuntimeError"
        desktop.broken = False
        endpoint.replies = [said("Recovered")]
        rig.hold(Tool.DICTATE)
        assert rig.ok("dictate")


def test_voice_diagnostics_keep_the_full_ending_and_record_only_lengths() -> None:
    transcript = "It gets neatly cut off after like the first sentence.\nEverything afterwards just kind of disappears."
    for tool in (Tool.DICTATE, Tool.AGENT_VOICE):
        with fake_endpoint() as endpoint:
            endpoint.replies = [said(transcript)]
            rig = Rig(endpoint)
            rig.hold(tool)
            details = dict(rig.used)[tool.name.lower()]
            expected = transcript.replace("\n", " ") + " " if tool is Tool.DICTATE else transcript
            assert details["transcript_characters"] == len(transcript)
            assert details["requested_characters"] == details["submitted_characters"] == len(expected)
            for name in ("transcribe_seconds", "submit_seconds"):
                duration = details[name]
                assert isinstance(duration, float) and duration >= 0
            assert "Everything afterwards" not in str(rig.used)
            assert len(endpoint.received) == 1  # B and N do not send a cleanup request.
            if tool is Tool.DICTATE:
                assert rig.take()[-1] == f"type {expected!r}"
            else:
                assert rig.agent == [expected]


def test_voice_diagnostics_distinguish_a_failed_request_from_failed_input() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [Reply(b'{"error":{"message":"Unavailable"}}', status=503)]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE)
        details = dict(rig.used)["dictate"]
        assert "transcribe_seconds" in details and "transcript_characters" not in details
        assert "requested_characters" not in details and not details["ok"]

        transcript = "The first sentence. The missing ending."
        endpoint.replies = [said(transcript)]
        rig = Rig(endpoint, desktop=FakeDesktop(input_error=OSError("Input was not accepted")))
        rig.hold(Tool.DICTATE)
        details = dict(rig.used)["dictate"]
        assert details["transcript_characters"] == len(transcript)
        assert rig.assistant.latest_transcription == transcript
        assert f"clipboard {transcript}" in rig.desktop.log
        assert details["requested_characters"] == len(transcript) + 1
        assert "submit_seconds" in details and "submitted_characters" not in details and not details["ok"]


def test_queued_voice_diagnostics_belong_to_their_own_recording() -> None:
    with fake_endpoint() as endpoint:
        transcripts = ("The first recording. Its ending.", "The second recording is longer. It also keeps its last sentence.")
        endpoint.replies = [said(text) for text in transcripts]
        jobs: list[Callable[[], None]] = []
        rig = Rig(endpoint, submit=jobs.append)
        rig.hold(Tool.DICTATE)
        rig.desktop.speech = SPEECH * 2
        rig.hold(Tool.DICTATE)
        starts = [details["capture_id"] for _, details in rig.used if details["phase"] == "recording"]
        assert starts == [1, 2]
        assert all(feature == "voice_capture" for feature, _ in rig.used)
        for job in jobs:
            job()
        completed = [(feature, details) for feature, details in rig.used if feature == "dictate"]
        for index, (_, details) in enumerate(completed):
            assert details["capture_id"] == index + 1
            assert details["audio_seconds"] == index + 1
            assert details["transcript_characters"] == len(transcripts[index])
            assert details["submitted_characters"] == len(transcripts[index]) + 1


def test_a_tap_of_a_talk_key_sends_nothing() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.desktop.speech = bytes(100)
        rig.hold(Tool.DICTATE)
        assert rig.take() == ["listen", "stop listening"]
        assert endpoint.received == []


def test_a_second_talk_key_while_listening_is_ignored() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("one")]
        rig = Rig(endpoint)
        rig.assistant.handle(Tool.DICTATE, down=True)
        rig.assistant.handle(Tool.AGENT_VOICE, down=True)
        rig.assistant.handle(Tool.AGENT_VOICE, down=False)
        rig.assistant.handle(Tool.DICTATE, down=False)
        assert rig.take() == ["listen", "stop listening", "clipboard one", "type 'one '"]


def test_endpoint_failures_are_reported_and_logged() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [Reply(b'{"error": {"message": "Invalid session key"}}', status=401)]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE)
        assert rig.take()[-1] == "problem HTTP 401: Invalid session key"
        assert dict(rig.used)["dictate"]["ok"] is False


def test_an_incomplete_recording_is_reported_without_sending_a_partial_prompt() -> None:
    for tool in (Tool.DICTATE, Tool.AGENT_VOICE):
        with fake_endpoint() as endpoint:
            rig = Rig(endpoint, desktop=FakeDesktop(recording_error=OSError("The microphone did not finish returning audio.")))
            rig.hold(tool)
            assert endpoint.received == []
            assert rig.agent == []
            assert rig.take()[-1] == "problem The microphone did not finish returning audio."
            assert not rig.ok(tool.name.lower())
            assert rig.assistant.listening is None


def test_the_tray_shows_listening_then_working_then_ready() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("hi")]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE)
        states = [entry for entry in rig.desktop.log if entry.startswith("state ")]
        assert states == ["state LISTENING", "state WORKING", "state READY"]


# ---- the agent -------------------------------------------------------------------------


def test_voice_sends_a_task_and_typed_opens_the_agent_session() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("tidy my downloads")]
        rig = Rig(endpoint)
        rig.hold(Tool.AGENT_VOICE)
        rig.press(Tool.AGENT_TYPED)
        rig.press(Tool.STOP)
        assert rig.agent == ["tidy my downloads", "SHOW", "STOP"]


# ---- apps and windows ------------------------------------------------------------------

TERMINAL = App("terminal", Installed("windowsterminal.exe", "wt.exe"))


def test_app_and_navigation_keys_hand_their_orders_to_the_window_owner() -> None:
    # Defects: an app key no longer reaches the window owner, a desktop key
    # jumps to the wrong desktop, or placement keys are dropped.
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        for request in (TERMINAL, Tool.DESKTOP_2, Tool.FOCUS_UP, Tool.ZOOM, Tool.PLACEMENT_PAUSE):
            rig.press(request)
        assert rig.desktop.orders == [
            AppKey(TERMINAL, Source.KEY),
            JumpDesktop(1, Source.KEY),
            SpatialFocus(Direction.UP, Source.KEY),
            Zoom(Source.KEY),
            Placing.TOGGLE_PAUSE,
        ]
        assert rig.ok("app:terminal")


def test_desktop_controls_run_on_press_without_worker_submission() -> None:
    # Detect UI actions firing on release, entering the worker, or resetting recording state through timed().
    with fake_endpoint() as endpoint:
        # This test owns the bounded queue of submitted effects and never executes them.
        jobs: list[Callable[[], None]] = []
        rig = Rig(endpoint, submit=jobs.append)
        for tool in (Tool.OPEN_INBOX, Tool.WINDOW_SWITCHER, Tool.MEETING_TOGGLE):
            rig.press(tool)
        assert rig.agent == ["INBOX", "SWITCHER", "MEETING"]
        assert not jobs and not rig.used and not rig.desktop.jobs and not rig.take()


# ---- without the AI settings -----------------------------------------------------------


def test_without_ai_settings_ai_tools_say_what_is_missing_and_the_rest_works() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, missing=Missing(("OPENAI_API_KEY",)))
        rig.hold(Tool.DICTATE)
        rig.press(Tool.AGENT_TYPED)
        rig.press(TERMINAL)
        rig.press(Tool.OPEN_INBOX)
        rig.press(Tool.MEETING_TOGGLE)
        problem = "problem Set OPENAI_API_KEY to use the AI tools (see the README)."
        assert rig.take() == [problem, problem, "navigate"]
        assert rig.agent == ["INBOX", "MEETING"]
        assert endpoint.received == []


def test_voice_limit_uses_the_deadline_across_a_float_precision_boundary() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("Full limited recording")]
        rig = Rig(endpoint)
        rig.assistant.handle(Tool.DICTATE, down=True)
        capture = rig.assistant.capture
        assert capture is not None
        started = 2**20 - 100 + 2**-33
        assert (started + MAX_SECONDS) - started < MAX_SECONDS
        rig.assistant.capture = replace(capture, started=started)
        rig.assistant.expire_capture(started + MAX_SECONDS)
        assert rig.assistant.listening is None
        assert dict(rig.used)["dictate"]["stop_reason"] == "limit"
