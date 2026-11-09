# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.9 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 81,707 | 13,753 |
| **support** | 54,642 | 8,055 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 41,595 | 6,983 |
| tests | 39,477 | 5,668 |
| winapi | 19,634 | 3,301 |
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
| `desktop_ui/island_surface.py` | 5,322 | 674 |
| `tests/test_keyboard_hook.py` | 3,963 | 478 |
| `keyboard/win.py` | 3,632 | 595 |
| `tests/test_engine.py` | 3,447 | 564 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,737 | 456 |
| `desktop_ui/desktop_bar.py` | 2,333 | 421 |
| `desktop_ui/keymap_views.py` | 2,314 | 333 |
| `keyboard/engine.py` | 2,152 | 338 |
| `desktop_ui/application_observer.py` | 2,093 | 346 |
| `desktop_ui/island_menu.py` | 2,050 | 339 |
| `desktop_ui/desktop_control.py` | 2,004 | 428 |
| `desktop_ui/desktop_app.py` | 1,956 | 381 |
| `desktop_ui/bar_events.py` | 1,866 | 390 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `winapi/composition.py` | 1,765 | 308 |
| `desktop_ui/shell_surface.py` | 1,705 | 244 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/island_layout.py` | 1,635 | 261 |
| `desktop_ui/window_layout.py` | 1,628 | 199 |
| `assistant/meeting_store.py` | 1,596 | 252 |
