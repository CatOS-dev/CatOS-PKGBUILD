from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catos_secureboot.config import Config
from catos_secureboot.service import SecureBootService
from catos_secureboot.system import CommandResult


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: list[str], *, check: bool = True, input_text: str | None = None) -> CommandResult:
        del check, input_text
        self.calls.append(tuple(arguments))
        if arguments[0] == "sbverify":
            if arguments[1] == "--list":
                return CommandResult(0, "vendor signature", "")
            path = Path(arguments[-1])
            valid = path.is_file() and path.read_bytes().endswith(b"-signed")
            return CommandResult(0 if valid else 1, "", "")
        if arguments[0] == "sbsign":
            output = Path(arguments[arguments.index("--output") + 1])
            output.write_bytes(Path(arguments[-1]).read_bytes() + b"-signed")
            return CommandResult(0, "", "")
        if arguments[0] == "mkinitcpio":
            return CommandResult(0, "", "")
        raise AssertionError(arguments)


class ServiceTests(unittest.TestCase):
    def test_maintain_builds_and_deploys_complete_machine_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            esp = root / "esp"
            boot = root / "boot"
            modules = root / "modules"
            keys = root / "keys"
            vendor = root / "vendor"
            version = modules / "6.12.1-catos"
            for path in (esp / "EFI/CatOS", boot, keys, vendor, version):
                path.mkdir(parents=True, exist_ok=True)
            (version / "pkgbase").write_text("linux\n", encoding="utf-8")
            (version / "vmlinuz").write_bytes(b"kernel")
            deployed_kernel = esp / "machine-id/6.12.1-catos/linux"
            deployed_kernel.parent.mkdir(parents=True)
            deployed_kernel.write_bytes(b"deployed-kernel")
            (boot / "initramfs-linux.img").write_bytes(b"initramfs")
            (esp / "EFI/CatOS/grubx64.efi").write_bytes(b"grub")
            (keys / "machine.key").write_bytes(b"key")
            (keys / "machine.crt").write_bytes(b"certificate")
            (keys / "machine.der").write_bytes(b"certificate-der")
            (vendor / "shimx64.efi").write_bytes(b"shim")
            (vendor / "mmx64.efi").write_bytes(b"mok-manager")
            cmdline = root / "cmdline"
            cmdline.write_text("root=UUID=test quiet\n", encoding="utf-8")
            config = replace(
                Config.defaults(),
                esp_path=esp,
                boot_path=boot,
                cmdline_path=cmdline,
                grub_dropin_path=root / "grub-secureboot.cfg",
                key_dir=keys,
                module_root=modules,
                kernel_globs=(str(version / "vmlinuz"), str(deployed_kernel)),
                vendor_shim=vendor / "shimx64.efi",
                vendor_mok_manager=vendor / "mmx64.efi",
                register_efi=False,
            )
            runner = FakeRunner()
            service = SecureBootService(config, runner)

            with patch("catos_secureboot.service.os.geteuid", return_value=0):
                result = service.maintain()

            self.assertEqual(result["deployed"], 8)
            self.assertFalse(result["efi_registered"])
            self.assertEqual(result["kernels_signed"], 2)
            self.assertTrue((version / "vmlinuz").read_bytes().endswith(b"-signed"))
            self.assertTrue(deployed_kernel.read_bytes().endswith(b"-signed"))
            self.assertEqual((esp / "EFI/BOOT/BOOTX64.EFI").read_bytes(), b"shim")
            self.assertTrue((esp / "EFI/BOOT/grubx64.efi").read_bytes().endswith(b"-signed"))
            self.assertFalse(any(call[0] == "ukify" for call in runner.calls))
            enforced = cmdline.read_text(encoding="utf-8")
            self.assertIn("module.sig_enforce=1", enforced)
            self.assertIn("lockdown=integrity", enforced)


if __name__ == "__main__":
    unittest.main()
