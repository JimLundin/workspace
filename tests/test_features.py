"""What each tool and app key does, against a fake desktop and a fake endpoint."""

import json
from collections.abc import Callable, Mapping
from typing import cast
lazy from dataclasses import replace

from assistant.features import Assistant, pick_window, switcher_windows
from assistant.geometry import Shot
from assistant.llm import MAX_SECONDS, Missing, Settings
from automation.json_value import Json
from desktop_ui.icons import State
from desktop_ui.island_model import Job
from protocol import App, Tool
from tests.fake_endpoint import FakeEndpoint, Reply, fake_endpoint, sse
from usage import Detail
from winapi.pcm import RATE
from winapi.shapes import InputRejectedError, Rect, Window

SPEECH = bytes(2 * RATE)  # a second of silence: long enough to send


def test_window_list_keeps_hidden_managed_windows_and_excludes_cloaked_shell_hosts() -> None:
    current = Window(1, "Editor", "editor.exe", minimized=False)
    hidden = Window(2, "Other workspace", "terminal.exe", minimized=False)
    shell = Window(3, "Settings background host", "systemsettings.exe", minimized=False)
    visible = Window(4, "Settings", "applicationframehost.exe", minimized=False)
    assert switcher_windows((current, hidden, shell, visible), frozenset({1, 4}), frozenset({1, 2})) == (current, hidden, visible)


def dumps(value: Json) -> str:
    return json.dumps(value)


def said(text: str) -> Reply:
    return Reply(dumps({"text": text}).encode())


def answered(text: str) -> Reply:
    return Reply(dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode())


def streamed(*pieces: str) -> Reply:
    return sse(*(dumps({"choices": [{"delta": {"content": p}}]}) for p in pieces))


class FakeAnswer:
    __slots__ = ("desktop",)

    def __init__(self, desktop: FakeDesktop) -> None:
        self.desktop = desktop

    def write(self, text: str) -> None:
        self.desktop.log.append(f"write {text}")

    def finish(self) -> None:
        self.desktop.log.append("finish")

    def fail(self, message: str) -> None:
        self.desktop.log.append(f"fail {message}")


class FakeDesktop:
    __slots__ = ("follow_up", "input_error", "jobs", "log", "prompts", "recording_error", "region", "selection", "speech", "windows_open")

    def __init__(self, *, input_error: OSError | None = None, recording_error: OSError | None = None) -> None:
        self.input_error, self.recording_error = input_error, recording_error
        self.log: list[str] = []
        self.jobs: list[Job | None] = []
        self.speech = SPEECH
        self.selection: str | None = None
        self.prompts: list[str | None] = []
        self.region: Rect | None = Rect(0, 0, 100, 50)
        self.windows_open: list[Window] = []
        self.follow_up: Callable[[str], None] | None = None

    def start_listening(self) -> str | None:
        self.log.append("listen")
        return None

    def stop_listening(self) -> bytes:
        if self.recording_error is not None:
            raise self.recording_error
        self.log.append("stop listening")
        return self.speech

    def copy_selection(self) -> str | None:
        return self.selection

    def paste(self, text: str) -> None:
        self.log.append(f"paste {text}")

    def type_text(self, text: str) -> None:
        if self.input_error is not None:
            raise self.input_error
        self.log.append(f"type {text!r}")

    def set_clipboard(self, text: str) -> None:
        self.log.append(f"clipboard {text}")

    def choose_region(self) -> Rect | None:
        return self.region

    def capture(self, area: Rect, longest: int) -> tuple[bytes, Shot]:
        return b"\x89PNG", Shot(area, area.width, area.height)

    def prompt(self, title: str) -> str | None:
        self.log.append(f"prompt {title}")
        return self.prompts.pop(0) if self.prompts else None

    def answer(self, title: str, follow_up: Callable[[str], None]) -> FakeAnswer:
        self.log.append(f"answer window {title}")
        self.follow_up = follow_up
        return FakeAnswer(self)

    def show_state(self, state: State) -> None:
        self.log.append(f"state {state.name}")

    def busy(self, job: Job | None) -> None:
        self.jobs.append(job)

    def notify(self, title: str, text: str) -> None:
        self.log.append(f"notify {title}: {text}")

    def problem(self, message: str) -> None:
        self.log.append(f"problem {message}")

    def windows(self) -> list[Window]:
        return self.windows_open

    def foreground(self) -> int:
        return self.windows_open[0].handle if self.windows_open else 0

    def focus(self, handle: int) -> bool:
        self.log.append(f"focus {handle}")
        return True

    def launch(self, command: str) -> None:
        self.log.append(f"launch {command}")

    def arrange(self, tool: Tool, *, target: int | None) -> None:
        self.log.append(f"arrange {tool.name.lower()} {target}")


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

    def balance_windows(self) -> None:
        self.record("BALANCE")


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
        settings = Settings(endpoint.url, "k", "transcribe", "chat", "agent", "", "")
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


