# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 4.2 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 100,943 | 24,116 |
| **support** | 64,418 | 14,155 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 56,440 | 12,805 |
| tests | 47,473 | 10,068 |
| winapi | 21,456 | 5,598 |
| scripts | 12,816 | 2,986 |
| keyboard | 8,731 | 1,878 |
| assistant | 6,743 | 1,611 |
| typings | 4,129 | 1,101 |
| desktop | 2,555 | 1,126 |
| (top level) | 1,517 | 328 |
| contracts | 1,513 | 361 |
| settings | 1,011 | 167 |
| gateway | 977 | 242 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 8,545 | 1,781 |
| `tests/test_keyboard_hook.py` | 4,006 | 736 |
| `keyboard/win.py` | 3,764 | 854 |
| `tests/test_engine.py` | 3,464 | 641 |
| `desktop_ui/island_menu.py` | 3,226 | 728 |
| `tests/test_meetings.py` | 3,106 | 680 |
| `desktop_ui/island_layout.py` | 2,847 | 637 |
| `desktop_ui/bar_events.py` | 2,718 | 659 |
| `assistant/meetings.py` | 2,717 | 658 |
| `desktop_ui/keymap_views.py` | 2,672 | 573 |
| `desktop_ui/desktop_bar.py` | 2,620 | 667 |
| `desktop_ui/desktop_app.py` | 2,577 | 620 |
| `desktop_ui/desktop_control.py` | 2,305 | 594 |
| `desktop_ui/marker_window.py` | 2,248 | 456 |
| `desktop_ui/application_observer.py` | 2,228 | 536 |
| `keyboard/engine.py` | 2,224 | 472 |
| `tests/test_island_menu.py` | 2,127 | 550 |
| `desktop_ui/shell_surface.py` | 2,108 | 423 |
| `desktop_ui/island_model.py` | 2,001 | 473 |
| `winapi/composition.py` | 1,860 | 441 |
| `winapi/audio.py` | 1,805 | 443 |
| `tests/test_meeting_audio.py` | 1,795 | 304 |
| `tests/test_features.py` | 1,781 | 349 |
| `tests/test_island_layout.py` | 1,755 | 323 |
| `winapi/recording.py` | 1,696 | 430 |
