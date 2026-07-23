from __future__ import annotations

from pathlib import Path

from .config import Config
from .model import ProbeResult
from .modules import discover_external_modules
from .signing import Signer, discover_efi_targets, discover_kernel_targets
from .state import State
from .system import Runner


def efivar_enabled(name: str) -> bool:
    root = Path("/sys/firmware/efi/efivars")
    matches = list(root.glob(name + "-*")) if root.is_dir() else []
    if not matches:
        return False
    data = matches[0].read_bytes()
    return len(data) >= 5 and data[4] == 1


def module_signature_enforced() -> bool:
    for path in (
        Path("/sys/module/module/parameters/sig_enforce"),
        Path("/proc/sys/kernel/module_sig_enforce"),
    ):
        if path.is_file():
            return path.read_text(encoding="utf-8").strip().casefold() in {"1", "y", "yes", "true"}
    return False


def certificate_enrolled(config: Config, runner: Runner) -> bool:
    if not config.certificate_der.is_file():
        return False
    return runner.run(["mokutil", "--test-key", str(config.certificate_der)], check=False).returncode == 0


def signatures_valid(config: Config, runner: Runner) -> bool:
    if not config.certificate_pem.is_file():
        return False
    signer = Signer(key=config.private_key, certificate=config.certificate_pem, runner=runner)
    efi_targets = discover_efi_targets(config.esp_path, config.efi_globs)
    if not efi_targets or not all(signer.verify_pe(path) for path in efi_targets):
        return False
    kernel_targets = discover_kernel_targets(config.kernel_globs)
    if not kernel_targets or not all(signer.verify_pe(path) for path in kernel_targets):
        return False
    subject = runner.run(
        ["openssl", "x509", "-in", str(config.certificate_pem), "-noout", "-subject"],
        check=False,
    ).stdout.strip()
    common_name = subject.partition("CN = ")[2].strip()
    if not common_name:
        return False
    modules = discover_external_modules(config.module_root, config.module_directories)
    for module in modules:
        module_signer = runner.run(["modinfo", "-F", "signer", str(module)], check=False).stdout.strip()
        if common_name not in module_signer:
            return False
    return True


def probe(config: Config, runner: Runner) -> ProbeResult:
    state = State.load(config.state_path)
    enrolled = certificate_enrolled(config, runner)
    return ProbeResult(
        secure_boot_enabled=efivar_enabled("SecureBoot"),
        key_exists=config.private_key.is_file() and config.certificate_pem.is_file() and config.certificate_der.is_file(),
        certificate_enrolled=enrolled,
        certificate_pending=state.enrollment_pending and not enrolled,
        signatures_valid=signatures_valid(config, runner),
        module_signature_enforced=module_signature_enforced(),
    )
