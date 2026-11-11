# Glossary

**Journal**: a SQLite file one owner keeps durably, such as a meeting
recording's `session.sqlite3` (`assistant/journal.py`).

**Activity**: something running that the bar shows beside or in its island: a
quick **job** such as transcription (`contracts/status.py`), or a meeting
recording. See [the island bar](docs/toolbar-design.md).

**Panel**: what the bar's status capsule expands into when one of its readings
is pressed: the calendar under the clock, the networks under Wi-Fi, Workspace's
own controls under its glyph (`desktop_ui/island_menu.py`, `Panel`). See [the
island bar](docs/toolbar-design.md#the-panels).

**Dictation marker**: the small capsule beside the caret of the app you dictate
into, which shows listening, transcribing, typing and the outcome. It stays
where the capture started; the bar shows dictation only when there is nothing
to mark (`desktop_ui/dictation_marker.py`, `winapi/caret.py`).

**Component**: one of the programs `launch.py` starts (the gateway, the layout
and the desktop), declared in `settings/programs.py`.
