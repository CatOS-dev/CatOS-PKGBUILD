# catos-secureboot

`catos-secureboot` owns the installed-system Secure Boot lifecycle for CatOS. It is intentionally separate from Calamares and `bootloadu`.

## Trust model

The CatOS release certificate remains enrolled after booting the live image. This package creates a second, machine-specific MOK for installed kernels, bootloader EFI images and external kernel modules.

The package does not bundle a private release key. It packages a pinned, matching Fedora-signed `shimx64.efi` and `mmx64.efi` pair as immutable vendor inputs and never re-signs them.

## Commands

```text
catos-secureboot enable
catos-secureboot enable --generate-enrollment-password
catos-secureboot status
catos-secureboot verify
catos-secureboot maintain
```

`enable` performs the following transaction:

1. creates a 3072-bit per-machine RSA key and X.509 certificate;
2. enforces `module.sig_enforce=1` and integrity lockdown in the installed boot configuration;
3. signs modules under `updates/` and `extramodules/`, then runs `depmod` for affected kernel versions;
4. signs canonical installed kernels under `/usr/lib/modules/*/vmlinuz` before any provider copies or packages them;
5. refreshes only the selected provider: Limine through `limine-mkinitcpio`, GRUB through `mkinitcpio` and `grub-mkconfig`, or systemd-boot through `kernel-install --entry-type=all add-all`;
6. for systemd-boot Type #1 entries, copies the already signed canonical kernel as the final EFISTUB payload; for Type #2 layouts, lets `kernel-install` and `ukify` generate the final UKI under `EFI/Linux/`;
7. signs the final EFI artifacts owned by the selected GRUB, systemd-boot or Limine provider, including generated UKIs;
8. atomically deploys shim, MokManager, the signed second stage and the machine certificate;
9. registers `CatOS Secure Boot` in firmware and submits the machine certificate to `mokutil`;
10. records `enrollment-pending` until MokManager enrollment completes.

For unattended installation, Calamares may use `--generate-enrollment-password` and display the returned one-time password. The password is stored root-only at `/var/lib/catos-secureboot/enrollment-password` until enrollment is observed.

## Configuration

`/etc/catos/secureboot.conf` is TOML. EFI fallback paths are deliberately not scanned as machine-signed payloads because `BOOTX64.EFI` is Fedora shim. Boot providers may override `second_stage_candidates` and `kernel_globs`.

For systemd-boot, `/etc/kernel/install.conf` selects the payload format. `layout=bls` produces Type #1 entries containing a signed EFISTUB kernel and separate initrd. `layout=uki` invokes `systemd-ukify`, installs Type #2 images under `EFI/Linux/`, and signs the finished UKIs with the machine MOK.

Direct firmware execution of a kernel or UKI is not covered by the MOK trust database: firmware only knows keys enrolled in its `db`. CatOS supports EFISTUB and UKI through the trusted shim → systemd-boot chain. Direct firmware entries require a separate firmware-`db` enrollment design.

## Update integration

The pacman hooks split the lifecycle into two ordered stages. The early stage runs after DKMS and before boot artifact generation, signs external modules and canonical kernels, and never touches deployed kernel copies. The provider generator then consumes those final bytes: Limine records its hash, systemd `kernel-install` copies an EFISTUB or builds a UKI, and GRUB regenerates initramfs/configuration. The final EFI stage signs only EFI payloads and verifies that any systemd-boot Type #1 `linux` copy is byte-for-byte identical to the signed canonical kernel. Limine kernel copies and their recorded hashes are not modified by the final stage.
