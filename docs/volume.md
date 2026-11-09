# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 6.0 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 89,314 | 14,861 |
| **support** | 57,737 | 8,502 |

| area | nodes | lines |
|---|---:|---:|
| desktop_ui | 48,053 | 7,976 |
| tests | 43,044 | 6,165 |
| winapi | 19,623 | 3,295 |
| scripts | 10,694 | 1,585 |
| miryoku | 10,110 | 1,571 |
| assistant | 7,044 | 1,202 |
| typings | 3,999 | 752 |
| (top level) | 1,774 | 318 |
| contracts | 1,612 | 305 |
| gateway | 1,067 | 186 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/island_surface.py` | 5,817 | 714 |
| `scripts/architecture.py` | 5,333 | 768 |
| `tests/test_engine.py` | 4,498 | 750 |
| `miryoku/win.py` | 4,234 | 687 |
| `tests/test_keyboard_hook.py` | 4,082 | 515 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `miryoku/engine.py` | 2,873 | 436 |
| `desktop_ui/desktop_bar.py` | 2,858 | 539 |
| `assistant/meetings.py` | 2,738 | 456 |
| `desktop_ui/keymap_views.py` | 2,364 | 322 |
| `desktop_ui/island_menu.py` | 2,313 | 349 |
| `desktop_ui/bar_events.py` | 2,217 | 443 |
| `miryoku/layout.py` | 2,196 | 299 |
| `tests/test_features.py` | 2,057 | 304 |
| `desktop_ui/application_observer.py` | 2,035 | 339 |
| `desktop_ui/shell_surface.py` | 2,017 | 291 |
| `winapi/audio.py` | 1,826 | 277 |
| `tests/test_meeting_audio.py` | 1,795 | 226 |
| `winapi/composition.py` | 1,768 | 308 |
| `desktop_ui/desktop_app.py` | 1,712 | 345 |
| `winapi/recording.py` | 1,696 | 257 |
| `tests/test_microphone.py` | 1,689 | 300 |
| `desktop_ui/desktop_control.py` | 1,688 | 372 |
| `desktop_ui/window_layout.py` | 1,678 | 201 |
| `assistant/meeting_store.py` | 1,596 | 252 |
