# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.9 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 91,101 | 15,559 |
| **support** | 58,749 | 8,732 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 47,683 | 7,990 |
| tests | 43,004 | 6,261 |
| winapi | 20,278 | 3,399 |
| scripts | 11,988 | 1,734 |
| keyboard | 8,723 | 1,462 |
| assistant | 6,969 | 1,197 |
| typings | 3,757 | 737 |
| desktop | 2,194 | 589 |
| contracts | 1,723 | 330 |
| (top level) | 1,517 | 280 |
| settings | 1,041 | 147 |
| gateway | 973 | 165 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 7,027 | 975 |
| `desktop_ui/island_surface.py` | 6,178 | 757 |
| `tests/test_keyboard_hook.py` | 4,006 | 479 |
| `keyboard/win.py` | 3,764 | 623 |
| `tests/test_engine.py` | 3,464 | 568 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,717 | 454 |
| `desktop_ui/keymap_views.py` | 2,672 | 411 |
| `desktop_ui/desktop_bar.py` | 2,408 | 440 |
| `desktop_ui/desktop_app.py` | 2,347 | 428 |
| `desktop_ui/desktop_control.py` | 2,228 | 467 |
| `desktop_ui/application_observer.py` | 2,218 | 376 |
| `keyboard/engine.py` | 2,218 | 349 |
| `desktop_ui/shell_surface.py` | 2,015 | 277 |
| `desktop_ui/island_menu.py` | 1,997 | 316 |
| `desktop_ui/bar_events.py` | 1,931 | 404 |
| `desktop_ui/island_model.py` | 1,885 | 310 |
| `desktop_ui/island_layout.py` | 1,879 | 349 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,781 | 277 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `assistant/meeting_store.py` | 1,596 | 252 |
