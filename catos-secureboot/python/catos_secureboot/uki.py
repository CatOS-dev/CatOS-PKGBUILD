from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
import re


class UkiError(RuntimeError):
    pass


@dataclass(frozen=True)
class DirectUkiConfig:
    label_prefix: str
    default_kernel: str


def load_direct_uki_config(path: Path) -> DirectUkiConfig | None:
    if not path.is_file():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        loaded = parser.read(path)
    except configparser.Error as error:
        raise UkiError(f"cannot parse direct firmware boot configuration {path}: {error}") from error
    if not loaded or "boot" not in parser:
        raise UkiError(f"direct firmware boot configuration has no [boot] section: {path}")
    section = parser["boot"]
    if section.get("method", "disabled").strip().casefold() != "uki":
        return None
    label_prefix = section.get("label_prefix", "CatOS").strip() or "CatOS"
    default_kernel = section.get("default_kernel", "linux").strip() or "linux"
    return DirectUkiConfig(label_prefix=label_prefix, default_kernel=default_kernel)


def discover_direct_ukis(esp: Path) -> dict[str, Path]:
    directory = esp / "EFI/Linux"
    ukis: dict[str, Path] = {}
    for path in sorted(directory.glob("catos-*.efi")) if directory.is_dir() else []:
        package = path.name.removeprefix("catos-").removesuffix(".efi")
        if not package or not re.fullmatch(r"[A-Za-z0-9._+\-]+", package):
            raise UkiError(f"invalid CatOS UKI package name: {path.name}")
        ukis[package] = path
    return ukis


def select_default_uki(ukis: dict[str, Path], requested: str) -> str:
    if not ukis:
        raise UkiError("no CatOS UKIs were generated under EFI/Linux")
    return requested if requested in ukis else sorted(ukis)[0]
