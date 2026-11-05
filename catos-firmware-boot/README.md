# catos-firmware-boot

The package builds UKIs or deploys EFI-stub kernels from installed kernels under
`/usr/lib/modules`. It owns artifact generation and its recorded deployments.
The caller owns destination selection and supplies any requested firmware
registration coordinates. No partition discovery, filesystem-type check,
partition-type check, or mountpoint check is performed.

## Configuration

`/etc/catos/firmware-boot.conf` uses INI syntax:

```ini
[boot]
method = uki
esp_path = /path/to/output
label_prefix = CatOS
default_kernel = linux
efi_disk =
efi_partition = 0
firmware_directory = /
install_fallback = no
```

`method` is `disabled`, `uki`, or `efistub`. `esp_path` is the output root and may
be any directory, including an ordinary directory on a non-EFI filesystem. The
program creates it when needed. Files are placed beneath `EFI/Linux` for UKIs
and `EFI/CatOS/<kernel>` for EFI-stub deployments. Each stub pair occupies an
immutable content-addressed subdirectory so a failed preparation does not mix
an old initramfs with a new kernel. The current paths are recorded in
`.catos-firmware-boot/<method>.json` under the output root.

The package enumerates kernels before generating initramfs. For each installed
version it invokes `mkinitcpio --kernel <version> --generate <private-path>
--nopost`, using the system mkinitcpio configuration and drop-ins. This avoids
running unrelated boot providers' post hooks or relying on pre-existing files
in `/boot`. Microcode inclusion follows mkinitcpio's configured hooks. UKIs are
built with `ukify`, which reads its own signing configuration. Kernel parameters
come from `/etc/kernel/cmdline`. Multiple versions of the same package receive
separate names containing the kernel version.

Providing both `efi_disk` and a positive `efi_partition` requests firmware
registration through `efibootmgr`. `firmware_directory` is the absolute directory
within that partition corresponding to the output root; the caller supplies it
when deploying into a subdirectory. These values are supplied by the caller, not
discovered or used to validate the output directory. Leaving them unset performs
file deployment only. `--no-variables` suppresses all firmware access even when
coordinates are configured. Enabling `install_fallback` explicitly copies the
selected UKI to `EFI/BOOT/BOOT*.EFI`; it defaults to `no`.

## Commands

```sh
catos-firmware-boot-update
catos-firmware-boot-update --config /path/to/firmware-boot.conf --no-variables
catos-firmware-boot-update --verify --no-variables
```

`--force` runs during the Calamares installation marker. The pacman hook calls
`--hook` for kernel, initcpio and firmware changes. Both manual invocations and
hooks use the same generation path and configuration.

The GUI uses the same executable to read and change settings; it does not parse
INI or build images independently:

```sh
catos-firmware-boot-update --describe
catos-firmware-boot-update --configure-only --cmdline='root=UUID=example rw'
catos-firmware-boot-update --method uki --output-root /any/directory --efi-disk '' --efi-partition 0 --no-variables --save-config
```

`--describe` prints JSON without writes, firmware access, or image generation.
`--configure-only` updates the native configuration using Python's INI parser;
`--cmdline` updates `/etc/kernel/cmdline`. Configuration changes preserve unrelated
INI sections and keys. Deployment overrides are persisted with `--save-config`
only after generation and verification succeed. `--method` without `--save-config`
lets a rebuild target a specific method without changing the hook's selected method.

Firmware entries are created before old owned entries are retired. Existing
boot order is preserved and an owned replacement keeps its predecessor's slot.
Unchanged owned entries are reused. Current and next-boot entries retain their
referenced files. A failed firmware operation leaves earlier entries available.
Files and entries are cleaned only from this tool's deployment records; label
prefixes and directory names never establish ownership. Modified files and
reassigned firmware entries are retained. UKI and stub records are separate.

When CatOS machine Secure Boot management owns the UKI chain, this package
builds the UKIs and leaves signing, shim deployment and firmware registration to
`catos-secureboot`. Verification permits that owner's subsequent signature
changes. It does not perform that owner's signature verification.

## Tests

Run `python -B test_update.py`. The package's `check()` runs the same regression
tests. They exercise ordinary-directory deployment, per-version generation,
failed-build preservation, firmware failure and retry ordering, ownership-based
cleanup, and independent UKI/stub deployment records. External programs and
firmware variables are simulated in these unit tests.
