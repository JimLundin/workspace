# Windows notifications and shared window controls

Investigated on 2026-10-26 for Workspace's existing unpackaged Windows Python/Qt
runtime. Notification mirroring is feasible. A unified tab system that replaces
the existing title bars and application-drawn tabs across arbitrary apps is not
supported by the checked Windows APIs. Native banner suppression has separate
platform limits.

## Implemented behavior

`winapi/notifications.py` reads Notification Center on a bounded MTA worker and
converts the pinned SDK's aware Python datetime projection into a typed creation
identity. The listener's change event fails with "Element not found" without
package identity, so the worker stats Windows' `wpndatabase.db` and its WAL every
250 ms and reads only after they change, with a 30-second fallback read. A full
read costs about 0.2 s of process CPU for 50 notices; reads reuse known notices
by key because each row's app display name costs about 40 ms. `system_notices.py` seeds history quietly and deduplicates later changes.
`system_toasts.py` renders source-labeled glass cards using Workspace's existing
material and composition, with local source-app opening and individual dismissal.
The Notification Center remains the durable history; Workspace does not save or
submit these notification bodies to the agent.

Cards use a small source-app monogram, a compact source line, a stronger title,
and quieter body text. The same native text document measures and paints each
preview; short notices shrink to their contents instead of filling a fixed
360-by-96 rectangle. Titles and bodies wrap even unbroken text, with bounded
previews and a Read more control for the complete notification history. The close
control shares the agent messages' centered vector drawing and square hit area.
Background sampling runs on a bounded worker and discards stale geometry. Uniform
light/dark backgrounds use the conversation material's 22% tint and contrasting
ink; mixed backgrounds retain stronger shading. Windows transparency and
high-contrast preferences still choose the corresponding accessible fallback.

Banner suppression uses Windows notification settings, separately from mirroring.

The initial duplicate window-controls segment and tabbed-window prototype were
removed. Workspace uses ordinary automatic tiling and preserves each application's title bar.
The tabbed-window prototype was removed after workflow regressions. Keyboard
navigation uses Apps + arrow keys for tiling focus and Apps + Esc for the window
switcher.

## Notification access

`UserNotificationListener.Current` exposes Notification Center's app
notifications. Workspace can obtain the notification ID and creation time, the
source app's name/logo/AUMID, and visual text from the `ToastGeneric` binding.
The listener provides added/dismissed events, individual removal, and clearing.
It is not a general interceptor for every Windows dialog or an app's private
popup UI. [1, 2, 3, 4]

Microsoft's listener guide specifies the `userNotificationListener` manifest
capability and a UI-thread `RequestAccessAsync` permission request. It also
documents denied/unspecified access and user revocation; availability must be
checked rather than assumed. Capability rules differ between AppContainer and
full-trust desktop processes. [1, 2, 5]

**Observed on this machine:** the task's main agent performed a read-only probe
using the installed Windows Python. `GetCurrentPackageFullName` returned 15700
(no package identity), but `GetAccessStatus` returned `Allowed`.
`GetNotificationsAsync(Toast)` returned 39 notifications, with 84 nonempty text
elements in their `ToastGeneric` bindings. No permission prompt was used and no
notification bodies were printed or saved. This demonstrates access on this
target without a packaged helper. It does not guarantee access on every other
installation.

If another target needs package identity for access/consent, Microsoft's
external-location identity package can retain the existing runtime and
installer. It requires package registration, signing/trust, and matching
executable identity metadata. It is a fallback, not a prerequisite established
by the successful local probe. [6]

Notification mirroring should start with a baseline snapshot so existing
history does not appear as a burst of new alerts. Render new notifications
locally using Workspace's glass/chat material, deduplicate by ID, and remove the
specific source notification when the user dismisses it. Keep source app
notifications separate from agent conversation messages.

The exposed `UserNotification`/`Notification` model provides visual content,
not arbitrary original toast activation arguments, inline reply handlers, or
action-button contracts. Opening the source app and dismissing its notification
are appropriate initial controls; reproducing every app-specific action needs
additional integration. [1, 3, 4]

## Suppressing native banners

