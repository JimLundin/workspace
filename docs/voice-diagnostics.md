# Voice diagnostics and recovery

Spacebar/B dictation and N agent requests send captured audio directly to the configured
transcription endpoint. Neither uses the cleanup prompt. Dictation normalizes whitespace
and removes control characters before submitting Unicode input; N queues the
full returned transcript. Clean dictation is a separate tool.

Space is push-to-talk; B toggles dictation; N toggles agent speech. Toggle key
releases do nothing, and Space release cannot stop a capture begun with B.

Each completed use in `%LOCALAPPDATA%\workspace\usage.jsonl` records:

| Field | Meaning |
| --- | --- |
| `capture_id`, `source`, `stop_reason` | Correlate capture start and completion within one assistant process; identify the initiating request and why capture stopped. |
| `phase` | Last phase reached: starting, recording, stopping, transcribing, cleaning, formatting, rewriting, or submitting. |
| `error_type`, `locations` | Exception class and up to eight file/line/function locations, with no exception message or source lines. |
| `input_accepted`, `input_expected` | Native input events accepted/requested when Windows rejects a batch. |
| `held_seconds`, `audio_seconds` | How long the capture ran and the size of the returned PCM in seconds. |
| `transcribe_seconds` | Time spent preparing and requesting transcription, including failed requests. |
| `transcript_characters` | Length of the complete text field returned by the endpoint. Absent when transcription failed. |
| `requested_characters` | Length handed to the text-input or agent-queue operation. Dictation includes its trailing separator space. |
| `submitted_characters` | Length after that operation returned successfully. Absent when submission failed. |
| `submit_seconds` | Time spent submitting the text, including failed submissions. |

These fields store no audio or transcript content. They are measured on the
assistant worker after recording; no sampling work is added to the microphone
or keyboard event loop. Each queued recording owns its own measurements.
Successful Unicode input submission means Windows accepted the events; it is
not a readback proving that the receiving text field displayed every character.

## Recovery

A failed insertion keeps the complete transcript in memory and attempts to put
it on the Windows clipboard before input submission. Use Copy latest transcript
in Workspace controls if the clipboard was busy. Input is never automatically
repeated: a partially accepted batch could otherwise duplicate the text.
Unexpected worker errors report the failed phase instead of only “crashed”; the
next capture remains available. Microphone start/stop failures clear capture
ownership and record their phase. Disabling the layout finishes the current
capture; shutdown discards active audio. A window-message watchdog finishes a
capture at the existing five-minute microphone limit if its release or toggle
was lost. This does not shorten the buffer or sample inside the audio loop.

Keyboard exceptions disable remapping immediately and pass the physical event
through. Cleanup clears engine state and attempts every tracked release even
when another fails. The native output owner also tracks temporarily added chord
modifiers and rejected output attempts. Timer ticks retry only Workspace-owned
key-ups, at most five times. Recovery targets Workspace output instead of resetting
all native modifiers.
A failed assistant request also disables the layout instead of silently losing
its voice control message. Recovery diagnostics are written outside keyboard
callbacks as `layout/input_recovery` in the same usage log. They include the
failure location, cleanup failure count and pending release count, with no
physical key identities or transcript text. Re-enabling stays blocked while
pending key-ups are rejected. If Windows refuses input, switch away from the
elevated application before re-enabling the layout with § or Workspace controls. If the assistant is unavailable,
restart Workspace before re-enabling tools.

The live keyboard disables cyclic GC. Its pending diagnostics retain only
immutable scalar evidence, never exception or traceback objects. Counts prove
input acceptance, not delivery to an application's text box. Native end-to-end
checks read back mapped typing and Unicode text from disposable text windows and
a console; they require an unlocked Windows desktop.

## Investigation on 2026-10-22

The reported symptom is a whole trailing sentence disappearing, sometimes after
only the first sentence. Existing timing metadata from 227 captures showed no
held/audio discrepancy above 0.24 seconds; this does not exclude silence or
device dropouts within the buffer.

Generated English speech was sent through the configured `gpt-4o-transcribe`
endpoint without microphone capture or playback:

