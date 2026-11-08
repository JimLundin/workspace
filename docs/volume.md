# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 97,389 | 16,291 |
| **support** | 68,607 | 10,186 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 48,655 | 8,083 |
| tests | 47,473 | 6,878 |
| winapi | 22,256 | 3,699 |
| scripts | 18,853 | 2,856 |
| miryoku | 10,188 | 1,576 |
| assistant | 9,833 | 1,765 |
| typings | 2,281 | 452 |
| contracts | 2,020 | 375 |
| (top level) | 1,861 | 350 |
| link | 1,579 | 271 |
| gateway | 966 | 164 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 6,265 | 785 |
| `scripts/architecture.py` | 5,444 | 787 |
| `tests/test_engine.py` | 4,498 | 750 |
| `tests/test_keyboard_hook.py` | 4,318 | 535 |
| `miryoku/win.py` | 4,312 | 692 |
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
| `desktop_ui/desktop_app.py` | 1,702 | 338 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/window_layout.py` | 1,678 | 201 |
| `assistant/meeting_store.py` | 1,596 | 252 |
