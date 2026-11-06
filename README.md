# Workspace

Workspace is a personal work environment for a Windows laptop. It runs on the
installed Python 3.15 and needs no admin rights. It runs three processes:

- **The layout** (`miryoku/`) remaps the laptop's ISO keyboard to Colemak Mod-DH
  in the Miryoku style, with home row mods, layers, caps word and snippets.
- **The assistant** (`assistant/`) owns dictation, window placement, the
  floating bar, the tray icon, the work canvas and the agent. Durable agent work
  runs on the assistant's own threads (`automation/`).
- **The keeper** (`keeper.py`) starts the other two, restarts them if they
  crash, and installs every change to Workspace.

## Install and start

1. Install Windows x64 Python 3.15 with the Python launcher.
2. Extract `workspace-sdk-python315-win64.zip` into a folder you can write to.
   Keep its `.runtime` folder beside `StartWorkspace.cmd`.
3. Set the environment variables below for your account, then restart
   Workspace whenever you change one.
4. Turn on **Let desktop apps access your microphone** in Windows privacy
   settings.
5. Double-click `StartWorkspace.cmd`. To start Workspace at login, put a
   shortcut to it in `shell:startup`.

`pyw -3.15 miryoku.pyw` runs the layout alone.

| Variable | Default | Use |
|---|---|---|
| `OPENAI_BASE_URL` | required | Your OpenAI-style endpoint, ending in `/v1` |
| `OPENAI_API_KEY` | required | Its key |
| `WORKSPACE_FAST_MODEL` | `gpt-6-luna` | Tidied dictation, dictated commands, notification screening |
| `WORKSPACE_AGENT_MODEL` | `gpt-6-astra` | The agent and every other model job |
| `WORKSPACE_AGENT_REASONING_EFFORT` | `low` | Reasoning effort for agent tasks |
| `WORKSPACE_TRANSCRIBE_MODEL` | `gpt-4o-transcribe` | Speech to text (the Foundry proxy serves no `gpt-transcribe`) |
| `WORKSPACE_VOCABULARY` | empty | Names and jargon to expect in dictation |
| `WORKSPACE_AGENT_CONTEXT` | `recent` | `off` stops sending recent windows and a screenshot with each request |
| `WORKSPACE_COLEMAK_LAYOUT` | your Colemak entry | The Windows layout ID used while the layout is off |
| `WORKSPACE_GIT_REMOTE` | `https://github.com/JimLundin/workspace.git` | Where the agent's changes land |
| `WORKSPACE_GIT_BASE` | `main` | The branch they land on |

Without the two required variables, the layout, snippets and window keys still
work, and the AI keys say what is missing.

Your apps, snippets, the agent's step limit (`AGENT_MAX_STEPS`, 80) and the
idle delay for dark screens live in `config.py`.

## The keys

Physical keys are named by their Nordic keycaps. **Key map** in the tray menu,
or **Keyboard map** in the bar menu, draws every layer.

| Key | Does |
|---|---|
| **§** | Tap: layout on or off. Hold 2 s: quit the layout |
| thumbs **X C V** | Esc, Space or **Nav**, Tab |
| thumbs **M , .** | Enter or **Sym**, Backspace or **Num**, Delete or **Apps** |

The **Apps** layer (hold **.**) holds every Workspace key; nothing else in the
layout talks to Workspace. Desktops are reached directly by number, never
cycled.

| Hold **.** and press | Does |
|---|---|
| **2 3 4 5 6**, **Q W E R T** | The ten apps in `APPS` |
| **8 9 0 + ´** | Desktops 1 to 5 |
| **I** | Zoom |
| **O P Å ¨** | Focus ← ↓ ↑ → |
| **A S D** | Pause placement, switch windows, re-place |
| **F** | Stop the agent |
| **K** | Hold to speak to the agent; release to send |
| **L** | Hold to dictate; the text is typed at the cursor on release |
| **Ö** | Type a task for the agent |
| **Ä** | Copy the latest transcript |
| **'** | Dictation on or off |
| thumbs **X C V** | The inbox; start or stop a meeting recording; agent speech on or off |

