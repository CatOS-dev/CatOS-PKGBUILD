from __future__ import annotations

from dataclasses import dataclass
import glob
import os
from pathlib import Path
import shutil
import struct

from .system import Runner


class SigningError(RuntimeError):
    pass


@dataclass(frozen=True)
class _PeSection:
    name: str
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_offset: int


@dataclass(frozen=True)
class _PeLayout:
    image_base: int
    section_alignment: int
    sections: tuple[_PeSection, ...]

    @property
    def next_section_vma(self) -> int:
        end = max(
            (section.virtual_address + max(section.virtual_size, section.raw_size) for section in self.sections),
            default=self.section_alignment,
        )
        aligned = (end + self.section_alignment - 1) // self.section_alignment * self.section_alignment
        return self.image_base + aligned


def _pe_layout(data: bytes) -> _PeLayout:
    if len(data) < 0x40 or data[0:2] != b"MZ":
        raise SigningError("image is not a DOS/PE executable")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise SigningError("image does not contain a valid PE header")
    coff = pe_offset + 4
    section_count = struct.unpack_from("<H", data, coff + 2)[0]
    optional_size = struct.unpack_from("<H", data, coff + 16)[0]
    optional = coff + 20
    if optional + optional_size > len(data) or optional_size < 40:
        raise SigningError("image contains a truncated PE optional header")
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic == 0x20B:
        image_base = struct.unpack_from("<Q", data, optional + 24)[0]
    elif magic == 0x10B:
        image_base = struct.unpack_from("<I", data, optional + 28)[0]
    else:
        raise SigningError(f"unsupported PE optional header magic: 0x{magic:04x}")
    section_alignment = struct.unpack_from("<I", data, optional + 32)[0]
    if section_alignment == 0:
        raise SigningError("PE section alignment is zero")
    section_table = optional + optional_size
    if section_table + section_count * 40 > len(data):
        raise SigningError("image contains a truncated PE section table")
    sections: list[_PeSection] = []
    for index in range(section_count):
        offset = section_table + index * 40
        name = data[offset : offset + 8].split(b"\0", 1)[0].decode("ascii", errors="strict")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from("<IIII", data, offset + 8)
        if raw_size and raw_offset + raw_size > len(data):
            raise SigningError(f"PE section {name or index} extends beyond the image")
        sections.append(_PeSection(name, virtual_size, virtual_address, raw_size, raw_offset))
    return _PeLayout(image_base, section_alignment, tuple(sections))


def read_pe_section(path: Path, name: str) -> bytes | None:
    data = path.read_bytes()
    layout = _pe_layout(data)
    for section in layout.sections:
        if section.name != name:
            continue
        size = section.virtual_size or section.raw_size
        return data[section.raw_offset : section.raw_offset + min(size, section.raw_size)]
    return None


def _validate_sbat(payload: bytes, *, source: str) -> None:
    try:
        text = payload.rstrip(b"\0").decode("utf-8")
    except UnicodeDecodeError as error:
        raise SigningError(f"invalid UTF-8 SBAT metadata in {source}") from error
    lines = [line for line in text.splitlines() if line]
    if not lines or not lines[0].startswith("sbat,1,"):
        raise SigningError(f"SBAT metadata in {source} has no version header")
    for line in lines:
        fields = line.split(",")
        if len(fields) != 6 or not fields[0] or not fields[1].isdigit():
            raise SigningError(f"invalid SBAT record in {source}: {line}")


