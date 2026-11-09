# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 81,503 | 13,675 |
| **support** | 54,718 | 8,080 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 41,687 | 6,980 |
| tests | 40,045 | 5,747 |
| winapi | 19,605 | 3,292 |
| scripts | 10,674 | 1,581 |
| keyboard | 8,949 | 1,422 |
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
| `tests/test_engine.py` | 3,889 | 650 |
| `tests/test_keyboard_hook.py` | 3,884 | 490 |
| `keyboard/win.py` | 3,882 | 634 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/keymap_views.py` | 2,335 | 333 |
| `desktop_ui/desktop_bar.py` | 2,333 | 421 |
| `keyboard/engine.py` | 2,292 | 372 |
| `keyboard/layout.py` | 2,085 | 283 |
| `desktop_ui/island_menu.py` | 2,050 | 339 |
| `desktop_ui/desktop_control.py` | 2,023 | 433 |
| `desktop_ui/application_observer.py` | 2,005 | 336 |
| `desktop_ui/desktop_app.py` | 1,967 | 387 |
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
