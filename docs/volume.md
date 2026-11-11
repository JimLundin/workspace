# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.9 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 91,845 | 15,681 |
| **support** | 59,202 | 8,772 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 48,302 | 8,082 |
| tests | 43,447 | 6,300 |
| winapi | 20,309 | 3,405 |
| scripts | 11,988 | 1,734 |
| keyboard | 8,723 | 1,462 |
| assistant | 6,969 | 1,197 |
| typings | 3,767 | 738 |
| desktop | 2,288 | 613 |
| contracts | 1,723 | 330 |
| (top level) | 1,517 | 280 |
| settings | 1,041 | 147 |
| gateway | 973 | 165 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 7,027 | 975 |
| `desktop_ui/island_surface.py` | 6,243 | 763 |
| `tests/test_keyboard_hook.py` | 4,006 | 479 |
| `keyboard/win.py` | 3,764 | 623 |
| `tests/test_engine.py` | 3,464 | 568 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,717 | 454 |
| `desktop_ui/keymap_views.py` | 2,672 | 411 |
| `desktop_ui/desktop_bar.py` | 2,422 | 443 |
| `desktop_ui/desktop_app.py` | 2,347 | 428 |
| `desktop_ui/application_observer.py` | 2,235 | 382 |
| `desktop_ui/desktop_control.py` | 2,228 | 467 |
| `keyboard/engine.py` | 2,218 | 349 |
| `desktop_ui/bar_events.py` | 2,108 | 430 |
| `desktop_ui/shell_surface.py` | 2,101 | 285 |
| `desktop_ui/island_menu.py` | 2,054 | 326 |
| `desktop_ui/island_layout.py` | 1,933 | 356 |
| `desktop_ui/island_model.py` | 1,898 | 314 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,781 | 277 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `assistant/meeting_store.py` | 1,596 | 252 |
