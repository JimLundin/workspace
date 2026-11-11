# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.9 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 96,948 | 16,440 |
| **support** | 61,228 | 9,032 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 52,606 | 8,694 |
| tests | 45,325 | 6,525 |
| winapi | 20,943 | 3,502 |
| scripts | 11,988 | 1,734 |
| keyboard | 8,723 | 1,462 |
| assistant | 6,969 | 1,197 |
| typings | 3,915 | 773 |
| desktop | 2,453 | 663 |
| contracts | 1,723 | 330 |
| (top level) | 1,517 | 280 |
| settings | 1,041 | 147 |
| gateway | 973 | 165 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 7,996 | 955 |
| `scripts/architecture.py` | 7,027 | 975 |
| `tests/test_keyboard_hook.py` | 4,006 | 479 |
| `keyboard/win.py` | 3,764 | 623 |
| `tests/test_engine.py` | 3,464 | 568 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `desktop_ui/island_menu.py` | 2,973 | 504 |
| `assistant/meetings.py` | 2,717 | 454 |
| `desktop_ui/keymap_views.py` | 2,672 | 411 |
| `desktop_ui/desktop_bar.py` | 2,581 | 465 |
| `desktop_ui/bar_events.py` | 2,500 | 498 |
| `desktop_ui/island_layout.py` | 2,418 | 414 |
| `desktop_ui/desktop_app.py` | 2,347 | 428 |
| `desktop_ui/application_observer.py` | 2,235 | 382 |
| `desktop_ui/desktop_control.py` | 2,228 | 467 |
| `keyboard/engine.py` | 2,218 | 349 |
| `desktop_ui/shell_surface.py` | 2,101 | 285 |
| `desktop_ui/island_model.py` | 1,934 | 319 |
| `tests/test_island_menu.py` | 1,919 | 254 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,781 | 277 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
