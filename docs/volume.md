# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 81,418 | 13,594 |
| **support** | 53,852 | 7,979 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 41,804 | 6,960 |
| tests | 38,730 | 5,608 |
| winapi | 19,634 | 3,301 |
| scripts | 11,513 | 1,665 |
| keyboard | 8,730 | 1,352 |
| assistant | 6,982 | 1,198 |
| typings | 3,609 | 706 |
| contracts | 1,612 | 306 |
| (top level) | 1,560 | 283 |
| gateway | 1,065 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 6,585 | 918 |
| `desktop_ui/island_surface.py` | 5,322 | 674 |
| `tests/test_keyboard_hook.py` | 3,961 | 477 |
| `keyboard/win.py` | 3,638 | 595 |
| `tests/test_engine.py` | 3,437 | 569 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,737 | 456 |
| `desktop_ui/desktop_bar.py` | 2,333 | 421 |
| `desktop_ui/keymap_views.py` | 2,330 | 330 |
| `keyboard/engine.py` | 2,145 | 337 |
| `desktop_ui/application_observer.py` | 2,093 | 346 |
| `desktop_ui/island_menu.py` | 2,050 | 339 |
| `desktop_ui/desktop_control.py` | 2,006 | 427 |
| `desktop_ui/desktop_app.py` | 1,956 | 381 |
| `desktop_ui/bar_events.py` | 1,866 | 390 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `winapi/composition.py` | 1,765 | 308 |
| `desktop_ui/island_layout.py` | 1,718 | 269 |
| `desktop_ui/shell_surface.py` | 1,705 | 244 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,628 | 199 |
| `assistant/meeting_store.py` | 1,596 | 252 |
