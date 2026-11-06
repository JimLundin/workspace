#!/usr/bin/env bash
# Build Workspace's Miryoku firmware for the Charybdis Nano in WSL.
# Needs ~/build/miryoku_qmk (manna-harbour/miryoku_qmk, branch miryoku), the Arm
# GNU toolchain in ~/.local/opt/arm-gnu-toolchain and QMK's Python requirements
# in ~/build/qmk-venv; see README.md. Writes one .uf2 per Splinky revision to out/.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
qmk=~/build/miryoku_qmk
target="$qmk/keyboards/bastardkb/charybdis/3x5/keymaps/workspace"
rm -rf "$target" && mkdir -p "$target" && cp "$here"/keymap/* "$target"/
export PATH="$HOME/.local/opt/arm-gnu-toolchain/bin:$HOME/build/qmk-venv/bin:$PATH"
export QMK_HOME="$qmk"
mkdir -p "$here/out"
for revision in splinky_3 splinky_2; do
  make -C "$qmk" -j"$(nproc)" "bastardkb/charybdis/3x5/v2/$revision:workspace"
  cp "$qmk"/bastardkb_charybdis_3x5_v2_${revision}_workspace.uf2 "$here/out/"
done
ls -la "$here/out"
