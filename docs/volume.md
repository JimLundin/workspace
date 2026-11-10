# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.8 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 86,583 | 14,869 |
| **support** | 57,140 | 8,524 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 45,860 | 7,951 |
| tests | 41,986 | 6,142 |
| winapi | 19,646 | 3,299 |
| scripts | 11,545 | 1,676 |
| keyboard | 8,737 | 1,459 |
| assistant | 6,962 | 1,196 |
| typings | 3,609 | 706 |
| contracts | 1,612 | 306 |
| (top level) | 1,482 | 269 |
| gateway | 1,074 | 187 |
| settings | 1,066 | 149 |
| desktop | 144 | 53 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `scripts/architecture.py` | 6,585 | 918 |
| `desktop_ui/island_surface.py` | 5,825 | 716 |
| `tests/test_keyboard_hook.py` | 4,006 | 479 |
| `keyboard/win.py` | 3,781 | 623 |
| `tests/test_engine.py` | 3,464 | 568 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `desktop_ui/keymap_views.py` | 2,869 | 477 |
| `assistant/meetings.py` | 2,717 | 454 |
| `desktop_ui/desktop_bar.py` | 2,419 | 432 |
| `keyboard/engine.py` | 2,218 | 349 |
| `desktop_ui/island_menu.py` | 2,140 | 366 |
| `desktop_ui/desktop_app.py` | 2,125 | 392 |
| `desktop_ui/desktop_control.py` | 2,104 | 459 |
| `desktop_ui/application_observer.py` | 2,098 | 360 |
| `desktop_ui/island_layout.py` | 1,949 | 371 |
| `desktop_ui/bar_events.py` | 1,926 | 403 |
| `desktop_ui/components/appearance.py` | 1,846 | 412 |
| `desktop_ui/island_model.py` | 1,846 | 318 |
| `winapi/composition.py` | 1,845 | 314 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `tests/test_features.py` | 1,779 | 277 |
| `desktop_ui/shell_surface.py` | 1,745 | 247 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
