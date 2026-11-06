# Charybdis Nano firmware

Workspace's keymap for the Charybdis Nano (3x5, USB `A8F8:1832`): Miryoku's own
Charybdis Nano keymap (`manna-harbour_miryoku` in
[miryoku_qmk](https://github.com/manna-harbour/miryoku_qmk)), Colemak-DH, with
one change. The **outer left thumb** taps Esc and, held, holds **F24**:
Workspace's Apps key. While it is held, Workspace reads the next key the way
the laptop's Apps layer reads that place (see "The keys" in the README) and
swallows it, so F24 never reaches an application.

That thumb's Miryoku hold was the Media layer; Media stays reachable with
Miryoku's thumb combo, Space and Tab pressed together. Everything else is stock
Miryoku: Nav on Space, Mouse on Tab, Sym on Enter, Num on Backspace, Fun on the
Enter and Backspace combo.

`keymap/` holds the overlay: `config.h` redefines Miryoku's base layer with
the one thumb changed, and `workspace.c` sends F24 while that thumb is held.

## Build

In WSL, once:

```sh
mkdir -p ~/build ~/.local/opt/arm-gnu-toolchain
curl -sSL https://developer.arm.com/-/media/Files/downloads/gnu/13.3.rel1/binrel/arm-gnu-toolchain-13.3.rel1-x86_64-arm-none-eabi.tar.xz \
  | tar -xJ -C ~/.local/opt/arm-gnu-toolchain --strip-components=1
git clone --depth 1 -b miryoku --recurse-submodules --shallow-submodules \
  https://github.com/manna-harbour/miryoku_qmk.git ~/build/miryoku_qmk
python3 -m venv ~/build/qmk-venv
~/build/qmk-venv/bin/pip install -r ~/build/miryoku_qmk/requirements.txt qmk
```

Then `bash docs/firmware/charybdis-nano/build.sh` writes
`out/bastardkb_charybdis_3x5_v2_splinky_3_workspace.uf2` and the `splinky_2`
one. No admin rights are needed.

## Flash

1. Pick the file for your controller: the Splinky board is marked v2 or v3
   (BastardKB has shipped v3 since 2023). A wrong pick just doesn't type; flash
   the other one.
2. Unplug the keyboard. Plug the **left** half in on its own, then double-tap
   its reset button (or hold BOOT while plugging in). A drive named `RPI-RP2`
   appears. Copy the `.uf2` onto it; the half restarts.
3. Do the same for the **right** half.
4. Reconnect the halves and plug the USB cable into the **right** half (the
   trackball side, `MASTER_RIGHT`).

To go back to BastardKB's stock VIA firmware, flash their `.uf2` the same way.
