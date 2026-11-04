# Keyboard hook watchdog

Windows removes a `WH_KEYBOARD_LL` hook whose callback misses
`LowLevelHooksTimeout` (capped at 1000 ms since Windows 10 1709). It reports
nothing: on Windows 7 and later "there is no way for the application to know
whether the hook is removed"
([LowLevelKeyboardProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc)).
Under heavy desktop load the layout process lost its hook. Remapping, the firmware
keyboard's chords and voice shortcuts stopped until the keeper restarted the
layout. The layout now detects the loss and reinstalls the hook itself.

## Signal

| Option | Keyboard-only | Cost | Decision |
| --- | --- | --- | --- |
| `GetLastInputInfo` | No: mouse input advances it too | One call per timer tick | Rejected. Separating mouse input needs a second signal anyway. |
| `WH_MOUSE_LL` alongside it | Yes, by elimination | A second hook on every mouse move, with the same timeout risk | Rejected. |
| `GetAsyncKeyState` polling | Partly: misses keys pressed and released between polls | 256 calls per tick | Rejected. |
| Raw keyboard input (`RIDEV_INPUTSINK`) | Yes: only the keyboard usage is registered | One posted `WM_INPUT` per key, handled in the message loop outside the hook | Chosen. |

The hidden layout window registers HID usage page 1, usage 6 with
`RIDEV_INPUTSINK`. Raw input reaches it whether or not the hook still runs. The
window is never foreground, so every message is `RIM_INPUTSINK` and needs no
`DefWindowProc` cleanup. Mouse input never produces a keyboard `WM_INPUT`.

## Decision

`miryoku/hook_watch.py` is pure. The hook callback stores only the key's
timestamp in `Keyboard.hook_tick`. Each `WM_INPUT` passes its message time to
`keyboard_input`. The existing 200 ms timer calls `assess` with the hook's newest
key time and the current tick:

- **Answered.** The hook has seen every keyboard input.
- **Unanswered.** Raw input arrived at `since` and the hook has no key within
  1000 ms of it. A hook may legitimately run up to 1000 ms before Windows posts
  the input, so that slack never flags a slow live hook.
- **Probe.** After 250 ms unanswered, the layout taps the unassigned
  `MENU_MASK` key with `LAYOUT_MAGIC`. A live hook sees it and passes it through.
  Workspace already taps this key to stop a lone Alt from opening menus.
- **Reinstall.** The hook has not seen the probe after 1000 ms. Hooks earlier in
  the chain can each hold an event for up to the timeout, so the probe gets the
  same allowance.

A refused probe returns the watch to Answered. Windows refuses `SendInput` on the
secure desktop and into elevated windows. The hook cannot see keys in either
place, so raw input there is not evidence. This keeps the watchdog from reinstalling
while the session is locked or an elevated window is foreground. Raw input also
stops on the lock screen.

Injected input and Workspace's own output (`LAYOUT_MAGIC`, `MAGIC`) pass through
every low-level hook, so they update `hook_tick` exactly like physical keys. They
count as evidence in both directions and cannot make a live hook look dead.

Ticks are 32-bit message times. `offset` compares them across the 49.7-day wrap.

## Effects

`miryoku/win.py` owns the effects. `serve` installs the replacement hook before
removing the dead one. If Windows refuses the replacement, the loop exits with
`Exit.HOOK_REFUSED`, as at startup. `Keyboard.hook_reinstalled` reuses the
release paths: captured firmware shortcuts finish their requests, the engine
releases modifiers, layers, voice and desktop holds, and Workspace output is
released. It also forgets captured shortcut keys, native releases and a held
Escape, because the dead hook dropped their key-ups. A stale Escape press would
otherwise quit the layout on the next tap. The usage log gets an
`input_recovery` record with `phase: hook_reinstall`, `outage_ms` (first unanswered
input to reinstall) and `hook_silent_ms` (the dead hook's last key to reinstall).

After a reinstall the probe's own raw input can arrive late. It causes at most one
more probe, which the new hook answers.

## Measurements

On 2026-11-04, paired synthetic runs used the installed Windows Python 3.15.1
under ordinary desktop load. GC was enabled, and no hook or input was involved.
Four alternating runs of `Keyboard.hook_proc` used eight rounds of 100,000 keys
through a silent platform. They measured a median p50 of 6.4 to 8.6 µs before the
change and 6.2 to 8.0 µs after it. Median p99 was 17.9 to 32.9 µs before and
16.6 to 29.9 µs after. The timestamp store is within noise. `keyboard_input` costs
0.26 to 0.39 µs per `WM_INPUT`, outside the hook. `scripts/benchmark_keyboard.py`
measures only the unchanged engine. It reported the same 2,191-byte traced peak
and no GC collections before and after.

## Open native questions

The documentation does not say whether raw input with `RIDEV_INPUTSINK` reaches
a medium-integrity process while an elevated window is foreground. Either way the
refused probe prevents a reinstall. If raw input does arrive, typing in an
elevated window costs one refused `SendInput` every few hundred milliseconds.
