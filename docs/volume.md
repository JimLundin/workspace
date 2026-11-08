# Code volume

Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);
CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);
lines are code lines. Product code averages 5.9 nodes a line.

| | nodes | lines |
|---|---:|---:|
| **product** | 241,922 | 40,821 |
| **support** | 179,362 | 26,435 |

| area | nodes | lines |
|---|---:|---:|
| tests | 155,320 | 22,682 |
| desktop_ui | 85,939 | 14,082 |
| assistant | 81,847 | 14,047 |
| winapi | 25,874 | 4,411 |
| contracts | 21,894 | 3,769 |
| scripts | 21,761 | 3,301 |
| automation | 11,709 | 2,132 |
| miryoku | 10,193 | 1,576 |
| typings | 2,281 | 452 |
| (top level) | 1,890 | 361 |
| link | 1,579 | 271 |
| gateway | 966 | 164 |
| desktop | 31 | 8 |

The 25 largest files:

| file | nodes | lines |
|---|---:|---:|
| `desktop_ui/work_canvas_panel.py` | 8,437 | 1,312 |
| `desktop_ui/island_surface.py` | 7,243 | 894 |
| `tests/test_windows_work_canvas.py` | 6,131 | 816 |
| `scripts/architecture.py` | 5,450 | 787 |
| `tests/test_engine.py` | 4,517 | 751 |
| `tests/test_keyboard_hook.py` | 4,493 | 553 |
| `miryoku/win.py` | 4,312 | 692 |
| `tests/test_personal_work.py` | 4,094 | 534 |
| `scripts/check.py` | 3,813 | 521 |
| `desktop_ui/desktop_bar.py` | 3,696 | 702 |
| `tests/test_agent.py` | 3,668 | 530 |
| `tests/test_work_canvas.py` | 3,628 | 407 |
| `assistant/browser.py` | 3,566 | 618 |
| `tests/test_work_store.py` | 3,531 | 399 |
| `tests/test_browser.py` | 3,523 | 572 |
| `assistant/app.py` | 3,521 | 724 |
| `contracts/personal_work.py` | 3,384 | 500 |
| `desktop_ui/bar_events.py` | 3,230 | 623 |
| `assistant/work_agent.py` | 3,107 | 531 |
| `tests/test_meetings.py` | 3,106 | 474 |
| `tests/test_windows_island_bar.py` | 2,996 | 418 |
| `miryoku/engine.py` | 2,873 | 436 |
| `automation/store.py` | 2,855 | 497 |
| `assistant/meetings.py` | 2,803 | 467 |
| `tests/test_feed_triage_service.py` | 2,772 | 361 |
