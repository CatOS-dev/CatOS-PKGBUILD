hl.config({
    input = {
        -- Empty inherits XKB_DEFAULT_LAYOUT and otherwise falls back to "us".
        kb_layout = "",
        numlock_by_default = true,
        follow_mouse = 0,
        touchpad = {
            tap_to_click = true,
            natural_scroll = true,
        },
    },
})