Windows **Do not disturb** sends ordinary notifications directly to Notification
Center while suppressing their banners. Calls, reminders, alarms, and selected
priority apps can still appear, depending on Windows settings. Per-app settings
also distinguish **Show notification banners** from **Show notifications in
notification center**. Preserve delivery to Notification Center so the listener
can mirror it. Turning notifications off entirely is a different setting. [7]

`ToastNotification.SuppressPopup` silently delivers a toast to Notification
Center, but this is a property of the sending app's toast. The listener's model
does not expose a supported pre-display suppression hook for another app's
notification; removing a notification after observing it is not a guarantee
that its native banner never appeared. [1, 4, 8]

`FocusSessionManager.IsSupported` and `IsFocusActive` can report availability
and state. However, Microsoft explicitly marks `TryStartFocusSession` and
`DeactivateFocus` as Limited Access Features requiring an unlock token.
`IsSupported == True` is not permission to use those mutations. Focus sessions
normally turn on Do not disturb, but that is also a configurable user option.
[9, 10]

Use the documented Windows notification settings UI for banner suppression
(`ms-settings:notifications`; notification access settings are
`ms-settings:privacy-notifications`). No supported unrestricted global Do not
disturb mutation API was identified in the checked APIs. Registry changes or
private shell interfaces were not validated by this investigation. [7, 11]

## Sharing window controls with Workspace's bar

A compact foreground-window segment can show the active app/title and invoke
minimize, maximize/restore, or close against its captured window handle. This
fits into Workspace's existing bar without attaching the app's rendering surface
to Workspace. Capture the target before Workspace's controls take focus.

GlazeWM v3.10.1 already has `hide_title_bar` window effects. Its Windows
implementation clears/restores the native `WS_DLGFRAME` style and requests a
frame recalculation with `SWP_FRAMECHANGED`. That can remove a conventional
native title bar. It does not move application content into Workspace. [12]

Apps can draw their own tabs, search fields, ribbons, title controls, or entire
window frames in their client area. Microsoft's custom-frame documentation
describes frame/layout/hit-testing changes made by the application that owns
the window. Clearing an external native frame style cannot universally relocate
those app-drawn controls. Use per-app/native-titlebar support and restoration
rather than blindly hiding every app's top content. [12, 13]

## Sources

1. [Microsoft: Notification listener](https://learn.microsoft.com/en-us/windows/apps/design/shell/tiles-and-notifications/notification-listener).
2. [Microsoft: UserNotificationListener](https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.management.usernotificationlistener).
3. [Microsoft: UserNotification](https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.usernotification).
4. [Microsoft: Notification](https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.notification).
5. [Microsoft: App capability declarations, application types and privacy-sensitive capabilities](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations#which-kinds-of-apps-do-app-capabilities-apply-to).
6. [Microsoft: Grant package identity by packaging with external location](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/grant-identity-to-nonpackaged-apps).
7. [Microsoft Support: Notifications and Do Not Disturb in Windows](https://support.microsoft.com/en-us/windows/change-notification-settings-in-windows-8942c744-6198-fe56-4639-34320cf9444e).
8. [Microsoft: ToastNotification.SuppressPopup](https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.toastnotification.suppresspopup).
9. [Microsoft: FocusSessionManager](https://learn.microsoft.com/en-us/uwp/api/windows.ui.shell.focussessionmanager) and [TryStartFocusSession](https://learn.microsoft.com/en-us/uwp/api/windows.ui.shell.focussessionmanager.trystartfocussession).
10. [Microsoft Support: Focus in Windows](https://support.microsoft.com/en-us/windows/how-to-use-focus-in-windows-11-cbcc9ddb-8164-43fa-8919-b9a2af072382).
11. [Microsoft: Launch the Windows Settings app](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-settings-app).
12. [GlazeWM v3.10.1: native Windows title-bar visibility implementation](https://github.com/glzr-io/glazewm/blob/v3.10.1/packages/wm-platform/src/platform_impl/windows/native_window.rs#L578).
13. [Microsoft: Custom Window Frame Using DWM](https://learn.microsoft.com/en-us/windows/win32/dwm/customframe).
