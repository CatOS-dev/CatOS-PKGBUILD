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
3. signs modules under `updates/` and `extramodules/`, then regenerates initramfs;
4. signs the installed kernel images found through `kernel_globs`;
5. when GRUB is selected, reruns `grub-install` with the CatOS normal-disk Secure Boot module set preloaded into the EFI core and with the distribution SBAT metadata;
6. signs the final EFI artifacts owned by the selected GRUB, systemd-boot or Limine provider;
7. atomically deploys shim, MokManager, the signed second stage and the machine certificate;
8. registers `CatOS Secure Boot` in firmware and submits the machine certificate to `mokutil`;
9. records `enrollment-pending` until MokManager enrollment completes.

For unattended installation, Calamares may use `--generate-enrollment-password` and display the returned one-time password. The password is stored root-only at `/var/lib/catos-secureboot/enrollment-password` until enrollment is observed.

## Configuration

`/etc/catos/secureboot.conf` is TOML. EFI fallback paths are deliberately not scanned as machine-signed payloads because `BOOTX64.EFI` is Fedora shim. Boot providers may override `second_stage_candidates` and `kernel_globs`.

This package does not create, convert to, or update UKIs. If a separately selected boot provider already generates a UKI, its existing file under `EFI/Linux/` is treated only as an ordinary EFI signing target.

## Update integration

The pacman hooks split the lifecycle into two ordered stages. The early stage runs after DKMS and before `mkinitcpio`, signs external modules and canonical kernels, and never touches deployed kernel copies. The final EFI stage runs after bootloader generation. For GRUB it rebuilds `grubx64.efi` with a curated normal-disk module set inside the core image, then signs and deploys the final shim chain. The set covers GRUB configuration, Linux loading, common filesystems, LUKS/LVM/MD RAID, TPM2, compression and the EFI GOP/UGA video path used by generated `load_video` functions, while excluding native disk-controller, raw memory, fallback `all_video` backends and test modules. Limine kernel copies and their recorded hashes are not modified by the final stage.
