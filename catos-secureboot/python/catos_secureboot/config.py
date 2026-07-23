from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Config:
    esp_path: Path
    boot_path: Path
    cmdline_path: Path
    grub_dropin_path: Path
    key_dir: Path
    state_path: Path
    enrollment_password_path: Path
    module_root: Path
    vendor_shim: Path
    vendor_mok_manager: Path
    efi_globs: tuple[str, ...]
    kernel_globs: tuple[str, ...]
    second_stage_candidates: tuple[str, ...]
    module_directories: tuple[str, ...]
    efi_label: str
    register_efi: bool
    certificate_days: int

    @classmethod
    def defaults(cls) -> "Config":
        return cls(
            esp_path=Path("/boot/efi"),
            boot_path=Path("/boot"),
            cmdline_path=Path("/etc/kernel/cmdline"),
            grub_dropin_path=Path("/etc/default/grub.d/90-catos-secureboot.cfg"),
            key_dir=Path("/var/lib/catos-secureboot/keys"),
            state_path=Path("/var/lib/catos-secureboot/state.json"),
            enrollment_password_path=Path("/var/lib/catos-secureboot/enrollment-password"),
            module_root=Path("/usr/lib/modules"),
            vendor_shim=Path("/usr/share/catos-secureboot/vendor/shimx64.efi"),
            vendor_mok_manager=Path("/usr/share/catos-secureboot/vendor/mmx64.efi"),
            efi_globs=(
                "EFI/CatOS/*.efi",
                "EFI/Linux/*.efi",
                "EFI/systemd/*.efi",
                "EFI/limine/*.efi",
            ),
            kernel_globs=(
                "/usr/lib/modules/*/vmlinuz",
                "/boot/vmlinuz-*",
                "/boot/efi/*/*/linux",
                "/boot/efi/*/*/vmlinuz",
            ),
            second_stage_candidates=(
                "EFI/systemd/systemd-bootx64.efi",
                "EFI/limine/limine_x64.efi",
                "EFI/limine/limine.efi",
                "EFI/CatOS/grubx64.efi",
            ),
            module_directories=("updates", "extramodules"),
            efi_label="CatOS Secure Boot",
            register_efi=True,
            certificate_days=36500,
        )

    @classmethod
    def load(cls, path: Path) -> "Config":
        config = cls.defaults()
        if not path.is_file():
            return config
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        section = data.get("secureboot", {})
        if not isinstance(section, dict):
            raise ValueError("[secureboot] must be a table")
        values: dict[str, object] = {}
        for name in (
            "esp_path",
            "boot_path",
            "cmdline_path",
            "grub_dropin_path",
            "key_dir",
            "state_path",
            "enrollment_password_path",
            "module_root",
            "vendor_shim",
            "vendor_mok_manager",
        ):
            if name in section:
                values[name] = Path(str(section[name]))
        for name in ("efi_globs", "kernel_globs", "second_stage_candidates", "module_directories"):
            if name in section:
                raw = section[name]
                if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
                    raise ValueError(f"{name} must be an array of non-empty strings")
                values[name] = tuple(raw)
        for name in ("efi_label",):
            if name in section:
                value = str(section[name]).strip()
                if not value:
                    raise ValueError(f"{name} must not be empty")
                values[name] = value
        if "register_efi" in section:
            value = section["register_efi"]
            if not isinstance(value, bool):
                raise ValueError("register_efi must be a boolean")
            values["register_efi"] = value
        if "certificate_days" in section:
            days = int(section["certificate_days"])
            if days < 1:
                raise ValueError("certificate_days must be positive")
            values["certificate_days"] = days
        return replace(config, **values)

    @property
    def private_key(self) -> Path:
        return self.key_dir / "machine.key"

    @property
    def certificate_pem(self) -> Path:
        return self.key_dir / "machine.crt"

    @property
    def certificate_der(self) -> Path:
        return self.key_dir / "machine.der"
