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
| `WORKSPACE_TRANSCRIBE_MODEL` | `gpt-transcribe` | Speech to text |
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
| **Spacebar** | Hold to dictate. The text is typed at the cursor on release |
| **B** | Dictation on or off |
| **N** | Hold to speak to the agent. Release to send |
| thumbs **X C V** | Esc, Space or **Nav**, Tab or **Tools** |
| thumbs **M , .** | Enter or **Sym**, Backspace or **Num**, Delete or **Apps** |

**Tools** layer (hold **V**): **I** dictates tidied text, **O** dictates a
command, **K** speaks to the agent, **L** opens the agent session, **Ö** stops
the agent, **M** dictates, and **T** opens the inbox. Hold **I**, **O**, **K**
and **M** while you speak.

**Apps** layer (hold **.**): **C** copies the latest transcript, **V** starts
or stops a meeting recording, **M** toggles agent speech, and **'** toggles
dictation.

While the Charybdis Nano keyboard (USB `A8F8:1832`) is connected, the layout
pauses and keeps English (US). On it, **Ctrl+Shift+D** holds dictation and
**Ctrl+Shift+G** holds agent speech.

**Chords.** Hold Ctrl+Alt+Shift and tap a letter. On the laptop, hold the
home-row mods **R S T** or **I E N** with one hand and tap the letter with the
other. The letters are the same on both keyboards. While you hold the chord,
the bar shows each target's letter. App chords focus the app, cycle its
windows, or start it. The app letters follow `APPS` in `config.py`. Held for 600 ms without a
letter, a panel lists every chord.

| chord | does |
|---|---|
| ⌃⌥⇧ **N** | Focus ← |
| ⌃⌥⇧ **E** | Focus ↓ |
| ⌃⌥⇧ **I** | Focus ↑ |
| ⌃⌥⇧ **O** | Focus → |
| ⌃⌥⇧ **J** | Desk 1 |
| ⌃⌥⇧ **L** | Desk 2 |
| ⌃⌥⇧ **U** | Desk 3 |
| ⌃⌥⇧ **Y** | Desk 4 |
| ⌃⌥⇧ **K** | Desk ← |
| ⌃⌥⇧ **H** | Desk → |
| ⌃⌥⇧ **M** | Zoom |
| ⌃⌥⇧ **Q** | Terminal |
| ⌃⌥⇧ **W** | Browser |
| ⌃⌥⇧ **F** | Outlook |
| ⌃⌥⇧ **P** | Teams |
| ⌃⌥⇧ **B** | Files |
| ⌃⌥⇧ **A** | Code |
| ⌃⌥⇧ **R** | Notepad |
| ⌃⌥⇧ **S** | Excel |
| ⌃⌥⇧ **T** | Word |
| ⌃⌥⇧ **G** | PowerPoint |
| ⌃⌥⇧ **X** | Pause place |
| ⌃⌥⇧ **C** | Windows |
| ⌃⌥⇧ **D** | Re-place |
| ⌃⌥⇧ **V** | Min |

**Snippets.** Type a trigger and Workspace replaces it: `,,date`, `,,time`,
`,,now`, `,,week`, `,,shrug`, `,,thx`, `,,mvh` and `,,br`. Add your own in
`config.py`.

Workspace keeps the Windows taskbar hidden. Tap the Windows key to show it and
open Start, and tap it again to hide it.

## The bar and the tray

The floating bar sits at the top of the main screen. Its centre shows only live
activity: dictation, transcription, agent work with **Stop**, a meeting
recording, a question waiting for you, or a short notice of the agent's news.
On the left are the **Canvas** button, the Outlook and Teams web apps, the
desktop pager and the running apps. On the right are the keyboard state,
volume, Wi-Fi, the clock and the battery. Click the clock or battery to open the
controls menu. The bell lists pending questions and recent notices. See
[the island bar](docs/toolbar-design.md) for the full policy.

The tray dot is green when the layout is on, grey when it is off, red while
listening, amber while working or waiting for you, and blue while the agent is
on a task. Its menu has **Undo the last update**, **Usage report**, **Open logs
folder**, **Restart assistant** and **Quit Workspace**.

Workspace places each app's windows without overlap for the connected monitors
and creates virtual desktops as needed. See
[window placement](docs/window-placement.md).

## The agent

Hold **N** and speak to the agent. **Hold V + L** opens the agent session. The agent works on the
desktop, in files, in PowerShell, and in its own headless Edge profile at
`%LOCALAPPDATA%\workspace\browser-profile`, where it uses Outlook, Teams and AIP
Kanban. It runs without confirmation prompts and stops after 80 steps. It asks
questions in the bar, and you answer by holding **N**. It collects work,
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
