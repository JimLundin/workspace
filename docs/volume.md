# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.8 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 86,843 | 14,898 |
| **support** | 57,458 | 8,539 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 44,174 | 7,458 |
| tests | 41,987 | 6,120 |
| winapi | 19,657 | 3,302 |
| scripts | 11,862 | 1,713 |
| assistant | 6,962 | 1,196 |
| keyboard | 6,445 | 1,071 |
| contracts | 3,992 | 719 |
| typings | 3,609 | 706 |
| desktop | 2,081 | 560 |
| (top level) | 1,517 | 280 |
| settings | 1,042 | 147 |
| gateway | 973 | 165 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 6,901 | 954 |
| `desktop_ui/island_surface.py` | 5,811 | 716 |
| `tests/test_keyboard_hook.py` | 4,006 | 479 |
| `keyboard/win.py` | 3,764 | 623 |
| `tests/test_engine.py` | 3,464 | 568 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `assistant/meetings.py` | 2,717 | 454 |
| `desktop_ui/keymap_views.py` | 2,672 | 411 |
| `desktop_ui/desktop_bar.py` | 2,434 | 440 |
| `keyboard/engine.py` | 2,218 | 349 |
| `desktop_ui/application_observer.py` | 2,134 | 365 |
| `desktop_ui/desktop_app.py` | 2,117 | 392 |
| `desktop_ui/desktop_control.py` | 2,010 | 428 |
| `desktop_ui/island_menu.py` | 1,997 | 316 |
| `desktop_ui/bar_events.py` | 1,931 | 404 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `desktop_ui/island_layout.py` | 1,793 | 320 |
| `tests/test_features.py` | 1,779 | 277 |
| `desktop_ui/shell_surface.py` | 1,735 | 247 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/island_model.py` | 1,688 | 273 |
| `assistant/meeting_store.py` | 1,596 | 252 |
