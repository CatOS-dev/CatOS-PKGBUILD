from __future__ import annotations

from dataclasses import replace
import getpass
import os
from pathlib import Path
import shutil

from .config import Config
from .efi import deploy_boot_chain, deploy_uki_boot_chains, register_boot_entry, select_second_stage
from .enforcement import configure_enforcement
from .grub import rebuild_grub_core
from .kernels import deploy_grub_kernel_copies, discover_grub_kernel_copies, verify_grub_kernel_copies
from .keys import generate_key_material, random_enrollment_password, request_enrollment
from .model import Phase, evaluate_phase
from .modules import discover_external_modules, kernel_version_for, sign_module
from .probe import probe
from .signing import Signer, discover_efi_targets, discover_kernel_targets, second_stage_sbat_source
from .state import State
from .system import Runner
from .uki import DirectUkiConfig, discover_direct_ukis, load_direct_uki_config, select_default_uki


class SecureBootService:
    def __init__(self, config: Config, runner: Runner):
        self.config = config
        self.runner = runner

    def require_root(self) -> None:
        if os.geteuid() != 0:
            raise PermissionError("catos-secureboot must run as root")

    def _disabled_result(self) -> dict[str, object]:
        return {
            "efi_signed": 0,
            "kernels_signed": 0,
            "modules_signed": 0,
            "deployed": 0,
            "deployed_kernels_verified": 0,
            "efi_registered": False,
            "provider": "",
            "boot_chain_verified": False,
            "skipped": "not-enabled",
        }

    def _enabled(self) -> bool:
        return self.config.private_key.is_file() and self.config.certificate_pem.is_file()

    @staticmethod
    def _bootloader_kind(second_stage: Path) -> str:
        normalized = second_stage.as_posix().casefold()
        name = second_stage.name.casefold()
        if "limine" in normalized:
            return "limine"
        if name.startswith("systemd-boot") or "/efi/systemd/" in normalized:
            return "systemd-boot"
        if name.startswith("grub") or "grub" in normalized:
            return "grub"
        raise RuntimeError(f"unsupported shim second stage: {second_stage}")

    @staticmethod
    def _validate_provider(provider: str) -> str:
        if provider not in {"grub", "limine", "systemd-boot", "uki"}:
            raise ValueError(f"unsupported Secure Boot provider: {provider}")
        return provider

    def _requested_provider(self, provider: str | None) -> str | None:
        selected = provider or State.load(self.config.state_path).provider or None
        return self._validate_provider(selected) if selected is not None else None

    def _select_second_stage_for_provider(self, provider: str) -> Path:
        for candidate in self.config.second_stage_candidates:
            path = self.config.esp_path / candidate.lstrip("/")
            if path.is_file() and self._bootloader_kind(path) == provider:
                return path
        raise RuntimeError(f"no configured {provider} bootloader is available as shim second stage")

    def _resolve_boot_artifacts(
        self,
        *,
        provider: str | None,
        second_stage: Path | None,
        direct_uki: DirectUkiConfig | None,
    ) -> tuple[str, Path | None, DirectUkiConfig | None]:
        selected = self._requested_provider(provider)
        if direct_uki is not None:
            if selected not in {None, "uki"}:
                raise RuntimeError(f"selected provider {selected} does not match the direct UKI configuration")
            return "uki", None, direct_uki
        if second_stage is not None:
            kind = self._bootloader_kind(second_stage)
            if selected not in {None, kind}:
                raise RuntimeError(f"selected provider {selected} does not match shim second stage {second_stage}")
            return kind, second_stage, None
        if selected == "uki":
            configured = load_direct_uki_config(self.config.firmware_boot_config_path)
            if configured is None:
                raise RuntimeError("the selected direct UKI provider is not configured")
            return "uki", None, configured
        if selected is not None:
            return selected, self._select_second_stage_for_provider(selected), None

        configured = load_direct_uki_config(self.config.firmware_boot_config_path)
        if configured is not None:
            return "uki", None, configured
        detected = select_second_stage(self.config.esp_path, self.config.second_stage_candidates)
        return self._bootloader_kind(detected), detected, None

    def prepare(self) -> dict[str, object]:
        """Sign inputs consumed later by mkinitcpio and bootloader tooling."""
        self.require_root()
        if not self._enabled():
            return self._disabled_result()

        signer = Signer(
            key=self.config.private_key,
            certificate=self.config.certificate_pem,
            runner=self.runner,
        )
        module_changed = 0
        changed_versions: set[str] = set()
        for path in discover_external_modules(
            self.config.module_root,
            self.config.module_directories,
            dkms_root=self.config.dkms_root,
        ):
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
        kernel_targets = discover_kernel_targets(self.config.canonical_kernel_globs)
        if not kernel_targets:
            raise RuntimeError("no canonical installed kernel image was found")
        kernels_signed = sum(int(signer.sign_pe(path)) for path in kernel_targets)
        return {
            "efi_signed": 0,
            "kernels_signed": kernels_signed,
            "modules_signed": module_changed,
            "deployed": 0,
            "efi_registered": False,
            "skipped": "",
        }

    def _refresh_boot_artifacts(
        self,
        second_stage: Path | None,
        direct_uki: DirectUkiConfig | None,
    ) -> None:
        if direct_uki is not None:
            if not shutil.which("catos-firmware-boot-update"):
                raise FileNotFoundError("catos-firmware-boot-update is required for the direct UKI provider")
            self.runner.run(["catos-firmware-boot-update", "--force"])
            return
        if second_stage is None:
            raise RuntimeError("no shim second stage was selected")
        kind = self._bootloader_kind(second_stage)
        if kind == "limine":
            if not shutil.which("limine-mkinitcpio"):
                raise FileNotFoundError("limine-mkinitcpio is required for the selected Limine bootloader")
            self.runner.run(["limine-mkinitcpio"])
            return
        if kind == "systemd-boot":
            if not shutil.which("kernel-install"):
                raise FileNotFoundError("kernel-install is required for systemd-boot EFISTUB and UKI deployment")
            self.runner.run(["kernel-install", "--entry-type=all", "add-all"])
            return

        if kind == "grub":
            self.runner.run(["mkinitcpio", "-P"])
            grub_config = self.config.boot_path / "grub/grub.cfg"
            if grub_config.is_file() and shutil.which("grub-mkconfig"):
                self.runner.run(["grub-mkconfig", "-o", str(grub_config)])

    def _verify_systemd_efistub_copies(self, signer: Signer) -> int:
        canonical_kernels = discover_kernel_targets(self.config.canonical_kernel_globs)
        verified = 0
        for canonical in canonical_kernels:
            version = canonical.parent.name
            deployed: set[Path] = set()
            for root in (self.config.esp_path, self.config.boot_path):
                if not root.is_dir():
                    continue
                deployed.update(path for path in root.glob(f"*/{version}/linux") if path.is_file())
            for path in sorted(deployed, key=lambda item: str(item)):
                if path.read_bytes() != canonical.read_bytes():
                    raise RuntimeError(
                        f"systemd-boot EFISTUB copy is stale or differs from the signed canonical kernel: {path}"
                    )
                if not signer.verify_pe(path):
                    raise RuntimeError(f"systemd-boot EFISTUB copy is not signed by the machine key: {path}")
                verified += 1
        return verified

    def finalize_efi(
        self,
        *,
        second_stage: Path | None = None,
        direct_uki: DirectUkiConfig | None = None,
        provider: str | None = None,
    ) -> dict[str, object]:
        """Sign final EFI loaders without modifying any kernel image."""
        self.require_root()
        if not self._enabled():
            return self._disabled_result()
        if not self.config.esp_path.is_dir():
            raise FileNotFoundError(f"EFI system partition is not mounted: {self.config.esp_path}")
        for vendor in (self.config.vendor_shim, self.config.vendor_mok_manager):
            if not vendor.is_file():
                raise FileNotFoundError(f"vendor Secure Boot binary is missing: {vendor}")
            if self.runner.run(["sbverify", "--list", str(vendor)], check=False).returncode != 0:
                raise RuntimeError(f"vendor Secure Boot binary is not signed: {vendor}")

        signer = Signer(
            key=self.config.private_key,
            certificate=self.config.certificate_pem,
            runner=self.runner,
        )
        resolved_provider, second_stage, direct_uki = self._resolve_boot_artifacts(
            provider=provider,
            second_stage=second_stage,
            direct_uki=direct_uki,
        )
        if direct_uki is not None:
            ukis = discover_direct_ukis(self.config.esp_path)
            default_package = select_default_uki(ukis, direct_uki.default_kernel)
            efi_changed = 0
            for path in ukis.values():
                efi_changed += int(signer.sign_pe(path, require_sbat=True))
                if not signer.verify_pe(path):
                    raise RuntimeError(f"direct UKI is not signed by the machine key: {path}")
            deployed, loaders = deploy_uki_boot_chains(
                esp=self.config.esp_path,
                shim=self.config.vendor_shim,
                mok_manager=self.config.vendor_mok_manager,
                certificate=self.config.certificate_der,
                ukis=ukis,
                default_package=default_package,
            )
            registered = False
            if self.config.register_efi:
                ordered_packages = [package for package in sorted(ukis) if package != default_package]
                ordered_packages.append(default_package)
                for package in ordered_packages:
                    register_boot_entry(
                        esp=self.config.esp_path,
                        label=f"{direct_uki.label_prefix} {package}",
                        loader=loaders[package],
                        runner=self.runner,
                    )
                registered = True
            return {
                "efi_signed": efi_changed,
                "kernels_signed": 0,
                "modules_signed": 0,
                "deployed": len(deployed),
                "deployed_kernels_verified": len(ukis),
                "efi_registered": registered,
                "provider": resolved_provider,
                "boot_chain_verified": True,
                "skipped": "",
            }
        if second_stage is None:
            raise RuntimeError("no shim second stage was selected")
        kind = resolved_provider
        deployed_kernels_verified = 0
        if kind == "grub":
            copies = discover_grub_kernel_copies(
                discover_kernel_targets(self.config.canonical_kernel_globs),
                boot_path=self.config.boot_path,
                preset_dir=self.config.mkinitcpio_preset_dir,
            )
            deployed_kernels_verified = verify_grub_kernel_copies(copies, signer)
            rebuild_grub_core(
                esp_path=self.config.esp_path,
                boot_path=self.config.boot_path,
                second_stage=second_stage,
                runner=self.runner,
            )
        second_stage_resolved = second_stage.resolve()
        sbat_source = second_stage_sbat_source(second_stage)
        efi_changed = 0
        for path in discover_efi_targets(self.config.esp_path, self.config.efi_globs):
            is_second_stage = path.resolve() == second_stage_resolved
            efi_changed += int(
                signer.sign_pe(
                    path,
                    require_sbat=is_second_stage,
                    sbat_source=sbat_source if is_second_stage else None,
                )
            )
        if not signer.verify_pe(second_stage):
            raise RuntimeError(f"shim second stage is not signed by the machine key: {second_stage}")
        if kind == "systemd-boot":
            deployed_kernels_verified = self._verify_systemd_efistub_copies(signer)
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
            "kernels_signed": 0,
            "modules_signed": 0,
            "deployed": len(deployed),
            "deployed_kernels_verified": deployed_kernels_verified,
            "efi_registered": registered,
            "provider": resolved_provider,
            "boot_chain_verified": True,
            "skipped": "",
        }

    def maintain(self, *, provider: str | None = None) -> dict[str, object]:
        self.require_root()
        prepared = self.prepare()
        if prepared["skipped"]:
            return prepared
        resolved_provider, second_stage, direct_uki = self._resolve_boot_artifacts(
            provider=provider,
            second_stage=None,
            direct_uki=None,
        )
        if resolved_provider == "grub":
            copies = discover_grub_kernel_copies(
                discover_kernel_targets(self.config.canonical_kernel_globs),
                boot_path=self.config.boot_path,
                preset_dir=self.config.mkinitcpio_preset_dir,
            )
            deploy_grub_kernel_copies(copies)
        self._refresh_boot_artifacts(second_stage, direct_uki)
        finalized = self.finalize_efi(
            second_stage=second_stage,
            direct_uki=direct_uki,
            provider=resolved_provider,
        )
        return {
            "efi_signed": finalized["efi_signed"],
            "kernels_signed": prepared["kernels_signed"],
            "modules_signed": prepared["modules_signed"],
            "deployed": finalized["deployed"],
            "deployed_kernels_verified": finalized["deployed_kernels_verified"],
            "efi_registered": finalized["efi_registered"],
            "provider": finalized["provider"],
            "boot_chain_verified": finalized["boot_chain_verified"],
            "skipped": "",
        }

    def enable(
        self,
        *,
        password: str | None,
        generate_password: bool,
        enroll: bool = True,
        provider: str | None = None,
    ) -> dict[str, object]:
        self.require_root()
        material = generate_key_material(self.config, self.runner)
        maintenance = self.maintain(provider=provider)
        state = State.load(self.config.state_path)
        result: dict[str, object] = {
            "fingerprint": material.fingerprint,
            "efi_signed": maintenance["efi_signed"],
            "kernels_signed": maintenance["kernels_signed"],
            "modules_signed": maintenance["modules_signed"],
            "deployed": maintenance["deployed"],
            "deployed_kernels_verified": maintenance["deployed_kernels_verified"],
            "efi_registered": maintenance["efi_registered"],
            "provider": maintenance["provider"],
            "boot_chain_verified": maintenance["boot_chain_verified"],
            "enrollment_pending": False,
        }
        if enroll:
            if self.runner.run(["mokutil", "--test-key", str(material.certificate_der)], check=False).returncode == 0:
                state = replace(
                    state,
                    enrollment_pending=False,
                    certificate_fingerprint=material.fingerprint,
                    provider=str(maintenance["provider"]),
                    last_error="",
                )
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
                state = replace(
                    state,
                    enrollment_pending=True,
                    certificate_fingerprint=material.fingerprint,
                    provider=str(maintenance["provider"]),
                    last_error="",
                )
                result["enrollment_password"] = password
                result["enrollment_pending"] = True
        else:
            state = replace(
                state,
                enrollment_pending=False,
                certificate_fingerprint=material.fingerprint,
                provider=str(maintenance["provider"]),
                last_error="",
            )
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