def test_quick_jobs_announce_what_they_are_and_end_when_finished() -> None:
    # Defects: transcription and a quick request read the same on the bar, or a job never ends.
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("hej")]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE)
        assert rig.desktop.jobs[-2:] == [Job.TRANSCRIBING, None]
        rig.desktop.prompts = ["Is it Friday?"]
        endpoint.replies = [streamed("Ja")]
        rig.press(Tool.ASK)
        assert Job.ANSWERING in rig.desktop.jobs and rig.desktop.jobs[-1] is None


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


def test_dictate_clean_types_the_tidied_text() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("um so like the the meeting"), answered("So, the meeting.")]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE_CLEAN)
        assert rig.take()[-1] == "type 'So, the meeting. '"
        messages = cast("list[dict[str, object]]", rig.sent()["messages"])
        assert [m["role"] for m in messages] == ["system", "user"]
        assert messages[1]["content"] == "um so like the the meeting"


def test_dictate_command_types_one_line_and_never_enter() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("list big files"), answered("```powershell\nGet-ChildItem |\n Sort-Object Length\n```")]
        rig = Rig(endpoint)
        rig.hold(Tool.DICTATE_COMMAND)
        assert rig.take()[-1] == "type 'Get-ChildItem | Sort-Object Length'"


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
        rig.assistant.handle(Tool.DICTATE_CLEAN, down=True)
        rig.assistant.handle(Tool.DICTATE_CLEAN, down=False)
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


# ---- rewriting -------------------------------------------------------------------------


def test_rewrite_keys_replace_the_selection() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [answered('"Hello, world."')]
        rig = Rig(endpoint)
        rig.desktop.selection = "helo wrld"
        rig.press(Tool.FIX)
        assert rig.take() == ["paste Hello, world."]
        messages = rig.sent()["messages"]
        assert isinstance(messages, list)
        assert cast("list[dict[str, object]]", messages)[1] == {"role": "user", "content": "helo wrld"}
        assert "spelling" in str(cast("list[dict[str, object]]", messages)[0]["content"])


def test_rewrite_without_a_selection_says_so() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.press(Tool.TRANSLATE)
        assert rig.take() == ["problem Select some text first."]
        assert endpoint.received == []


def test_rewrite_by_voice_follows_the_spoken_instruction() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("make it sound less annoyed"), answered("Could you take a look?")]
        rig = Rig(endpoint)
        rig.desktop.selection = "Fix this NOW."
        rig.hold(Tool.REWRITE_VOICE)
        assert rig.take()[-1] == "paste Could you take a look?"
        assert "make it sound less annoyed" in json.dumps(rig.sent())


# ---- asking ----------------------------------------------------------------------------


def test_ask_streams_the_answer_and_takes_follow_ups() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [streamed("Ja", "!"), streamed("Nej.")]
        rig = Rig(endpoint)
        rig.desktop.prompts = ["Is it Friday?"]
        rig.press(Tool.ASK)
        assert rig.take() == ["prompt Ask", "answer window Is it Friday?", "write Ja", "write !", "finish"]
        follow_up = rig.desktop.follow_up
        assert follow_up is not None
        follow_up("Tomorrow?")
        assert rig.take() == ["write Nej.", "finish"]
        roles = [m["role"] for m in cast("list[dict[str, object]]", rig.sent()["messages"])]
        assert roles == ["system", "user", "assistant", "user"]


def test_ask_includes_the_selection() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [streamed("ok")]
        rig = Rig(endpoint)
        rig.desktop.prompts = ["What does this mean?"]
        rig.desktop.selection = "ERROR 0x80070005"
        rig.press(Tool.ASK)
        assert "ERROR 0x80070005" in json.dumps(rig.sent())


def test_cancelled_prompts_do_nothing() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.press(Tool.ASK)
        assert rig.take() == ["prompt Ask"]
        assert dict(rig.used)["ask"]["cancelled"] is True


# ---- the screen ------------------------------------------------------------------------


def test_screen_text_copies_the_text_in_the_area() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [answered("Line one\nLine two")]
        rig = Rig(endpoint)
        rig.press(Tool.SCREEN_TEXT)
        assert rig.take() == ["clipboard Line one\nLine two", "notify Text copied: Line one Line two"]
        assert "data:image/png;base64," in json.dumps(rig.sent())


def test_screen_ask_answers_about_the_area() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [streamed("It's a chart.")]
        rig = Rig(endpoint)
        rig.desktop.prompts = [""]  # Enter on an empty box: the default question
        rig.press(Tool.SCREEN_ASK)
        assert rig.take()[-2:] == ["write It's a chart.", "finish"]
        assert "data:image/png;base64," in json.dumps(rig.sent())


def test_screen_tools_do_nothing_when_no_area_is_chosen() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.desktop.region = None
        rig.press(Tool.SCREEN_TEXT)
        assert rig.take() == []


# ---- the agent -------------------------------------------------------------------------


