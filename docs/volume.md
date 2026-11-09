# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 83,604 | 13,942 |
| **support** | 56,525 | 8,325 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 42,341 | 7,059 |
| tests | 41,832 | 5,988 |
| winapi | 19,611 | 3,292 |
| scripts | 10,694 | 1,585 |
| miryoku | 10,110 | 1,571 |
| assistant | 7,044 | 1,202 |
| typings | 3,999 | 752 |
| (top level) | 1,788 | 319 |
| contracts | 1,612 | 305 |
| gateway | 1,067 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 5,333 | 768 |
| `desktop_ui/island_surface.py` | 5,325 | 674 |
| `tests/test_engine.py` | 4,498 | 750 |
| `miryoku/win.py` | 4,234 | 687 |
| `tests/test_keyboard_hook.py` | 4,075 | 511 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `miryoku/engine.py` | 2,873 | 436 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/desktop_bar.py` | 2,374 | 432 |
| `desktop_ui/keymap_views.py` | 2,344 | 333 |
| `miryoku/layout.py` | 2,196 | 299 |
| `desktop_ui/island_menu.py` | 2,100 | 350 |
| `desktop_ui/desktop_control.py` | 2,070 | 440 |
| `tests/test_features.py` | 2,057 | 304 |
| `desktop_ui/application_observer.py` | 2,019 | 336 |
| `desktop_ui/desktop_app.py` | 2,010 | 392 |
| `desktop_ui/bar_events.py` | 1,892 | 398 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `winapi/composition.py` | 1,768 | 308 |
| `desktop_ui/island_layout.py` | 1,718 | 269 |
| `desktop_ui/shell_surface.py` | 1,705 | 244 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,678 | 201 |
