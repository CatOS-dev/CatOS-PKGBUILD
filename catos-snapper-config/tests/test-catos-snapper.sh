#!/usr/bin/env bash
set -Eeuo pipefail

project_root=$(cd "$(dirname "$0")/.." && pwd -P)
helper="$project_root/catos-snapper"
hook="$project_root/05-catos-snapper.hook"
pkgbuild="$project_root/PKGBUILD"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_contains() {
    local file=$1 expected=$2
    grep -F -- "$expected" "$file" >/dev/null || fail "$file does not contain: $expected"
}

assert_not_contains() {
    local file=$1 unexpected=$2
    if grep -F -- "$unexpected" "$file" >/dev/null; then
        fail "$file unexpectedly contains: $unexpected"
    fi
}

run_helper() {
    local config=$1 input=$2 log=$3 exit_code=${4:-0} marker=${5:-$tmp/no-install-marker}
    CATOS_SNAPPER_CONFIG_FILE="$config" \
    CATOS_SNAPPER_BIN="$tmp/fake-snapper" \
    CATOS_SNAPPER_INSTALL_MARKER="$marker" \
    FAKE_SNAPPER_LOG="$log" \
    FAKE_SNAPPER_EXIT_CODE="$exit_code" \
        "$helper" <<<"$input"
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/fake-snapper" <<'EOF_FAKE'
#!/usr/bin/env bash
set -eu
{
    printf 'call\n'
    printf '%s\n' "$@"
} >> "$FAKE_SNAPPER_LOG"
exit "${FAKE_SNAPPER_EXIT_CODE:-0}"
EOF_FAKE
chmod 0755 "$tmp/fake-snapper"

[[ -x "$helper" ]] || fail "missing executable helper: $helper"
[[ -f "$hook" ]] || fail "missing ALPM hook: $hook"

cat > "$tmp/config" <<'EOF_CONFIG'
ENABLED=yes
PACKAGE_THRESHOLD=3
SNAPPER_CONFIG=root
EOF_CONFIG

ordinary_log="$tmp/ordinary.log"
run_helper "$tmp/config" $'firefox\nlibfoo' "$ordinary_log"
[[ ! -e "$ordinary_log" ]] || fail 'ordinary small transaction created a snapshot'

large_log="$tmp/large.log"
run_helper "$tmp/config" $'alpha\nbeta\ngamma' "$large_log"
[[ $(grep -c '^call$' "$large_log") -eq 1 ]] || fail 'large transaction did not create exactly one snapshot'
assert_contains "$large_log" '--type'
assert_contains "$large_log" 'single'
assert_contains "$large_log" 'Before large package transaction (3 packages)'
assert_contains "$large_log" 'catos_reason=large-transaction'
assert_contains "$large_log" 'catos_package_count=3'
assert_not_contains "$large_log" 'important=yes'

critical_log="$tmp/critical.log"
run_helper "$tmp/config" $'linux-custom\nusr/lib/modules/6.18.0/vmlinuz' "$critical_log"
[[ $(grep -c '^call$' "$critical_log") -eq 1 ]] || fail 'critical path did not create exactly one snapshot'
assert_contains "$critical_log" 'Before boot-critical package transaction'
assert_contains "$critical_log" 'catos_reason=boot-critical'
assert_contains "$critical_log" 'important=yes'

combined_log="$tmp/combined.log"
run_helper "$tmp/config" $'alpha\nbeta\ngamma\nusr/lib/initcpio/install/base' "$combined_log"
[[ $(grep -c '^call$' "$combined_log") -eq 1 ]] || fail 'combined trigger created more than one snapshot'
assert_contains "$combined_log" 'catos_reason=boot-critical'
assert_contains "$combined_log" 'catos_package_count=3'

duplicate_log="$tmp/duplicate.log"
run_helper "$tmp/config" $'alpha\nalpha\nbeta' "$duplicate_log"
[[ ! -e "$duplicate_log" ]] || fail 'duplicate package targets inflated the transaction count'

cat > "$tmp/disabled.conf" <<'EOF_CONFIG'
ENABLED=no
PACKAGE_THRESHOLD=1
SNAPPER_CONFIG=root
EOF_CONFIG
disabled_log="$tmp/disabled.log"
run_helper "$tmp/disabled.conf" 'usr/lib/modules/6.18.0/vmlinuz' "$disabled_log"
[[ ! -e "$disabled_log" ]] || fail 'disabled policy created a snapshot'

cat > "$tmp/invalid.conf" <<'EOF_CONFIG'
ENABLED=yes
PACKAGE_THRESHOLD=invalid
SNAPPER_CONFIG=root
EOF_CONFIG
install_marker="$tmp/bootloadu-installing"
touch "$install_marker"
installer_log="$tmp/installer.log"
run_helper "$tmp/invalid.conf" $'alpha\nusr/lib/modules/6.18.0/vmlinuz' "$installer_log" 0 "$install_marker"
[[ ! -e "$installer_log" ]] || fail 'installer marker did not suppress transaction snapshots'

if run_helper "$tmp/invalid.conf" 'alpha' "$tmp/invalid.log"; then
    fail 'invalid threshold was accepted'
fi

if run_helper "$tmp/config" $'alpha\nbeta\ngamma' "$tmp/failure.log" 23; then
    fail 'snapper failure was not propagated'
fi

assert_contains "$hook" 'Type = Package'
assert_contains "$hook" 'Target = *'
assert_contains "$hook" 'Type = Path'
assert_contains "$hook" 'Target = usr/lib/modules/*/vmlinuz'
assert_contains "$hook" 'Target = usr/lib/modules/*/pkgbase'
assert_contains "$hook" 'Target = usr/lib/initcpio/*'
assert_contains "$hook" 'Target = usr/lib/firmware/*'
assert_contains "$hook" 'Target = usr/src/*/dkms.conf'
assert_contains "$hook" 'Target = usr/lib/systemd/ukify'
assert_contains "$hook" 'AbortOnFail'
assert_contains "$hook" 'NeedsTargets'
assert_contains "$hook" 'When = PreTransaction'

assert_not_contains "$pkgbuild" "depends=('snapper' 'snap-pac')"
assert_contains "$pkgbuild" "provides=('snap-pac')"
assert_contains "$pkgbuild" "replaces=('snap-pac')"
assert_contains "$pkgbuild" "conflicts=('snap-pac' 'timeshift')"

echo 'PASS: catos-snapper-config transaction policy'
