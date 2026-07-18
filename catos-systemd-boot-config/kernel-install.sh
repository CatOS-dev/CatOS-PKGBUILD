#!/bin/bash

set -euo pipefail
shopt -s inherit_errexit nullglob

readonly action="${1:?usage: kernel-install.sh add|remove}"
case "$action" in
	add | remove) ;;
	*)
		printf 'unsupported action: %s\n' "$action" >&2
		exit 2
		;;
esac

readonly install_marker=/run/calamares/bootloadu-installing
if [[ -e "$install_marker" ]]; then
	cat >/dev/null
	printf 'kernel-install hook deferred while bootloadu is preparing the installed system\n'
	exit 0
fi

cd /

exec 9>/run/lock/boot-partition.lock
flock 9

all_kernels=0
declare -A versions=()

add_file() {
	local path="$1"
	local kver
	kver="${path##usr/lib/modules/}"
	kver="${kver%%/*}"
	[[ -n "$kver" && "$kver" != "$path" ]] || return 0
	versions["$kver"]=""
}

while IFS= read -r path; do
	case "$action:$path" in
		remove:usr/lib/modules/*/vmlinuz)
			add_file "$path"
			;;
		add:usr/lib/modules/*/vmlinuz | add:usr/lib/modules/*/extramodules/*)
			add_file "$path"
			;;
		add:*)
			all_kernels=1
			;;
	esac
done

if [[ "$action" == add ]] && ((all_kernels)); then
	for file in usr/lib/modules/*/vmlinuz; do
		if pacman -Qqo "$file" >/dev/null 2>&1; then
			add_file "$file"
		fi
	done
fi

ordered_versions=()
if ((${#versions[@]})); then
	mapfile -t ordered_versions < <(printf '%s\n' "${!versions[@]}" | sort -V)
fi

for kver in "${ordered_versions[@]}"; do
	case "$action" in
		add)
			kimage="/usr/lib/modules/$kver/vmlinuz"
			[[ -f "$kimage" ]] || continue
			kernel-install add "$kver" "$kimage"
			;;
		remove)
			kernel-install remove "$kver"
			;;
	esac
done
