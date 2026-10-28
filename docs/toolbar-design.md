# Contextual Workspace toolbar

The desktop control surface uses the agent messages' native Windows backdrop,
blue/lilac tint, opaque ink, rounded edges and adaptive light/dark contrast.
Windows' reduced-transparency and high-contrast settings retain solid fallbacks.

| Situation | Visible controls |
| --- | --- |
| Idle | Local time, battery level and available local temperature; the entire capsule opens controls |
| Dictating | Microphone, Listening and live audio waveform; release Spacebar, press B again, or use Stop to finish |
| Transcribing | Transcribing and the dimmed, frozen captured waveform |
| Agent working | Activity label and Stop |
| Agent needs input | Needs you; conversation access is in the capsule's menu |
| Meeting recording | Separate microphone/timer capsule and its own Stop |
| Saving or interrupted recording | Separate progress or attention capsule |
| Temporary keyboard layer or layout disabled | Small keyboard-mode capsule |

Agent, recording and keyboard state are independent. Finishing a recording
removes its capsule without hiding an active agent or dictation. Routine Work,
recording-start, conversation and keyboard actions live in the controls menu.
There is no separate dropdown target. Its entire capsule, including the padding,
opens the menu; the content button also supports keyboard focus and activation.
A small bell beside the controls opens the work feed directly when inbox items
need attention. Its count follows unhandled work and unanswered questions,
including items beyond the visible bubble page. Curated work uses its grouped
items; handled items and muted sources do not re-alert. The bell stays available
during dictation and agent work, and disappears when the count reaches zero.
Counts above 99 display `99+`; hover and accessibility retain the exact count.
**Hold V + T** opens the same inbox while Workspace's layout is enabled, including
when the bell is hidden. The bell tooltip and key map show the shortcut.
Opening the inbox restores the current feed's first page and reveals locally
hidden bubbles without reviving work that was handled or dismissed in its source.
Space holds dictation; B toggles dictation; N toggles agent speech. These voice
buttons work on every layer independently of held modifiers. Meeting recording
remains available in Workspace controls.
Speech capture continues after key release, until the next toggle or Stop.
The menu includes Copy latest transcript, the Apps + Esc window switcher and an explicit
action to spread visible tiles across connected screens.
Tabbed groups add a shared glass tab strip along each occupied screen's top edge.
On the primary screen, the ambient capsule moves to the right and joins the strip;
active recording and keyboard capsules still expand independently. Each group's
selected window has a filled tab; the focused group has stronger contrast. Inactive
tabs show the app name, selected tabs show the window title, and long text elides
with the full title available to accessibility and hover. The focused group's
single close control closes its selected app window. Apps-layer arrows focus
groups, Control+left/right cycles tabs, and Shift+arrows transfer windows. No
function-key or number shortcut is required.
The main capsule stays centered against the top screen edge and overlays tiled
windows without reserving a full-width strip. Its outer shoulders
curve outward into that edge, with no horizontal top outline or native window
frame. Its height is 28 logical pixels, with 24-pixel controls and the existing
12-pixel text. Adjacent segments meet across their upper six pixels, with curved
cutouts below the connection. Their glass masks meet without overlapping tint or
drawing a border through the joint. Auxiliary capsules can stack below on narrow
screens, using the ordinary rounded shape when detached.

Read-only system observations add an unmuted-speaker icon for the default playback
endpoint and a disconnected-Wi-Fi icon when adapters exist but none is associated.
They remain visible during dictation, transcription and agent work. The icons
disappear when their conditions clear; muted playback is the quiet default. Unknown readings and absent Wi-Fi adapters
do not imply a fault. Ethernet or internet reachability is separate from Wi-Fi
association. A background worker refreshes the observations once per second,
without opening an audio stream, scanning for networks or blocking the UI.

Keyboard-triggered content and layout changes take effect immediately. New
segments enter from above the screen edge using a reversible 160 ms slide and
opacity transition with the existing conversation curve. They exit upward; a
reversal continues from the current position. Reduced motion uses an immediate
transition. Windows composition follows the foreground's position and opacity,
with the same vector silhouette for glass and shadow. Geometry changes only when
size or joining state changes. Text stays opaque at rest, and no idle animation
loop runs. Content changes resize immediately rather than animating dimensions.

The audio trace is a bounded 24-sample history of real RMS levels, read every
50 ms only while dictating. `waveInGetPosition` marks recorded data in the same
PCM buffer used for transcription. Each read copies at most 40 ms (1,280 bytes
at 16 kHz). A nonblocking lock prevents reads during reset or release without
making the UI wait. Silence remains flat; unavailable observations do not
simulate activity. Stopping capture stops the meter and dims its final trace while the
transcription request runs. Completion restores the ambient presentation.

Windows `GetSystemPowerStatus` supplies battery percentage, charging and external
power. Unknown readings show a dash; machines without a battery show AC. Power
refreshes every fifteen seconds and the local clock updates at minute changes.
Weather uses Windows geolocation when already available, with no consent request
or IP-based fallback. A background worker sends coordinates rounded to a tenth
of a degree to Open-Meteo, refreshes successful observations every fifteen minutes,
and quietly retries missing location or network access. A failed refresh removes
temperature rather than displaying stale or invented weather. Location and
weather are neither persisted nor logged.

[Native glass previews with illustrative battery, weather and audio observations](images/workspace-toolbar.png).
These precede the flared shoulders and joining segments.

[Current shape and motion storyboard](images/workspace-bar-shape.png) shows the
flared shoulders, partial connections and an entrance frame. It uses the Qt solid
fallback with illustrative observations because the Windows desktop was locked
during capture. Native Direct2D mask containment, composition clip creation and
geometry-source cleanup were checked independently.

## References

- [Apple: Toolbars](https://developer.apple.com/design/human-interface-guidelines/toolbars):
  deliberate item selection, logical grouping, restrained backgrounds and familiar
  symbols; less-frequent actions belong in a More menu.
- [Apple: Live Activities](https://developer.apple.com/design/human-interface-guidelines/live-activities):
  compact resting presentations, independent simultaneous activities, and more
  space only when the activity has more useful information.
- Workspace's existing `toast_style`, `appearance`, `composition` and `qt_ui` modules
  remain the material, motion-preference and composition-lifetime references.