def ensure_sbat(path: Path, source: Path, runner: Runner) -> bool:
    existing = read_pe_section(path, ".sbat")
    if existing is not None:
        _validate_sbat(existing, source=str(path))
        return False
    if not source.is_file():
        raise FileNotFoundError(f"SBAT metadata source is missing: {source}")
    payload = source.read_bytes()
    _validate_sbat(payload, source=str(source))
    layout = _pe_layout(path.read_bytes())
    temporary = path.with_name(path.name + ".catos-secureboot-sbat.tmp")
    temporary.unlink(missing_ok=True)
    try:
        runner.run(
            [
                "objcopy",
                "--add-section",
                f".sbat={source}",
                "--set-section-flags",
                ".sbat=contents,alloc,load,readonly,data",
                "--change-section-vma",
                f".sbat=0x{layout.next_section_vma:x}",
                str(path),
                str(temporary),
            ]
        )
        injected = read_pe_section(temporary, ".sbat")
        if injected is None:
            raise SigningError(f"objcopy did not add an SBAT section to {path}")
        _validate_sbat(injected, source=str(temporary))
        if injected.rstrip(b"\0") != payload.rstrip(b"\0"):
            raise SigningError(f"SBAT metadata changed while updating {path}")
        os.chmod(temporary, path.stat().st_mode & 0o7777)
        os.replace(temporary, path)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def second_stage_sbat_source(path: Path) -> Path | None:
    normalized = path.as_posix().casefold()
    name = path.name.casefold()
    if "limine" in normalized:
        return Path("/usr/share/catos-secureboot/sbat/limine.csv")
    if name in {"grubx64.efi", "grubaa64.efi", "grubia32.efi"} or "grub" in normalized:
        return Path("/usr/share/grub/sbat.csv")
    return None


class Signer:
    _VENDOR_NAMES = {
        "mokmanager.efi",
        "fallback.efi",
        "fbx64.efi",
        "fbaa64.efi",
    }

    def __init__(self, *, key: Path, certificate: Path, runner: Runner):
        self.key = key
        self.certificate = certificate
        self.runner = runner

    @classmethod
    def is_vendor_binary(cls, path: Path) -> bool:
        name = path.name.casefold()
        return name.startswith("shim") or name.startswith("mm") or name in cls._VENDOR_NAMES

    @classmethod
    def filter_signable_efi(cls, paths) -> list[Path]:
        return sorted(
            (Path(path) for path in paths if Path(path).is_file() and Path(path).suffix.casefold() == ".efi" and not cls.is_vendor_binary(Path(path))),
            key=lambda path: str(path),
        )

    def verify_pe(self, path: Path) -> bool:
        result = self.runner.run(
            ["sbverify", "--cert", str(self.certificate), str(path)],
            check=False,
        )
        return result.returncode == 0

    def sign_pe(self, path: Path, *, require_sbat: bool = False, sbat_source: Path | None = None) -> bool:
        prepared = path
        prepared_temporary = path.with_name(path.name + ".catos-secureboot-prepared.tmp")
        signed_temporary = path.with_name(path.name + ".catos-secureboot.tmp")
        prepared_temporary.unlink(missing_ok=True)
        signed_temporary.unlink(missing_ok=True)
        try:
            sbat_changed = False
            if require_sbat:
                existing = read_pe_section(path, ".sbat")
                if existing is None:
                    if sbat_source is None:
                        raise SigningError(f"shim second stage has no SBAT metadata: {path}")
                    shutil.copy2(path, prepared_temporary)
                    ensure_sbat(prepared_temporary, sbat_source, self.runner)
                    prepared = prepared_temporary
                    sbat_changed = True
                else:
                    _validate_sbat(existing, source=str(path))
            if not sbat_changed and self.verify_pe(path):
                return False
            self.runner.run(
                [
                    "sbsign",
                    "--key",
                    str(self.key),
                    "--cert",
                    str(self.certificate),
                    "--output",
                    str(signed_temporary),
                    str(prepared),
                ]
            )
            if not self.verify_pe(signed_temporary):
                raise SigningError(f"signature verification failed for {path}")
            if require_sbat:
                payload = read_pe_section(signed_temporary, ".sbat")
                if payload is None:
                    raise SigningError(f"SBAT metadata was lost while signing {path}")
                _validate_sbat(payload, source=str(signed_temporary))
            os.chmod(signed_temporary, path.stat().st_mode & 0o7777)
            os.replace(signed_temporary, path)
            return True
        finally:
            prepared_temporary.unlink(missing_ok=True)
            signed_temporary.unlink(missing_ok=True)


def discover_efi_targets(esp_path: Path, patterns: tuple[str, ...]) -> list[Path]:
    targets: set[Path] = set()
    for pattern in patterns:
        targets.update(path for path in esp_path.glob(pattern) if path.is_file())
    return Signer.filter_signable_efi(targets)


def discover_kernel_targets(patterns: tuple[str, ...]) -> list[Path]:
    targets: set[Path] = set()
    for pattern in patterns:
        for match in glob.glob(pattern):
            path = Path(match)
            if not path.is_file():
                continue
            targets.add(path.resolve())
    return sorted(targets, key=lambda path: str(path))
