// Workspace's Miryoku keymap for the Charybdis Nano (3x5), based on
// manna-harbour_miryoku (https://github.com/manna-harbour/miryoku, GPL-2.0-or-later).

#pragma once

// The Charybdis Nano's matrix, as manna-harbour_miryoku maps it: three left
// thumbs, two right thumbs; the missing right outer thumb is a thumb combo.
#define LAYOUT_miryoku( \
K00,   K01,   K02,   K03,   K04,          K05,   K06,   K07,   K08,   K09, \
K10,   K11,   K12,   K13,   K14,          K15,   K16,   K17,   K18,   K19, \
K20,   K21,   K22,   K23,   K24,          K25,   K26,   K27,   K28,   K29, \
N30,   N31,   K32,   K33,   K34,          K35,   K36,   K37,   N38,   N39 \
) \
LAYOUT_charybdis_3x5( \
K00,   K01,   K02,   K03,   K04,          K05,   K06,   K07,   K08,   K09, \
K10,   K11,   K12,   K13,   K14,          K15,   K16,   K17,   K18,   K19, \
K20,   K21,   K22,   K23,   K24,          K25,   K26,   K27,   K28,   K29, \
              K32,   K33,   K34,          K35,   K36 \
)

// The outer left thumb taps Esc and, held, holds F24: Workspace's Apps key.
// While it is held, Workspace reads the next key as the laptop's Apps layer
// reads that place (README, "The keys"). Media stays reachable through
// Miryoku's thumb combo: Space and Tab together.
#define WS_APPS LT(U_BASE, KC_ESC)

// Miryoku's Colemak-DH base, with the outer left thumb as WS_APPS.
#define MIRYOKU_LAYER_BASE \
KC_Q,              KC_W,              KC_F,              KC_P,              KC_B,              KC_J,              KC_L,              KC_U,              KC_Y,              KC_QUOT,           \
LGUI_T(KC_A),      LALT_T(KC_R),      LCTL_T(KC_S),      LSFT_T(KC_T),      KC_G,              KC_M,              LSFT_T(KC_N),      LCTL_T(KC_E),      LALT_T(KC_I),      LGUI_T(KC_O),      \
LT(U_BUTTON,KC_Z), ALGR_T(KC_X),      KC_C,              KC_D,              KC_V,              KC_K,              KC_H,              KC_COMM,           ALGR_T(KC_DOT),    LT(U_BUTTON,KC_SLSH),\
U_NP,              U_NP,              WS_APPS,           LT(U_NAV,KC_SPC),  LT(U_MOUSE,KC_TAB),LT(U_SYM,KC_ENT),  LT(U_NUM,KC_BSPC), LT(U_FUN,KC_DEL),  U_NP,              U_NP