def test_voice_sends_a_task_and_typed_opens_the_agent_session() -> None:
    with fake_endpoint() as endpoint:
        endpoint.replies = [said("tidy my downloads")]
        rig = Rig(endpoint)
        rig.hold(Tool.AGENT_VOICE)
        rig.press(Tool.AGENT_TYPED)
        rig.press(Tool.STOP)
        assert rig.agent == ["tidy my downloads", "SHOW", "STOP"]
        assert not any(action.startswith("prompt ") for action in rig.desktop.log)


# ---- apps and windows ------------------------------------------------------------------

TERMINAL = App("terminal", "windowsterminal.exe", "wt.exe")


def window(handle: int, exe: str = "windowsterminal.exe", title: str = "PowerShell") -> Window:
    return Window(handle, title, exe, minimized=False)


def test_app_key_focuses_the_app() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.desktop.windows_open = [window(1, "msedge.exe"), window(2)]
        rig.press(TERMINAL)
        assert rig.take() == ["focus 2"]
        assert rig.ok("app:terminal")


def test_app_key_starts_the_app_if_it_isnt_running() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        rig.press(TERMINAL)
        assert rig.take() == ["launch wt.exe"]


def test_pressing_again_goes_through_the_apps_windows() -> None:
    windows = [window(1), window(2, "msedge.exe"), window(3), window(4)]  # front to back
    assert pick_window(windows, TERMINAL, foreground=1) == 4  # the one furthest back: repeated presses visit all
    assert pick_window(windows, TERMINAL, foreground=2) == 1
    assert pick_window([window(1)], TERMINAL, foreground=1) == 1


def test_app_title_narrows_the_windows() -> None:
    teams = App("teams", "msedge.exe", "msedge.exe", title="Teams")
    windows = [window(1, "msedge.exe", "News"), window(2, "msedge.exe", "Chat | Microsoft Teams")]
    assert pick_window(windows, teams, foreground=0) == 2


def test_window_keys_arrange_the_window() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint)
        for tool in (Tool.SNAP_LEFT, Tool.MAXIMIZE, Tool.NEXT_MONITOR):
            rig.press(tool)
        assert rig.take() == ["arrange snap_left None", "arrange maximize None", "arrange next_monitor None"]


def test_menu_window_tool_keeps_its_target_and_records_timed_usage() -> None:
    # Defects: worker dispatch drops the menu's captured window, bypasses usage,
    # or fails to return the desktop indicator to idle after arranging it.
    with fake_endpoint() as endpoint:
        jobs: list[Callable[[], None]] = []
        rig = Rig(endpoint, submit=jobs.append)
        rig.assistant.handle(Tool.TILE_FLOAT, down=True, target=42)
        assert len(jobs) == 1 and not rig.take() and not rig.used
        jobs[0]()
        assert rig.desktop.log[-1] == "state READY"
        assert rig.take() == ["arrange tile_float 42"]
        assert tuple(feature for feature, _ in rig.used) == ("tile_float",) and rig.ok("tile_float")
        assert rig.desktop.jobs == [None]


def test_desktop_controls_run_on_press_without_worker_submission() -> None:
    # Detect UI actions firing on release, entering the worker, or resetting recording state through timed().
    with fake_endpoint() as endpoint:
        # This test owns the bounded queue of submitted effects and never executes them.
        jobs: list[Callable[[], None]] = []
        rig = Rig(endpoint, submit=jobs.append)
        for tool in (Tool.OPEN_INBOX, Tool.WINDOW_SWITCHER, Tool.MEETING_TOGGLE, Tool.TILE_BALANCE):
            rig.press(tool)
        assert rig.agent == ["INBOX", "SWITCHER", "MEETING", "BALANCE"]
        assert not jobs and not rig.used and not rig.desktop.jobs and not rig.take()


# ---- without the AI settings -----------------------------------------------------------


def test_without_ai_settings_ai_tools_say_what_is_missing_and_the_rest_works() -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, missing=Missing(("OPENAI_API_KEY",)))
        rig.hold(Tool.DICTATE)
        rig.press(Tool.FIX)
        rig.press(TERMINAL)
        rig.press(Tool.SNAP_LEFT)
        rig.press(Tool.OPEN_INBOX)
        rig.press(Tool.MEETING_TOGGLE)
        problem = "problem Set OPENAI_API_KEY to use the AI tools (see the README)."
        assert rig.take() == [problem, problem, "launch wt.exe", "arrange snap_left None"]
        assert rig.agent == ["INBOX", "MEETING"]
        assert endpoint.received == []


def test_tiling_commands_use_worker_without_ai_credentials() -> None:
    with fake_endpoint() as endpoint:
        jobs: list[Callable[[], None]] = []
        rig = Rig(endpoint, missing=Missing(("OPENAI_API_KEY",)), submit=jobs.append)
        for tool in (Tool.TILE_FOCUS_LEFT, Tool.TILE_FLOAT, Tool.TILE_NEXT_WORKSPACE, Tool.TILE_PAUSE):
            rig.press(tool)
        assert not rig.take() and len(jobs) == 4
        for job in jobs:
            job()
        assert rig.take() == [
            "arrange tile_focus_left None",
            "arrange tile_float None",
            "arrange tile_next_workspace None",
            "arrange tile_pause None",
        ]
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