While the Charybdis Nano keyboard (USB `A8F8:1832`) is connected, the layout
pauses and keeps English (US). Workspace adds one key to its keymap rather than
replacing anything: put **F24** (`KC_F24`) on a thumb key of the Charybdis. Held,
it is the Charybdis's Apps key: the next key is read by the letter it sends, as
on the laptop's Apps layer at that place (listed below), and swallowed. F24
itself never reaches an application. A hold-to-talk key lasts while it is held.

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
| Apps **V** | Stop |
| Apps **K** | Agent talk |
| Apps **H** | Talk |
| Apps **,** | Agent |
| Apps **.** | Copy speech |
| Apps **/** | Dictate toggle |
| Apps **Esc** | Inbox |
| Apps **Space** | Record |
| Apps **Tab** | Agent toggle |

**Snippets.** Type a trigger and Workspace replaces it: `,,date`, `,,time`,
`,,now`, `,,week`, `,,shrug`, `,,thx`, `,,mvh` and `,,br`. Add your own in
`config.py`.

Workspace keeps the Windows taskbar hidden. Tap the Windows key to show it and
open Start, and tap it again to hide it.

## The bar and the tray

The floating bar sits at the top of the main screen. Its centre shows only live
activity: dictation, transcription, agent work with **Stop**, a meeting
recording, a question waiting for you, or a short notice of the agent's news.
On the left, one capsule holds the **Canvas** button and the Outlook and Teams
web apps, followed by the desktop pager and the running apps. One capsule on the
right holds CPU and memory use, a keyboard icon while the keyboard types plainly
(layout off or the Charybdis connected), volume, Wi-Fi, the clock and the
battery. Click the clock or battery to open the controls menu. The bell lists pending questions and recent
notices. See [the island bar](docs/toolbar-design.md) for the full policy.

The tray dot is green when the layout is on, grey when it is off, red while
listening, amber while working or waiting for you, and blue while the agent is
on a task. Its menu has **Undo the last update**, **Usage report**, **Open logs
folder**, **Restart assistant** and **Quit Workspace**.

Workspace places each app's windows without overlap for the connected monitors
and creates virtual desktops as needed. See
[window placement](docs/window-placement.md).

## The agent

Hold **. + K** and speak to the agent. **Hold . + Ö** opens the agent session. The agent works on the
desktop, in files, in PowerShell, and in its own headless Edge profile at
`%LOCALAPPDATA%\workspace\browser-profile`, where it uses Outlook, Teams and AIP
Kanban. It runs without confirmation prompts and stops after 80 steps. It asks
questions in the bar, and you answer by holding **. + K**. It collects work,
sources and notes on the canvas. Tasks are saved, so a restart resumes them.

Ask the agent to change Workspace, such as "add a snippet for my email
address". It edits a copy of the source under `%LOCALAPPDATA%\workspace` and
runs the checks. Then the keeper checks the copy again, installs it, and restarts
only the programs the change affects. If the new version crashes during its
ten-minute trial, the keeper undoes it. Each installed version is a commit in
`%LOCALAPPDATA%\workspace\versions.git`. After installation, the agent pushes
the change to `main`. Ask it to "publish it for review" to push a
`workspace/agent-*` branch instead, without installing. Publishing needs Git for
Windows on `PATH` with credentials.

## Logs and data

Everything is in `%LOCALAPPDATA%\workspace`.

| File | Contents |
|---|---|
| `usage.jsonl` | Feature use and timings, never what you typed or said |
| `assistant.log`, `layout.log` | Problems and crashes |
| `keeper.log` | Starts, installs, trials and undos |
| `agent-ui.log` | View startup and errors |
| `work/work.sqlite3` | Saved tasks, questions and action outcomes |
| `work/canvas.sqlite3` | The canvas |
| `work/worker.log` | Agent work diagnostics |
| `meetings\` | One folder per recorded meeting, with `transcript.md` |

Recordings, dictated text and the agent's requests go to your endpoint. Bar
weather sends coordinates rounded to 0.1 degree to Open-Meteo.

## Development

Read [AGENTS.md](AGENTS.md) and
[the iteration pipeline](docs/iteration-pipeline.md). Develop in
`C:\Users\Jim.Lundin\Projects\workspace` with `Dev.cmd`.
