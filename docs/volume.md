# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 92,083 | 15,299 |
| **support** | 66,853 | 9,908 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 48,272 | 8,020 |
| tests | 45,829 | 6,619 |
| winapi | 22,173 | 3,689 |
| scripts | 18,743 | 2,837 |
| miryoku | 10,110 | 1,571 |
| assistant | 7,044 | 1,202 |
| typings | 2,281 | 452 |
| (top level) | 1,774 | 318 |
| contracts | 1,612 | 305 |
| gateway | 1,067 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 5,817 | 714 |
| `scripts/architecture.py` | 5,334 | 768 |
| `tests/test_engine.py` | 4,498 | 750 |
| `miryoku/win.py` | 4,234 | 687 |
| `tests/test_keyboard_hook.py` | 4,082 | 515 |
| `scripts/check.py` | 3,787 | 516 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `desktop_ui/desktop_bar.py` | 3,043 | 575 |
| `miryoku/engine.py` | 2,873 | 436 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/keymap_views.py` | 2,364 | 322 |
| `desktop_ui/island_menu.py` | 2,313 | 349 |
| `desktop_ui/bar_events.py` | 2,251 | 451 |
| `miryoku/layout.py` | 2,196 | 299 |
| `tests/test_features.py` | 2,057 | 304 |
| `desktop_ui/application_observer.py` | 2,035 | 339 |
| `desktop_ui/shell_surface.py` | 2,017 | 291 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `winapi/recording.py` | 1,789 | 265 |
| `winapi/composition.py` | 1,768 | 308 |
| `desktop_ui/desktop_app.py` | 1,712 | 345 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/desktop_control.py` | 1,688 | 372 |
| `desktop_ui/window_layout.py` | 1,678 | 201 |
