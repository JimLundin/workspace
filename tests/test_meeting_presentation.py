"""How a recorded meeting reads in its canvas detail: offsets, the transcript and the speaker caveat."""

from pathlib import Path

from assistant.meeting_store import MeetingStore
from contracts.meeting_presentation import meeting_text

SPEECH = b"\x01\x00" * 16_000


def test_a_meeting_reads_as_its_conversation_with_offsets_and_the_speaker_caveat(tmp_path: Path) -> None:
    # Defect: a meeting detail shows only its preview, loses the captured-audio
    # offsets, or reads as if speakers were identified.
    meeting = MeetingStore.create(tmp_path / "meetings", "both", "Planning event")
    meeting.append(SPEECH)
    meeting.finish_capture()
    batch = meeting.batch()
    assert batch is not None
    meeting.complete(batch, "Supplier approval SA-42 is ready for Friday.")
    text = meeting_text(meeting.conversation())
    assert "00:00:00 - 00:00:01" in text and "SA-42" in text
    assert "Speakers have not been identified" in text and "Transcript complete" in text
