# Glossary

**Journal**: a SQLite file one owner keeps durably, such as a meeting
recording's `session.sqlite3` (`assistant/journal.py`).

**Activity**: something running that the bar shows beside or in its island: a
quick **job** such as transcription (`contracts/status.py`), or a meeting
recording. See [the island bar](docs/toolbar-design.md).

**Component**: one of the programs `launch.py` starts (the gateway, the layout,
the assistant and the desktop), listed in the catalogue in `components.py`.
