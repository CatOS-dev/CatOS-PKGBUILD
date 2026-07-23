from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile

from .system import Runner


class EfiError(RuntimeError):
    pass


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.resolve() == destination.resolve():
            return
    except FileNotFoundError:
        pass
    fd, temporary_name = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def select_second_stage(esp: Path, candidates: tuple[str, ...]) -> Path:
    for candidate in candidates:
        path = esp / candidate.lstrip("/")
        if path.is_file():
            return path
    raise EfiError("no configured bootloader is available as shim second stage")


def deploy_boot_chain(
    *,
    esp: Path,
    shim: Path,
    mok_manager: Path,
    second_stage: Path,
    certificate: Path,
) -> tuple[Path, ...]:
    required = (shim, mok_manager, second_stage, certificate)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise EfiError("missing boot-chain files: " + ", ".join(missing))
    destinations = {
        esp / "EFI/BOOT/BOOTX64.EFI": shim,
        esp / "EFI/BOOT/mmx64.efi": mok_manager,
        esp / "EFI/BOOT/grubx64.efi": second_stage,
        esp / "EFI/CatOS/shimx64.efi": shim,
        esp / "EFI/CatOS/mmx64.efi": mok_manager,
        esp / "EFI/CatOS/grubx64.efi": second_stage,
        esp / "EFI/CatOS/catos-machine.cer": certificate,
        esp / "catos-machine.cer": certificate,
    }
    for destination, source in destinations.items():
        atomic_copy(source, destination)
    return tuple(destinations)


def _efi_entries(runner: Runner) -> list[tuple[str, str]]:
    result = runner.run(["efibootmgr"], check=False)
    if result.returncode != 0:
        raise EfiError(result.stderr.strip() or "efibootmgr failed")
    entries: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        match = re.match(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.+)$", line)
        if not match:
            continue
        label = match.group(2).split("\t", 1)[0].rstrip()
        entries.append((match.group(1), label))
    return entries


def detect_esp_partition(esp: Path, runner: Runner) -> tuple[str, int]:
    source = runner.run(["findmnt", "-n", "-o", "SOURCE", "--target", str(esp)]).stdout.strip()
    if not source.startswith("/dev/"):
        raise EfiError(f"cannot identify ESP block device: {source or '<empty>'}")
    parent = runner.run(["lsblk", "-nro", "PKNAME", source]).stdout.strip()
    part_number = runner.run(["lsblk", "-nro", "PARTN", source]).stdout.strip()
    if not parent or not part_number.isdigit():
        raise EfiError(f"cannot identify ESP parent disk and partition: {source}")
    return f"/dev/{parent}", int(part_number)


def register_boot_entry(*, esp: Path, label: str, runner: Runner) -> None:
    disk, partition = detect_esp_partition(esp, runner)
    for number, existing_label in _efi_entries(runner):
        if existing_label == label:
            runner.run(["efibootmgr", "--bootnum", number, "--delete-bootnum"])
    runner.run(
        [
            "efibootmgr",
            "--create",
            "--disk",
            disk,
            "--part",
            str(partition),
            "--label",
            label,
            "--loader",
            "\\EFI\\CatOS\\shimx64.efi",
        ]
    )
