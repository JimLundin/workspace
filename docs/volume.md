# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 95,300 | 15,917 |
| **support** | 67,911 | 10,058 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 48,446 | 8,042 |
| tests | 46,778 | 6,750 |
| winapi | 22,256 | 3,699 |
| scripts | 18,852 | 2,856 |
| miryoku | 10,187 | 1,576 |
| assistant | 9,675 | 1,719 |
| typings | 2,281 | 452 |
| (top level) | 1,850 | 345 |
| contracts | 1,766 | 338 |
| gateway | 1,067 | 186 |
| desktop | 53 | 12 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 6,265 | 785 |
| `scripts/architecture.py` | 5,443 | 787 |
| `tests/test_engine.py` | 4,498 | 750 |
| `tests/test_keyboard_hook.py` | 4,318 | 535 |
| `miryoku/win.py` | 4,311 | 692 |
| `scripts/check.py` | 3,787 | 516 |
| `desktop_ui/desktop_bar.py` | 3,228 | 608 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `miryoku/engine.py` | 2,873 | 436 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/keymap_views.py` | 2,448 | 330 |
| `desktop_ui/island_menu.py` | 2,313 | 349 |
| `desktop_ui/bar_events.py` | 2,285 | 457 |
| `tests/test_features.py` | 2,240 | 328 |
| `miryoku/layout.py` | 2,196 | 299 |
| `desktop_ui/shell_surface.py` | 2,159 | 312 |
| `desktop_ui/application_observer.py` | 2,035 | 339 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `winapi/recording.py` | 1,789 | 265 |
| `winapi/composition.py` | 1,768 | 308 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,678 | 201 |
| `assistant/meeting_store.py` | 1,596 | 252 |
| `desktop_ui/desktop_app.py` | 1,589 | 317 |
