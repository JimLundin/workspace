# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 4.2 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 98,942 | 23,786 |
| **support** | 63,056 | 13,930 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 54,301 | 12,406 |
| tests | 46,170 | 9,845 |
| winapi | 21,186 | 5,567 |
| scripts | 12,814 | 2,985 |
| keyboard | 8,723 | 1,891 |
| assistant | 6,969 | 1,676 |
| typings | 4,072 | 1,100 |
| desktop | 2,509 | 1,096 |
| contracts | 1,723 | 409 |
| (top level) | 1,517 | 330 |
| settings | 1,041 | 170 |
| gateway | 973 | 241 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 8,187 | 1,721 |
| `tests/test_keyboard_hook.py` | 4,006 | 744 |
| `keyboard/win.py` | 3,764 | 862 |
| `tests/test_engine.py` | 3,464 | 651 |
| `tests/test_meetings.py` | 3,106 | 680 |
| `desktop_ui/island_menu.py` | 3,023 | 677 |
| `desktop_ui/island_layout.py` | 2,790 | 619 |
| `assistant/meetings.py` | 2,717 | 658 |
| `desktop_ui/keymap_views.py` | 2,672 | 573 |
| `desktop_ui/desktop_bar.py` | 2,595 | 665 |
| `desktop_ui/desktop_app.py` | 2,563 | 618 |
| `desktop_ui/bar_events.py` | 2,524 | 615 |
| `desktop_ui/desktop_control.py` | 2,287 | 593 |
| `desktop_ui/application_observer.py` | 2,228 | 546 |
| `keyboard/engine.py` | 2,218 | 472 |
| `desktop_ui/shell_surface.py` | 2,101 | 424 |
| `desktop_ui/island_model.py` | 2,001 | 475 |
| `tests/test_island_menu.py` | 1,943 | 508 |
| `winapi/composition.py` | 1,845 | 445 |
| `winapi/audio.py` | 1,826 | 452 |
| `tests/test_meeting_audio.py` | 1,795 | 312 |
| `tests/test_features.py` | 1,781 | 351 |
| `desktop_ui/marker_window.py` | 1,772 | 366 |
| `tests/test_island_layout.py` | 1,755 | 323 |
| `winapi/recording.py` | 1,696 | 432 |
