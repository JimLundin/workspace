# Workspace

Workspace is a personal work environment for a Windows laptop. It runs on the
installed Python 3.15 and needs no admin rights. It runs five processes:

- **The layout** (`keyboard/`) remaps the laptop's ISO keyboard to Colemak Mod-DH
  in the Miryoku style, with home row mods, layers and caps word.
- **The desktop** (`desktop/`, `desktop_ui/`) owns everything you see: the
  floating bar, the tray icon, the key map and overlay, and window placement.
  It also runs dictation and meeting recording (`assistant/`). Every key
  request goes straight to it.
- **The AI connection** (`gateway/`) is a local pass-through to your endpoint
  that dictation and meetings share. It holds the key.
- **The launcher** (`launch.py`) starts the three programs from this folder's
  environment, and stops or restarts them. Nothing restarts a program that
  crashes; start Workspace again.

## Install and start

1. Install Windows x64 Python 3.15 with the Python launcher, and
   [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Clone the repository into a folder you can write to.
3. Set the environment variables below for your account, then restart
   Workspace whenever you change one.
4. Turn on **Let desktop apps access your microphone** in Windows privacy
   settings.
5. Double-click `StartWorkspace.cmd`. It syncs the pinned dependencies from
   PyPI with [uv](https://docs.astral.sh/uv/) into the folder's `.venv` (the
   first time takes a minute or two and needs the network), then starts the
   programs. To start Workspace at login, put a shortcut to it in
   `shell:startup`. `python launch.py restart` restarts them after a change.

`pyw -3.15 keyboard.pyw` runs the layout alone.

| Variable | Default | Use |
|---|---|---|
| `OPENAI_BASE_URL` | required | Your OpenAI-style endpoint, ending in `/v1` |
| `OPENAI_API_KEY` | required | Its key |
| `WORKSPACE_TRANSCRIBE_MODEL` | `gpt-4o-transcribe` | Speech to text (the Foundry proxy serves no `gpt-transcribe`) |
| `WORKSPACE_VOCABULARY` | empty | Names and jargon to expect in dictation |
| `WORKSPACE_COLEMAK_LAYOUT` | your Colemak entry | The Windows layout ID used while the layout is off |

Without the two required variables, the layout and window keys still
work, and the dictation and recording keys say what is missing.

Your apps live in `config.py`.

## The keys

Physical keys are named by their Nordic keycaps. **Key map** in the tray menu,
or **Keyboard map** in the bar menu, draws every layer.

| Key | Does |
|---|---|
| **§** | Tap: layout on or off. Hold 2 s: quit the layout |
| thumbs **X C V** | Esc or **Apps**, Space or **Nav**, Tab |
| thumbs **M , .** | Enter or **Sym**, Backspace or **Num**, Delete |

The **Apps** layer (hold the **X** thumb, left outer) holds every Workspace key; nothing else in the
layout talks to Workspace. Desktops are reached directly by number, never
cycled.

| Hold **X** and press | Does |
|---|---|
| **2 3 4 5 6**, **Q W E R T** | The ten apps in `APPS` |
| **8 9 0 + ´** | Desktops 1 to 5 |
| **I** | Zoom |
| **O P Å ¨** | Focus ← ↓ ↑ → |
| **A S D** | Pause placement, switch windows, re-place |
| **L** | Hold to dictate; the text is typed at the cursor on release |
| **Ä** | Copy the latest transcript |
| **'** | Dictation on or off |
| thumb **C** | Start or stop a meeting recording |

While the Charybdis Nano keyboard (USB `A8F8:1832`) is connected, the layout
pauses and keeps English (US). Its Tab thumb is the Charybdis's Apps key: set
it in VIA to `MT(MOD_RALT, KC_TAB)`, so a tap types Tab and a hold sends Right
Alt. While it is held, the next key is read by the letter it sends, as on the
laptop's Apps layer at that place (listed below), and swallowed. Right Alt never
reaches an application. A hold-to-talk key lasts while it is held.

While either keyboard holds its Apps key, the bar shows each target's letter.
App keys focus the app, cycle its windows, or start it.

| Apps + | does |
|---|---|
| Apps **Q** | Terminal |
| Apps **W** | Browser |
| Apps **F** | Outlook |
| Apps **P** | Teams |
| Apps **B** | Files |
| Apps **J** | Desk 1 |
| Apps **L** | Desk 2 |
| Apps **U** | Desk 3 |
| Apps **Y** | Desk 4 |
| Apps **'** | Desk 5 |
| Apps **A** | Code |
| Apps **R** | Notepad |
| Apps **S** | Excel |
| Apps **T** | Word |
| Apps **G** | PowerPoint |
| Apps **M** | Zoom |
| Apps **N** | Focus ← |
| Apps **E** | Focus ↓ |
| Apps **I** | Focus ↑ |
| Apps **O** | Focus → |
| Apps **X** | Pause place |
| Apps **C** | Windows |
| Apps **D** | Re-place |
| Apps **H** | Talk |
| Apps **.** | Copy speech |
| Apps **/** | Dictate toggle |
| Apps **Space** | Record |

Workspace keeps the Windows taskbar hidden while it runs, and restores it when
it exits or crashes. The Windows key opens Start as usual.

## The bar and the tray

The floating bar sits at the top of the main screen. Its centre shows only live
activity: dictation, transcription and a meeting recording.
On the left, the desktop pager is the only toolbar: each desktop as its apps'
icons, left to right as they sit on screen, running or not. Click an icon to go
to that app; right-click lists its windows. One
capsule on the right holds a keyboard icon while the keyboard types plainly
(layout off or the Charybdis connected), volume, Wi-Fi, the battery, CPU and
memory use, and the clock at the far right. Click the clock or battery to open the controls menu. See [the island bar](docs/toolbar-design.md) for the full policy.

The tray dot is green when the layout is on, grey when it is off, red while
listening or recording, and amber while working. Its menu switches or restarts
the layout, opens the keyboard overlay and key map,
starts or stops a meeting recording, opens the meeting transcripts and the logs
folder, restarts the layout or the desktop, and quits Workspace. The tray menu's
items and their order are `TRAY` in `desktop_ui/desktop_control.py`.

Workspace places each app's windows without overlap for the connected monitors
and creates virtual desktops as needed. See
[window placement](docs/window-placement.md).

## Logs and data

Everything is in `%LOCALAPPDATA%\workspace`.

| File | Contents |
|---|---|
| `desktop.log` | Problems and crashes, dictation failures with their details (never what you said), and views that could not open or fell back |
| `keyboard.log` | The keyboard's input recoveries: a lost hook reinstalled, or failing open after an error |
| `state\*.log` | Each program's output and crashes, written by the launcher |
| `meetings\` | One folder per recorded meeting, with `transcript.md` |

Recordings and dictated speech go to your endpoint.

## Development

Read [AGENTS.md](AGENTS.md) and
[the iteration pipeline](docs/iteration-pipeline.md). Develop in
`C:\Users\Jim.Lundin\Projects\workspace` with `Dev.cmd`.
