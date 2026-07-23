from __future__ import annotations

from pathlib import Path

from .system import Runner


DEFAULT_GRUB_MODULE_DIRECTORY = Path("/usr/lib/grub/x86_64-efi")
DEFAULT_GRUB_SBAT_PATH = Path("/usr/share/grub/sbat.csv")


def discover_grub_modules(module_directory: Path) -> tuple[str, ...]:
    if not module_directory.is_dir():
        raise FileNotFoundError(f"GRUB platform module directory is missing: {module_directory}")
    modules = tuple(sorted(path.stem for path in module_directory.glob("*.mod") if path.is_file()))
    if not modules:
        raise RuntimeError(f"no GRUB modules were found in {module_directory}")
    return modules


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
    modules = discover_grub_modules(module_directory)
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
