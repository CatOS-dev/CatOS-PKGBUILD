from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .system import Runner


MODULE_SUFFIXES = (".ko", ".ko.zst", ".ko.xz", ".ko.gz")


def discover_external_modules(module_root: Path, directories: tuple[str, ...]) -> list[Path]:
    modules: set[Path] = set()
    if not module_root.is_dir():
        return []
    for version in module_root.iterdir():
        if not version.is_dir():
            continue
        for directory in directories:
            root = version / directory
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.name.endswith(MODULE_SUFFIXES):
                    modules.add(path)
    return sorted(modules, key=lambda path: str(path))


def kernel_version_for(path: Path, module_root: Path) -> str:
    return path.relative_to(module_root).parts[0]


def find_sign_file(module_root: Path, version: str) -> Path:
    candidates = (
        module_root / version / "build/scripts/sign-file",
        Path(f"/usr/src/linux-headers-{version}/scripts/sign-file"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"sign-file is missing for kernel {version}")


def _decompress(source: Path, destination: Path) -> str:
    suffix = source.suffix.casefold()
    if suffix == ".zst":
        command = ["zstd", "-q", "-d", "-c", str(source)]
        compression = "zst"
    elif suffix == ".xz":
        command = ["xz", "-d", "-c", str(source)]
        compression = "xz"
    elif suffix == ".gz":
        command = ["gzip", "-d", "-c", str(source)]
        compression = "gz"
    else:
        shutil.copy2(source, destination)
        return "none"
    with destination.open("wb") as output:
        subprocess.run(command, check=True, stdout=output)
    return compression


def _compress(source: Path, destination: Path, compression: str) -> None:
    if compression == "none":
        shutil.copy2(source, destination)
        return
    commands = {
        "zst": ["zstd", "-q", "-19", "-T0", "-c", str(source)],
        "xz": ["xz", "-c", "-9", str(source)],
        "gz": ["gzip", "-n", "-c", "-9", str(source)],
    }
    with destination.open("wb") as output:
        subprocess.run(commands[compression], check=True, stdout=output)


def sign_module(path: Path, *, module_root: Path, key: Path, certificate: Path, runner: Runner) -> bool:
    signer = runner.run(["modinfo", "-F", "signer", str(path)], check=False).stdout.strip()
    fingerprint = runner.run(
        ["openssl", "x509", "-in", str(certificate), "-noout", "-subject"],
        check=False,
    ).stdout.strip()
    common_name = fingerprint.partition("CN = ")[2].strip()
    if signer and common_name and common_name in signer:
        return False
    version = kernel_version_for(path, module_root)
    sign_file = find_sign_file(module_root, version)
    temporary_dir = Path(tempfile.mkdtemp(prefix="catos-secureboot-module.", dir=path.parent))
    raw = temporary_dir / "module.ko"
    output = path.with_name(path.name + ".catos-secureboot.tmp")
    try:
        compression = _decompress(path, raw)
        runner.run([str(sign_file), "sha256", str(key), str(certificate), str(raw)])
        _compress(raw, output, compression)
        os.chmod(output, path.stat().st_mode & 0o7777)
        os.replace(output, path)
        verified = runner.run(["modinfo", "-F", "signer", str(path)], check=False).stdout.strip()
        if not verified:
            raise RuntimeError(f"signed module has no signer metadata: {path}")
        return True
    finally:
        output.unlink(missing_ok=True)
        shutil.rmtree(temporary_dir, ignore_errors=True)
