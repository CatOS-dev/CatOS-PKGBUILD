from __future__ import annotations

from dataclasses import replace
import getpass
import os
import shutil

from .config import Config
from .efi import deploy_boot_chain, register_boot_entry, select_second_stage
from .enforcement import configure_enforcement
from .keys import generate_key_material, random_enrollment_password, request_enrollment
from .model import Phase, evaluate_phase
from .modules import discover_external_modules, kernel_version_for, sign_module
from .probe import probe
from .signing import Signer, discover_efi_targets, discover_kernel_targets
from .state import State
from .system import Runner


class SecureBootService:
    def __init__(self, config: Config, runner: Runner):
        self.config = config
        self.runner = runner

    def require_root(self) -> None:
        if os.geteuid() != 0:
            raise PermissionError("catos-secureboot must run as root")

    def maintain(self) -> dict[str, object]:
        self.require_root()
        if not self.config.private_key.is_file() or not self.config.certificate_pem.is_file():
            return {
                "efi_signed": 0,
                "kernels_signed": 0,
                "modules_signed": 0,
                "deployed": 0,
                "efi_registered": False,
                "skipped": "not-enabled",
            }
        if not self.config.esp_path.is_dir():
            raise FileNotFoundError(f"EFI system partition is not mounted: {self.config.esp_path}")
        for vendor in (self.config.vendor_shim, self.config.vendor_mok_manager):
            if not vendor.is_file():
                raise FileNotFoundError(f"vendor Secure Boot binary is missing: {vendor}")
            if self.runner.run(["sbverify", "--list", str(vendor)], check=False).returncode != 0:
                raise RuntimeError(f"vendor Secure Boot binary is not signed: {vendor}")

        signer = Signer(key=self.config.private_key, certificate=self.config.certificate_pem, runner=self.runner)
        module_changed = 0
        changed_versions: set[str] = set()
        for path in discover_external_modules(self.config.module_root, self.config.module_directories):
            if sign_module(
                path,
                module_root=self.config.module_root,
                key=self.config.private_key,
                certificate=self.config.certificate_pem,
                runner=self.runner,
            ):
                module_changed += 1
                changed_versions.add(kernel_version_for(path, self.config.module_root))
        for version in sorted(changed_versions):
            self.runner.run(["depmod", version])

        configure_enforcement(self.config.cmdline_path, self.config.grub_dropin_path)
        self.runner.run(["mkinitcpio", "-P"])
        grub_config = self.config.boot_path / "grub/grub.cfg"
        if grub_config.is_file() and shutil.which("grub-mkconfig"):
            self.runner.run(["grub-mkconfig", "-o", str(grub_config)])

        kernel_targets = discover_kernel_targets(self.config.kernel_globs)
        if not kernel_targets:
            raise RuntimeError("no installed kernel image was found")
        kernels_signed = sum(int(signer.sign_pe(path)) for path in kernel_targets)

        efi_changed = 0
        for path in discover_efi_targets(self.config.esp_path, self.config.efi_globs):
            efi_changed += int(signer.sign_pe(path))
        second_stage = select_second_stage(
            self.config.esp_path,
            self.config.second_stage_candidates,
        )
        if not signer.verify_pe(second_stage):
            raise RuntimeError(f"shim second stage is not signed by the machine key: {second_stage}")
        deployed = deploy_boot_chain(
            esp=self.config.esp_path,
            shim=self.config.vendor_shim,
            mok_manager=self.config.vendor_mok_manager,
            second_stage=second_stage,
            certificate=self.config.certificate_der,
        )
        registered = False
        if self.config.register_efi:
            register_boot_entry(esp=self.config.esp_path, label=self.config.efi_label, runner=self.runner)
            registered = True
        return {
            "efi_signed": efi_changed,
            "kernels_signed": kernels_signed,
            "modules_signed": module_changed,
            "deployed": len(deployed),
            "efi_registered": registered,
            "skipped": "",
        }

    def enable(self, *, password: str | None, generate_password: bool, enroll: bool = True) -> dict[str, object]:
        self.require_root()
        material = generate_key_material(self.config, self.runner)
        maintenance = self.maintain()
        state = State.load(self.config.state_path)
        result: dict[str, object] = {
            "fingerprint": material.fingerprint,
            "efi_signed": maintenance["efi_signed"],
            "kernels_signed": maintenance["kernels_signed"],
            "modules_signed": maintenance["modules_signed"],
            "deployed": maintenance["deployed"],
            "efi_registered": maintenance["efi_registered"],
            "enrollment_pending": False,
        }
        if enroll:
            if self.runner.run(["mokutil", "--test-key", str(material.certificate_der)], check=False).returncode == 0:
                state = replace(state, enrollment_pending=False, certificate_fingerprint=material.fingerprint, last_error="")
            else:
                if password is None:
                    if generate_password:
                        password = random_enrollment_password()
                    else:
                        first = getpass.getpass("MOK enrollment password: ")
                        second = getpass.getpass("Confirm MOK enrollment password: ")
                        if first != second:
                            raise ValueError("MOK enrollment passwords do not match")
                        password = first
                request_enrollment(material.certificate_der, password, self.runner)
                self.config.enrollment_password_path.parent.mkdir(parents=True, exist_ok=True)
                self.config.enrollment_password_path.write_text(password + "\n", encoding="utf-8")
                os.chmod(self.config.enrollment_password_path, 0o600)
                state = replace(state, enrollment_pending=True, certificate_fingerprint=material.fingerprint, last_error="")
                result["enrollment_password"] = password
                result["enrollment_pending"] = True
        state.write(self.config.state_path)
        return result

    def status(self) -> dict[str, object]:
        result = probe(self.config, self.runner)
        phase = evaluate_phase(result)
        if result.certificate_enrolled:
            state = State.load(self.config.state_path)
            if state.enrollment_pending:
                replace(state, enrollment_pending=False).write(self.config.state_path)
                self.config.enrollment_password_path.unlink(missing_ok=True)
        return {
            "phase": phase.value,
            "secure_boot_enabled": result.secure_boot_enabled,
            "key_exists": result.key_exists,
            "certificate_enrolled": result.certificate_enrolled,
            "certificate_pending": result.certificate_pending,
            "signatures_valid": result.signatures_valid,
            "module_signature_enforced": result.module_signature_enforced,
        }
