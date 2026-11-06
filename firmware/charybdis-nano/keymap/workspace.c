// The Apps key: tap Esc, hold F24 for as long as the thumb is down.

#include QMK_KEYBOARD_H

#include "manna-harbour_miryoku.h"

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    if (keycode == WS_APPS && !record->tap.count) {
        // A hold: QMK would hold the (already active) base layer; send F24 instead.
        if (record->event.pressed) {
            register_code(KC_F24);
        } else {
            unregister_code(KC_F24);
        }
        return false;
    }
    return true;
}
