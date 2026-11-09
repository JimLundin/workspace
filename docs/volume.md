# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 82,808 | 13,851 |
| **support** | 56,041 | 8,269 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 42,050 | 7,033 |
| tests | 41,355 | 5,934 |
| winapi | 19,611 | 3,292 |
| scripts | 10,687 | 1,583 |
| keyboard | 9,783 | 1,529 |
| assistant | 6,994 | 1,198 |
| typings | 3,999 | 752 |
| (top level) | 1,660 | 300 |
| contracts | 1,612 | 305 |
| gateway | 1,067 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 5,333 | 768 |
| `desktop_ui/island_surface.py` | 5,325 | 674 |
| `tests/test_engine.py` | 4,395 | 734 |
| `keyboard/win.py` | 4,095 | 669 |
| `tests/test_keyboard_hook.py` | 4,075 | 511 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `keyboard/engine.py` | 2,785 | 426 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/desktop_bar.py` | 2,365 | 430 |
| `desktop_ui/keymap_views.py` | 2,344 | 333 |
| `desktop_ui/island_menu.py` | 2,100 | 350 |
| `keyboard/layout.py` | 2,096 | 285 |
| `desktop_ui/desktop_control.py` | 2,070 | 440 |
| `desktop_ui/application_observer.py` | 2,019 | 336 |
| `desktop_ui/desktop_app.py` | 2,010 | 392 |
| `desktop_ui/bar_events.py` | 1,892 | 398 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `winapi/composition.py` | 1,768 | 308 |
| `desktop_ui/island_layout.py` | 1,718 | 269 |
| `desktop_ui/shell_surface.py` | 1,705 | 244 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,678 | 201 |
