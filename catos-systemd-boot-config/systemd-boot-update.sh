#!/bin/sh
set -eu

if [ -e /run/calamares/bootloadu-installing ]; then
    echo "systemd-boot update deferred while bootloadu is preparing the installed system"
    exit 0
fi

exec /usr/bin/flock /run/lock/boot-partition.lock /usr/bin/systemctl restart systemd-boot-update.service
