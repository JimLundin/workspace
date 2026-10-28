# Native UI retained by Workspace tests

The reported "Workspace accessibility fixture" is `tests/uia_fixture.ps1`, a
test-only WPF application. It is deliberately plain so the automation adapter
can inspect editable text, buttons, disabled controls, password redaction,
selection, values and expansion. It is not an old Workspace design. The native
test uses control identities from one process, operates them from another and
reads the resulting state from a third. Removing it would lose coverage of our
PowerShell/UIA integration, escaping, bounds and action validation.

The flashing bubble cards are real `assistant/toast_card.py` surfaces constructed
by `tests/test_windows_agent_toasts.py` and its consumers. The fixture supplies
synthetic requests, replies, approvals, recordings and feed items, sometimes at
narrow widths or fractional DPI. These are current product variants; standalone
replies also remain in use for notices. There is no separate retired bubble
renderer in the checkout. Short-lived synthetic layouts are not evidence that a
second UI design ships. This audit does not establish a title-placement defect;
the tests retain header geometry, wrapping, hit targets and DPI checks.

| Surface | Product caller or test ownership | Decision |
| --- | --- | --- |
| Accessibility WPF fixture | `test_windows_computer.py::test_uia_controls_are_inspected_and_operated_across_separate_processes` | Retain the native adapter integration; contain its window. |
| Floating bubbles, step views and tool rows | `Ui.agent`, inbox/history, communications, console approvals and recordings | Retain current rendering, input, reading and lifecycle tests. |
| Floating toolbar and its capsules | `Controller` → `Ui.desktop` | Retain native geometry, joined contours, actions and ownership tests. |
| Work overview, routines and context editors | `Controller.show_work`; live task snapshots via `Controller.work_changed` | Retain task identity, drafts, hidden-state preservation, approval previews and controls. |
| Meeting editors | `Controller.show_meetings` → Work tab; `Ui.configure_meetings` attaches `MeetingPanel` | Retain sourced transcripts, revision selection, draft/action edits and saved receipts. |
| Text prompt and answer window | `Assistant.ask` and `Assistant.screen_ask` → `WinDesktop` → `Ui` | Retain: these keyboard actions still use this separate conversation window. Its design is a product migration question, not unused code. |
| Region picker | Screenshot/OCR and screen-question keyboard actions | Retain the selected-region workflow. |
| Keyboard map, overlay and layer indicator | Toolbar/tray commands and keyboard-layer observations | Retain; these belong to Workspace's keyboard UI. |
| Window switcher | `Controller.switch_windows` → `Ui.switch_windows` | Retain filtering, navigation and selected-window activation. |
| Plain browser fixture pages | Disposable Edge profiles in browser/Teams/communications tests | Retain DOM/action and native tab integration. These pages are not Workspace UI. |
| `Ui.review` / `ReviewWindow` ("Change Workspace?") | No caller outside their own definitions; `WinMachine.review` delegates actual candidate review to the keeper | Remove unused entry point, dialog and its two stale signature migration entries. |
| Keeper review/trial dialogs | `keeper.py` uses protected `keeper_ui.py` | Retain actual installation, trial and rollback ownership. |
| Preview test's visible "Transcribing" caption requirement | Current toolbar deliberately presents a compact spinner, with speech state in its tooltip/accessibility | Remove the stale caption expectation; retain sample-to-real-view processing-state coverage. |
| Previous notification/inbox/history panels and native canvas | Already removed; history uses the floating feed and canvas belongs to Shared Workspace | Keep retired; do not restore their implementations or tests. |

## Cause and containment

The old fixtures suppressed activation or used coordinates such as `(-4000,
-3000)`. Suppressing activation prevents focus theft but does not prevent
painting. Some fixtures explicitly used the real work area or `(40, 60)`;
offscreen coordinates can also fall on another monitor. Repeated native UI
construction therefore displayed a stream of fixture windows on the user's
desktop.

A focused probe constructed a notification through the production fixture and
observed `fixture_visible=True` and `intersects_monitor=True`; its no-flashing
assertion failed. Moving the test thread to an unshown Windows desktop preserved
the native stop-button hit test and cross-process UIA scenario.

`tests/__init__.py` now relaunches ordinary Windows test processes on a private
startup desktop before importing their fixtures. `tests/desktop_session.py` uses
the already installed win32more desktop/process APIs and the existing process
job owner. One random `workspace-tests-*` identity is inherited by subprocesses;
children already on that desktop continue without relaunching. Actual widgets,
native handles, composition and event loops remain in use. The input desktop is
never switched, and launch failure blocks execution. The launcher retains the
desktop until the isolated process tree has exited, then closes it. The native
editing runtime bootstraps tests before broad SDK/Qt import work.

The first thread-only implementation passed native behavior checks but failed
the containment regression: WPF inherited the process's original desktop.
Specifying `STARTUPINFO.lpDesktop` for the complete test process fixed that
failure and also contains headful browser and fresh-runtime child fixtures.

`test_windows_test_desktop.py` exercises the Qt-card and WPF-child fixture owners,
checks that their real visible windows belong to the private desktop, and checks
that it differs from the input desktop. The defect it detects is our bootstrap
attaching too late or a child escaping isolation. It does not test Windows'
implementation of desktop APIs.

The second bootstrap scenario requests a fresh desktop identity and exercises
the editing executor with a preexisting E2E opt-in. It verifies that ordinary
checks clear that opt-in before bootstrap, preserve quoted/Unicode arguments and
input/output streams, and return a deliberately failing child's status. The
launcher exits only after releasing its native owners; it avoids raising a
collection exception in pytest.

The test selection and protected selfcheck/CI gates are unchanged. Ordinary
`Dev.cmd check`, watch checks, pytest and selfcheck use the same test bootstrap.
Explicit `WORKSPACE_E2E=1` runs retain their existing interactive desktop behavior;
selfcheck and editing checks continue to clear that opt-in.

Private desktops isolate window presentation, not all workstation resources.
Keep native tests sequential: clipboard, audio devices, registry and other
session resources still need their existing ownership and cleanup. Required
native checks are retained; there is no replacement with generic dependency
tests, patched bindings or screenshot-only assertions.
Foreground activation checks retain their existing desktop-availability skips;
interactive input-desktop behavior remains available through the explicit E2E
opt-in. An unshown desktop cannot prove a real foreground handoff on the user's
input desktop.

## Interactive controls

| Before | After | Why |
| --- | --- | --- |
| Bubble dismiss, stop and disclosure paint only their glyph; the old test explicitly forbids pressed fill | Shared immediate hover/press shading and focus outline | The same feedback identifies all clickable icon targets; disabled controls stay quiet. |
| Toolbar buttons inherit native icon/caption size hints and CSS feedback | Compact measured caption spacing and the same feedback painter as bubble icons | The notification count has balanced trailing space; shading remains inside its unchanged hit rectangle. |

`assistant/control_feedback.py` owns the shared native paint contract. Qt supplies
pointer, press, enabled and focus state; no additional mutable interaction model
or animation is needed. The obsolete no-pressed-fill assertion is replaced by
behavioral coverage for all three bubble controls. Existing toolbar action tests
also constrain caption padding so a wide empty hover area cannot return.

Seven focused seeded regressions were detected, with no survivors, timeouts or
runner errors: three feedback failures (missing hover, disabled shading and
indistinguishable press), two toolbar failures (omitted feedback and excess
caption spacing), lost child failure status, and an E2E opt-in restored before
ordinary check bootstrap. This is evidence for those decisions, not a general
mutation score. Native rendered samples also confirmed the shaded dismiss
target and centered 34 × 24 notification icon/count target.
