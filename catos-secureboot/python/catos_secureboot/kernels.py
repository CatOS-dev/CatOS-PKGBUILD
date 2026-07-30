from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex

from .efi import atomic_copy
from .signing import Signer


_ASSIGNMENT = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")


@dataclass(frozen=True)
class KernelCopy:
    canonical: Path
    package: str
    deployed: Path


def _pkgbase(canonical: Path) -> str:
    path = canonical.parent / "pkgbase"
    if not path.is_file():
        raise RuntimeError(f"kernel pkgbase metadata is missing: {path}")
    package = path.read_text(encoding="utf-8").strip()
    if not package or "/" in package:
        raise RuntimeError(f"kernel pkgbase metadata is invalid: {path}")
    return package


def _preset_kver_values(path: Path, package: str) -> tuple[Path, ...]:
    if not path.is_file():
        return ()
    values: list[Path] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name != "ALL_kver" and not name.endswith("_kver"):
            continue
        try:
            tokens = shlex.split(match.group("value"), comments=True, posix=True)
        except ValueError as error:
            raise RuntimeError(f"invalid mkinitcpio preset assignment in {path}: {line}") from error
        if len(tokens) != 1:
            continue
        value = (
            tokens[0]
            .replace("%PKGBASE%", package)
            .replace("${pkgbase}", package)
            .replace("$pkgbase", package)
        )
        candidate = Path(value)
        if candidate.is_absolute():
            values.append(candidate)
    return tuple(dict.fromkeys(values))


def _deployed_paths(package: str, *, boot_path: Path, preset_dir: Path) -> tuple[Path, ...]:
    preset = preset_dir / f"{package}.preset"
    configured = _preset_kver_values(preset, package)
    deployed: list[Path] = []
    for path in configured:
        try:
            relative = path.relative_to("/boot")
        except ValueError:
            continue
        deployed.append(boot_path / relative)
    if deployed:
        return tuple(dict.fromkeys(deployed))
    return (boot_path / f"vmlinuz-{package}",)


def discover_grub_kernel_copies(
    canonical_kernels: list[Path],
    *,
    boot_path: Path,
    preset_dir: Path,
) -> tuple[KernelCopy, ...]:
    copies: list[KernelCopy] = []
    owners: dict[Path, Path] = {}
    for canonical in sorted(canonical_kernels, key=str):
        package = _pkgbase(canonical)
        for deployed in _deployed_paths(package, boot_path=boot_path, preset_dir=preset_dir):
            previous = owners.get(deployed)
            if previous is not None and previous != canonical:
                raise RuntimeError(
                    f"multiple installed kernels map to the same GRUB kernel path: {previous}, {canonical} -> {deployed}"
                )
            owners[deployed] = canonical
            copies.append(KernelCopy(canonical=canonical, package=package, deployed=deployed))
    return tuple(copies)


def deploy_grub_kernel_copies(copies: tuple[KernelCopy, ...]) -> int:
    changed = 0
    for copy in copies:
        if copy.deployed.is_file() and copy.deployed.read_bytes() == copy.canonical.read_bytes():
            continue
        atomic_copy(copy.canonical, copy.deployed)
        changed += 1
    return changed


def verify_grub_kernel_copies(copies: tuple[KernelCopy, ...], signer: Signer) -> int:
    if not copies:
        raise RuntimeError("no GRUB kernel deployment target was found")
    for copy in copies:
        if not copy.deployed.is_file():
            raise RuntimeError(f"GRUB kernel copy is missing: {copy.deployed}")
        if copy.deployed.read_bytes() != copy.canonical.read_bytes():
            raise RuntimeError(
                f"GRUB kernel copy is stale or differs from the signed canonical kernel: {copy.deployed}"
            )
        if not signer.verify_pe(copy.deployed):
            raise RuntimeError(f"GRUB kernel copy is not signed by the machine key: {copy.deployed}")
    return len(copies)
