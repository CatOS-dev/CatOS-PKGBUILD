#!/bin/bash

if [ -n "$WAYLAND_DISPLAY" ]; then
    export XMODIFIERS=@im=fcitx
elif [ -n "$DISPLAY" ]; then
    export GTK_IM_MODULE=fcitx
    export QT_IM_MODULE=fcitx
    export XMODIFIERS=@im=fcitx
    export SDL_IM_MODULE=fcitx
fi