# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.8 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 85,255 | 14,580 |
| **support** | 55,835 | 8,343 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 45,179 | 7,819 |
| tests | 40,707 | 5,966 |
| winapi | 19,646 | 3,299 |
| scripts | 11,519 | 1,671 |
| keyboard | 9,184 | 1,482 |
| assistant | 6,982 | 1,198 |
| typings | 3,609 | 706 |
| contracts | 1,612 | 306 |
| (top level) | 1,556 | 282 |
| gateway | 1,065 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 6,585 | 918 |
| `desktop_ui/island_surface.py` | 5,765 | 709 |
| `tests/test_keyboard_hook.py` | 3,964 | 479 |
| `keyboard/win.py` | 3,632 | 595 |
| `tests/test_engine.py` | 3,447 | 564 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `desktop_ui/keymap_views.py` | 2,835 | 467 |
| `assistant/meetings.py` | 2,737 | 456 |
| `desktop_ui/desktop_bar.py` | 2,383 | 425 |
| `keyboard/engine.py` | 2,146 | 338 |
| `desktop_ui/island_menu.py` | 2,121 | 362 |
| `desktop_ui/application_observer.py` | 2,098 | 360 |
| `desktop_ui/desktop_control.py` | 2,002 | 428 |
| `desktop_ui/desktop_app.py` | 1,966 | 381 |
| `desktop_ui/island_layout.py` | 1,941 | 368 |
| `desktop_ui/bar_events.py` | 1,912 | 400 |
| `desktop_ui/island_model.py` | 1,846 | 318 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `desktop_ui/components/appearance.py` | 1,775 | 391 |
| `desktop_ui/shell_surface.py` | 1,735 | 247 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
