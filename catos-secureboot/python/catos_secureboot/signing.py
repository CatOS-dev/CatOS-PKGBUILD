from __future__ import annotations

import glob
import os
from pathlib import Path

from .system import Runner


class SigningError(RuntimeError):
    pass


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

    def sign_pe(self, path: Path) -> bool:
        if self.verify_pe(path):
            return False
        temporary = path.with_name(path.name + ".catos-secureboot.tmp")
        temporary.unlink(missing_ok=True)
        try:
            self.runner.run(
                [
                    "sbsign",
                    "--key",
                    str(self.key),
                    "--cert",
                    str(self.certificate),
                    "--output",
                    str(temporary),
                    str(path),
                ]
            )
            if not self.verify_pe(temporary):
                raise SigningError(f"signature verification failed for {path}")
            os.chmod(temporary, path.stat().st_mode & 0o7777)
            os.replace(temporary, path)
            return True
        finally:
            temporary.unlink(missing_ok=True)


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