| Fixture | Audio duration | Result |
| --- | --- | --- |
| Two sentences, short pause | 7.64 seconds | All 16 words returned. |
| Same sentences, 2.5-second pause | 12.14 seconds | All 16 words returned. |
| Six sentences with pauses | 36.69 seconds | All 75 words returned. |

The two-sentence fixture included “Everything afterwards just kind of
disappears.” Its ending was present in both responses. The intermittent loss
has not been reproduced, so these results do not establish an audio, model, or
delivery cause. No speculative transcription or input-delivery change is made.

On another occurrence, compare that use's `transcript_characters` and
`submitted_characters` with the visible text. A short endpoint response locates
the loss before submission; complete counts with missing visible text direct
the investigation to input delivery. Audio durations alone cannot distinguish
missing microphone signal from a transcription omission.

The documented model output limit is 2,000 tokens, which does not explain a
short two-sentence cutoff on its own. Sources:
[model limits](https://developers.openai.com/api/docs/models/gpt-4o-transcribe)
and [speech-to-text guide](https://developers.openai.com/api/docs/guides/speech-to-text).

## Investigation on 2026-10-27

The user reports delay both after pressing Space and after releasing it, plus
periodic waveform stalls. A real-microphone baseline reproduced a 160.46 ms
`Microphone.level()` call. Its nonblocking lock acquisition does not make the
driver's `waveInGetPosition` call nonblocking. Calling it from the toolbar's
50 ms Qt timer therefore blocks waveform frames and other UI work.

`assistant.audio_meter.AudioMeter` now owns that native read on one worker.
Qt reads only the latest immutable observation through a short handoff lock;
native reads never hold that lock. Capture revisions reject a result from a
stopped or restarted recording, and observations expire after 250 ms instead
of keeping old speech visible when the driver stalls. Closing wakes the worker
and bounds the UI's shutdown wait. The native microphone buffer and its sample
loop are unchanged.

A paired real-microphone run, with GC enabled and three captures per mode,
measured these UI reads:

| Measurement | Direct native read | Cached observation |
| --- | --- | --- |
| Median | 0.397 ms | 0.013 ms |
| Maximum in this paired run | 4.356 ms | 0.100 ms |

The earlier 160.46 ms stall was intermittent; this later direct round did not
reproduce it. A native toolbar regression also blocks the reader deliberately
for 250 ms and verifies that sampling returns within 25 ms, that native reading
occurs off Qt's thread, and that the resulting sample reaches the waveform.

Opening the real microphone took 536.08 ms at construction, before a recording.
Per-recording start calls took 0.52–4.24 ms across the baseline and paired runs.
The first baseline capture's PCM was 158 ms shorter than its held duration;
the paired run's held/PCM gaps were between -6 and 12 ms. Those observations do
not prove instantaneous signal capture on every device. Moving the meter off
Qt removes the measured UI stall; it does not establish that every reported
startup delay has the same cause.

The configured transcription endpoint was also tested directly with generated
English speech, without microphone capture or speaker playback:

| Fixture | Trials | Result |
| --- | --- | --- |
| Short opening sentence, 2.5-second pause, longer final sentence; 8.94 s | 3 | Final sentence present each time; opening sentence missing twice. |
| Longer opening sentence, 2.5-second pause, short final sentence; 8.94 s | 3 | Final sentence present each time. |
| Five sentences, 1 / 2.5 / 5-second pause before the final sentence; 23.43–27.43 s | 9 | Final sentence present each time. |

The opening-sentence omission proves that this endpoint can omit a whole
sentence from these fixtures. It has not reproduced the reported trailing
sentence loss. Requests took 1.24–3.40 seconds, excluding any application queue
delay; file transcription still begins after Space is released. No model,
prompt, capture-padding or input-delivery change is justified by these results.

On the next trailing-sentence omission, compare **Copy latest transcript** with
the receiving field before another recording replaces it. A complete copied
transcript with an incomplete field identifies an insertion problem. If the
copied transcript also lacks the sentence, distinguishing microphone loss from
endpoint omission requires the corresponding audio. Timing and character
counts alone cannot make that distinction. These probes retained no user
audio or transcript content.
