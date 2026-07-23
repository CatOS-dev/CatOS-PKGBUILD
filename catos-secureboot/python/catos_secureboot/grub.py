from __future__ import annotations

from pathlib import Path

from .system import Runner


DEFAULT_GRUB_MODULE_DIRECTORY = Path("/usr/lib/grub/x86_64-efi")
DEFAULT_GRUB_SBAT_PATH = Path("/usr/share/grub/sbat.csv")

# Based on the Debian GRUB 2.14 normal-disk Secure Boot image, extended for
# filesystems, compression formats and TPM2/LUKS2 paths supported by CatOS.
# Native disk-controller modules are deliberately excluded: UEFI GRUB should
# use firmware Block I/O rather than preloading nativedisk/AHCI/ATA/USB stacks.
GRUB_PRELOAD_MODULES = tuple(
    sorted(
        {
            "argon2",
            "bli",
            "blsuki",
            "boot",
            "btrfs",
            "cat",
            "chain",
            "configfile",
            "cpuid",
            "cryptodisk",
            "echo",
            "efi_gop",
            "efi_uga",
            "efifwsetup",
            "efinet",
            "erofs",
            "exfat",
            "ext2",
            "f2fs",
            "fat",
            "file",
            "font",
            "gcry_arcfour",
            "gcry_aria",
            "gcry_blake2",
            "gcry_blowfish",
            "gcry_camellia",
            "gcry_cast5",
            "gcry_crc",
            "gcry_des",
            "gcry_dsa",
            "gcry_gost28147",
            "gcry_gostr3411_94",
            "gcry_hwfeatures",
            "gcry_idea",
            "gcry_kdf",
            "gcry_keccak",
            "gcry_md4",
            "gcry_md5",
            "gcry_rfc2268",
            "gcry_rijndael",
            "gcry_rmd160",
            "gcry_rsa",
            "gcry_salsa20",
            "gcry_seed",
            "gcry_serpent",
            "gcry_sha1",
            "gcry_sha256",
            "gcry_sha512",
            "gcry_sm3",
            "gcry_sm4",
            "gcry_stribog",
            "gcry_tiger",
            "gcry_twofish",
            "gcry_whirlpool",
            "gettext",
            "gfxmenu",
            "gfxterm",
            "gfxterm_background",
            "gzio",
            "halt",
            "help",
            "hfsplus",
            "iso9660",
            "jpeg",
            "json",
            "keystatus",
            "linux",
            "loadenv",
            "loopback",
            "ls",
            "lsefi",
            "lsefimmap",
            "lsefisystab",
            "lssal",
            "luks",
            "luks2",
            "lvm",
            "lzopio",
            "mdraid09",
            "mdraid09_be",
            "mdraid1x",
            "minicmd",
            "normal",
            "ntfs",
            "ntfscomp",
            "part_apple",
            "part_gpt",
            "part_msdos",
            "parttool",
            "password_pbkdf2",
            "pbkdf2",
            "play",
            "png",
            "probe",
            "raid5rec",
            "raid6rec",
            "reboot",
            "regexp",
            "search",
            "search_fs_file",
            "search_fs_uuid",
            "search_label",
            "serial",
            "sleep",
            "smbios",
            "squash4",
            "test",
            "tpm",
            "tpm2_key_protector",
            "true",
            "video",
            "video_fb",
            "xfs",
            "xzio",
            "zfs",
            "zfscrypt",
            "zfsinfo",
            "zstd",
            "zstdio",
        }
    )
)


def select_grub_modules(module_directory: Path) -> tuple[str, ...]:
    if not module_directory.is_dir():
        raise FileNotFoundError(f"GRUB platform module directory is missing: {module_directory}")
    missing = tuple(name for name in GRUB_PRELOAD_MODULES if not (module_directory / f"{name}.mod").is_file())
    if missing:
        raise RuntimeError(f"GRUB package is missing required preload modules: {', '.join(missing)}")
    return GRUB_PRELOAD_MODULES


def rebuild_grub_core(
    *,
    esp_path: Path,
    boot_path: Path,
    second_stage: Path,
    runner: Runner,
    module_directory: Path = DEFAULT_GRUB_MODULE_DIRECTORY,
    sbat_path: Path = DEFAULT_GRUB_SBAT_PATH,
) -> int:
    if not sbat_path.is_file():
        raise FileNotFoundError(f"GRUB SBAT metadata is missing: {sbat_path}")
    try:
        relative = second_stage.relative_to(esp_path)
    except ValueError as error:
        raise ValueError(f"GRUB second stage is outside the ESP: {second_stage}") from error
    if len(relative.parts) < 3 or relative.parts[0].casefold() != "efi" or relative.name.casefold() != "grubx64.efi":
        raise ValueError(f"unsupported installed GRUB EFI path: {second_stage}")

    bootloader_id = relative.parent.name
    modules = select_grub_modules(module_directory)
    runner.run(
        [
            "grub-install",
            "--target=x86_64-efi",
            f"--directory={module_directory}",
            f"--efi-directory={esp_path}",
            f"--boot-directory={boot_path}",
            f"--bootloader-id={bootloader_id}",
            "--no-nvram",
            "--recheck",
            f"--sbat={sbat_path}",
            f"--modules={' '.join(modules)}",
        ]
    )
    if not second_stage.is_file():
        raise RuntimeError(f"grub-install did not create the expected EFI image: {second_stage}")
    return len(modules)
