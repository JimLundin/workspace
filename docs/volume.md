# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.9 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 83,611 | 14,193 |
| **support** | 55,826 | 8,317 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 43,389 | 7,407 |
| tests | 40,661 | 5,930 |
| winapi | 19,744 | 3,317 |
| scripts | 11,556 | 1,681 |
| keyboard | 9,228 | 1,488 |
| assistant | 6,982 | 1,198 |
| typings | 3,609 | 706 |
| contracts | 1,612 | 306 |
| (top level) | 1,560 | 283 |
| gateway | 1,065 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 6,622 | 928 |
| `desktop_ui/island_surface.py` | 5,711 | 704 |
| `tests/test_keyboard_hook.py` | 3,963 | 478 |
| `keyboard/win.py` | 3,632 | 595 |
| `tests/test_engine.py` | 3,447 | 564 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,737 | 456 |
| `desktop_ui/desktop_bar.py` | 2,394 | 426 |
| `desktop_ui/keymap_views.py` | 2,329 | 333 |
| `keyboard/engine.py` | 2,152 | 338 |
| `desktop_ui/application_observer.py` | 2,098 | 360 |
| `desktop_ui/island_menu.py` | 2,050 | 339 |
| `desktop_ui/desktop_control.py` | 2,004 | 428 |
| `desktop_ui/desktop_app.py` | 1,957 | 381 |
| `desktop_ui/island_layout.py` | 1,941 | 368 |
| `desktop_ui/bar_events.py` | 1,905 | 401 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `desktop_ui/shell_surface.py` | 1,735 | 247 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,673 | 214 |
| `assistant/meeting_store.py` | 1,596 | 252 |
