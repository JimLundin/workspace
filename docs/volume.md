# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 81,373 | 13,649 |
| **support** | 53,615 | 7,928 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 41,812 | 6,987 |
| tests | 38,942 | 5,595 |
| winapi | 19,577 | 3,288 |
| scripts | 10,674 | 1,581 |
| keyboard | 8,722 | 1,393 |
| assistant | 6,982 | 1,198 |
| typings | 3,999 | 752 |
| contracts | 1,609 | 305 |
| (top level) | 1,573 | 284 |
| gateway | 1,067 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 5,330 | 768 |
| `desktop_ui/island_surface.py` | 5,322 | 674 |
| `tests/test_keyboard_hook.py` | 3,899 | 489 |
| `keyboard/win.py` | 3,677 | 611 |
| `tests/test_engine.py` | 3,597 | 597 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/keymap_views.py` | 2,335 | 333 |
| `desktop_ui/desktop_bar.py` | 2,333 | 421 |
| `keyboard/engine.py` | 2,270 | 366 |
| `desktop_ui/application_observer.py` | 2,086 | 343 |
| `keyboard/layout.py` | 2,085 | 283 |
| `desktop_ui/island_menu.py` | 2,050 | 339 |
| `desktop_ui/desktop_control.py` | 2,004 | 427 |
| `desktop_ui/desktop_app.py` | 1,952 | 384 |
| `desktop_ui/bar_events.py` | 1,864 | 390 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `winapi/composition.py` | 1,765 | 308 |
| `desktop_ui/island_layout.py` | 1,718 | 269 |
| `desktop_ui/shell_surface.py` | 1,705 | 244 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,634 | 199 |
