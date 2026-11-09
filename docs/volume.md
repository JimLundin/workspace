# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 82,688 | 13,846 |
| **support** | 56,035 | 8,269 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 41,976 | 7,033 |
| tests | 41,355 | 5,934 |
| winapi | 19,605 | 3,292 |
| scripts | 10,681 | 1,583 |
| keyboard | 9,758 | 1,524 |
| assistant | 6,982 | 1,198 |
| typings | 3,999 | 752 |
| (top level) | 1,660 | 300 |
| contracts | 1,609 | 305 |
| gateway | 1,067 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 5,330 | 768 |
| `desktop_ui/island_surface.py` | 5,322 | 674 |
| `tests/test_engine.py` | 4,395 | 734 |
| `keyboard/win.py` | 4,088 | 664 |
| `tests/test_keyboard_hook.py` | 4,075 | 511 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `keyboard/engine.py` | 2,770 | 426 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/desktop_bar.py` | 2,365 | 430 |
| `desktop_ui/keymap_views.py` | 2,335 | 333 |
| `desktop_ui/island_menu.py` | 2,097 | 350 |
| `keyboard/layout.py` | 2,096 | 285 |
| `desktop_ui/desktop_control.py` | 2,061 | 440 |
| `desktop_ui/application_observer.py` | 2,005 | 336 |
| `desktop_ui/desktop_app.py` | 1,989 | 392 |
| `desktop_ui/bar_events.py` | 1,892 | 398 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `winapi/composition.py` | 1,765 | 308 |
| `desktop_ui/island_layout.py` | 1,718 | 269 |
| `desktop_ui/shell_surface.py` | 1,705 | 244 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,669 | 201 |
